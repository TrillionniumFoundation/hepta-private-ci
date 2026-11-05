"""Independent adversarial checks for the V15 research reference implementation."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from admission import Case, MatchedEvaluator, Protocol, Run, budget_digest
from admission_test_support import fixture_cost_protocol, fixture_ledger, fixture_registration
from authority import (Authority, COMPONENTS, GateDecision, Rejected, StructureDecision,
                       bundle, canonical, digest, public, sign)


def experiment(size=256):
    cases = [Case(str(i), str(i), "retained", "public question", {}, [1])
             for i in range(size)]
    protocol = fixture_cost_protocol(Protocol("independent-review", True, size, 0.05, 1, 0.25,
                        16, 1.0, ("retained",), (), ()))
    return cases, protocol


def model(bundle, predictor):
    return Run(bundle, "memory-cut", "train-cut", "executor-v1", budget_digest(experiment()[1]),
               predictor, "encoder-v1", "decoder-v1", "tools-v1")


def assess(evaluator, candidate, incumbent, horizon):
    return evaluator.evaluate(candidate, incumbent, fixture_ledger(evaluator, candidate),
                              fixture_ledger(evaluator, incumbent),
                              manifest={"bundle": candidate.bundle, "memory": candidate.memory})


class IndependentAdmissionReview(unittest.TestCase):
    def test_frozen_dataset_survives_callers_nested_mutation(self):
        cases, protocol = experiment()
        evaluator = MatchedEvaluator(cases, lambda: (lambda choice, payload: [choice]), protocol, registration=fixture_registration(cases, protocol,
                    model("new", None), model("old", None)))
        for case in cases:
            case.expected[0] = 2
            case.payload["after_freeze"] = "changed"
        result = assess(evaluator, model("new", lambda query: 1),
                        model("old", lambda query: 0), len(cases))
        self.assertTrue(all(row["correct"] for row in result["traces"]["candidate"]),
                        "caller mutation changed labels after their recorded identity was frozen")
        self.assertTrue(result["approved"], result["reasons"])

    def test_identical_predictors_do_not_gain_from_shared_executor_state(self):
        cases, protocol = experiment()

        class FiniteExecutor:
            def __init__(self):
                self.remaining = len(cases)

            def __call__(self, choice, payload):
                self.remaining -= 1
                return [1 if self.remaining >= 0 else 0]

        evaluator = MatchedEvaluator(cases, FiniteExecutor, protocol, registration=fixture_registration(cases, protocol,
                    model("new", None), model("old", None)))
        predictor = lambda query: 7
        result = assess(evaluator, model("new", predictor), model("old", predictor), len(cases))
        self.assertFalse(result["approved"],
                         "shared execution state created a false positive for identical predictors")
        self.assertEqual(result["paired_mean"], 0)
        self.assertFalse(any("unbound_cost" in reason for reason in result["reasons"]))

    def test_factory_reusing_one_executor_is_isolated_in_fresh_arms(self):
        cases, protocol = experiment()
        remaining = [len(cases)]
        def executor(choice, payload):
            remaining[0] -= 1
            return [int(remaining[0] >= 0)]
        candidate, incumbent = model("new", lambda query: 7), model("old", lambda query: 7)
        evaluator = MatchedEvaluator(cases, lambda: executor, protocol,
            registration=fixture_registration(cases, protocol, candidate, incumbent))
        result = assess(evaluator, candidate, incumbent, len(cases))
        self.assertEqual(result["paired_mean"], 0)
        self.assertFalse(result["approved"])
        self.assertTrue(result["resource_qualified"], result["reasons"])
        self.assertEqual(remaining, [len(cases)])

    def test_different_wrappers_cannot_share_backing_state_between_arms(self):
        cases, protocol = experiment()
        shared = {"calls": 0}
        def factory():
            def execute(choice, payload):
                shared["calls"] += 1
                return [int(shared["calls"] <= len(cases))]
            return execute
        candidate, incumbent = model("new", lambda query: 7), model("old", lambda query: 7)
        evaluator = MatchedEvaluator(cases, factory, protocol,
            registration=fixture_registration(cases, protocol, candidate, incumbent))
        result = assess(evaluator, candidate, incumbent, len(cases))
        self.assertEqual(result["paired_mean"], 0)
        self.assertFalse(result["approved"])
        self.assertTrue(all(row["correct"] for rows in result["traces"].values() for row in rows))
        self.assertEqual(shared, {"calls": 0})


class IndependentAuthorityReview(unittest.TestCase):
    """Protocol fixtures use fake model bytes and are not evidence of model quality."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "authority.sqlite"
        self.authority_key, self.admin, self.owner, self.reader, self.target = [
            Ed25519PrivateKey.generate() for _ in range(5)]
        self.authority = Authority(str(self.path), self.authority_key, public(self.admin),
                                   self.fixture_gate, self.fixture_structure)
        record = self.call("source", {"scope": "tenant", "id": "source", "expected_revision": 0,
                                      "body": "truth-v1", "active": True}, self.admin)
        self.source = {k: record[k] for k in ("id", "revision", "hash")}
        self.original = self.make_bundle(["a", "b"], acl=[public(self.reader), public(self.target)])
        self.call("create", {"cell": "original", "owner": public(self.owner), "bundle": self.original}, self.admin)

    def tearDown(self):
        self.authority.close()
        self.temp.cleanup()

    @staticmethod
    def fixture_gate(candidate, parents, manifest, *verified_components):
        return GateDecision(candidate, parents, True, digest(canonical({"fixture_only": candidate})))

    @staticmethod
    def fixture_structure(plan_digest, plan, verified_children):
        return StructureDecision(plan_digest, True, digest(canonical({"fixture_structure_only": plan_digest})))

    def make_bundle(self, addresses, acl=None, sources=None, label="v1"):
        return bundle("tenant", addresses, acl or [public(self.reader)],
                      sources if sources is not None else [self.source],
                      {name: (name + ":" + label).encode() for name in COMPONENTS})

    def call(self, operation, args, actor=None, request_id=None):
        request = sign(actor or self.owner, self.authority.identity, operation, args, request_id)
        return self.authority.apply(request)["result"]

    def head(self, cell="original", actor=None):
        return self.call("status", {"cell": cell}, actor or self.owner)["cell"]

    def pointer(self, cell="original", actor=None):
        head = self.head(cell, actor)
        return {"cell": cell, "epoch": head["epoch"], "expected": head["bundle"]}

    def read(self, address="a", actor=None):
        return self.call("read", {"scope": "tenant", "address": address}, actor or self.reader)

    def prepare(self):
        pointer = self.pointer()
        self.call("prepare", dict(pointer, target=public(self.target), transfer="move"))
        return dict(self.pointer(), transfer="move")

    def test_transfer_abort_fences_the_preparation_and_original_epochs(self):
        original_pointer = self.pointer()
        transfer_pointer = self.prepare()
        self.call("ready", dict(transfer_pointer, bundle=self.original), self.target)
        self.call("abort", transfer_pointer)
        with self.assertRaises(Rejected):
            self.call("commit", transfer_pointer, self.target)
        for pointer in (original_pointer, transfer_pointer):
            with self.assertRaises(Rejected):
                self.call("publish", dict(pointer, bundle=self.original))
        self.assertEqual(self.read()["owner"], public(self.owner))

    def test_source_revoked_after_ready_blocks_commit_and_all_old_model_reads(self):
        transfer_pointer = self.prepare()
        self.call("ready", dict(transfer_pointer, bundle=self.original), self.target)
        self.call("source", {"scope": "tenant", "id": "source", "expected_revision": 1,
                             "body": "truth-v1", "active": False}, self.admin)
        with self.assertRaises(Rejected):
            self.call("commit", transfer_pointer, self.target)
        self.call("abort", transfer_pointer)
        with self.assertRaises(Rejected):
            self.read()
        with self.assertRaises(Rejected):
            self.call("publish", dict(self.pointer(), bundle=self.original))

    def test_read_request_replay_rechecks_current_permission(self):
        request = sign(self.target, self.authority.identity, "read",
                       {"scope": "tenant", "address": "a"}, "replayed-read")
        self.authority.apply(request)
        self.call("restrict", dict(self.pointer(), acl=[public(self.reader)]))
        with self.assertRaises(Rejected):
            self.authority.apply(request)

    def test_restriction_survives_restart_and_old_bundle_republication(self):
        broader = self.original
        self.call("restrict", dict(self.pointer(), acl=[public(self.reader)]))
        self.authority.close()
        self.authority = Authority(str(self.path), self.authority_key, public(self.admin),
                                   self.fixture_gate, self.fixture_structure)
        with self.assertRaises(Rejected):
            self.read(actor=self.target)
        with self.assertRaises(Rejected):
            self.call("publish", dict(self.pointer(), bundle=broader))
        self.assertEqual(self.read()["acl"], [public(self.reader)])

    def test_split_cannot_drop_source_lineage_or_duplicate_addresses(self):
        before = self.head()
        acl = self.original["manifest"]["acl"]
        for children in ([{"cell": "left", "bundle": self.make_bundle(["a"], acl=acl, sources=[])},
                          {"cell": "right", "bundle": self.make_bundle(["b"], acl=acl)}],
                         [{"cell": "left", "bundle": self.make_bundle(["a", "b"], acl=acl)},
                          {"cell": "right", "bundle": self.make_bundle(["b"], acl=acl)}]):
            with self.assertRaises(Rejected):
                self.call("reshape", {"parents": [self.pointer()], "children": children})
            self.assertEqual(self.head(), before)
            self.assertEqual(self.read()["cell"], "original")

    def test_second_child_gate_failure_rolls_back_the_whole_split(self):
        acl = self.original["manifest"]["acl"]
        left = self.make_bundle(["a"], acl=acl)
        right = self.make_bundle(["b"], acl=acl)

        def one_child_rejected(candidate, parents, manifest, *verified_components):
            return GateDecision(candidate, parents, candidate != right["id"],
                                digest(canonical({"fixture_only": candidate})))

        self.authority.evaluator = one_child_rejected
        with self.assertRaises(Rejected):
            self.call("reshape", {"parents": [self.pointer()], "children": [
                {"cell": "left", "bundle": left}, {"cell": "right", "bundle": right}]})
        self.assertEqual(self.head()["state"], "active")
        self.assertEqual(self.read("a")["cell"], "original")
        self.assertEqual(self.read("b")["cell"], "original")
        self.assertEqual(self.authority.db.execute("SELECT count(*) FROM bundles WHERE id=?", (left["id"],)).fetchone()[0], 0)

    def test_successful_split_retires_parent_and_prevents_its_reuse(self):
        old_pointer = self.pointer()
        acl = self.original["manifest"]["acl"]
        self.call("reshape", {"parents": [old_pointer], "children": [
            {"cell": "left", "bundle": self.make_bundle(["a"], acl=acl)},
            {"cell": "right", "bundle": self.make_bundle(["b"], acl=acl)}]})
        self.assertEqual((self.read("a")["cell"], self.read("b")["cell"]), ("left", "right"))
        with self.assertRaises(Rejected):
            self.call("publish", dict(old_pointer, bundle=self.original))
        with self.assertRaises(Rejected):
            self.call("create", {"cell": "original", "owner": public(self.owner),
                                  "bundle": self.make_bundle(["c"])}, self.admin)

    def test_idempotency_key_conflict_cannot_change_owner_or_repeat_effect(self):
        request = sign(self.owner, self.authority.identity, "prepare",
                       dict(self.pointer(), target=public(self.target), transfer="move"), "fixed-id")
        result = self.authority.apply(request)
        self.assertEqual(self.authority.apply(request), result)
        self.assertEqual(self.head()["epoch"], 2)
        altered = sign(self.owner, self.authority.identity, "prepare",
                       dict(self.pointer(), target=public(self.target), transfer="other"), "fixed-id")
        with self.assertRaises(Rejected):
            self.authority.apply(altered)
        self.assertEqual(self.head()["epoch"], 2)

    def test_commit_fences_former_owner_after_restart(self):
        old_pointer = self.pointer()
        transfer_pointer = self.prepare()
        self.call("ready", dict(transfer_pointer, bundle=self.original), self.target)
        self.call("commit", transfer_pointer, self.target)
        self.authority.close()
        self.authority = Authority(str(self.path), self.authority_key, public(self.admin),
                                   self.fixture_gate, self.fixture_structure)
        with self.assertRaises(Rejected):
            self.call("publish", dict(old_pointer, bundle=self.original))
        self.assertEqual(self.read()["owner"], public(self.target))

    def test_revoke_all_readers_is_local_to_the_cell(self):
        other = self.make_bundle(["unrelated"], acl=[public(self.reader)])
        self.call("create", {"cell": "unrelated", "owner": public(self.owner), "bundle": other}, self.admin)
        self.call("restrict", dict(self.pointer(), acl=[]))
        for actor in (self.reader, self.target):
            with self.assertRaises(Rejected):
                self.read(actor=actor)
        self.assertEqual(self.read("unrelated")["cell"], "unrelated")
        self.assertEqual(self.head()["state"], "active")
        self.authority.close()
        self.authority = Authority(str(self.path), self.authority_key, public(self.admin),
                                   self.fixture_gate, self.fixture_structure)
        with self.assertRaises(Rejected):
            self.read()
        self.assertEqual(self.read("unrelated")["cell"], "unrelated")
        # The historical bundle ACL is wider than the current deny-all policy.
        # Recovery must still work, while retaining the current policy.
        pointer = self.pointer(actor=self.admin)
        self.call("recover_prepare", dict(pointer, target=public(self.target), transfer="deny-all-recovery"), self.admin)
        transfer = {"cell": "original", "epoch": pointer["epoch"] + 1,
                    "expected": pointer["expected"], "transfer": "deny-all-recovery"}
        self.call("ready", dict(transfer, bundle=self.original), self.target)
        self.call("commit", transfer, self.target)
        for actor in (self.reader, self.target):
            with self.assertRaises(Rejected):
                self.read(actor=actor)
        self.assertEqual(self.read("unrelated")["cell"], "unrelated")

    def test_merge_uses_permission_intersection_and_rejects_union(self):
        other = self.make_bundle(["c"], acl=[public(self.reader), public(self.admin)])
        self.call("create", {"cell": "other", "owner": public(self.owner), "bundle": other}, self.admin)
        parents = [self.pointer(), self.pointer("other")]
        union = self.make_bundle(["a", "b", "c"], acl=[public(self.reader), public(self.target), public(self.admin)])
        with self.assertRaises(Rejected):
            self.call("reshape", {"parents": parents, "children": [{"cell": "merged", "bundle": union}]})
        self.assertEqual(self.read("a")["cell"], "original")
        self.assertEqual(self.read("c")["cell"], "other")
        intersection = self.make_bundle(["a", "b", "c"], acl=[public(self.reader)])
        self.call("reshape", {"parents": parents, "children": [{"cell": "merged", "bundle": intersection}]})
        self.assertEqual(self.read("c")["cell"], "merged")
        with self.assertRaises(Rejected):
            self.read(actor=self.target)
        with self.assertRaises(Rejected):
            self.read("c", self.admin)

    def test_truthy_non_boolean_gate_and_nonhex_evidence_do_not_publish(self):
        item = self.make_bundle(["a", "b"], acl=self.original["manifest"]["acl"], label="v2")
        for approved, evidence in (("false", "a" * 64), (1, "a" * 64), (True, "z" * 64)):
            with self.subTest(approved=approved, evidence=evidence):
                self.authority.evaluator = lambda candidate, parents, manifest, *parts: GateDecision(
                    candidate, parents, approved, evidence)
                with self.assertRaises(Rejected):
                    self.call("publish", dict(self.pointer(), bundle=item))
                self.assertEqual(self.head()["bundle"], self.original["id"])

    def test_evaluator_annotation_cannot_corrupt_signed_candidate_manifest(self):
        item = self.make_bundle(["a", "b"], acl=self.original["manifest"]["acl"], label="v2")

        def annotate(candidate, parents, manifest, *parts):
            manifest["scope"] = "annotation-that-is-not-the-signed-scope"
            return GateDecision(candidate, parents, True, "a" * 64)

        self.authority.evaluator = annotate
        try:
            self.call("publish", dict(self.pointer(), bundle=item))
        except Rejected:
            self.assertEqual(self.head()["bundle"], self.original["id"])
        else:
            received = self.read()["bundle"]
            self.assertEqual(received["id"], digest(canonical(received["manifest"])))
            self.assertEqual(received["manifest"]["scope"], "tenant")

    def test_individual_child_approvals_cannot_replace_joint_structure_admission(self):
        acl = self.original["manifest"]["acl"]
        children = [{"cell": "left", "bundle": self.make_bundle(["a"], acl=acl)},
                    {"cell": "right", "bundle": self.make_bundle(["b"], acl=acl)}]
        callbacks = (
            None,
            lambda identity, plan, parts: StructureDecision(identity, False, "a" * 64),
            lambda identity, plan, parts: StructureDecision("0" * 64, True, "a" * 64),
        )
        for callback in callbacks:
            with self.subTest(callback=callback):
                self.authority.structure_evaluator = callback
                with self.assertRaises(Rejected):
                    self.call("reshape", {"parents": [self.pointer()], "children": children})
                self.assertEqual(self.read("a")["cell"], "original")
                self.assertEqual(self.read("b")["cell"], "original")

    def test_admin_can_recover_unreachable_owner_without_old_owner_signature(self):
        old_pointer = self.pointer()
        arguments = dict(old_pointer, target=public(self.target), transfer="recovery")
        with self.assertRaises(Rejected):
            self.call("recover_prepare", arguments, self.reader)
        self.call("recover_prepare", arguments, self.admin)
        transfer = {"cell": "original", "epoch": old_pointer["epoch"] + 1,
                    "expected": old_pointer["expected"], "transfer": "recovery"}
        with self.assertRaises(Rejected):
            self.call("publish", dict(old_pointer, bundle=self.original))
        with self.assertRaises(Rejected):
            self.call("abort", transfer)
        self.call("ready", dict(transfer, bundle=self.original), self.target)
        self.call("commit", transfer, self.target)
        self.assertEqual(self.read()["owner"], public(self.target))

    def test_rejected_request_id_cannot_be_rebound_to_a_successful_payload(self):
        item = self.make_bundle(["a", "b"], acl=self.original["manifest"]["acl"], label="v2")
        denied = sign(self.owner, self.authority.identity, "publish",
                      dict(self.pointer(), epoch=999, bundle=item), "one-logical-write")
        with self.assertRaises(Rejected) as error:
            self.authority.apply(denied)
        self.assertIsNotNone(error.exception.receipt)
        corrected = sign(self.owner, self.authority.identity, "publish",
                         dict(self.pointer(), bundle=item), "one-logical-write")
        with self.assertRaises(Rejected):
            self.authority.apply(corrected)
        self.assertEqual(self.head()["bundle"], self.original["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
