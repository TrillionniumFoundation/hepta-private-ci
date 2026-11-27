"""Independent replay rejects hidden errors and source-bound trajectory tampering."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_audit_v5 import audit_policy
from cell_field_policy_v5 import execute_policy
from cell_field_run_v5 import save_policy
from cell_field_score_v5 import independent_path, score
from cell_field_state import CellTrainingState, dataset_digest
from test_cell_field_response_v5 import example


class AuditV5Tests(unittest.TestCase):
    def fixture(self, output, policy="zero"):
        original, train, probes = example("gated")
        state = CellTrainingState(original.head, bindings={"test": "independent-audit"},
            protocol=original.protocol, contexts={"current_train": dataset_digest(*train)})
        state.set_vector(original.vector())
        state.step_count = original.step_count
        split = {"current_train": train, "current_probe": probes[0], "old_probe": probes[1]}
        config = {"steps": 32, "dt": .02, "effort_price": .03, "action_bound": 4.,
                  "old_weight": 0., "hard_retention": True, "backtracking": [1., .5, .25, .125, 0.]}
        result = execute_policy(state, split, 3., policy, config)
        save_policy(result, probes[0][0], output)
        return state, probes[0][0], split, 3., config

    def test_replay_full_guarded_and_zero_traces_then_reject_changed_action(self):
        for policy in ("zero", "response_h8_guarded"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/"policy"
                fixture = self.fixture(path, policy)
                result = audit_policy(path, *fixture)
                self.assertEqual((result["valid_record"], result["replayed_transitions"]), (True, 32))
                with np.load(path/"trajectory.npz", allow_pickle=False) as source:
                    arrays = {key: source[key] for key in source.files}
                arrays["actions"][0, 0] += 1e-7
                np.savez(path/"trajectory.npz", **arrays)
                with self.assertRaisesRegex(ValueError, "receipt differs|replay differs"):
                    audit_policy(path, *fixture)

    def test_nested_execution_error_and_changed_clock_digest_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"policy"
            fixture = self.fixture(path)
            record = json.loads((path/"result.json").read_bytes())
            record["steps"][0]["error"] = {"type": "RuntimeError", "message": "injected"}
            (path/"result.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "execution error"):
                audit_policy(path, *fixture)
            del record["steps"][0]["error"]
            record["state_digests"][8] = "wrong-clock-digest"
            (path/"result.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "terminal state/clock"):
                audit_policy(path, *fixture)

    def test_no_advance_does_not_become_successful_continuation(self):
        p, y = np.full((4, 4), .25), np.arange(4)
        row = independent_path(np.asarray([p]), y, p)
        self.assertEqual((row["committed_steps"], row["maximum_future_mean_nll_excess"], row["future_probe_style_feasible"]), (0, None, None))
        continuing = independent_path(np.asarray([p, p]), y, p)
        self.assertEqual((continuing["committed_steps"], continuing["maximum_future_mean_nll_excess"], continuing["future_probe_style_feasible"]), (1, 0., True))

    def test_failed_replay_never_reaches_label_decryption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = Path(__file__).parent/"cell_field_protocol_v5.json"
            with patch("cell_field_score_v5.audit_run", side_effect=ValueError("changed source")), patch("cell_field_score_v5.decrypt_roles") as decrypt:
                result = score(root/"run", root/"data", protocol, root/"evaluation", b"x"*32)
            decrypt.assert_not_called()
            self.assertEqual((result["disposition"], result["heldout_labels_opened"]), ("REJECT_PRE_LABEL_AUDIT", False))


if __name__ == "__main__":
    unittest.main()
