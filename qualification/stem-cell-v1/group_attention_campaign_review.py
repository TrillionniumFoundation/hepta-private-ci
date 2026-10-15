"""Independent stdlib-only replay of Group evidence-attention campaign records.

Recomputes symbolic labels from public text; never imports model, Torch,
teacher, fitting code, or checkpoint. Artifact identities are NOT signatures,
and untrusted self-reported execution timing is not hardware attestation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from group_campaign_review import _parse

ARMS = ("static", "wide", "core", "attention")
COHORTS = ("test", "long", "deleted", "composition")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _summarize(rows):
    times = sorted(x["wall_ns"] for x in rows)
    return dict(n=len(rows), correct=sum(x["success"] for x in rows),
                unsupported_attempts=sum(x["unsupported_attempt"] for x in rows),
                cpu_ns=sum(x["cpu_ns"] for x in rows), wall_ns=sum(times),
                p50_ns=times[len(times) // 2],
                p95_ns=times[min(len(times) - 1, int(.95 * len(times)))])


def review(root):
    root = Path(root)
    protocol = json.loads((root / "protocol.json").read_text())
    rows = json.loads((root / "observations.json").read_text())
    report = json.loads((root / "report.json").read_text())
    teacher = json.loads((root / "teacher.json").read_text())
    encoder = json.loads((root / "encoder.json").read_text())
    if (protocol["schema"] != "hepta.group.paired-step-campaign.v1"
            or report["schema"] != "hepta.group.paired-step-observation.v1"
            or report["protocol_sha256"] != _digest(protocol)
            or tuple(protocol["frozen_candidate_arms"]) != ARMS
            or protocol["evaluation_cohorts"] != list(COHORTS)
            or report["authority"] != "DENY_ALL" or report["production_authorized"]
            or report["natural_future_win_established"]
            or report["equal_actual_training_work"]):
        raise ValueError("unregistered protocol, authority or unsupported efficacy assertion")
    public, seen_groups, replay_labels = protocol["public_cases"], {}, {}
    if set(public) != {"train", *COHORTS}:
        raise ValueError("complete training and heldout cohorts required")
    for cohort, cases in public.items():
        identifiers = set()
        seen_groups[cohort] = set()
        replay_labels[cohort] = {}
        for case in cases:
            cid, source = case["case_id"], case["source_group"]
            if cid in identifiers or source in seen_groups[cohort]:
                raise ValueError("duplicate public case or source group")
            identifiers.add(cid)
            seen_groups[cohort].add(source)
            answer, _, _ = _parse(case, missing=cohort == "deleted")
            replay_labels[cohort][cid] = answer
        if not cases:
            raise ValueError("empty heldout cohort")
    if not (seen_groups["train"] == set(protocol["train_source_groups"])):
        raise ValueError("training source membership drift")
    if any(seen_groups[a] & seen_groups[b] for a, b in
           (("train", "test"), ("train", "long"), ("test", "long"))):
        raise ValueError("leaked train/test/long source groups")
    if (seen_groups["test"] != seen_groups["deleted"]
            or set(replay_labels["test"]) != set(replay_labels["deleted"])):
        raise ValueError("deleted cohort does not preserve original cases")
    if (teacher["source_groups_sha256"] != _digest(sorted(seen_groups["train"]))
            or teacher["authority"] != "DENY_ALL" or not teacher["train_only"]
            or teacher["supervised_steps"] < len(public["train"])
            or teacher["tokenizer_calls"] != len(public["train"])
            or report["teacher"] != teacher or report["encoder_cost"] != encoder
            or type(encoder["actual_forward_calls"]) is not int
            or encoder["actual_forward_calls"] <= 0):
        raise ValueError("teacher or physical Encoder receipt mismatch")
    training = report["training"]
    if (set(training) != set(ARMS)
            or training["core"]["sample_and_depth_sha256"] !=
               training["attention"]["sample_and_depth_sha256"]
            or training["core"]["parameter_count"] != training["attention"]["parameter_count"]
            or not training["attention"]["attention_supervision_enabled"]
            or training["core"]["attention_supervision_enabled"]
            or training["attention"]["attention_target_sha256"] !=
               teacher["teacher_tensor_sha256"]):
        raise ValueError("paired training schedule or teacher digest mismatch")
    for name in ARMS:
        receipt = training[name]
        if (receipt["status"] != "completed" or
                receipt["completed_steps"] != protocol["steps"] or
                receipt["seed"] != protocol["seed"] or
                receipt["cpu_ns"] <= 0 or receipt["wall_ns"] <= 0 or
                receipt["parameter_count"] <= 0):
            raise ValueError("partial or unmeasured training")
    expected = {(cohort, arm, case["case_id"]) for cohort in COHORTS
                for arm in ARMS for case in public[cohort]}
    cases = {cohort: {r["case_id"]: r for r in public[cohort]} for cohort in COHORTS}
    seen, by_arm, model_hashes, feature_hashes = set(), defaultdict(list), defaultdict(set), defaultdict(set)
    for row in rows:
        key = row["cohort"], row["arm"], row["case_id"]
        if key not in expected or key in seen:
            raise ValueError("unexpected, duplicate or out-of-cohort observation")
        seen.add(key)
        cohort, arm, cid = key
        case = cases[cohort][cid]
        label = replay_labels[cohort][cid]
        if (type(row["prediction"]) is not int or not 0 <= row["prediction"] <= 7
                or type(row["success"]) is not bool
                or type(row["evidence_supported"]) is not bool
                or type(row["unsupported_attempt"]) is not bool
                or row["source_group"] != case["source_group"]
                or row["evidence_supported"] != (label is not None)
                or row["unsupported_attempt"] != (label is None)
                or row["success"] != (label is not None and row["prediction"] == label)):
            raise ValueError("independently replayed evidence outcome differs")
        if any(type(row[name]) is not int or row[name] <= 0
               for name in ("wall_ns", "cpu_ns")):
            raise ValueError("missing physical observation")
        for field in ("feature_sha256", "model_sha256"):
            value = row[field]
            if (type(value) is not str or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("unbound digest")
        feature_hashes[(cohort, cid)].add(row["feature_sha256"])
        model_hashes[arm].add(row["model_sha256"])
        by_arm[f"{cohort}.{arm}"].append(row)
    if seen != expected or any(len(v) != 1 for v in
                               (*feature_hashes.values(), *model_hashes.values())):
        raise ValueError("incomplete pairs, drifting frozen models or feature mismatch")
    for cid in replay_labels["test"]:
        if feature_hashes[("deleted", cid)] == feature_hashes[("test", cid)]:
            raise ValueError("deleted and original evidence cannot reuse a snapshot")
    summaries = {k: _summarize(values) for k, values in by_arm.items()}
    if report["summaries"] != summaries:
        raise ValueError("reported scores/timing disagree with complete raw observations")
    return dict(schema="hepta.group.paired-attention-independent-review.v1",
                passed=True, authority="DENY_ALL",
                complete_group_replay=True,
                public_evidence_labels_independently_recomputed=True,
                teacher_bound_to_train_sources=True,
                same_initial_core_claim_still_unattested=True,
                equal_compute_claim_allowed=False,
                real_host_execution_independently_attested=False,
                future_task_efficacy_proved=False,
                observation_sha256=_digest(rows),
                protocol_sha256=_digest(protocol),
                paired_summaries=summaries)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    with Path(args.output).open("x") as stream:
        json.dump(review(args.root), stream, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
