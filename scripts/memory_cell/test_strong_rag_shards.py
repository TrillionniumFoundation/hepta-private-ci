"""Untrusted model-journal shards must replay to one exact frozen task census."""

import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ShardedReaderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prefer the exact production modules when installed. A standalone local
        # test environment may use an explicitly isolated stdlib stub set.
        try:
            import strong_rag_shards as shards

            cls.shards = shards
            return
        except ModuleNotFoundError as error:
            if error.name not in (
                "peft",
                "transformers",
                "event_memory_trial",
                "native",
                "strong_rag_trial",
                "strong_rag_stability",
            ):
                raise
        stubs = {}
        native = types.ModuleType("native")
        native.digest = _hash
        native.Question = object
        stubs["native"] = native
        event = types.ModuleType("event_memory_trial")

        def read(path, digest=None):
            raw = path.read_bytes()
            if digest is not None and hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("wrong pinned bytes")
            return json.loads(raw)

        event.read = read
        stubs["event_memory_trial"] = event
        trial = types.ModuleType("strong_rag_trial")
        trial.EVAL_ARMS = (
            "selected_k",
            "hybrid_k4",
            "hybrid_k6",
            "hybrid_k4_reversed",
            "single_hop",
            "entity_time",
            "organized",
            "program_support",
            "empty",
        )
        trial.file_sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        stubs["strong_rag_trial"] = trial
        stability = types.ModuleType("strong_rag_stability")
        stability.KS = (1, 2, 3, 4, 6)
        stability.leave_one_out = lambda *args: None
        stubs["strong_rag_stability"] = stability
        with patch.dict(sys.modules, stubs):
            sys.modules.pop("strong_rag_shards", None)
            cls.shards = importlib.import_module("strong_rag_shards")

    def _fixtures(self, path, phase="calibration"):
        shard = self.shards
        cases = [
            dict(query=dict(identity=f"q{i}"), candidate_digest=f"pool-{i}")
            for i in range(8)
        ]
        for idx, case in enumerate(cases):
            for part, arms in enumerate(shard.groups(phase)):
                folder = path / shard.name(phase, idx, part)
                folder.mkdir()
                inventory = dict(
                    inventory_digest="f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
                )
                for key, obj in (
                    ("inventory.json", inventory),
                    ("publisher.json", {"research_only": True}),
                    ("runtime-preflight.json", {"schema": "fixture"}),
                ):
                    (folder / key).write_text(json.dumps(obj) + "\n")
                inv_sha = hashlib.sha256(
                    (folder / "inventory.json").read_bytes()
                ).hexdigest()
                (folder / "stage.json").write_text(
                    json.dumps(
                        dict(
                            tier="qwen-3b",
                            inventory_sha256=inv_sha,
                            publisher_sha256=hashlib.sha256(
                                (folder / "publisher.json").read_bytes()
                            ).hexdigest(),
                        )
                    )
                    + "\n"
                )
                stage_sha = hashlib.sha256(
                    (folder / "stage.json").read_bytes()
                ).hexdigest()
                records = [
                    dict(
                        question_id=case["query"]["identity"],
                        arm=arm,
                        status="succeeded",
                        candidate_digest=case["candidate_digest"],
                        answer=f"answer-{idx}-{arm}",
                    )
                    for arm in arms
                ]
                with (folder / "raw-answers.jsonl").open("w") as f:
                    for row in records:
                        f.write(json.dumps(row) + "\n")
                raw_sha = hashlib.sha256(
                    (folder / "raw-answers.jsonl").read_bytes()
                ).hexdigest()
                runtime_sha = hashlib.sha256(
                    (folder / "runtime-preflight.json").read_bytes()
                ).hexdigest()
                run = dict(
                    schema=shard.SCHEMA,
                    phase=phase,
                    source_commit="c" * 40,
                    case_index=idx,
                    part=part,
                    case_id=case["query"]["identity"],
                    arms=list(arms),
                    generated=len(arms),
                    reader_identity=inventory["inventory_digest"],
                    model_stage_sha256=stage_sha,
                    runtime_preflight_sha256=runtime_sha,
                    raw_answers_sha256=raw_sha,
                    calibration_plan_sha256="a" * 64
                    if phase == "calibration"
                    else None,
                    test_plan_sha256="b" * 64 if phase == "evaluation" else None,
                    policy_sha256="d" * 64 if phase == "evaluation" else None,
                    seconds=1.0,
                    production_accepted=False,
                )
                if phase == "evaluation":
                    (folder / "single-hop-control.json").write_text(
                        json.dumps({"registered": "public-hop"}) + "\n"
                    )
                    run["single_hop_control_sha256"] = hashlib.sha256(
                        (folder / "single-hop-control.json").read_bytes()
                    ).hexdigest()
                else:
                    run["single_hop_control_sha256"] = None
                (folder / "run.json").write_text(json.dumps(run) + "\n")
                files = (
                    "run.json",
                    "raw-answers.jsonl",
                    "inventory.json",
                    "stage.json",
                    "publisher.json",
                    "runtime-preflight.json",
                )
                files = files + (
                    ("single-hop-control.json",) if phase == "evaluation" else ()
                )
                pins = {
                    n: hashlib.sha256((folder / n).read_bytes()).hexdigest()
                    for n in files
                }
                (folder / "sha-pins.json").write_text(json.dumps(pins) + "\n")
        return cases

    def test_collection_cli_preserves_actual_plan_and_inputs_paths(self):
        from contextlib import redirect_stdout
        from io import StringIO

        observed = {}

        def collect(plan, inputs, prep, calibration, shards, output, **pins):
            observed.update(
                plan=plan,
                inputs=inputs,
                prep=prep,
                calibration=calibration,
                shards=shards,
                output=output,
                **pins,
            )
            return {"read_only_recovery": True}

        arguments = [
            "strong_rag_shards.py",
            "evaluation-collect",
            "/original/plan",
            "/original/observations",
            "/joined/prep",
            "/joined/calibration",
            "/shards/evaluation",
            "/release/evaluation",
            "--plan-sha",
            "a" * 64,
            "--policy-sha",
            "b" * 64,
        ]
        with (
            patch.object(self.shards, "collect_evaluation", side_effect=collect),
            patch.object(sys, "argv", arguments),
            redirect_stdout(StringIO()),
        ):
            self.shards.main()
        self.assertEqual(
            observed,
            dict(
                plan=Path("/original/plan"),
                inputs=Path("/original/observations"),
                prep=Path("/joined/prep"),
                calibration=Path("/joined/calibration"),
                shards=Path("/shards/evaluation"),
                output=Path("/release/evaluation"),
                plan_sha="a" * 64,
                policy_sha="b" * 64,
            ),
        )

    def test_exact_frozen_calibration_40_and_evaluation_72(self):
        s = self.shards
        self.assertEqual(sum(len(x) for x in s.groups("calibration")), 5)
        self.assertEqual(sum(len(x) for x in s.groups("evaluation")), 9)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for phase, total in (("calibration", 40), ("evaluation", 72)):
                cases = self._fixtures(root, phase)
                kwargs = dict(commit="c" * 40)
                kwargs.update(
                    prep_sha="a" * 64
                ) if phase == "calibration" else kwargs.update(
                    plan_sha="b" * 64, policy_sha="d" * 64
                )
                rows, shards = s._merge_shards(phase, root, cases, **kwargs)
                self.assertEqual(len(rows), total)
                self.assertEqual(len(shards), 16)
                self.assertEqual(
                    [
                        x["arm"]
                        for x in rows[
                            : len(s.groups(phase)[0]) + len(s.groups(phase)[1])
                        ]
                    ],
                    [f"k{k}" for k in (1, 2, 3, 4, 6)]
                    if phase == "calibration"
                    else list(s.trial.EVAL_ARMS),
                )

    def test_self_consistent_mixed_model_shards_reject(self):
        s = self.shards
        for changed_file in ("stage.json", "inventory.json", "publisher.json"):
            with self.subTest(file=changed_file), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                cases = self._fixtures(path)
                folder = path / s.name("calibration", 6, 1)
                changed = folder / changed_file
                changed_json = json.loads(changed.read_text())
                changed_json["unexpected_model_metadata"] = changed_file
                changed.write_text(json.dumps(changed_json) + "\n")

                stage_path = folder / "stage.json"
                stage = json.loads(stage_path.read_text())
                if changed_file == "inventory.json":
                    stage["inventory_sha256"] = hashlib.sha256(
                        changed.read_bytes()
                    ).hexdigest()
                elif changed_file == "publisher.json":
                    stage["publisher_sha256"] = hashlib.sha256(
                        changed.read_bytes()
                    ).hexdigest()
                stage_path.write_text(json.dumps(stage) + "\n")

                run_path = folder / "run.json"
                run = json.loads(run_path.read_text())
                run["model_stage_sha256"] = hashlib.sha256(
                    stage_path.read_bytes()
                ).hexdigest()
                run_path.write_text(json.dumps(run) + "\n")
                pin_path = folder / "sha-pins.json"
                pins = json.loads(pin_path.read_text())
                for filename in pins:
                    pins[filename] = hashlib.sha256(
                        (folder / filename).read_bytes()
                    ).hexdigest()
                pin_path.write_text(json.dumps(pins) + "\n")
                with self.assertRaisesRegex(
                    ValueError, "mixed frozen reader model files"
                ):
                    s._merge_shards(
                        "calibration",
                        path,
                        cases,
                        commit="c" * 40,
                        prep_sha="a" * 64,
                    )

    def test_changes_to_model_answers_and_manifests_reject(self):
        s = self.shards
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            cases = self._fixtures(path)
            p = path / s.name("calibration", 0, 0) / "raw-answers.jsonl"
            p.write_bytes(p.read_bytes().replace(b"answer-0", b"fabricated"))
            with self.assertRaises(ValueError):
                s._merge_shards(
                    "calibration", path, cases, commit="c" * 40, prep_sha="a" * 64
                )

    def test_wrong_or_unobserved_source_sha_rejects(self):
        s = self.shards
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            cases = self._fixtures(path)
            for mismatched in (
                dict(commit="e" * 40, prep_sha="a" * 64),
                dict(commit="c" * 40, prep_sha="f" * 64),
            ):
                with self.assertRaises(ValueError):
                    s._merge_shards("calibration", path, cases, **mismatched)

    def test_missing_shard_and_missing_arm_never_qualify(self):
        s = self.shards
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            cases = self._fixtures(path)
            (path / s.name("calibration", 6, 1) / "sha-pins.json").unlink()
            with self.assertRaises((FileNotFoundError, ValueError)):
                s._merge_shards(
                    "calibration", path, cases, commit="c" * 40, prep_sha="a" * 64
                )

    def test_budget_guard_changes_only_after_original_journal(self):
        shard = self.shards
        observed = []

        def original_guard(row, *, max_seconds):
            observed.append(("guard", max_seconds, row["status"]))

        def historical_journal(
            reader, cases, originals, arms, selection, journal, *, seed
        ):
            observed.append(("journal", tuple(arms), seed))
            shard.trial.fail_if_unviable_reader(dict(status="succeeded"))
            return [dict(status="succeeded")]

        with (
            patch.object(
                shard.trial, "fail_if_unviable_reader", original_guard, create=True
            ),
            patch.object(
                shard.trial, "_journal_answers", historical_journal, create=True
            ),
        ):
            rows = shard._journal_shard(
                object(), {}, {}, ("k1", "k3"), None, Path("unused"), seed="fixed"
            )
        self.assertEqual(rows, [dict(status="succeeded")])
        self.assertEqual(
            observed,
            [
                ("journal", ("k1", "k3"), "fixed"),
                ("guard", shard.SHARD_MAX_SECONDS, "succeeded"),
            ],
        )

    def test_evaluation_single_hop_shard_requires_sealed_original_bytes(self):
        s = self.shards
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = self._fixtures(root, "evaluation")
            folder = root / s.name("evaluation", 0, 0)
            original = folder / "single-hop-control.json"
            original.write_text('{"registered":"tampered"}\n')
            with self.assertRaises(ValueError):
                s._merge_shards(
                    "evaluation",
                    root,
                    cases,
                    commit="c" * 40,
                    plan_sha="b" * 64,
                    policy_sha="d" * 64,
                )

    def test_self_consistent_mixed_single_hop_shard_rejects(self):
        s = self.shards
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = self._fixtures(root, "evaluation")
            folder = root / s.name("evaluation", 6, 1)
            hop = folder / "single-hop-control.json"
            hop.write_text('{"registered":"other-hop"}\n')
            hop_sha = hashlib.sha256(hop.read_bytes()).hexdigest()
            run_path = folder / "run.json"
            run = json.loads(run_path.read_text())
            run["single_hop_control_sha256"] = hop_sha
            run_path.write_text(json.dumps(run) + "\n")
            pins_path = folder / "sha-pins.json"
            pins = json.loads(pins_path.read_text())
            pins["single-hop-control.json"] = hop_sha
            pins["run.json"] = hashlib.sha256(run_path.read_bytes()).hexdigest()
            pins_path.write_text(json.dumps(pins) + "\n")
            with self.assertRaisesRegex(ValueError, "mixed original single-hop"):
                s._merge_shards(
                    "evaluation",
                    root,
                    cases,
                    commit="c" * 40,
                    plan_sha="b" * 64,
                    policy_sha="d" * 64,
                )

    def test_unsealed_extra_shard_file_rejects(self):
        s = self.shards
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = self._fixtures(root, "calibration")
            (root / s.name("calibration", 0, 0) / "unexpected.txt").write_text(
                "not part of source census"
            )
            with self.assertRaisesRegex(ValueError, "unsealed or extra"):
                s._merge_shards(
                    "calibration",
                    root,
                    cases,
                    commit="c" * 40,
                    prep_sha="a" * 64,
                )

    def test_shard_indices_invalid_and_no_accidental_oracle_stage(self):
        s = self.shards
        for wrong in (
            ("calibration", 8, 0),
            ("evaluation", 0, 3),
            ("evaluation", -1, 0),
            ("untrusted", 0, 0),
        ):
            with self.assertRaises(ValueError):
                s.name(*wrong)
        with self.assertRaises(ValueError):
            s.groups("gold_answers")
        self.assertFalse(
            any(
                "oracle" in key for keys in s.CAL_GROUPS + s.EVAL_GROUPS for key in keys
            )
        )


if __name__ == "__main__":
    unittest.main()
