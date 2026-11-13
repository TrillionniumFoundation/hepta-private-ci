"""Read exact HEPLCP04 local-choice receipts without granting use authority.

The explicit profile preserves qualified Evaluation and UpdateCandidates even
when local policy keeps the parent. The checkpoint contains receipt commitments,
not their signatures or a native-use export; no ACK or FinalUse is inferred.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import cell_adoption_readback as native
import cell_learning_iteration_join as legacy
import cell_learning_scope_join as scoped

MAGIC = b"HEPLCP04"
DOMAIN = b"hepta.learning.iteration-local-decision.v2\0"
FIELDS = ("proposal_head", "candidate_bundle", "selected_bundle", "policy_digest", "reason_digest")
CHOICES = ("adopt_candidate", "defer_candidate", "retain_parent")
REPORT_SCHEMA = "trnm-cell-learning-local-decision-structural-readback-v1"


class _Reader(legacy._Reader):
    def observation(self):
        if self.raw[self.offset:self.offset + 1] != b"\x09":
            return super().observation()
        self.take(1)
        choice = self.number(1)
        native.require(choice in range(3), "LOCAL_DECISION_ENUM")
        return dict(tag=9, disposition=choice, **{name: self.digest() for name in FIELDS})


def receipt_signing_bytes(receipt):
    value = receipt["observation"]
    if value["tag"] != 9:
        domain = legacy.RECEIPT_DOMAIN
        observation = legacy._observation_signing_bytes(value)
    else:
        domain = DOMAIN
        native.require(type(value["disposition"]) is int and value["disposition"] in range(3),
                       "LOCAL_DECISION_ENUM")
        observation = bytes((9, value["disposition"])) + b"".join(
            legacy._digest(value[name]) for name in FIELDS)
    return (domain + legacy._id(receipt["operation_id"]) + legacy._digest(receipt["predecessor"])
            + legacy._id(receipt["actor_id"]) + legacy._digest(receipt["evidence_digest"])
            + legacy._number(receipt["observed_unix_seconds"], 8, minimum=1) + observation)


def _replay(snapshot):
    request, owners, receipts = snapshot["request"], snapshot["owners"], snapshot["receipts"]
    native.require(6 <= len(receipts) <= 8 and
                   [r["observation"]["tag"] for r in receipts[:6]] == [0, 1, 2, 3, 4, 9],
                   "LOCAL_DECISION_STAGE_ORDER")
    prefix = dict(request=request, owners=owners, receipts=receipts[:5],
                  head_digest=receipts[5]["predecessor"])
    replay = legacy._replay(prefix)
    native.require(replay["next_stage"] == 5 and not replay["no_update"],
                   "LOCAL_DECISION_QUALIFIED_PROPOSAL")
    choice = receipts[5]["observation"]
    candidate = replay["candidate_bundle"]
    selected = candidate if choice["disposition"] == 0 else replay["selected_bundle"]
    native.require(choice["proposal_head"] == replay["head"] and
                   choice["candidate_bundle"] == candidate and
                   choice["selected_bundle"] == selected, "LOCAL_DECISION_BINDING")
    head, prior_time, selection = replay["head"], receipts[4]["observed_unix_seconds"], None
    for index, receipt in enumerate(receipts[5:], 5):
        value = receipt["observation"]
        expected_tag = 9 if index == 5 else 5 if index == 6 else 6 if choice["disposition"] == 0 else 7
        native.require(value["tag"] == expected_tag, "LOCAL_DECISION_STAGE_ORDER")
        owner = owners["selector" if index < 7 else "next_use_observer"]
        native.require(receipt["operation_id"] == request["operation_id"], "LEARNING_OPERATION")
        native.require(receipt["actor_id"] == owner, "LEARNING_ACTOR")
        native.require(receipt["predecessor"] == head, "LEARNING_RECEIPT_PREDECESSOR")
        observed = receipt["observed_unix_seconds"]
        native.require(0 < observed < request["envelope"]["expiry_unix_seconds"]
                       and observed >= prior_time, "LEARNING_RECEIPT_TIME")
        if index == 6:
            native.require(value["candidate_bundle"] == selected, "LEARNING_SELECTION_BUNDLE")
            selection = value["selection_digest"]
        elif index == 7:
            native.require(value["candidate_bundle" if expected_tag == 6 else "retained_bundle"] == selected,
                           "LEARNING_NEXT_USE_BUNDLE")
            partition = value["state_partition"]
            native.require(all(partition[name] == request[name] for name in
                               ("principal_id", "agent_id", "cell_id")) and
                           partition["run_id"] != request["source_run_id"] and
                           value["selection_digest"] == selection, "LEARNING_NEXT_USE_PARTITION")
        head, prior_time = native.sha(receipt_signing_bytes(receipt)), observed
    native.require(head == snapshot["head_digest"], "LEARNING_CHECKPOINT_HEAD")
    replay.update(head=head, next_stage={6: 5, 7: 6, 8: None}[len(receipts)],
                  next_task_bundle=selected, local_decision=copy.deepcopy(choice),
                  retained_model=choice["disposition"] != 0)
    return replay


def decode_native_local_checkpoint(raw):
    """Decode the original bounded codec; HEPLCP02/03 are separate profiles."""
    reader = _Reader(raw)
    native.require(reader.take(8) == MAGIC, "LEARNING_CHECKPOINT_VERSION")
    request = {name: reader.identifier() for name in legacy.REQUEST_IDS}
    for name in ("completed_task_receipt", "selected_artifact_digest", "evaluation_profile"):
        request[name] = reader.digest()
    request["selected_bundle"] = reader.bundle()
    envelope = dict(envelope_id=reader.identifier())
    envelope.update({name: reader.digest() for name in legacy.ENVELOPE_DIGESTS})
    for name, width in (("maximum_files", 2), ("maximum_diff_bytes", 8), ("maximum_candidates", 2),
                        ("maximum_parallel_sandboxes", 1), ("expiry_unix_seconds", 8)):
        envelope[name] = reader.number(width)
    request["envelope"] = envelope
    request["budget"] = {name: reader.number(4 if name == "maximum_dataset_rows" else 8)
                         for name in legacy.BUDGET_LIMITS}
    owners = dict(evidence_trust_digest=reader.digest())
    owners.update({name: reader.identifier() for name in legacy.OWNER_IDS})
    count = reader.number(1)
    native.require(6 <= count <= 8, "LEARNING_CHECKPOINT_RECEIPTS")
    receipts = []
    for _ in range(count):
        receipts.append(dict(operation_id=reader.identifier(), predecessor=reader.digest(),
            actor_id=reader.identifier(), evidence_digest=reader.digest(),
            observed_unix_seconds=reader.number(8), observation=reader.observation()))
    snapshot = dict(request=request, owners=owners, receipts=receipts, head_digest=reader.digest())
    native.require(reader.offset == len(raw), "LEARNING_CHECKPOINT_TRAILING_BYTES")
    return snapshot, _replay(snapshot)


def review_native_local_decision(selection_raw, completed_raw, root_profile_raw, *,
        expected_selection_sha256, expected_completed_sha256, expected_root_profile_sha256, frozen):
    """Bind two original codec cuts and a separately pinned scoped Root profile."""
    decoded = []
    for raw, pin in ((selection_raw, expected_selection_sha256), (completed_raw, expected_completed_sha256)):
        native.require(type(raw) is bytes and len(raw) <= legacy.MAX_CHECKPOINT, "LEARNING_CHECKPOINT_LIMIT")
        native.require(native.sha(raw) == native.hex_digest(pin), "LEARNING_CHECKPOINT_PIN")
        decoded.append(decode_native_local_checkpoint(raw))
    (selection, before), (completed, replay) = decoded
    native.fields(frozen, "schema initial_head request owners", "LEARNING_FREEZE_FIELDS")
    native.require(frozen["schema"] == legacy.FREEZE_SCHEMA, "LEARNING_FREEZE_SCHEMA")
    frozen_head = legacy._initial_head(frozen["request"], frozen["owners"])
    native.require(frozen_head == native.hex_digest(frozen["initial_head"]), "LEARNING_FREEZE_HEAD")
    native.require(selection["request"] == completed["request"] == frozen["request"] and
                   selection["owners"] == completed["owners"] == frozen["owners"] and
                   before["initial_head"] == replay["initial_head"] == frozen_head, "LEARNING_FROZEN_REQUEST")
    native.require(before["next_stage"] == 6 and replay["next_stage"] is None and
                   len(completed["receipts"]) == len(selection["receipts"]) + 1 and
                   completed["receipts"][:-1] == selection["receipts"], "LOCAL_DECISION_EXACT_CONTINUATION")
    scope = scoped._review_scope(root_profile_raw, expected_root_profile_sha256, completed, replay, frozen)
    final = completed["receipts"][-1]
    request, choice = completed["request"], replay["local_decision"]
    descriptor = (request["selected_bundle"] if replay["retained_model"]
                  else completed["receipts"][2]["observation"]["candidate"])
    return dict(schema=REPORT_SCHEMA, scope="pinned-heplcp04-receipt-chain-and-root-scope-only",
        checkpoint_schema=MAGIC.decode("ascii"), selection_checkpoint_sha256=expected_selection_sha256,
        completed_checkpoint_sha256=expected_completed_sha256, frozen_initial_head=frozen_head,
        selection_head=before["head"], completed_learning_head=replay["head"], receipt_count=8,
        local_disposition=CHOICES[choice["disposition"]], local_decision=choice,
        evaluation_disposition="qualified", proposal_disposition="update_candidates", no_update=False,
        retained_model=replay["retained_model"], complete_version_descriptor=copy.deepcopy(descriptor),
        selected_bundle_digest=replay["next_task_bundle"], original_receipt_prefix_preserved=True,
        receipt_commitment_chain_complete=True, final_observation=copy.deepcopy(final["observation"]),
        root_scope_review=scope, next_use_provenance=dict(
            status="SAME_ORIGINAL_ACTOR_DISTINCT_RUN_ONLY", authenticated=False,
            source_actor={name: request[name] for name in ("principal_id", "agent_id", "cell_id", "source_run_id")},
            next_use_actor=copy.deepcopy(final["observation"]["state_partition"])),
        authority="DENY_ALL", current_permission="NOT_EXPORTED", qualification="HOLD_NO_GO",
        acknowledged_use_observed=False, full_learning_iteration_completed=False,
        native_origin_authenticated=False, source_execution_authenticated=False,
        learning_signatures_verified=False, policy_origin_authenticated=False,
        pre_dispatch_freeze_authenticated=False, independent_consumer_verified=False,
        real_model_training_verified=False, cost_completeness_verified=False,
        physical_installation_accepted=False, settlement_verified=False,
        current_permission_exported=False, independent_control_accepted=False,
        grant_signature_verified_by_this_reader=False, full_state_restore_qualified=False,
        hepta_final_use_accepted=False, production_activation=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("selection-checkpoint", "completed-checkpoint", "root-profile", "freeze"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    args = parser.parse_args()
    frozen_raw = native.read_bounded(args.freeze, legacy.MAX_FREEZE)
    native.require(native.sha(frozen_raw) == native.hex_digest(args.freeze_sha256), "LEARNING_FREEZE_PIN")
    result = review_native_local_decision(
        native.read_bounded(args.selection_checkpoint, legacy.MAX_CHECKPOINT),
        native.read_bounded(args.completed_checkpoint, legacy.MAX_CHECKPOINT),
        native.read_bounded(args.root_profile, scoped.MAX_PROFILE),
        expected_selection_sha256=args.selection_checkpoint_sha256,
        expected_completed_sha256=args.completed_checkpoint_sha256,
        expected_root_profile_sha256=args.root_profile_sha256,
        frozen=native.decode(frozen_raw, legacy.MAX_FREEZE))
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
