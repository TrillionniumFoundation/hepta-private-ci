"""Independent, read-only audit of exact pinned Qwen strong-RAG artifact ZIPs.

Requires the four original ZIPs beside this script. Does not download weights,
generate answers, perform training, or issue production acceptance.
"""

from pathlib import Path, PurePosixPath
import argparse
import os
import collections
import hashlib
import json
import math
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

SOURCE = "3b03ea7dee4b270bdf328251f7a404571c9d1013"
PINS = {
    "original": (
        "event-inputs-20261010.zip",
        "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
    ),
    "generator": (
        "memory-strong-rag-20261013-real-reader.zip",
        "de7087dbd3ee367475ef279d01dbeeeea46ee991b11399324289300df10c40bf",
    ),
    "checkpoint": (
        "memory-strong-rag-20261013-calibration-checkpoint.zip",
        "26ff349eef1e78367577be7dc59308166bb73ea13d5f63070ecdfd6fbc093f24",
    ),
    "replay": (
        "memory-strong-rag-20261013-independent-replay.zip",
        "442c7171cb2c522988e6e6c52b12201d1b59104702229dc256ca91b7bf6559c1",
    ),
}
ANSWER = re.compile(r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*")
CITES = re.compile(r"\[E([1-9][0-9]*)\]")
SCORER_ONLY = {
    "parsed_identifier",
    "strict_task_success",
    "required_sources_covered",
    "procedure_verification",
}


def strict_json(raw):
    def no_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key " + key)
            result[key] = value
        return result

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=no_duplicate,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
    )


def value_digest(v):
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def open_archive(label, archive_dir):
    filename, expected_hash = PINS[label]
    raw = (archive_dir / filename).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected_hash, label
    files = {}
    with zipfile.ZipFile(archive_dir / filename) as archive:
        metadata = archive.infolist()
        assert (
            1 <= len(metadata) <= 128
            and sum(v.file_size for v in metadata) <= 16_000_000
        )
        for item in metadata:
            name = item.filename
            path = PurePosixPath(name)
            assert (
                not path.is_absolute() and ".." not in path.parts and "\\\\" not in name
            )
            assert not item.is_dir() and not stat.S_ISLNK(item.external_attr >> 16)
            assert name not in files
            files[name] = archive.read(item)
    assert "SHA256SUMS" in files
    declared = {}
    for line in files["SHA256SUMS"].decode().splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        assert m, line
        sha, name = m.groups()
        assert name not in declared and name in files
        declared[name] = sha
        assert hashlib.sha256(files[name]).hexdigest() == sha, name
    assert set(declared) == set(files) - {"SHA256SUMS"}
    return files


