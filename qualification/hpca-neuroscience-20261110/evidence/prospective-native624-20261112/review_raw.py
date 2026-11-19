"""Recount retained native bytes without importing the model or experiment runner."""
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import zipfile


def check(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def equal(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def scores(rows):
    return {"n": len(rows), "valid": sum(x["valid"] for x in rows),
            "correct": sum(x["correct"] for x in rows),
            "first_eos": sum(x["first_eos"] for x in rows),
            "accuracy_including_invalid": sum(x["correct"] for x in rows)/len(rows)}


def main():
    path = Path(sys.argv[1])
    check(sha(path.read_bytes()) == "583a41faee2ea035aa93b89d6ffc774d1b01ef293c761e304552e265b3dc836a",
          "original ZIP identity")
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))
        check(set(archive.namelist()) == set(manifest["members"]) | {"MANIFEST.json"}, "ZIP roster")
        for name, item in manifest["members"].items():
            raw = archive.read(name)
            check(len(raw) == item["bytes"] and sha(raw) == item["sha256"], "member: " + name)
        pub = json.loads(archive.read("source-v2/PUBLICATION.json"))
        pre = json.loads(archive.read("execution-v2/PREEXECUTION.json"))
        result = json.loads(archive.read("execution-v2/RESULT.json"))
        selection = json.loads(archive.read("execution-v2/WRAPPER_SELECTION.json"))
        config = json.loads(archive.read("execution-v2/GENERATION_CONFIG.json"))
        data = json.loads(archive.read("source-v2/PROSPECTIVE_DEVEL_DATA.json"))
        tasks = {x["id"]: x for x in data["tasks"]}
        check(pub["commit"] == pre["source_publication"] == result["source_publication"] ==
              "5fe8da68b1c6488957e49b8d874946b2d6b6604f", "source publication")
        check(pub["sources"] == pre["sources"], "source manifest")
        check(equal(config, pre["generation_config"]), "resolved configuration")
        for name, expected in pub["sources"].items():
            check(sha(archive.read("source-v2/" + name)) == expected, "source bytes")
        for field, name in (("preexecution_sha256", "PREEXECUTION.json"),
                            ("journal_sha256", "ROWS.jsonl"),
                            ("generation_config_sha256", "GENERATION_CONFIG.json"),
                            ("wrapper_selection_sha256", "WRAPPER_SELECTION.json")):
            check(result[field] == sha(archive.read("execution-v2/" + name)), field)
        check(pre["publication_manifest_sha256"] == sha(archive.read("source-v2/PUBLICATION.json")),
              "publication file hash")
        journal = [json.loads(line) for line in archive.read("execution-v2/ROWS.jsonl").splitlines()]
        rows = result["rows"]
        check(len(rows) == result["actual_generations"] == 624 and len(journal) == 1249,
              "complete denominator")
        for index, event in enumerate(journal):
            check(type(event["sequence"]) is int and event["sequence"] == index, "sequence")
            check(event["run_id"] == result["run_id"] == pre["run_id"], "run identity")
        for index, row in enumerate(rows):
            task = tasks[row["id"]]
            check(all(row[key] == value for key, value in task.items()), "frozen task")
            match = re.match(r"^\s*(yes|no)(?!\w)", row["text"], flags=re.I)
            parsed = match.group(1).lower() if match else None
            check(row["parsed"] == parsed, "parser")
            check(all(type(row[key]) is bool and row[key] is value for key, value in {
                "valid": parsed is not None, "correct": parsed == task["truth"],
                "first_eos": row["tokens"][0] == 2}.items()), "row flags")
            check(1 <= len(row["tokens"]) <= 8 and all(type(t) is int and t >= 0 for t in row["tokens"]),
                  "generated tokens")
            check(math.isfinite(row["inference_wall_seconds"]) and row["inference_wall_seconds"] >= 0,
                  "inference time")
            start, finish = journal[2*index:2*index+2]
            check(start["kind"] == "attempt_started" and all(start[k] == row[v] for k, v in
                  (("condition", "condition"), ("wrapper", "wrapper"), ("task_id", "id"), ("split", "split"))),
                  "adjacent start")
            check(finish["kind"] == "row_completed" and equal(finish["row"], row), "adjacent completion")
        check(journal[-1]["kind"] == "all_rows_complete" and journal[-1]["n"] == 624, "terminal")
        wrappers = ("original_chat", "explicit_binary_chat")
        cal = {w: [r for r in rows if r["split"] == "calibration" and r["wrapper"] == w] for w in wrappers}
        check(all(len(cal[w]) == 16 and all(r["condition"] == "base" for r in cal[w]) for w in wrappers),
              "base-only calibration")
        selected = max(wrappers, key=lambda w: (sum(r["valid"] for r in cal[w]),
                      sum(r["correct"] for r in cal[w]), -wrappers.index(w)))
        check(selected == selection["selected_wrapper"] == result["selected_wrapper"], "fixed selection")
        check(equal({w: scores(cal[w]) for w in wrappers}, result["calibration_scores"]) and
              equal(result["calibration_scores"], selection["calibration_scores"]), "calibration arithmetic")
        old = [r for r in rows if r["split"] == "old_development"]
        check(len(old) == 16 and all(r["condition"] == "base" for r in old) and
              equal(scores(old), result["old_development"]), "development arithmetic")
        conditions = {"base"} | {f"seed{s} {a}" for s in (11, 17, 23, 29) for a in ("bursty", "interleaved")}
        check(len(result["runs"]) == 9 and {r["condition"] for r in result["runs"]} == conditions,
              "nine frozen conditions")
        expected_main = [t["id"] for t in data["tasks"] if t["split"] in ("context_worlds", "retention")]
        counts, distributions = {}, {}
        for run in result["runs"]:
            subset = [r for r in rows if r["condition"] == run["condition"] and r["split"] in
                      ("context_worlds", "retention")]
            check([r["id"] for r in subset] == expected_main and all(r["wrapper"] == selected for r in subset),
                  "common primary roster")
            counts[run["condition"]] = {}
            distributions[run["condition"]] = {}
            for split in ("context_worlds", "retention"):
                part = [r for r in subset if r["split"] == split]
                recounted = scores(part)
                check(equal(recounted, run["scores"][split]), "primary arithmetic")
                counts[run["condition"]][split] = recounted
                distributions[run["condition"]][split] = dict(collections.Counter(r["parsed"] for r in part))
        pairs = {}
        for seed in (11, 17, 23, 29):
            pairs[str(seed)] = {split: counts[f"seed{seed} bursty"][split]["correct"] -
                               counts[f"seed{seed} interleaved"][split]["correct"]
                               for split in ("context_worlds", "retention")}
        def exact_label(part):
            return sum(r["text"].strip().casefold() in ("yes", "no") for r in part)
        report = {"schema": "hpca-native624-retained-byte-review-v1", "status": "CONSISTENCY_PASS",
                  "zip_sha256": sha(path.read_bytes()), "verified_members": len(manifest["members"]),
                  "new_model_inferences": 0, "native_generations_recounted": 624, "journal_events": 1249,
                  "selected_wrapper": selected, "calibration": {w: scores(cal[w]) for w in wrappers},
                  "main": counts, "prediction_counts": distributions, "paired_correct_count_deltas": pairs,
                  "exact_label_only_calibration": {w: exact_label(cal[w]) for w in wrappers},
                  "exact_label_only_main": exact_label([r for r in rows if r["split"] in
                                                          ("context_worlds", "retention")]),
                  "exact_label_only_scope": "descriptive entire stripped answer, case-insensitive; primary parser unchanged",
                  "independent_future_B": False, "external_custody": "MISSING", "decision": "HOLD_NO_GO"}
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
