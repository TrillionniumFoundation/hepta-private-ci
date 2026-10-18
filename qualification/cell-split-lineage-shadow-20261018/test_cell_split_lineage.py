import unittest

from cell_fast_path_actionir import canonical_digest
from cell_split_lineage import CellArtifactV1, CellChildSpecV1, CellEvaluationLedgerV1, CellSplitPolicyV1, decide_cell_split, revoke_cell


D, E, F, G, H, I = tuple(x * 64 for x in "abcdef")


def parent():
    return CellArtifactV1("cell.parent", None, D, E, F, G, H, "snap-1", 1, 0, ("audio", "text"), "general", I)


def child(name, tag):
    return CellChildSpecV1(name, tag, D, E, H, ("audio", "text"), I)


def ledger(child_id, *, gain=100, regression=5, calibration=3, ood=0, latency=10, memory=10, safety=0, rollback=True):
    payload = {"child": child_id, "gain": gain, "regression": regression, "calibration": calibration, "ood": ood, "latency": latency, "memory": memory, "safety": safety, "rollback": rollback}
    return CellEvaluationLedgerV1("cell.parent", child_id, F, gain, regression, calibration, ood, latency, memory, safety, rollback, canonical_digest(payload))


def policy(**overrides):
    values = dict(benchmark_digest=F, min_task_gain_lcb_ppm=50, max_global_regression_ppm=10, max_calibration_regression_ppm=10, min_ood_delta_ppm=-10, max_latency_delta_ns=20, max_memory_delta_bytes=20)
    values.update(overrides)
    return CellSplitPolicyV1(**values)


class CellSplitLineageTests(unittest.TestCase):
    def test_accepts_children_with_measured_gain(self):
        decision = decide_cell_split(parent(), "split-1", (child("child.a", "vision"), child("child.b", "audio")), (ledger("child.a"), ledger("child.b", gain=80)), policy())
        self.assertEqual(decision.accepted_child_ids, ("child.a", "child.b"))
        self.assertEqual(decision.authority, "DENY_ALL")
        self.assertFalse(decision.effect_admitted)

    def test_keeps_only_children_passing_gate(self):
        decision = decide_cell_split(parent(), "split-2", (child("child.a", "vision"), child("child.b", "audio")), (ledger("child.a"), ledger("child.b", gain=10)), policy())
        self.assertEqual(decision.accepted_child_ids, ("child.a",))

    def test_no_child_meets_gate_fails_closed(self):
        decision = decide_cell_split(parent(), "split-3", (child("child.a", "vision"), child("child.b", "audio")), (ledger("child.a", gain=10), ledger("child.b", safety=1)), policy())
        self.assertEqual(decision.reason_codes, ("NO_CHILD_MEETS_SPLIT_GATE",))
        self.assertEqual(decision.accepted_child_ids, ())

    def test_lineage_and_ledger_bindings_are_required(self):
        with self.assertRaisesRegex(ValueError, "LEDGER_SET"):
            decide_cell_split(parent(), "split-4", (child("child.a", "vision"), child("child.b", "audio")), (ledger("child.a"),), policy())
        with self.assertRaisesRegex(ValueError, "PARENT"):
            bad = CellEvaluationLedgerV1("wrong", "child.a", F, 100, 1, 1, 0, 1, 1, 0, True, I)
            decide_cell_split(parent(), "split-5", (child("child.a", "vision"), child("child.b", "audio")), (bad, ledger("child.b")), policy())

    def test_split_requires_two_children_and_unique_ids(self):
        with self.assertRaisesRegex(ValueError, "TWO_CHILDREN"):
            decide_cell_split(parent(), "split-6", (child("child.a", "vision"),), (ledger("child.a"),), policy())
        with self.assertRaisesRegex(ValueError, "UNIQUE"):
            decide_cell_split(parent(), "split-7", (child("child.a", "vision"), child("child.a", "audio")), (ledger("child.a"),), policy())

    def test_revocation_is_typed_and_digest_bound(self):
        receipt = revoke_cell(parent(), F)
        self.assertTrue(receipt.revoked)
        self.assertEqual(receipt.authority, "DENY_ALL")
        self.assertFalse(receipt.effect_admitted)

    def test_authority_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            CellArtifactV1("bad", None, D, E, F, G, H, "snap", 1, 0, ("text",), "bad", I, "OWNER")