def main(archive_dir, output_path):
    zipfiles = {key: open_archive(key, archive_dir) for key in PINS}
    src, gen, cal, replay = (
        zipfiles[x] for x in ("original", "generator", "checkpoint", "replay")
    )
    assert (
        src["tested-commit.txt"].strip().decode()
        == "c9dd3aeff958fbdc4356a98718e96dec47f9b820"
    )
    assert gen["tested-commit.txt"].strip().decode() == SOURCE
    assert cal["tested-commit.txt"].strip().decode() == SOURCE
    assert replay["auditor-source-commit.txt"].strip().decode() == SOURCE
    assert (
        hashlib.sha256(src["plan/plan.json"]).hexdigest()
        == "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
    )
    assert all(gen[path] == data for path, data in cal.items() if path != "SHA256SUMS")
    original_labels = strict_json(src["observations/labels.json"])
    original_sources = strict_json(src["plan/source-view.json"])
    assert len(original_labels) == 16 and len(original_sources) == 108
    label_by_id = {x["id"]: x for x in original_labels}
    source_by_id = {x["identity"]: x for x in original_sources}
    assert len(label_by_id) == 16 and len(source_by_id) == 108
    assert len([x for x in original_labels if x["phase"] == "calibration"]) == 8
    assert len([x for x in original_labels if x["phase"] == "test"]) == 8
    assert strict_json(gen["prep/calibration-labels.json"]) == [
        label_by_id[c["query"]["identity"]]
        for c in strict_json(gen["prep/calibration-plan.json"])["cases"]
    ]

    report_cal = strict_json(gen["calibration/report.json"])
    report_eval = strict_json(gen["evaluation/report.json"])
    receipt = strict_json(replay["receipt.json"])
    policy = strict_json(gen["calibration/frozen-policy.json"])
    inventory = strict_json(gen["inventory.json"])
    assert (
        report_cal["frozen_k"] == policy["selected_k"] == report_eval["selected_k"] == 1
    )
    assert receipt["generating_commit"] == SOURCE
    assert receipt["verified_artifact_files"] == len(gen) - 1
    assert receipt["production_accepted"] is False
    assert receipt["independent_semantic_judge"] is False
    assert (
        policy["reader_identity"]
        == inventory["inventory_digest"]
        == receipt["model_identity"]
    )

    expected_arms = {
        "calibration": ("k1", "k2", "k3", "k4", "k6"),
        "evaluation": (
            "selected_k",
            "hybrid_k4",
            "hybrid_k6",
            "hybrid_k4_reversed",
            "single_hop",
            "entity_time",
            "organized",
            "program_support",
            "empty",
        ),
    }
    output = {
        "schema": "hepta.memory-cell.actual-strong-rag-independent-source-audit.v1",
        "original_source_sha": PINS["original"][1],
        "generating_commit": SOURCE,
        "workflow_run_id": 38389920977,
        "artifact_sha256": {name: sha for name, (_, sha) in PINS.items()},
        "sha256_manifest_counts": {k: len(v) - 1 for k, v in zipfiles.items()},
        "reader_identity": receipt["model_identity"],
        "selected_calibration_k": policy["selected_k"],
        "calibration_stable_under_loo": report_cal["calibration_sensitivity"][
            "stable_to_one_calibration_case_removal"
        ],
        "phases": {},
        "deployment_or_semantic_acceptance": False,
    }
    probe_content = src["source/event_probe.py"]

    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "event_probe.py"
        script.write_bytes(probe_content)
        for phase in ("calibration", "evaluation"):
            rows = [
                strict_json(line)
                for line in gen[f"{phase}/raw-answers.jsonl"].splitlines()
                if line.strip()
            ]
            scored = strict_json(gen[f"{phase}/scored-answers.json"])
            arms = expected_arms[phase]
            expected = 8 * len(arms)
            assert len(rows) == len(scored) == expected
            qids = {r["question_id"] for r in rows}
            assert (
                len(qids) == 8
                and len({(r["question_id"], r["arm"]) for r in rows}) == expected
            )
            assert {(r["question_id"], r["arm"]) for r in rows} == {
                (qid, a) for qid in qids for a in arms
            }
            assert all(
                label_by_id[qid]["phase"]
                == ("calibration" if phase == "calibration" else "test")
                for qid in qids
            )
            summary = {
                a: dict(
                    planned=8,
                    generated=0,
                    correct=0,
                    full_program_citation=0,
                    covered=0,
                    input_tokens=0,
                    output_tokens=0,
                    reader_seconds=0.0,
                    procedures_replayed=0,
                )
                for a in arms
            }
            score_by_pair = {}
            for original, record in zip(rows, scored):
                assert set(record) - set(original) <= SCORER_ONLY
                assert all(record[k] == v for k, v in original.items())
                assert original["status"] == "succeeded"
                qid, arm = original["question_id"], original["arm"]
                label = label_by_id[qid]
                assert record["question_id"] == qid and record["arm"] == arm
                assert label["kind"] == record["kind"]
                supplied = original["answer"]
                regex = ANSWER.fullmatch(supplied)
                parsed = regex.group(1) if regex else None
                assert record["parsed_identifier"] == parsed
                correct = parsed == label["expected"]
                if label["kind"] == "procedure":
                    request = {
                        "operation": "execute",
                        "recipe": label["procedure"],
                        "supplied": parsed or "invalid_response",
                    }
                    child = subprocess.run(
                        [sys.executable, "-I", "-S", str(script)],
                        input=json.dumps(request, sort_keys=True),
                        text=True,
                        capture_output=True,
                        timeout=10,
                    )
                    assert (
                        child.returncode
                        == record["procedure_verification"]["exit_code"]
                    )
                    assert child.stdout == record["procedure_verification"]["stdout"]
                    assert child.stderr == record["procedure_verification"]["stderr"]
                    correct = child.returncode == 0
                    summary[arm]["procedures_replayed"] += 1
                assert type(record["strict_task_success"]) is bool
                assert record["strict_task_success"] == correct
                covered = set(label["support"]).issubset(record["selected"])
                assert record["required_sources_covered"] == covered
                delivered = original["receipt"]["delivered_evidence"]
                assert len(delivered) == len(original["selected"])
                assert (
                    original["receipt"]["reader_identity"] == receipt["model_identity"]
                )
                assert original["receipt"]["trainable_parameters"] == 0
                assert original["receipt"]["answer_postprocessed"] is False
                assert original["receipt"]["production_accepted"] is False
                for pos, d in enumerate(delivered):
                    sid = original["selected"][pos]
                    doc = source_by_id[sid]
                    assert d["original_id"] == sid and d["excerpt"] == doc["content"]
                    assert d["root"] == doc["root"] and d[
                        "source_digest"
                    ] == value_digest(doc["content"])
                    assert d["label"] == "E" + str(pos + 1)
                all_cites = {
                    d["original_id"]
                    for d in delivered
                    if int(d["label"][1:]) in [int(x) for x in CITES.findall(supplied)]
                }
                cites_full = correct and set(label["support"]).issubset(all_cites)
                assert all(
                    1 <= int(x) <= len(delivered) for x in CITES.findall(supplied)
                )
                v = summary[arm]
                v["generated"] += 1
                v["correct"] += int(correct)
                v["covered"] += int(covered)
                v["full_program_citation"] += int(cites_full)
                receipt_fields = original["receipt"]
                assert receipt_fields["token_limit"] == 2048
                for key in ("input_tokens", "generated_tokens"):
                    assert type(receipt_fields[key]) is int and receipt_fields[key] >= 0
                v["input_tokens"] += receipt_fields["input_tokens"]
                v["output_tokens"] += receipt_fields["generated_tokens"]
                seconds = receipt_fields["seconds"]
                assert (
                    isinstance(seconds, (int, float))
                    and math.isfinite(seconds)
                    and seconds >= 0
                )
                v["reader_seconds"] += seconds
                score_by_pair[(qid, arm)] = int(correct)
            assert all(v["generated"] == 8 for v in summary.values())
            original_report = report_cal if phase == "calibration" else report_eval
            original_arms = (
                original_report["arms"]
                if phase == "calibration"
                else original_report["success_by_arm"]
            )
            for arm, v in summary.items():
                published = original_arms[arm]
                assert v["correct"] == published["strict_success"]
                assert v["covered"] == published["support_covered"]
                assert v["input_tokens"] == published["input_tokens"]
                assert v["output_tokens"] == published["output_tokens"]
                assert abs(v["reader_seconds"] - published["inference_seconds"]) < 1e-7
            assert receipt[phase]["attempts"] == expected
            assert receipt[phase]["all_model_calls_succeeded"] is True
            assert (
                receipt[phase]["original_raw_sha256"]
                == hashlib.sha256(gen[f"{phase}/raw-answers.jsonl"]).hexdigest()
            )
            output["phases"][phase] = {"attempts": len(rows), "arms": summary}
            if phase == "evaluation":
                paired = {}
                contrasts = [
                    ("entity_time_minus_single_hop", "single_hop", "entity_time"),
                    ("organized_minus_entity_time", "entity_time", "organized"),
                    ("organized_minus_selected", "selected_k", "organized"),
                    ("selected_minus_hybrid4", "hybrid_k4", "selected_k"),
                ]
                for title, left, right in contrasts:
                    wins = sum(
                        score_by_pair[qid, right] > score_by_pair[qid, left]
                        for qid in qids
                    )
                    losses = sum(
                        score_by_pair[qid, right] < score_by_pair[qid, left]
                        for qid in qids
                    )
                    ties = 8 - wins - losses
                    assert (wins, losses, ties) == tuple(
                        report_eval["paired_contrasts"][title][k]
                        for k in ("wins", "losses", "ties")
                    )
                    paired[title] = {
                        "wins": wins,
                        "losses": losses,
                        "ties": ties,
                        "delta": (wins - losses) / 8,
                    }
                output["paired_contrasts"] = paired
    assert output["phases"]["calibration"]["attempts"] == 40
    assert output["phases"]["evaluation"]["attempts"] == 72
    assert all(
        value["full_program_citation"]
        == report_eval["formal_citation_chain"]["by_arm"][arm][
            "correct_with_full_program_declared_citations"
        ]
        for arm, value in output["phases"]["evaluation"]["arms"].items()
    )
    output["program_worker_replays"] = sum(
        a["procedures_replayed"]
        for x in output["phases"].values()
        for a in x["arms"].values()
    )
    output["all_112_model_answer_records_verified"] = True
    output["replayed_procedure_stdout_and_exit_status"] = True
    output["reader_or_parametric_model_retrained"] = False
    output["independent_semantic_citation_judge"] = False
    output["production_accepted"] = False
    target = output_path
    with target.open("x", encoding="utf-8") as f:
        f.write(
            json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        f.flush()
        os.fsync(f.fileno())
    print(
        json.dumps(
            {
                "saved": str(target),
                "calibration_attempts": 40,
                "evaluation_attempts": 72,
                "program_worker_replays": output["program_worker_replays"],
                "chosen_k": policy["selected_k"],
                "stable_LOO": output["calibration_stable_under_loo"],
                "scores": {
                    k: v["correct"]
                    for k, v in output["phases"]["evaluation"]["arms"].items()
                },
                "full_citations": {
                    k: v["full_program_citation"]
                    for k, v in output["phases"]["evaluation"]["arms"].items()
                },
                "pairs": output["paired_contrasts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    main(args.archive_dir, args.output)
