"""Controlled runner tests; fake generation is never real model evidence."""

import contextlib
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from . import run_episodic_diagnostic as experiment
from .episodic_memory import canonical_bytes


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "campaign"
        self.profile = {
            "model_name": "fixture-model",
            "model_dir": "/unused/model",
            "model_assets": {},
            "site_packages": "/unused/site",
            "runtime_sha256": "a" * 64,
            "python_sha256": "b" * 64,
        }
        self.plan = experiment.prepare(self.root, self.profile, "fixture-cohort")
        self.plan_sha = experiment.pin((self.root / "PLAN.json").read_bytes())["sha256"]
        self.calls = []

    def fake_actor(self, output, actor, task, *, mode, memory_context):
        self.assertEqual(actor, experiment.ACTOR)
        output.mkdir()
        inputs = output / "inputs"
        inputs.mkdir()
        (inputs / "actor.py").write_bytes(actor)
        task_path, memory_path = inputs / "task.json", inputs / "memory.txt"
        task_path.write_bytes(canonical_bytes(task))
        if mode == "on":
            memory_path.write_text(memory_context)
        source = (
            actor.decode()
            .replace('"/input/task.json"', repr(str(task_path)))
            .replace('"/input/memory.txt"', repr(str(memory_path)))
        )
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            exec(compile(source, "fixture-actor", "exec"), {})
        (output / "actor-output.bin").write_text(stream.getvalue())
        bootstrap = {
            "bootstrap": "hepta.mem9.namespace.v1",
            "pid": 1,
            "home_empty": True,
            "cache_empty": True,
            "workspace_empty": True,
            "namespaces": dict.fromkeys(
                ("mnt", "pid", "net", "ipc", "uts", "user"), "child"
            ),
        }
        stdout = canonical_bytes(bootstrap) + b"\n" + stream.getvalue().encode()
        (output / "stdout.bin").write_bytes(stdout)
        (output / "stderr.bin").write_bytes(b"")
        receipt = {
            "status": "EXECUTED",
            "fixture_only": True,
            "mode": mode,
            "actor_sha256": experiment.pin(actor)["sha256"],
            "task": experiment.pin(canonical_bytes(task)),
            "context_sha256": experiment.pin(memory_context.encode())["sha256"],
            "context_bytes": len(memory_context.encode()),
            "launcher_sha256": self.plan["sources"][
                "ndu_real_runtime/episodic_isolation.py"
            ]["sha256"],
            "returncode": 0,
            "source_unchanged": True,
            "capture_truncated": False,
            "input_transport": "sealed-memfd-ro-bind-data",
            "session_id": experiment.uuid.uuid4().hex,
            "process_identity": {"launcher_pid": os.getpid()},
            "started_at_unix_ns": experiment.time.time_ns(),
            "ended_at_unix_ns": experiment.time.time_ns() + 1,
            "bootstrap": bootstrap,
            "host_namespaces": dict.fromkeys(bootstrap["namespaces"], "host"),
            "stdout": experiment.pin(stdout),
            "stderr": experiment.pin(b""),
            "actor_output": experiment.pin(stream.getvalue().encode()),
        }
        (output / "RECEIPT.json").write_bytes(canonical_bytes(receipt))
        return receipt

    def fake_provider(
        self, root, request, *, request_id, launch_sha256, profile, timeout_seconds
    ):
        self.assertNotIn(request_id, self.calls)
        self.calls.append(request_id)
        value = json.loads(request)
        self.assertEqual(value["model"], profile.model_name)
        self.assertEqual(value["max_output_tokens"], 32)
        self.assertEqual(value["temperature"], 0)
        self.assertIs(value["store"], False)
        match = re.search(r"\b(" + "|".join(experiment.COLORS) + r")\b", value["input"])
        root.mkdir()
        directory = root / hashlib.sha256(request_id.encode()).hexdigest()
        directory.mkdir()
        model_input = {
            "schema": "hepta.mem12.model-input.v1",
            "rendered_prompt": "fixture:" + value["input"],
            "request_sha256": experiment.pin(request)["sha256"],
            "tensors": {
                name: {"dtype": "torch.int64", "shape": [1, 2], "values": [[1, 1]]}
                for name in ("input_ids", "attention_mask")
            },
        }
        model_raw = canonical_bytes(model_input)
        result = {
            "status": "RETURNED",
            "fixture_only": True,
            "profile": asdict(profile),
            "request_id": request_id,
            "request": experiment.pin(request),
            "launch_sha256": launch_sha256,
            "local_generation_returned": True,
            "model_input": experiment.pin(model_raw),
            "result": {
                "text": match[1] if match else "UNKNOWN",
                "tokens": [1],
                "prompt_tokens": 2,
                "user_cpu_seconds": 0.01,
                "request_sha256": experiment.pin(request)["sha256"],
                "model_input": experiment.pin(model_raw),
            },
        }
        result.update(
            source_unchanged=True,
            bootstrap={
                "empty": True,
                "namespaces": dict.fromkeys(
                    ("mnt", "pid", "net", "ipc", "uts", "user"), "child"
                ),
            },
            host_namespaces=dict.fromkeys(
                ("mnt", "pid", "net", "ipc", "uts", "user"), "host"
            ),
            runtime_before={"sha256": profile.runtime_sha256},
            runtime_after={"sha256": profile.runtime_sha256},
            execution={
                "returncode": 0,
                "timed_out": False,
                "output_limit_exceeded": False,
            },
            provider_source=self.plan["sources"][
                "ndu_real_runtime/episodic_local_provider.py"
            ],
            worker=self.plan["provider_worker"],
        )
        log = (
            b"MEM11_BOOTSTRAP "
            + canonical_bytes(result["bootstrap"])
            + b"\n"
            + b"MEM12_MODEL_INPUT "
            + model_raw
            + b"\n"
            + b"MEM11_RESULT "
            + canonical_bytes(result["result"])
            + b"\n"
        )
        result["combined_log"] = experiment.pin(log)
        result.update(
            schema="hepta.mem11.local-provider.v1",
            timeout_seconds=timeout_seconds,
            dependency_sources={
                name.rsplit("/", 1)[-1]: self.plan["sources"][name]
                for name in (
                    "hepta_ci_exec.py",
                    "ndu_real_runtime/episodic_provider_handoff.py",
                    "ndu_real_runtime/episodic_local_worker.py",
                )
            },
        )
        admission = {
            key: result[key]
            for key in (
                "schema",
                "request_id",
                "launch_sha256",
                "request",
                "profile",
                "worker",
                "timeout_seconds",
                "provider_source",
                "dependency_sources",
            )
        }
        (directory / "ADMISSION.json").write_bytes(experiment._canonical(admission))
        (directory / "request.bin").write_bytes(request)
        (directory / "model-input.json").write_bytes(model_raw)
        (directory / "combined.log").write_bytes(log)
        (directory / "RECEIPT.json").write_bytes(canonical_bytes(result))
        return result

    def test_plan_freezes_all_arms_without_labels_in_public_tasks(self):
        self.assertEqual(len(self.plan["cases"]), 8)
        for case in self.plan["cases"]:
            self.assertEqual(set(case["arm_order"]), set(experiment.ARMS))
            public = canonical_bytes(case["public_task"]).decode()
            self.assertTrue(all(color not in public for color in experiment.COLORS))
            self.assertEqual(len(case["facts"]), 3)
        result = experiment.report(self.root)
        self.assertEqual(result["planned_rows"], len(result["rows"]))
        self.assertEqual(result["planned_rows"], 80)
        self.assertEqual(
            result["contrasts"]["off"]["missing_label_difference_bounds"], [-1, 1]
        )
        self.assertEqual(result["known_returned_generations"], 0)

    def test_actual_writer_and_independent_interventions(self):
        case = self.plan["cases"][0]
        receipt = experiment._writer_observation(self.root, self.plan, case)
        self.assertEqual(receipt["status"], "EXITED")
        self.assertGreater(receipt["exited_at_unix_ns"], receipt["started_at_unix_ns"])
        snapshots = {}
        for name, mutation in (
            ("on", None),
            ("delete", "delete"),
            ("replace", "replace"),
            ("empty", "empty"),
        ):
            directory = self.root / case["case_id"] / name
            directory.mkdir()
            store = experiment.reader_store(
                self.root, directory, self.plan, case, mutation
            )
            snapshots[name] = store.view()["records"]
        key = case["public_task"]["key"]
        self.assertEqual(len(snapshots["on"]), 3)
        self.assertEqual(len(snapshots["delete"]), 2)
        self.assertEqual(snapshots["empty"], [])
        self.assertFalse(any(record["key"] == key for record in snapshots["delete"]))
        self.assertEqual(
            next(record["text"] for record in snapshots["on"] if record["key"] == key),
            f"{key} requires a {case['truth']} badge.",
        )
        self.assertEqual(
            next(
                record["text"]
                for record in snapshots["replace"]
                if record["key"] == key
            ),
            f"{key} requires a {case['replacement']} badge.",
        )

    def test_complete_fixture_flow_keeps_denominator_and_does_not_replay(self):
        with (
            mock.patch.object(
                experiment, "run_isolated_actor", side_effect=self.fake_actor
            ),
            mock.patch.object(
                experiment, "run_local_provider", side_effect=self.fake_provider
            ),
        ):
            result = experiment.run(self.root)
            again = experiment.run(self.root)
        self.assertEqual(result, again)
        self.assertEqual(len(self.calls), 80)
        self.assertEqual(result["known_returned_generations"], 80)
        self.assertEqual(result["unsettled_generation_rows"], 0)
        self.assertEqual(result["scientific_acceptance"], "HOLD")
        self.assertIs(result["observer_authenticated"], False)
        self.assertIs(result["native_owner_used"], False)
        for row in result["rows"]:
            receipt = row["memory_receipt"]
            if row["arm"] in {
                "off",
                "delete",
                "retrieval_off",
                "delivery_off",
                "retention_off",
            }:
                if row["arm"] != "delete":
                    self.assertEqual(receipt["context_bytes"], 0)
            if row["arm"] == "off":
                self.assertIs(receipt["store_read"], False)
            elif row["arm"] == "retrieval_off":
                self.assertIs(receipt["store_read"], True)
                self.assertIs(receipt["retrieval_executed"], False)
            elif row["arm"] == "delivery_off":
                self.assertIs(receipt["retrieval_executed"], True)
                self.assertGreater(len(receipt["selected_ids"]), 0)

    def test_unknown_generation_is_retained_and_never_reissued(self):
        case = self.plan["cases"][0]
        writer = experiment._writer_observation(self.root, self.plan, case)
        with (
            mock.patch.object(
                experiment, "run_isolated_actor", side_effect=self.fake_actor
            ),
            mock.patch.object(
                experiment,
                "run_local_provider",
                side_effect=RuntimeError("fixture interrupted after admission"),
            ) as provider,
        ):
            for _ in range(2):
                experiment.run_arm(
                    self.root, self.plan, self.plan_sha, case, "on_bm25", writer
                )
        self.assertEqual(provider.call_count, 1)
        report = experiment.report(self.root)
        self.assertEqual(report["planned_rows"], 80)
        self.assertEqual(report["unsettled_generation_rows"], 1)
        self.assertEqual(report["panels"]["on_bm25"]["missing"], 8)

    def test_incomplete_started_arm_and_tampered_plan_are_not_replayed(self):
        case = self.plan["cases"][0]
        (self.root / case["case_id"] / "on_bm25").mkdir(parents=True)
        with mock.patch.object(experiment, "run_local_provider") as provider:
            experiment.run_arm(
                self.root,
                self.plan,
                self.plan_sha,
                case,
                "on_bm25",
                {"status": "EXITED"},
            )
        provider.assert_not_called()
        self.assertEqual(experiment.report(self.root)["unsettled_generation_rows"], 1)
        (self.root / "PLAN.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "frozen plan changed"):
            experiment.run(self.root)

    def test_parser_is_fixed_and_does_not_search_for_truth_inside_prose(self):
        self.assertEqual(experiment.selected_text("Answer: Blue."), "blue")
        self.assertIsNone(experiment.selected_text("The badge could be blue or red."))
        self.assertIsNone(experiment.selected_text(["blue"]))
        self.assertEqual(experiment.selected_text("UNKNOWN"), "unknown")

    def test_report_recomputes_labels_and_rejects_changed_actual_model_inputs(self):
        case = self.plan["cases"][0]
        writer = experiment._writer_observation(self.root, self.plan, case)
        with (
            mock.patch.object(
                experiment, "run_isolated_actor", side_effect=self.fake_actor
            ),
            mock.patch.object(
                experiment, "run_local_provider", side_effect=self.fake_provider
            ),
        ):
            experiment.run_arm(
                self.root, self.plan, self.plan_sha, case, "on_bm25", writer
            )
        original = experiment.report(self.root)
        row_path = self.root / case["case_id"] / "on_bm25" / "ROW.json"
        row = json.loads(row_path.read_bytes())
        row["correct"] = not row["correct"]
        row_path.write_bytes(canonical_bytes(row))
        self.assertEqual(experiment.report(self.root), original)
        directory = (
            row_path.parent
            / "provider"
            / hashlib.sha256(row["request_id"].encode()).hexdigest()
        )
        (directory / "model-input.json").write_bytes(b"{}")
        changed = experiment.report(self.root)
        self.assertEqual(changed["panels"]["on_bm25"]["scored"], 0)
        self.assertEqual(changed["unsettled_generation_rows"], 1)

    def test_writer_actor_and_admission_custody_fail_without_dropping_rows(self):
        case = self.plan["cases"][0]
        writer = experiment._writer_observation(self.root, self.plan, case)
        with (
            mock.patch.object(
                experiment, "run_isolated_actor", side_effect=self.fake_actor
            ),
            mock.patch.object(
                experiment, "run_local_provider", side_effect=self.fake_provider
            ),
        ):
            experiment.run_arm(
                self.root, self.plan, self.plan_sha, case, "on_bm25", writer
            )
        arm = self.root / case["case_id"] / "on_bm25"
        writer_root = self.root / case["case_id"] / "writer"
        row = json.loads((arm / "ROW.json").read_bytes())
        provider = (
            arm / "provider" / hashlib.sha256(row["request_id"].encode()).hexdigest()
        )
        for path in (
            writer_root / "REQUEST.json",
            writer_root / "snapshot.json",
            writer_root / "authority.sqlite",
            writer_root / "RECEIPT.json",
            arm / "actor" / "stdout.bin",
            provider / "ADMISSION.json",
        ):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(b"{}")
                result = experiment.report(self.root)
                self.assertEqual(len(result["rows"]), 80)
                self.assertEqual(result["panels"]["on_bm25"]["scored"], 0)
                path.write_bytes(original)
        original = (writer_root / "RECEIPT.json").read_bytes()
        changed = json.loads(original)
        changed["exited_at_unix_ns"] = 2**63 - 1
        (writer_root / "RECEIPT.json").write_bytes(canonical_bytes(changed))
        self.assertEqual(experiment.report(self.root)["panels"]["on_bm25"]["scored"], 0)
        (writer_root / "RECEIPT.json").write_bytes(original)
        admission = json.loads((provider / "ADMISSION.json").read_bytes())
        receipt = json.loads((provider / "RECEIPT.json").read_bytes())
        admission["dependency_sources"]["hepta_ci_exec.py"]["sha256"] = "0" * 64
        receipt["dependency_sources"] = admission["dependency_sources"]
        receipt_raw = experiment._canonical(receipt)
        (provider / "ADMISSION.json").write_bytes(experiment._canonical(admission))
        (provider / "RECEIPT.json").write_bytes(receipt_raw)
        (arm / "PROVIDER.json").write_bytes(receipt_raw)
        row["provider_pin"] = experiment.pin(receipt_raw)
        (arm / "ROW.json").write_bytes(canonical_bytes(row))
        self.assertEqual(experiment.report(self.root)["panels"]["on_bm25"]["scored"], 0)


if __name__ == "__main__":
    unittest.main()
