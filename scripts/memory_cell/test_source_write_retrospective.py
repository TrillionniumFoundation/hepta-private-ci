"""Pure audit invariants on authored fixtures; pretrained proof is a separate run."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from source_write_retrospective import ARMS, PAIRS, checked_archive, diagnose, run

COMMIT = "a" * 40


def bytes_json(value):
    return (json.dumps(value, allow_nan=False) + "\n").encode()


def fixture():
    ready = dict(
        writer_source=COMMIT,
        task_payload_consumed=False,
        production_accepted=False,
        training=dict(
            steps=2,
            examples=2,
            input_tokens=10,
            supervised_tokens=4,
            adapter_delta_squared_norm=1.0,
            losses=[3.0, 2.0],
            write_schedule=dict(
                planned_steps=2,
                planned_input_tokens=10,
                planned_supervised_tokens=4,
                visits_per_example=[1, 1],
                unvisited_examples=[],
            ),
        ),
    )
    ready_raw = bytes_json(ready)
    execution = dict(
        source_commit=COMMIT,
        writer_source=COMMIT,
        ready_sha=hashlib.sha256(ready_raw).hexdigest(),
        snapshot_loaded_before_task_payload=True,
    )
    raw, scored = [], []
    for q in ("q1", "q2"):
        for arm in ARMS:
            empty = arm in ("empty", "parameter_only")
            yes = arm in ("organized", "knowledge", "policy")
            record = dict(
                question_id=q,
                kind="new_fact",
                arm=arm,
                status="succeeded",
                selected=[] if empty else ["source"],
                answer="site_deadbeef" if yes else "site_wrong [E1]",
                receipt=dict(
                    knowledge_module_enabled=arm in ("knowledge", "parameter_only"),
                    input_ids_digest="empty" if empty else "shared",
                    derived_evidence=[] if empty else ["derived"],
                    delivered_evidence=[] if empty else ["source"],
                ),
            )
            raw.append(record)
            scored.append(
                record
                | dict(
                    parsed_identifier="site_deadbeef" if yes else None,
                    strict_task_success=yes,
                )
            )
    report = dict(
        all_attempts=len(raw),
        source_commit=COMMIT,
        arms={
            a: dict(
                strict_task_successes=sum(
                    r["strict_task_success"] for r in scored if r["arm"] == a
                )
            )
            for a in ARMS
        },
    )
    pairs = {}
    for label, before, after in PAIRS:
        wins = losses = changed = 0
        for q in ("q1", "q2"):
            a = next(x for x in scored if x["question_id"] == q and x["arm"] == before)
            b = next(x for x in scored if x["question_id"] == q and x["arm"] == after)
            wins += int(b["strict_task_success"] and not a["strict_task_success"])
            losses += int(a["strict_task_success"] and not b["strict_task_success"])
            changed += int(a["answer"] != b["answer"])
        pairs[label] = dict(
            all=dict(
                wins=wins,
                losses=losses,
                missing_pairs=0,
                changed_answers=changed,
            )
        )
    raw_bytes = b"".join(bytes_json(r) for r in raw)
    return {
        "snapshot/READY.json": ready_raw,
        "tasks/execution.json": bytes_json(execution),
        "tested-commit.txt": (COMMIT + "\n").encode(),
        "tasks/raw-answers.jsonl": raw_bytes,
        "tasks/scored-answers.json": bytes_json(scored),
        "tasks/report.json": bytes_json(report),
        "tasks/source-effects.json": bytes_json(
            dict(
                raw_answers_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                contrasts=pairs,
            )
        ),
    }


def archive(found, path):
    manifest = "".join(
        hashlib.sha256(raw).hexdigest() + "  ./" + name + "\n"
        for name, raw in sorted(found.items())
    )
    with zipfile.ZipFile(path, "w") as z:
        for name, value in found.items():
            z.writestr(name, value)
        z.writestr("SHA256SUMS", manifest)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RetrospectiveTests(unittest.TestCase):
    def test_causal_losses_are_not_task_gains(self):
        result = diagnose(fixture(), COMMIT)
        self.assertEqual(result["original_generation_calls"], 14)
        self.assertEqual(result["actual_optimizer_updates"], 2)
        self.assertEqual(result["strict_task_successes"]["knowledge"], 2)
        self.assertEqual(result["strict_task_successes"]["parameter_only"], 0)
        self.assertEqual(
            result["paired_effects"]["knowledge_vs_same_evidence"]["wins"], 0
        )
        self.assertEqual(
            result["unsupported_empty_context_citation_answers"]["parameter_only"], 2
        )
        self.assertTrue(result["research_parameter_candidate_rejected"])
        self.assertIsNone(result["semantic_citation_precision"])

    def test_posthoc_answer_mutation_rejected(self):
        found = fixture()
        score = json.loads(found["tasks/scored-answers.json"])
        score[0]["answer"] = "changed"
        found["tasks/scored-answers.json"] = bytes_json(score)
        with self.assertRaises(ValueError):
            diagnose(found, COMMIT)

    def test_wrong_adapter_and_context_admission_rejected(self):
        for mode in ("adapter", "context"):
            found = fixture()
            rows = [
                json.loads(line)
                for line in found["tasks/raw-answers.jsonl"].splitlines()
            ]
            matching = next(r for r in rows if r["arm"] == "parameter_only")
            if mode == "adapter":
                matching["receipt"]["knowledge_module_enabled"] = False
            else:
                matching["receipt"]["delivered_evidence"].append("injected")
            found["tasks/raw-answers.jsonl"] = b"".join(bytes_json(r) for r in rows)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                diagnose(found, COMMIT)

    def test_missing_original_row_and_changed_published_counts_rejected(self):
        for mode in ("missing", "altered"):
            found = fixture()
            if mode == "missing":
                found["tasks/raw-answers.jsonl"] = (
                    b"\n".join(found["tasks/raw-answers.jsonl"].splitlines()[:-1])
                    + b"\n"
                )
            else:
                result = json.loads(found["tasks/source-effects.json"])
                result["contrasts"]["knowledge_vs_same_evidence"]["all"]["wins"] = 1
                found["tasks/source-effects.json"] = bytes_json(result)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                diagnose(found, COMMIT)

    def test_pinned_archive_inventory_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / "original.zip"
            digest = archive(fixture(), path)
            found = checked_archive(path, digest)
            self.assertEqual(set(found), set(fixture()) | {"SHA256SUMS"})
            output = folder / "result.json"
            data = run(path, digest, COMMIT, output)
            self.assertEqual(json.loads(output.read_text()), data)
            with self.assertRaises(ValueError):
                run(path, digest, COMMIT, output)
            with self.assertRaises(ValueError):
                checked_archive(path, "0" * 64)
            path.unlink()
            archive({"../bad": b"x"}, path)
            with self.assertRaises(ValueError):
                checked_archive(path, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
