"""V6 repaired-policy identities do not bypass actual replay or label denial."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_audit_v6 import audit_policy
from cell_field_evaluate_v6 import TASKS, HEADS, SEEDS, POLICIES, CANDIDATE, evaluation_protocol
from cell_field_score_v6 import score
import test_cell_field_audit_v5


class AuditV6Tests(unittest.TestCase):
    def test_repaired_identity_requires_all_actual_states_and_strict_original_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"policy"
            fixture = test_cell_field_audit_v5.AuditV5Tests().fixture(path, "response_h8_guarded")
            record = json.loads((path/"result.json").read_bytes())
            record["policy"] = "future_field_h8_repaired"
            (path/"result.json").write_text(json.dumps(record))
            result = audit_policy(path, *fixture)
            self.assertEqual((result["replayed_transitions"], result["guarded"]), (32, True))
            lowered = (*fixture[:3], -1., fixture[4])
            with self.assertRaisesRegex(ValueError, "original probe threshold"):
                audit_policy(path, *lowered)
            record["steps"][0]["repair"] = {"step_records": [{"error": {"type": "RuntimeError", "message": "repair failed"}}]}
            (path/"result.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "execution error"):
                audit_policy(path, *fixture)

    def test_replay_failure_does_not_decrypt_v6_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root/"protocol.json"
            protocol.write_text(json.dumps({"evaluation": evaluation_protocol()}))
            with patch("cell_field_score_v6.audit_run", side_effect=ValueError("changed source")), patch("cell_field_score_v6.decrypt_roles") as decrypt:
                result = score(root/"run", root/"data", protocol, root/"evaluation", b"6"*32)
            decrypt.assert_not_called()
            self.assertEqual((result["disposition"], result["heldout_labels_opened"]), ("REJECT_PRE_LABEL_AUDIT", False))

    def test_complete_score_retains_guard_repair_pairs_without_calling_zero_step_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root, y = Path(directory), np.arange(4)
            plan = root/"protocol.json"
            plan.write_text(json.dumps({"evaluation": evaluation_protocol()}))
            audit = {"all_replays_valid": True, "protocol_sha256": "fixture", "pre_evaluation_seal_sha256": "fixture", "rows": []}
            roles = {name: {"indices": np.arange(4)+4*i, "labels": y,
                "components": np.array([f"{name}-{k}" for k in range(4)])}
                for i, name in enumerate(("current_validation", "future_test", "old_test"))}
            def probabilities(confidence):
                p = np.full((12, 4), (1-confidence)/3)
                p[np.arange(12), np.tile(y, 3)] = confidence
                return p
            def write(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            for task in TASKS:
                write(root/"run"/task/"inputs.json", {})
                for head in HEADS:
                    for seed in SEEDS:
                        fit = root/"run"/task/f"seed{seed}-{head}"
                        (fit/"warmup").mkdir(parents=True)
                        np.savez(fit/"warmup/warmup.npz", probabilities=probabilities(.6))
                        for policy in POLICIES:
                            path = fit/"mpc"/policy
                            row = {"task": task, "head": head, "seed": seed, "policy": policy,
                                "status": "completed", "completed_steps": 32, "registered_steps": 32,
                                "cpu_ns": 2 if policy == CANDIDATE else 1, "wall_ns": 3, "valid_record": True}
                            audit["rows"].append(row)
                            write(path/"result.json", row)
                            p = probabilities(.7 if policy == CANDIDATE else .6)
                            np.savez(path/"trajectory.npz", terminal_probabilities=p, probabilities=np.stack([probabilities(.6), *([p]*32)]))
                        pressure = fit/"pressure"
                        write(pressure/"search.json", {"status": "pressure_crossing", "tau": 8, "checkpoint_offsets": {"prevention": 0}})
                        write(pressure/"prevention/frozen_plans.json", {"plans": [{"id": "paired-fixture"}]})
                        for name, certified, sequence in (("guarded", False, [probabilities(.6)[8:]]),
                            ("verified", True, [probabilities(.6)[8:], probabilities(.7)[8:]])):
                            target = pressure/"prevention"/name/"0"
                            write(target.with_suffix(".json"), {"verification": {"status": "certified" if certified else "unsafe", "certified": certified}})
                            np.savez(target.with_suffix(".npz"), retention_probabilities=np.asarray(sequence))
            with patch("cell_field_score_v6.audit_run", return_value=audit), patch("cell_field_score_v6.decrypt_roles", return_value=roles):
                result = score(root/"run", root/"data", plan, root/"evaluation", b"6"*32)
            self.assertTrue(result["all_registered_gates_met"])
            saved = json.loads((root/"evaluation/independent-retention.json").read_bytes())
            self.assertEqual(len(saved["policies"]), 72)
            pairs = [r for r in saved["pressure"] if r["kind"] == "slot"]
            self.assertEqual(len(pairs), 12)
            self.assertTrue(all(r["original_guard"]["future_probe_style_feasible"] is None
                and r["future_probe_style_feasible"] is True
                and not r["guard_repair_comparison"]["same_positive_returned_steps"] for r in pairs))


if __name__ == "__main__":
    unittest.main()
