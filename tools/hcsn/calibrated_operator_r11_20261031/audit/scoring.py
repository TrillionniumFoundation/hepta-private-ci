"""Score completed archived native answers directly, without model/owner replay."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import tarfile
import time
import traceback


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def save(path, value, compressed=False):
    data = (json.dumps(value, sort_keys=True, indent=None if compressed else 2, allow_nan=False) + "\n").encode()
    if compressed:
        data = gzip.compress(data, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    return sha(data)


def main(args):
    wall, cpu = time.perf_counter(), time.process_time()
    out = args.output.resolve()
    require(not out.exists(), "exclusive scoring-review output already exists")
    review = dict(schema="hcsn.native-answer-scoring.review.r11.v1", success=False,
                  predictions_from="raw native stdout end.task.answers", replay_used=False)
    detail = []
    try:
        folder = args.confirmation.resolve()
        # No result, archive, packet or label is read before this completion gate.
        complete_bytes = (folder / "COMPLETE.json").read_bytes()
        complete = json.loads(complete_bytes)
        require(complete["failures"] == 0, "confirmation is not successful and complete")
        results_bytes = (folder / "RESULTS.json.gz").read_bytes()
        require(sha(results_bytes) == complete["results_sha256"], "completed RESULTS identity changed")
        index_bytes = (folder / "ARCHIVES.json").read_bytes()
        index = json.loads(index_bytes)
        training_bytes = args.training_freeze.read_bytes()
        require(sha(training_bytes) == complete["training_freeze_sha256"], "training freeze identity changed")
        training = json.loads(training_bytes)
        rows = json.loads(gzip.decompress(results_bytes))
        native_rows = [r for r in rows if r["arm"] != "fitted_dp"]
        keys = [(r["seed"], r["split"], r["session"], r["arm"]) for r in native_rows]
        require(len(set(keys)) == len(keys) == complete["native_runs"] == 2560,
                "native score population is duplicated or incomplete")
        require(len(rows) == complete["runs"], "total result population differs from completion receipt")
        needed = set()
        for row in native_rows:
            prefix = f"seed{row['seed']}_{row['split']}"
            needed.add(f"{prefix}/data/{row['session']}/evaluator_labels.json")
            needed.add(f"{prefix}/runs/{row['session']}_{row['arm']}/receipt.json.gz")
        requested = defaultdict(dict)
        for key in needed:
            entry = index["members"][key]
            requested[entry["archive"]][entry["member"]] = (key, entry["sha256"])
        files, archive_digests = {}, {}
        for archive_name, selected in sorted(requested.items()):
            path = folder / archive_name
            actual = sha(path.read_bytes())
            require(actual == index["archives"][archive_name], "archive identity mismatch: " + archive_name)
            archive_digests[archive_name] = actual
            with tarfile.open(path, "r:gz") as archive:
                for member in archive:
                    if member.name not in selected:
                        continue
                    require(member.isfile(), "scoring member is not a regular file")
                    key, expected = selected.pop(member.name)
                    data = archive.extractfile(member).read()
                    require(sha(data) == expected, "archive member identity mismatch: " + key)
                    files[key] = data
            require(not selected, "requested scoring member absent from archive")
        require(set(files) == needed, "incomplete scoring input set")
        numeric_fields = ("utility", "charged_cost", "query_cost", "latency_cost")
        exact_fields = ("reward", "completed_jobs", "correct_jobs", "label_access_after_terminal")
        max_error = {key: 0.0 for key in numeric_fields}
        exact_numeric_mismatches, material_mismatches, answer_counts = Counter(), [], Counter()
        per_group = defaultdict(list)
        for row in native_rows:
            prefix = f"seed{row['seed']}_{row['split']}"
            receipt_key = f"{prefix}/runs/{row['session']}_{row['arm']}/receipt.json.gz"
            label_key = f"{prefix}/data/{row['session']}/evaluator_labels.json"
            receipt = json.loads(gzip.decompress(files[receipt_key]))
            raw = receipt["raw"]
            require(raw["returncode"] == 0 and not raw["error"], "failed raw native process")
            native = json.loads(raw["stdout"])
            require(native == raw["payload"], "parsed raw payload differs from original native stdout")
            require(native["source_digest"] == complete["source_digest"], "native source binding mismatch")
            model_name = f"models/seed{row['seed']}_{row['arm']}.json"
            require(native["policy_sha256"] == training["models"][model_name]["sha256"],
                    "native policy binding mismatch")
            state = native["end"]["task"]
            require(state["terminal"], "native task is not terminal; labels cannot score it")
            labels = json.loads(files[label_key])["labels"]
            answers = state["answers"]
            require(len({a["job"] for a in answers}) == len(answers), "duplicate native job answer")
            for answer in answers:
                p = answer["posterior"]
                require(answer["job"] in (0, 1) and answer["prediction"] in (0, 1)
                        and math.isfinite(p) and 0.0 <= p <= 1.0,
                        "native answer outside the declared task envelope")
                require(answer["prediction"] == int(p >= 0.5), "native FIRE prediction differs from recorded posterior")
                answer_counts["all"] += 1
                if p == 0.5:
                    answer_counts["exact_half"] += 1
                    answer_counts["exact_half_prediction_one"] += int(answer["prediction"] == 1)
                if abs(p - 0.5) <= 1e-12:
                    answer_counts["within_1e_minus_12_of_half"] += 1
                    answer_counts["near_half_prediction_one"] += int(answer["prediction"] == 1)
                    answer_counts["near_half_prediction_zero"] += int(answer["prediction"] == 0)
            fire_answers = [r["after"]["answers"][-1] for r in native["receipts"] if r["action"] == "FIRE"]
            require(fire_answers == answers, "terminal native answers differ from actual FIRE receipts")
            correct = sum(a["prediction"] == labels[a["job"]] for a in answers)
            reward = 2 * correct - len(answers)
            scored = dict(utility=reward-state["charged_cost"], reward=reward,
                charged_cost=state["charged_cost"], query_cost=state["query_cost"],
                latency_cost=state["latency_cost"], completed_jobs=len(answers),
                correct_jobs=correct, label_access_after_terminal=True)
            require(all(math.isfinite(scored[k]) for k in numeric_fields), "nonfinite native score")
            require(abs(state["charged_cost"]-state["query_cost"]-state["latency_cost"]) <= 1e-12,
                    "native charged-cost accounting mismatch")
            require(row["score"] == receipt["evaluation"]["score"], "RESULTS score differs from archived evaluation score")
            delta = {key: scored[key]-row["score"][key] for key in numeric_fields}
            mismatched_exact = [key for key in exact_fields if scored[key] != row["score"][key]]
            for key in numeric_fields:
                max_error[key] = max(max_error[key], abs(delta[key]))
                exact_numeric_mismatches[key] += int(scored[key] != row["score"][key])
            material = bool(mismatched_exact or any(abs(v) > 1e-12 for v in delta.values()))
            item = dict(seed=row["seed"], split=row["split"], session=row["session"], arm=row["arm"],
                native_score=scored, result_score=row["score"], numeric_difference=delta,
                exact_field_mismatch=mismatched_exact, material_difference=material,
                native_answers=answers, evaluator_labels=labels,
                receipt_member=receipt_key, receipt_member_sha256=sha(files[receipt_key]),
                original_stdout_sha256=sha(raw["stdout"].encode()),
                label_member=label_key, label_member_sha256=sha(files[label_key]))
            detail.append(item)
            if material:
                material_mismatches.append({k: item[k] for k in
                    ("seed", "split", "session", "arm", "native_score", "result_score", "exact_field_mismatch")})
            per_group[(row["seed"], row["split"], row["arm"])].append(scored["utility"])
        review.update(success=not material_mismatches, checked_native_runs=len(detail),
            archived_fitted_dp_runs_excluded=len(rows)-len(native_rows),
            material_mismatch_count=len(material_mismatches), material_mismatches=material_mismatches,
            max_absolute_numeric_difference=max_error,
            exact_numeric_mismatch_counts=dict(exact_numeric_mismatches),
            exact_discrete_score_mismatch_rows=sum(bool(r["exact_field_mismatch"]) for r in detail),
            answer_counts=dict(answer_counts), tolerance=1e-12,
            groups=[dict(seed=key[0], split=key[1], arm=key[2], n=len(values),
                         native_mean_utility=math.fsum(values)/len(values))
                    for key, values in sorted(per_group.items())],
            input_sha256=dict(complete=sha(complete_bytes), results=sha(results_bytes),
                archive_index=sha(index_bytes), training_freeze=sha(training_bytes)),
            checked_archive_sha256=archive_digests, checked_members=len(files),
            source_sha256=sha(Path(__file__).read_bytes()),
            score_formula="correct=sum(native_prediction==evaluator_label); reward=2*correct-native_answer_count; utility=reward-native_charged_cost",
            limits=["This validates native outcome scoring for the completed corpus, not a universal runtime proof.",
                    "No native process or model replay is run; predictions and costs come only from preserved original native stdout.",
                    "Float score equality is reported both exactly and at 1e-12; discrete reward/correct/completed fields require exact equality."])
    except Exception as exc:
        review["failure"] = dict(type=type(exc).__name__, reason=str(exc), traceback=traceback.format_exc())
    review["parent_cpu_seconds"] = time.process_time()-cpu
    review["wall_seconds"] = time.perf_counter()-wall
    detail_path = out.with_name(out.stem + "_ROWS.json.gz")
    review["detail"] = dict(path=detail_path.name, sha256=save(detail_path, detail, compressed=True))
    save(out, review)
    print(json.dumps({k: review.get(k) for k in ("success", "checked_native_runs", "material_mismatch_count",
        "exact_discrete_score_mismatch_rows", "max_absolute_numeric_difference", "answer_counts", "failure")}))
    return 0 if review["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("confirmation", "training-freeze", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
