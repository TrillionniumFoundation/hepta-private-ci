"""Negative binding controls; fixtures do not certify training or Cell execution."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

import hepta_neural_candidate_transport_v1 as target


class CandidateTransportBindings(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.parent_dir = self.root / "parent"
        self.child_dir = self.root / "child"
        self.parent_dir.mkdir()
        self.child_dir.mkdir()
        self.contract = {
            "backbone": {"index_root": "11" * 32},
            "tokenizer": {"files_root": "22" * 32},
        }
        contract_raw = target.canonical(self.contract)
        contract_id = target.semantic_id(
            "target-decoder-adapter-contract-v1", contract_raw
        )
        adapter_raw = target.canonical(
            {"contract": contract_id, "fixture": "changed child"}
        )
        child_weights = b"bounded fixture weights, not trained material"
        child_id = target.semantic_id("wrapped-decoder-lora-material-v1", adapter_raw)
        child_sha = hashlib.sha256(child_weights).hexdigest()
        self.parent = dict(
            schema="hepta-smollm-parent-material-v1",
            generation=1,
            operation_id="33" * 32,
            directory=str(self.parent_dir),
            contract=contract_id,
            adapter="44" * 32,
            file_sha256="55" * 32,
        )
        self.child = dict(
            self.parent,
            generation=2,
            operation_id="66" * 32,
            directory=str(self.child_dir),
            adapter=child_id,
            file_sha256=child_sha,
        )
        policy = dict(
            profile="linux-owned-exit-worker-pidfd-v4", maximum_drain_ns=100000000
        )
        self.observation = dict(
            plan_sha256="77" * 32,
            profile="canonical-parent-original-task-observed-execution-v1",
            observer=hashlib.sha256(target.canonical(policy)).hexdigest(),
            model_plan="88" * 32,
        )
        self.training = dict(
            schema="llm-runtime-parent-step-actual-observed-v1",
            outcome="success",
            operation="train",
            actual_backend="cpu",
            actual_device="cpu",
            training_changed_from_setup=True,
            input="99" * 32,
            attempt_binding="aa" * 32,
            observation_execution=self.observation,
            parent={k: self.parent[k] for k in ("contract", "adapter", "file_sha256")},
            parent_readback=self.parent["adapter"],
            candidate={k: self.child[k] for k in ("adapter", "file_sha256")},
            attempt_id=self.child["operation_id"],
            training=dict(steps=10, tokens=526, supervised_tokens=452),
            source={"fixture-source": "bb" * 32},
        )
        self.completion = dict(
            schema="llm-runtime-parent-step-result-observed-v1",
            outcome="success",
            completion_verified=True,
            input=self.training["input"],
            attempt_binding=self.training["attempt_binding"],
            observation_execution=self.observation,
            actual_receipt_sha256="00" * 32,
            supervisor=dict(
                outcome="success",
                exit_code=0,
                stop_reason=None,
                waited_child_reaped=True,
                owned_child_reap_resolved=True,
                owned_child_echild_observed=False,
                waited_child_observation_error=None,
                budget=dict(wall_seconds=1800, rss_bytes=16 * 1024**3),
                terminal_reconciliation_profile="explicit-linux-owned-exit-worker-pidfd-v4",
                exit_observation_profile=policy,
            ),
        )
        runtime = self.write("runtime.py", b"# synthetic pinned runtime control\n")
        binary_path = Path(shutil.which("true")).resolve()
        binary = dict(
            path=str(binary_path),
            sha256=hashlib.sha256(binary_path.read_bytes()).hexdigest(),
        )
        context = dict(
            family="smollm2-135m-cpu-dev-v1",
            base="11" * 32,
            parent=child_sha,
            tokenizer="22" * 32,
            layout=contract_id,
            runtime=runtime["sha256"],
        )
        self.value = dict(
            schema=target.SCHEMA,
            binary=binary,
            runtime=runtime,
            observation_execution=self.observation,
            context=context,
            members={},
        )
        for name, raw in zip(
            target.NAMES, (child_weights, contract_raw, adapter_raw), strict=True
        ):
            path = self.child_dir / name
            path.write_bytes(raw)
            self.value["members"][name] = dict(
                path=str(path),
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
                manifest_id=target.manifest_id(context, raw),
            )
        self.refresh()

    def write(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())

    def refresh(self):
        self.value["training"] = self.write(
            "training.json", target.canonical(self.training)
        )
        self.completion["actual_receipt_sha256"] = self.value["training"]["sha256"]
        for key in ("completion", "parent", "child"):
            self.value[key] = self.write(
                key + ".json", target.canonical(getattr(self, key))
            )

    def rejected(self, value=None):
        with self.assertRaises((ValueError, OSError, KeyError, TypeError)):
            target.preflight(self.value if value is None else value)

    def binary_fixture(self):
        self.observation = dict(
            self.observation,
            profile="canonical-positive-zero-binary-batch-observed-v2",
            recipe="cc" * 32,
            training_rows="dd" * 32,
            independent_source_rows=10,
            row_exposures=100,
            optimizer_steps=10,
        )
        self.value["schema"] = target.BINARY_SCHEMA
        del self.value["observation_execution"]
        self.value["binary_observed_execution"] = self.observation
        for record, kind in ((self.training, "actual"), (self.completion, "result")):
            del record["observation_execution"]
            record["binary_observed_execution"] = self.observation
            record["schema"] = "llm-runtime-parent-step-" + kind + "-binary-observed-v2"
        self.training["source"]["binary_answer_observed"] = "ee" * 32
        events = [
            dict(
                event="start",
                input=self.training["input"],
                recipe=self.observation["recipe"],
                plan_sha256=self.observation["plan_sha256"],
                source="ee" * 32,
            )
        ]
        for update in range(10):
            events.extend(
                dict(event="microstep", optimizer_step=update, row_ordinal=row)
                for row in range(10)
            )
            events.append(dict(event="optimizer-step", optimizer_step=update))
        events.append(
            dict(
                event="complete",
                optimizer_steps=10,
                microsteps=100,
                tokens=4860,
                supervised_tokens=100,
            )
        )
        trace = b"".join(target.canonical(row) + b"\n" for row in events)
        trace_pin = self.write("binary-training-trace-v2.jsonl", trace)
        self.training["training"] = dict(
            steps=10,
            tokens=4860,
            supervised_tokens=100,
            objective=dict(
                profile=self.observation["profile"],
                execution=self.observation,
                recipe=self.observation["recipe"],
                source_sha256="ee" * 32,
                optimizer_steps=10,
                microsteps=100,
                independent_source_rows=10,
                row_exposures=100,
                answer_tokens=100,
                eos_tokens=0,
                actual_input_tokens=4860,
                trace=dict(trace_pin, bytes=len(trace)),
                same_work_as_legacy_ten_single_rows=False,
                loss_scope="ten-row-mean-two-original-answer-token-CE-gradient-per-optimizer-step",
            ),
        )
        self.refresh()

    def test_explicit_binary_workload_preserves_parent_and_original_supervision_bindings(
        self,
    ):
        self.binary_fixture()
        records, payloads = target.preflight(self.value)
        self.assertEqual(records["training"], self.training)
        self.assertEqual(set(payloads), set(target.NAMES))
        old = copy.deepcopy(self.value)
        old["schema"] = target.SCHEMA
        self.rejected(old)

    def test_binary_trace_missing_bytes_and_independence_cost_relabel_are_refused(self):
        self.binary_fixture()
        for key, value in (
            ("row_exposures", 10),
            ("independent_source_rows", 100),
            ("same_work_as_legacy_ten_single_rows", True),
            ("eos_tokens", 30),
        ):
            original = copy.deepcopy(self.training)
            self.training["training"]["objective"][key] = value
            self.refresh()
            self.rejected()
            self.training = original
            self.refresh()
        Path(self.training["training"]["objective"]["trace"]["path"]).write_bytes(
            b"{}\n"
        )
        self.rejected()

    def test_well_formed_binding_fixture_only(self):
        records, payloads = target.preflight(self.value)
        self.assertEqual(
            records,
            {
                "training": self.training,
                "completion": self.completion,
                "parent": self.parent,
                "child": self.child,
            },
        )
        self.assertEqual(set(payloads), set(target.NAMES))

    def test_reject_training_receipt_parent_and_candidate_substitutions(self):
        original = copy.deepcopy(self.training)
        mutations = {
            "schema": "llm-runtime-parent-step-actual-v1",
            "outcome": "failed",
            "operation": "evaluate",
            "actual_backend": "cuda",
            "actual_device": "cuda",
            "training_changed_from_setup": False,
            "parent_readback": "00" * 32,
            "attempt_id": "00" * 32,
            "source": {},
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                self.training = dict(original, **{key: value})
                self.refresh()
                self.rejected()
        self.training = copy.deepcopy(original)
        self.training["candidate"]["file_sha256"] = "00" * 32
        self.refresh()
        self.rejected()

    def test_reject_completion_failure_and_cross_attempt_relabel(self):
        original = copy.deepcopy(self.completion)
        for key, value in {
            "schema": "llm-runtime-parent-step-result-v1",
            "outcome": "failed",
            "completion_verified": False,
            "input": "00" * 32,
            "attempt_binding": "00" * 32,
        }.items():
            with self.subTest(key=key):
                self.completion = dict(original, **{key: value})
                self.refresh()
                self.rejected()
        self.completion = original
        self.refresh()
        changed = dict(self.completion, actual_receipt_sha256="00" * 32)
        self.value["completion"] = self.write(
            "completion.json", target.canonical(changed)
        )
        self.rejected()

    def test_reject_unsettled_or_relaxed_supervision(self):
        original = copy.deepcopy(self.completion["supervisor"])
        mutations = {
            "outcome": "failed",
            "exit_code": True,
            "stop_reason": "deadline",
            "waited_child_reaped": False,
            "owned_child_reap_resolved": False,
            "owned_child_echild_observed": True,
            "waited_child_observation_error": "not found",
            "budget": dict(wall_seconds=1801, rss_bytes=16 * 1024**3),
            "terminal_reconciliation_profile": "strict-v1",
            "exit_observation_profile": dict(
                profile="linux-owned-exit-worker-pidfd-v4", maximum_drain_ns=101000000
            ),
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                self.completion["supervisor"] = dict(original, **{key: value})
                self.refresh()
                self.rejected()

    def test_reject_missing_steps_bad_token_count_and_observer_rebinding(self):
        for steps, tokens, supervised in (
            (True, 526, 452),
            (9, 526, 452),
            (11, 526, 452),
            (10, 0, 0),
            (10, 526, 527),
            (10, 526, -1),
        ):
            self.training["training"] = dict(
                steps=steps, tokens=tokens, supervised_tokens=supervised
            )
            self.refresh()
            self.rejected()
        self.training["training"] = dict(steps=10, tokens=526, supervised_tokens=452)
        self.refresh()
        value = copy.deepcopy(self.value)
        value["observation_execution"]["observer"] = "00" * 32
        self.rejected(value)

    def test_reject_wrong_generation_and_unchanged_child(self):
        parent, child = copy.deepcopy(self.parent), copy.deepcopy(self.child)
        for key, value in (
            ("generation", 1),
            ("generation", True),
            ("contract", "00" * 32),
            ("adapter", parent["adapter"]),
            ("file_sha256", parent["file_sha256"]),
        ):
            self.child = dict(child, **{key: value})
            self.refresh()
            self.rejected()
        self.child = child
        self.parent["generation"] = 2
        self.refresh()
        self.rejected()

    def test_reject_mismatched_member_manifest_and_external_context(self):
        for name in target.NAMES:
            for key, bad in (
                ("sha256", "00" * 32),
                ("manifest_id", "00" * 32),
                ("bytes", True),
            ):
                value = copy.deepcopy(self.value)
                value["members"][name][key] = bad
                self.rejected(value)
        for key in ("base", "parent", "tokenizer", "layout", "runtime"):
            value = copy.deepcopy(self.value)
            value["context"][key] = "00" * 32
            for member in value["members"].values():
                member["manifest_id"] = target.manifest_id(
                    value["context"], Path(member["path"]).read_bytes()
                )
            self.rejected(value)

    def test_reject_unknown_omitted_or_duplicate_input(self):
        value = dict(self.value, installation_authority=True)
        self.rejected(value)
        value = copy.deepcopy(self.value)
        value["members"].pop(target.NAMES[2])
        self.rejected(value)
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(ValueError):
                target.decode(raw)

    def test_pin_rejects_symlinks_relative_empty_oversized_and_mutated_bytes(self):
        path = self.root / "pin"
        path.write_bytes(b"small")
        link = self.root / "link"
        link.symlink_to(path)
        for candidate, bound in ((link, 99), (Path("relative"), 99), (path, 4)):
            with self.assertRaises((ValueError, OSError)):
                target.read_regular(candidate, bound)
        path.write_bytes(b"")
        with self.assertRaises(ValueError):
            target.read_regular(path, 99)
        raw_path = Path(self.value["members"][target.NAMES[0]]["path"])
        raw_path.write_bytes(b"substituted")
        self.rejected()

    def test_existing_output_cannot_be_replaced(self):
        output = self.root / "existing"
        output.mkdir()
        sentinel = output / "sentinel"
        sentinel.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            target.transport(self.value, output, "aa" * 32, time.monotonic() + 35)
        self.assertEqual(list(output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_expired_aggregate_deadline_produces_failed_receipt_without_cell_child(
        self,
    ):
        output = self.root / "expired"
        result = target.transport(self.value, output, "aa" * 32, time.monotonic() - 1)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["commands"], [])
        self.assertIsNone(result["server"])
        self.assertIs(result["installation_authority"], False)
        self.assertIs(result["model_qualification"], False)
        self.assertEqual(
            json.loads((output / "transport-result.json").read_text()), result
        )


if __name__ == "__main__":
    unittest.main()
