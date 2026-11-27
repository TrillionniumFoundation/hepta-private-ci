import copy
import math
import tempfile
import unittest
from pathlib import Path

from final_panels import (claim_attempt, create_registry, freeze_protocol, panel_statistics,
                          project_common_observer, validate_protocol, LABEL_SCHEMA)
from matrix_materials import freeze_config
from matrix_test_support import setup
from next_round_matrix import _digest


def final_setup():
    p, c, baseline, work = setup("shared_421m_head_no_ndu")
    _, _, candidate, _ = setup("shared_421m_sparse_fixed16_no_ndu")
    protocol = freeze_protocol(p, c, work, contrast_id="sparse_routing",
                               slots=[dict(attempt_id="baseline", role="baseline", config=baseline),
                                      dict(attempt_id="candidate", role="candidate", config=candidate)],
                               panels={"e0": "old", "e1": "new"}, registered_at_ns=12,
                               alpha=.05, max_old_accuracy_drop=.1, min_new_accuracy_gain=.01)
    return p, c, work, protocol


class FinalPanelTests(unittest.TestCase):
    def test_protocol_copies_inputs_and_binds_exact_workload(self):
        p, c, w, protocol = final_setup()
        validate_protocol(p, c, w, protocol, protocol["protocol_id"])
        w["eval"][0]["state"] = "different"
        with self.assertRaises(ValueError): validate_protocol(p, c, w, protocol, protocol["protocol_id"])
        self.assertFalse(protocol["final_model_selection_permitted"])

    def test_external_protocol_id_cannot_be_replaced_by_rehash(self):
        p, c, w, protocol = final_setup()
        identity = protocol["protocol_id"]
        protocol["alpha"] = .5
        protocol["protocol_id"] = _digest({k: v for k, v in protocol.items() if k != "protocol_id"})
        with self.assertRaises(ValueError): validate_protocol(p, c, w, protocol, identity)

    def test_final_partitions_are_complete_and_both_present(self):
        p, c, w, protocol = final_setup()
        for panels in ({"e0": "old"}, {"e0": "old", "e1": "old"},
                       {"e0": "old", "e1": "new", "t0": "new"}):
            with self.subTest(panels=panels), self.assertRaises(ValueError):
                self.refreeze(p, c, w, protocol, panels=panels)

    def refreeze(self, p, c, w, protocol, **changes):
        fields = ("contrast_id", "slots", "panels", "registered_at_ns", "alpha",
                  "max_old_accuracy_drop", "min_new_accuracy_gain")
        return freeze_protocol(p, c, w, **{**{k: protocol[k] for k in fields}, **changes})

    def test_bad_time_coefficients_or_slot_ids_reject(self):
        p, c, w, protocol = final_setup()
        for key, value in (("registered_at_ns", 20), ("alpha", True), ("alpha", float("nan")),
                           ("alpha", 0), ("max_old_accuracy_drop", -1), ("min_new_accuracy_gain", 2)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.refreeze(p, c, w, protocol, **{key: value})
        for name in ("../escape", "candidate", ""):
            slots = copy.deepcopy(protocol["slots"]); slots[0]["attempt_id"] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.refreeze(p, c, w, protocol, slots=slots)

    def test_different_training_protocol_or_role_reject(self):
        p, c, w, protocol = final_setup()
        slots = copy.deepcopy(protocol["slots"])
        cfg = slots[1]["config"]
        values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
        slots[1]["config"] = freeze_config(p, c, **{**values, "train_steps": values["train_steps"] + 1})
        with self.assertRaises(ValueError): self.refreeze(p, c, w, protocol, slots=slots)
        slots = copy.deepcopy(protocol["slots"]); slots[1]["role"] = "baseline"
        with self.assertRaises(ValueError): self.refreeze(p, c, w, protocol, slots=slots)

    def test_duplicate_content_cannot_inflate_source_groups(self):
        p, c, w, protocol = final_setup()
        for key in ("state", "question", "options"):
            w["eval"][1][key] = copy.deepcopy(w["eval"][0][key])
        with self.assertRaisesRegex(ValueError, "different source groups"):
            self.refreeze(p, c, w, protocol)

    def test_validation_source_groups_cannot_enter_final_panel(self):
        p, c, w, protocol = final_setup()
        w["eval"][0]["source_group"] = "t0"
        with self.assertRaises(ValueError): self.refreeze(p, c, w, protocol)

    def test_local_claim_is_exclusive_and_bound_to_config(self):
        _, _, _, protocol = final_setup()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "registry"; create_registry(root, protocol)
            record = claim_attempt(root, protocol, "baseline", started_at_ns=24)
            self.assertEqual(record["config_id"], protocol["slots"][0]["config"]["config_id"])
            with self.assertRaises(FileExistsError): claim_attempt(root, protocol, "baseline", started_at_ns=25)
            with self.assertRaises(ValueError): claim_attempt(root, protocol, "unregistered", started_at_ns=25)
            with self.assertRaises(ValueError): claim_attempt(root, protocol, "candidate", started_at_ns=11)

    def test_missing_scores_not_silently_scored_as_failure(self):
        protocol = final_setup()[3]
        for scores in ({"candidate": [1, 1]}, {"baseline": [None, 0], "candidate": [1, 1]},
                       {"baseline": [0, 0], "candidate": [True, 1]}):
            with self.subTest(scores=scores), self.assertRaises(ValueError): panel_statistics(protocol, scores)

    def test_bounds_are_group_based_not_row_or_repeat_based(self):
        protocol = final_setup()[3]
        scores = {"baseline": [0, 0], "candidate": [1, 1]}
        first = panel_statistics(protocol, scores)
        expanded = copy.deepcopy(protocol)
        expanded["tasks"] *= 50
        scores = {k: v * 50 for k, v in scores.items()}
        second = panel_statistics(expanded, scores)
        self.assertEqual(first["panels"]["old"]["radius"], second["panels"]["old"]["radius"])
        self.assertEqual(second["panels"]["old"]["independent_group_count_assumed"], 1)
        expanded["slots"] += [dict(attempt_id="b2", role="baseline"), dict(attempt_id="c2", role="candidate")]
        scores.update(b2=scores["baseline"], c2=scores["candidate"])
        third = panel_statistics(expanded, scores)
        self.assertEqual(second["panels"], third["panels"])
        self.assertFalse(third["conditional_gate_passed"])

    def test_failed_attempt_remains_in_quality_denominator(self):
        protocol = final_setup()[3]
        protocol["slots"] += [dict(attempt_id="b2", role="baseline"), dict(attempt_id="c2", role="candidate")]
        report = panel_statistics(protocol, {"baseline": [1, 1], "candidate": [1, 1], "b2": [1, 1], "c2": [0, 0]})
        self.assertEqual(report["panels"]["new"]["estimated_delta"], -.5)
        self.assertFalse(report["retention_established"])

    def test_conditional_lower_bound_matches_declared_formula(self):
        protocol = final_setup()[3]
        protocol["panels"] = {f"g{i}": "old" if i < 200 else "new" for i in range(400)}
        protocol["tasks"] = [dict(source_group=g) for g in protocol["panels"]]
        report = panel_statistics(protocol, {"baseline": [0]*400, "candidate": [1]*400})
        expected = 1 - math.sqrt(2 * math.log(2 / .05) / 200)
        self.assertAlmostEqual(report["panels"]["old"]["conditional_lower_bound"], expected)
        self.assertTrue(report["conditional_gate_passed"])
        self.assertFalse(report["statistical_superiority_established"])

    def test_common_observer_projection_preserves_raw_rows_and_owner(self):
        attempt = dict(attempt_id="candidate", protocol_id="a"*64)
        labels = dict(schema=LABEL_SCHEMA, protocol_id="a"*64, contract_id="b"*64,
                      observer_id="owner", created_at_ns=40, rows=[],
                      terminals={"candidate": {"kind": "completed", "id": "c"*64}})
        projected = project_common_observer(labels, {"final_attempt": attempt}, "c"*64)
        self.assertEqual(projected["observer_id"], "owner")
        with self.assertRaises(ValueError): project_common_observer(labels, {"final_attempt": attempt}, "d"*64)


if __name__ == "__main__":
    unittest.main()
