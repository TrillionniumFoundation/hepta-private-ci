"""Native HEPLCP04 interoperability and adversarial structural controls.

Positive wire/payload bytes are emitted by the unchanged pinned Rust codec and
coordinator. The policy, selection and next-use observations remain synthetic.
The encoder below is used only for hostile mutations, never native evidence.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cell_adoption_readback as native
import cell_learning_iteration_join as legacy
import cell_learning_local_decision_join as local
from test_cell_learning_iteration_join import MutationWriter
from test_cell_learning_scope_join import fixture_profile, wire

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evidence/heplcp04-interop-20261111/native-fixture.json"
NATIVE_FIXTURE_SHA256 = "b873d6f0606100ec8a3246548009b6afda5aa9fbc55e2bd85a4c6fed7fd81a46"


class MutationV4Writer(MutationWriter):
    def observation(self, value):
        if value["tag"] != 9:
            return super().observation(value)
        self.number(9, 1)
        self.number(value["disposition"], 1)
        for name in local.FIELDS:
            self.digest(value[name])


def mutated_encoding(snapshot):
    w = MutationV4Writer()
    w.raw.extend(local.MAGIC)
    request, owners = snapshot["request"], snapshot["owners"]
    for name in legacy.REQUEST_IDS:
        w.identifier(request[name])
    for name in ("completed_task_receipt", "selected_artifact_digest", "evaluation_profile"):
        w.digest(request[name])
    w.bundle(request["selected_bundle"])
    envelope = request["envelope"]
    w.identifier(envelope["envelope_id"])
    for name in legacy.ENVELOPE_DIGESTS:
        w.digest(envelope[name])
    for name, width in (("maximum_files", 2), ("maximum_diff_bytes", 8), ("maximum_candidates", 2),
                        ("maximum_parallel_sandboxes", 1), ("expiry_unix_seconds", 8)):
        w.number(envelope[name], width)
    for name in legacy.BUDGET_LIMITS:
        w.number(request["budget"][name], 4 if name == "maximum_dataset_rows" else 8)
    w.digest(owners["evidence_trust_digest"])
    for name in legacy.OWNER_IDS:
        w.identifier(owners[name])
    w.number(len(snapshot["receipts"]), 1)
    for receipt in snapshot["receipts"]:
        w.identifier(receipt["operation_id"])
        w.digest(receipt["predecessor"])
        w.identifier(receipt["actor_id"])
        w.digest(receipt["evidence_digest"])
        w.number(receipt["observed_unix_seconds"], 8)
        w.observation(receipt["observation"])
    w.digest(snapshot["head_digest"])
    return bytes(w.raw)


def rehash(snapshot):
    head = legacy._initial_head(snapshot["request"], snapshot["owners"])
    for receipt in snapshot["receipts"]:
        receipt["predecessor"] = head
        head = native.sha(local.receipt_signing_bytes(receipt))
    snapshot["head_digest"] = head
    return mutated_encoding(snapshot)


class LocalDecisionInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = FIXTURE.read_bytes()
        if native.sha(raw) != NATIVE_FIXTURE_SHA256:
            raise AssertionError("native fixture bytes changed")
        cls.fixture = json.loads(raw)
        if (cls.fixture["schema"] != "trnm-heplcp04-native-codec-fixture-v1" or
            cls.fixture["scope"] != "exact-native-codec-and-coordinator-engineering-fixture-only" or
            cls.fixture["hepta_source_commit"] != "afd2c91b3b9ef75ab9a174e3af772ad322118f7a"):
            raise AssertionError("native fixture scope/source changed")
        if cls.fixture["original_input_sha256"] != "49687e0ece90dceb6409978616700c0b32ec342631a1941994ae3b7a886a7496":
            raise AssertionError("original source input changed")
        for field in ("ordinary_task_executed", "actual_training_executed", "evaluation_executed",
                      "actual_next_use_executed", "hepta_final_use_accepted", "production_activation"):
            if cls.fixture[field] is not False:
                raise AssertionError("native fixture gained authority: " + field)
        cls.cases = cls.fixture["cases"]
        if [case["choice"] for case in cls.cases] != ["AdoptCandidate", "DeferCandidate", "RetainParent"]:
            raise AssertionError("native choice roster changed")

    def inputs(self, index=0):
        case = self.cases[index]
        initial, selection, completed = [bytes.fromhex(case[name + "_hex"])
                                          for name in ("initial", "selection", "completed")]
        snapshot, _ = local.decode_native_local_checkpoint(completed)
        profile = wire(fixture_profile(initial, snapshot))
        frozen = legacy.frozen_expectations_from_initial_checkpoint(initial)
        return selection, completed, profile, frozen

    def review(self, selection_raw, completed_raw, profile_raw, frozen, **pins):
        return local.review_native_local_decision(selection_raw, completed_raw, profile_raw,
            expected_selection_sha256=pins.get("selection", native.sha(selection_raw)),
            expected_completed_sha256=pins.get("completed", native.sha(completed_raw)),
            expected_root_profile_sha256=pins.get("profile", native.sha(profile_raw)), frozen=frozen)

    def test_all_native_cuts_and_24_original_signing_payloads_match(self):
        for index, case in enumerate(self.cases):
            for name in ("initial", "proposal"):
                legacy.decode_native_learning_checkpoint(bytes.fromhex(case[name + "_hex"]))
            for name, stage in (("local", 5), ("selection", 6), ("completed", None)):
                snapshot, replay = local.decode_native_local_checkpoint(bytes.fromhex(case[name + "_hex"]))
                self.assertEqual(replay["next_stage"], stage)
            self.assertEqual(replay["head"], case["completed_head"])
            self.assertEqual(replay["next_task_bundle"], case["selected_bundle"])
            for receipt, original in zip(snapshot["receipts"], case["receipt_signing_payloads_hex"], strict=True):
                self.assertEqual(local.receipt_signing_bytes(receipt).hex(), original)
            signed = bytes.fromhex(case["receipt_signing_payloads_hex"][5])
            self.assertTrue(signed.startswith(local.DOMAIN))
            self.assertFalse(signed.startswith(legacy.RECEIPT_DOMAIN))
            self.assertEqual(self.review(*self.inputs(index))["root_scope_review"]["scope_binding"], case["scope_binding"])

    def test_three_choices_keep_qualification_closed_and_never_relabel_no_update(self):
        for index in range(3):
            result = self.review(*self.inputs(index))
            self.assertEqual(result["local_disposition"], local.CHOICES[index])
            self.assertEqual(result["retained_model"], index != 0)
            self.assertEqual((result["no_update"], result["evaluation_disposition"],
                              result["proposal_disposition"]), (False, "qualified", "update_candidates"))
            self.assertEqual(result["receipt_count"], 8)
            self.assertEqual(result["next_use_provenance"]["status"], "SAME_ORIGINAL_ACTOR_DISTINCT_RUN_ONLY")
            for field in ("acknowledged_use_observed", "full_learning_iteration_completed",
                          "source_execution_authenticated", "learning_signatures_verified",
                          "policy_origin_authenticated", "independent_consumer_verified",
                          "physical_installation_accepted", "hepta_final_use_accepted", "production_activation"):
                self.assertIs(result[field], False, field)
            self.assertEqual((result["authority"], result["current_permission"], result["qualification"]),
                             ("DENY_ALL", "NOT_EXPORTED", "HOLD_NO_GO"))

    def test_original_legacy_reader_remains_closed_to_v4_and_new_reader_rejects_relabels(self):
        for case in self.cases:
            raw = bytes.fromhex(case["completed_hex"])
            with self.assertRaisesRegex(ValueError, "LEARNING_CHECKPOINT_VERSION"):
                legacy.decode_native_learning_checkpoint(raw)
            for magic in (b"HEPLCP01", b"HEPLCP02", b"HEPLCP03", b"HEPLCP05"):
                with self.subTest(magic=magic), self.assertRaisesRegex(ValueError, "LEARNING_CHECKPOINT_VERSION"):
                    local.decode_native_local_checkpoint(magic + raw[8:])
        original = bytes.fromhex(self.cases[0]["proposal_hex"])
        with self.assertRaises(ValueError):
            local.decode_native_local_checkpoint(local.MAGIC + original[8:])

    def test_boundaries_reject_nonbytes_truncation_trailing_data_and_excess_receipts(self):
        raw = bytes.fromhex(self.cases[0]["completed_hex"])
        for changed in (bytearray(raw), memoryview(raw), "HEPLCP04", b"x" * 8193,
                        raw[:7], raw[:50], raw[:-1], raw + b"\0"):
            with self.subTest(kind=type(changed).__name__), self.assertRaises(ValueError):
                local.decode_native_local_checkpoint(changed)
        snapshot, _ = local.decode_native_local_checkpoint(raw)
        snapshot["receipts"].append(copy.deepcopy(snapshot["receipts"][-1]))
        with self.assertRaisesRegex(ValueError, "LEARNING_CHECKPOINT_RECEIPTS"):
            local.decode_native_local_checkpoint(mutated_encoding(snapshot))

    def test_unknown_disposition_and_zero_policy_reason_are_refused(self):
        for field, value, error in (("disposition", 3, "LOCAL_DECISION_ENUM"),
                                    ("policy_digest", "0" * 64, "LEARNING_ZERO_DIGEST"),
                                    ("reason_digest", "0" * 64, "LEARNING_ZERO_DIGEST")):
            snapshot, _ = local.decode_native_local_checkpoint(self.inputs()[1])
            snapshot["receipts"][5]["observation"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                local.decode_native_local_checkpoint(mutated_encoding(snapshot))

    def test_rehashed_proposal_candidate_and_selected_bundle_substitution_are_refused(self):
        for index in range(3):
            for field in ("proposal_head", "candidate_bundle", "selected_bundle"):
                snapshot, _ = local.decode_native_local_checkpoint(self.inputs(index)[1])
                snapshot["receipts"][5]["observation"][field] = "ab" * 32
                with self.subTest(index=index, field=field), self.assertRaisesRegex(ValueError, "LOCAL_DECISION_BINDING"):
                    local.decode_native_local_checkpoint(rehash(snapshot))

    def test_evaluator_cannot_issue_local_choice_and_original_owners_bind_every_tail(self):
        for index in (5, 6, 7):
            snapshot, _ = local.decode_native_local_checkpoint(self.inputs()[1])
            snapshot["receipts"][index]["actor_id"] = snapshot["owners"]["evaluator"]
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "LEARNING_ACTOR"):
                local.decode_native_local_checkpoint(rehash(snapshot))

    def test_choice_cannot_skip_selection_repeat_it_or_follow_no_update(self):
        for mutation in ("skip", "repeat", "evaluation_no_update", "proposal_no_update"):
            snapshot, _ = local.decode_native_local_checkpoint(self.inputs()[1])
            if mutation == "skip":
                del snapshot["receipts"][6]
            elif mutation == "repeat":
                snapshot["receipts"][6] = copy.deepcopy(snapshot["receipts"][5])
            else:
                snapshot["receipts"][3 if mutation == "evaluation_no_update" else 4]["observation"]["disposition"] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                local.decode_native_local_checkpoint(rehash(snapshot))

    def test_wrong_selected_version_and_foreign_next_task_are_refused_even_after_rehash(self):
        for index in range(3):
            for mutation in ("selection", "next_bundle", "actor", "run", "selection_receipt"):
                snapshot, _ = local.decode_native_local_checkpoint(self.inputs(index)[1])
                final = snapshot["receipts"][-1]["observation"]
                if mutation == "selection":
                    snapshot["receipts"][6]["observation"]["candidate_bundle"] = "ab" * 32
                elif mutation == "next_bundle":
                    final["candidate_bundle" if index == 0 else "retained_bundle"] = "ab" * 32
                elif mutation == "actor":
                    final["state_partition"]["agent_id"] = "different-actor"
                elif mutation == "run":
                    final["state_partition"]["run_id"] = snapshot["request"]["source_run_id"]
                else:
                    final["selection_digest"] = "ab" * 32
                with self.subTest(index=index, mutation=mutation), self.assertRaises(ValueError):
                    local.decode_native_local_checkpoint(rehash(snapshot))

    def test_wrong_use_kind_and_changed_operation_time_predecessor_are_refused(self):
        for field, value, error in (("operation_id", "other-operation", "LEARNING_OPERATION"),
                                    ("observed_unix_seconds", 1, "LEARNING_RECEIPT_TIME"),
                                    ("predecessor", "ab" * 32, "LEARNING_RECEIPT_PREDECESSOR")):
            snapshot, _ = local.decode_native_local_checkpoint(self.inputs()[1])
            snapshot["receipts"][6][field] = value
            # Rehash all dependent heads for semantic mutations. A predecessor
            # attack must keep its forged predecessor; require its exact refusal.
            raw = mutated_encoding(snapshot) if field == "predecessor" else rehash(snapshot)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                local.decode_native_local_checkpoint(raw)
        for index in range(3):
            snapshot, _ = local.decode_native_local_checkpoint(self.inputs(index)[1])
            final = snapshot["receipts"][-1]["observation"]
            if index == 0:
                final.update(tag=7, retained_bundle=final.pop("candidate_bundle"),
                             task_owner_publication=final.pop("state_cutover_receipt"))
            else:
                final.update(tag=6, candidate_bundle=final.pop("retained_bundle"),
                             state_cutover_receipt=final.pop("task_owner_publication"))
            with self.assertRaisesRegex(ValueError, "LOCAL_DECISION_STAGE_ORDER"):
                local.decode_native_local_checkpoint(rehash(snapshot))

    def test_expired_receipt_cannot_become_current_by_rehashing(self):
        snapshot, _ = local.decode_native_local_checkpoint(self.inputs()[1])
        snapshot["receipts"][-1]["observed_unix_seconds"] = snapshot["request"]["envelope"]["expiry_unix_seconds"]
        with self.assertRaisesRegex(ValueError, "LEARNING_RECEIPT_TIME"):
            local.decode_native_local_checkpoint(rehash(snapshot))

    def test_external_byte_pins_and_exact_original_receipt_prefix_are_mandatory(self):
        values = self.inputs()
        for field in ("selection", "completed", "profile"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.review(*values, **{field: "ab" * 32})
        selection, _, profile, frozen = values
        with self.assertRaisesRegex(ValueError, "LOCAL_DECISION_EXACT_CONTINUATION"):
            self.review(selection, selection, profile, frozen)
        snapshot, _ = local.decode_native_local_checkpoint(values[1])
        snapshot["receipts"][6]["evidence_digest"] = "ab" * 32
        with self.assertRaisesRegex(ValueError, "LOCAL_DECISION_EXACT_CONTINUATION"):
            self.review(selection, rehash(snapshot), profile, frozen)

    def test_frozen_request_and_original_root_scope_cannot_be_relabelled(self):
        selection, completed, profile, frozen = self.inputs()
        bad_frozen = copy.deepcopy(frozen)
        bad_frozen["request"]["operation_id"] = "another-operation"
        bad_frozen["initial_head"] = legacy._initial_head(bad_frozen["request"], bad_frozen["owners"])
        with self.assertRaisesRegex(ValueError, "LEARNING_FROZEN_REQUEST"):
            self.review(selection, completed, profile, bad_frozen)
        for field, value in (("schema_version", 1), ("identity_digest", "0" * 64)):
            bad_profile = json.loads(profile)
            bad_profile[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.review(selection, completed, wire(bad_profile), frozen)
        bad_profile = json.loads(profile)
        bad_profile["update_scope"]["update_rule"] = "ab" * 32
        with self.assertRaises(ValueError):
            self.review(selection, completed, wire(bad_profile), frozen)
        bad_profile["update_scope"]["binding"] = native.sha(
            b"hepta.learning.frozen-update-scope.v2\0" + bytes.fromhex(frozen["initial_head"]) +
            b"\1" + bytes.fromhex("ab" * 32))
        with self.assertRaisesRegex(ValueError, "LEARNING_ROOT_SCOPE_RULE"):
            self.review(selection, completed, wire(bad_profile), frozen)

    def test_cli_has_only_readback_output_and_requires_all_four_pins(self):
        selection, completed, profile, frozen = self.inputs(1)
        with tempfile.TemporaryDirectory() as directory:
            files = {"selection-checkpoint": selection, "completed-checkpoint": completed,
                     "root-profile": profile, "freeze": wire(frozen)}
            command = [sys.executable, "-B", str(ROOT / "scripts/cell_learning_local_decision_join.py")]
            for name, raw in files.items():
                path = Path(directory) / name
                path.write_bytes(raw)
                command.extend(("--" + name, str(path), "--" + name + "-sha256", native.sha(raw)))
            result = subprocess.run(command, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), self.review(selection, completed, profile, frozen))
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), sorted(files))
            refused = subprocess.run(command[:-2], capture_output=True, timeout=15)
            self.assertNotEqual(refused.returncode, 0)


if __name__ == "__main__":
    unittest.main()
