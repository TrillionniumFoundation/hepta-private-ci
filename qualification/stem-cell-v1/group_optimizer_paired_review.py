"""Stdlib-only paired optimizer audit. No model execution or selection authority."""
import argparse
import hashlib
import json
from pathlib import Path

from group_attention_campaign_review import ARMS, COHORTS, DIRECT, review as audit
from group_checkpoint_audit import strict_json_file


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def positive(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(label + " requires an actual positive nanosecond count")
    return value


def cost_panel(root, report, rows):
    e = strict_json_file(root / "encoder.json")
    t = strict_json_file(root / "teacher.json")
    parts = dict(
        encoder=positive(e.get("cpu_ns"), "encoder"),
        teacher=positive(t.get("cpu_ns"), "teacher"),
        training=sum(positive(report["training"][name].get("cpu_ns"), name)
                     for name in DIRECT),
        critic=positive(report["critic_cost"].get("cpu_ns"), "critic"),
        archive=positive(report["checkpoint_materialization"].get("cpu_ns"), "archive"),
        online=sum(positive(row.get("cpu_ns"), "online") for row in rows),
        framework_setup=positive(report["torch_lazy_setup_cost"].get("cpu_ns"), "framework"))
    actual = positive(report.get("actual_lifecycle_cpu_ns"), "lifecycle")
    charged = sum(parts.values())
    if charged > actual:
        raise ValueError("measured component cost exceeds observed lifecycle")
    return dict(component_cpu_ns=parts, accounted_cpu_ns=charged,
                observed_lifecycle_cpu_ns=actual, unattributed_cpu_ns=actual-charged,
                energy_and_target_host_parity_verified=False)


def review_pair(sgd_root, adam_root):
    roots = [Path(sgd_root), Path(adam_root)]
    if roots[0].resolve() == roots[1].resolve():
        raise ValueError("two independently produced material roots required")
    reviews = [audit(root) for root in roots]
    if any(v.get("passed") is not True or v.get("authority") != "DENY_ALL"
           for v in reviews):
        raise ValueError("both individual evidence reviews must pass")
    protocols = [strict_json_file(root / "protocol.json") for root in roots]
    reports = [strict_json_file(root / "report.json") for root in roots]
    rows = [strict_json_file(root / "observations.json") for root in roots]
    if [p.get("training_profile") for p in protocols] != ["sgd_v1", "adam_v1"]:
        raise ValueError("registered SGD-before-Adam optimizer order required")
    for field in ("seed", "train_source_groups", "public_cases", "source_sha256",
                  "frozen_candidate_arms", "evaluation_cohorts", "training_sample_seed"):
        if protocols[0].get(field) != protocols[1].get(field):
            raise ValueError("optimizer pair changed its frozen " + field)
    if reports[0]["initial_core_sha256"] != reports[1]["initial_core_sha256"]:
        raise ValueError("paired Core initial weight digest changed")
    for name in ("core", "attention"):
        fit = [r["training"][name] for r in reports]
        for field in ("sample_and_depth_sha256", "initial_model_sha256",
                      "parameter_count", "actual_completed_training_exposures"):
            if fit[0].get(field) != fit[1].get(field):
                raise ValueError("optimizer fitting inventory drift: " + field)
    teachers = [strict_json_file(root / "teacher.json") for root in roots]
    for field in ("schema", "teacher_tensor_sha256", "trace_hashes_sha256",
                  "feature_hashes_sha256", "slot_assignment_sha256",
                  "supervised_steps", "total_teacher_steps",
                  "coalesced_teacher_steps",
                  "terminal_evidence_supervised_cases"):
        if teachers[0].get(field) != teachers[1].get(field):
            raise ValueError("paired optimizer teacher operation alignment drift: " + field)
    encoders = [strict_json_file(root / "encoder.json") for root in roots]
    for field in ("model_material", "actual_forward_calls"):
        if encoders[0].get(field) != encoders[1].get(field):
            raise ValueError("same-Encoder identity/physical forwards required")
    by_key = []
    for cohort_rows in rows:
        if type(cohort_rows) is not list:
            raise ValueError("actual episode array required")
        result = {}
        for row in cohort_rows:
            key = (row["cohort"], row["arm"], row["case_id"])
            if key in result or key[0] not in COHORTS or key[1] not in ARMS:
                raise ValueError("invalid or duplicated optimizer episode")
            result[key] = row
        by_key.append(result)
    if by_key[0].keys() != by_key[1].keys():
        raise ValueError("SGD/Adam episode inventories differ")
    comparisons = {}
    for cohort in COHORTS:
        comparisons[cohort] = {}
        for arm in ARMS:
            subset = sorted(k for k in by_key[0] if k[:2] == (cohort, arm))
            if not subset:
                raise ValueError("missing paired cohort")
            gained = lost = 0
            cpu = [0, 0]
            for key in subset:
                a, b = by_key[0][key], by_key[1][key]
                for field in ("source_group", "feature_sha256",
                              "evidence_supported", "execution_mode"):
                    if a.get(field) != b.get(field):
                        raise ValueError("input binding drift: " + field)
                gained += int(b["success"] and not a["success"])
                lost += int(a["success"] and not b["success"])
                cpu[0] += positive(a.get("cpu_ns"), "sgd episode")
                cpu[1] += positive(b.get("cpu_ns"), "adam episode")
            comparisons[cohort][arm] = dict(
                n=len(subset), adam_rescued=gained, adam_harmed=lost,
                adam_correct_delta=gained-lost, sgd_online_cpu_ns=cpu[0],
                adam_online_cpu_ns=cpu[1], matched_lifecycle_work=False)
    return dict(schema="hepta.group.optimizer-paired-replay.v1", authority="DENY_ALL",
                paired_structure_passed=True, production_promotion_permitted=False,
                source_independence_verified=False, natural_task_gain_proved=False,
                matched_compute_verified=False, causal_optimizer_effect_proved=False,
                external_execution_attested=False, seed=protocols[0]["seed"],
                common_case_sha256=digest(protocols[0]["public_cases"]),
                initial_core_sha256=reports[0]["initial_core_sha256"],
                original_observation_digests=[digest(x) for x in rows],
                costs={"sgd": cost_panel(roots[0], reports[0], rows[0]),
                       "adam": cost_panel(roots[1], reports[1], rows[1])},
                comparisons=comparisons)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sgd")
    parser.add_argument("adam")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with Path(args.output).open("x") as output:
        json.dump(review_pair(args.sgd, args.adam), output,
                  sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
