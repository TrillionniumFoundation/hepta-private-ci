"""Reproducible artifact-audit contracts; synthetic data, no model calls."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from ..field_bridge_v3_20261027.training_common import object_hash
from . import audit
from .records import Journal, complete


class TemporaryArtifacts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="v5-audit-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class TraceAndSealTests(TemporaryArtifacts):
    def make_trace(self):
        with Journal(self.root / "trace.jsonl.gz") as journal:
            journal.append({"kind": "decision", "step": 0})
            journal.append({"kind": "transaction", "grain": 8})
        return journal.head

    def make_seal(self):
        self.make_trace()
        (self.root / "START.json").write_text(json.dumps({"started_unix_ns": 1}))
        complete(self.root, {"seed": 17})

    def test_real_journal_chain_compatible(self):
        head = self.make_trace()
        rows = audit.read_trace(self.root / "trace.jsonl.gz", head)
        self.assertEqual([row["kind"] for row in rows], ["decision", "transaction"])
        self.assertEqual(rows[1]["previous_record_sha256"], rows[0]["record_sha256"])

    def test_tampered_record_rejected(self):
        head = self.make_trace()
        with gzip.open(self.root / "trace.jsonl.gz", "rt") as stream:
            rows = [json.loads(line) for line in stream]
        rows[0]["step"] = 48
        with gzip.open(self.root / "tampered.jsonl.gz", "wt") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        with self.assertRaisesRegex(ValueError, "Trace record hash mismatch"):
            audit.read_trace(self.root / "tampered.jsonl.gz", head)

    def test_real_stage_seal_compatible(self):
        self.make_seal()
        result = audit.verify_stage(self.root)
        self.assertEqual(set(result["files"]), {"START.json", "trace.jsonl.gz"})

    def test_unsealed_extra_rejected(self):
        self.make_seal()
        (self.root / "unsealed.txt").write_text("not covered by the seal")
        with self.assertRaisesRegex(ValueError, "Unsealed or missing stage files"):
            audit.verify_stage(self.root)


class HardOutputTests(TemporaryArtifacts):
    def fixture(self):
        pixels = np.zeros((2, 1, 2, 2), dtype=np.uint8)
        captions = np.asarray(["one", "two"])
        panel = {"batches": [{"source_ids": [["a", "b"], ["c", "d"]], "condition": "clean"}]}
        values = {"pixels_u8": pixels, "captions_utf8": captions,
                  "source_ids": np.asarray([["a", "b"], ["c", "d"]]),
                  "conditions": np.asarray(["clean", "clean"]),
                  "output_sha256": np.asarray([hashlib.sha256(pixel.tobytes() + str(caption).encode()).hexdigest()
                                                for pixel, caption in zip(pixels, captions, strict=True)]),
                  "values_reward": np.asarray([.1, .2]), "values_audit": np.asarray([.2, .3])}
        return panel, values

    def test_hard_bytes_and_pairing_verified(self):
        panel, values = self.fixture()
        np.savez_compressed(self.root / "hard.npz", **values)
        result = audit.hard_output(self.root / "hard.npz", panel)
        np.testing.assert_array_equal(result, [[.1, .2], [.2, .3]])

    def test_unpaired_endpoint_rejected(self):
        panel, values = self.fixture()
        values["source_ids"] = values["source_ids"][::-1]
        np.savez_compressed(self.root / "unpaired.npz", **values)
        with self.assertRaisesRegex(ValueError, "Unpaired endpoint sources"):
            audit.hard_output(self.root / "unpaired.npz", panel)


class DevelopmentGateTests(unittest.TestCase):
    def setUp(self):
        self.protocol = audit.read_json(audit.HERE / "PROTOCOL.json")
        self.endpoints, self.paths = [], []
        methods, schedules = self.protocol["methods"], self.protocol["schedules"]
        self.candidate = methods.index(self.protocol["development_entry"]["candidate"])
        for seed in self.protocol["seeds"]:
            arrays = {"task": np.full((len(methods), len(schedules), 2, 3), .1),
                      "clean": np.zeros((len(methods), len(schedules), 2, 3)),
                      "frozen_task": np.zeros((2, 3)), "frozen_clean": np.zeros((2, 3))}
            arrays["task"][self.candidate] = .2
            self.endpoints.append(arrays)
            for method in methods:
                for schedule in schedules:
                    self.paths.append({"seed": seed, "method": method, "schedule_id": schedule,
                                       "resources": {"scheduled_gradient_microsteps": 288},
                                       "cpu_ns": 10, "wall_ns": 20})

    def report(self):
        return audit.comparisons(self.protocol, self.endpoints, self.paths)

    def test_protocol_gate_positive_fixture(self):
        report = self.report()
        self.assertTrue(report["development_entry"]["passed"])
        self.assertTrue(all(report["development_entry"]["checks"].values()))

    def test_one_seed_observer_failure_rejected(self):
        self.endpoints[1]["task"][self.candidate, :, 1] = -.1
        report = self.report()["development_entry"]
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["audit_frozen_each_model"])
        self.assertTrue(report["checks"]["reward_frozen_each_model"])

    def test_gate_does_not_authorize_holdout(self):
        report = self.report()["development_entry"]
        self.assertTrue(report["passed"])
        self.assertFalse(report["new_holdout_authorized"])


class CompletePathTests(TemporaryArtifacts):
    def fixture(self, grain, corruption=None):
        protocol = audit.read_json(audit.HERE / "PROTOCOL.json")
        training = audit.read_json(audit.V3 / "PROTOCOL.json")["training"]
        steps, interval = protocol["physical_steps_per_path"], protocol["decision_interval"]
        seed, schedule = protocol["seeds"][0], protocol["schedules"][0]
        chosen, method = protocol["baseline_actions"][str(seed)], "ordinary_" + str(grain)
        state = {"parameters": "1" * 64, "optimizer": "2" * 64}
        resources, decisions, accepted = Counter(), [], 0
        with Journal(self.root / "trace.jsonl.gz") as journal:
            for step in range(0, steps, interval):
                selected = {"step": step, "chosen": chosen, "override": False}
                decisions.append(selected)
                journal.append({"kind": "decision", **selected, "baseline_action": chosen,
                                "certificate": False, "prediction_performed": False})
                for start in range(step, step + interval, grain):
                    before, accept = state.copy(), (start // grain) % 2 == 0
                    candidate = {"parameters": object_hash(["p", start]), "optimizer": object_hash(["o", start])}
                    after = candidate if accept else before
                    if corruption == "rollback" and not accept:
                        after = candidate
                    local = {"scheduled_gradient_microsteps": grain, "gradient_backward_calls": grain,
                             "gradient_backward_examples": grain * (training["adapt_batch_size"] + training["rehearsal_batch_size"]),
                             "optimizer_steps": grain, "transaction_snapshots": 1,
                             ("accepted_blocks" if accept else "rejected_blocks"): 1}
                    if not accept:
                        local["discarded_gradient_microsteps"] = grain
                    if corruption == "counter" and start == 0:
                        local["gradient_backward_calls"] -= 1
                    receipt = {"start": start, "end": start + grain, "action_index": chosen, "schedule_id": schedule,
                               "schedule_sha256": object_hash(audit.scheduled_rows(seed, schedule, start, start + grain, training)),
                               "before": before, "candidate": candidate, "after": after, "accepted": accept,
                               "guard_delta": .1 if accept else -.1, "multiplier": training["multipliers"][chosen],
                               "clock_advances_on_rejection": True,
                               "first_gradient": {"optimizer_advanced": True, "loss": 1., "unclipped_gradient_norm": 1.},
                               "last_gradient": {"optimizer_advanced": True, "loss": 1., "unclipped_gradient_norm": 1.},
                               "resources": local, "guard_values": [.8], "guard_output_sha256": ["3" * 64]}
                    if grain != interval:
                        journal.append({"kind": "transaction_start", **{key: receipt[key] for key in
                                        ("start", "end", "before", "schedule_sha256")}})
                    journal.append({"kind": "transaction", "grain": grain, "receipt": receipt})
                    state, accepted = after, accepted + accept
                    resources.update(local)
        record = {"seed": seed, "method": method, "schedule_id": schedule, "study_id": protocol["study_id"],
                  "final_step": steps, "endpoint_access": False, "trace_head_sha256": journal.head,
                  "trace_records": journal.count, "decisions": decisions, "transactions": steps // grain,
                  "accepted": accepted, "accepted_nonzero": accepted, "resources": dict(resources), "cpu_ns": 1, "wall_ns": 2}
        (self.root / "PATH.json").write_text(json.dumps(record))
        return protocol, training, seed, method, schedule, state

    def run_path(self, grain, corruption=None):
        protocol, training, seed, method, schedule, final = self.fixture(grain, corruption)
        # Isolate trace contracts. The production audit has no checkpoint bypass.
        with patch.object(audit, "checkpoint_identity", return_value=(final, "4" * 64)):
            return audit.audit_path(self.root, protocol, training, seed, method, schedule, None, None, None)

    def test_complete_trace_grain_48(self):
        result = self.run_path(48)
        self.assertEqual(result["transactions"], 6)
        self.assertEqual(result["accepted_parameter_changes"], 3)

    def test_complete_trace_grain_8(self):
        result = self.run_path(8)
        self.assertEqual(result["transactions"], 36)
        self.assertEqual(result["accepted_parameter_changes"], 18)

    def test_reject_incomplete_rollback_despite_valid_hash_chain(self):
        with self.assertRaisesRegex(ValueError, "Rejected state not fully restored"):
            self.run_path(8, "rollback")

    def test_reject_backward_counter_loss_despite_balanced_summary(self):
        with self.assertRaisesRegex(ValueError, "Transaction work counter mismatch"):
            self.run_path(48, "counter")


if __name__ == "__main__":
    unittest.main()
