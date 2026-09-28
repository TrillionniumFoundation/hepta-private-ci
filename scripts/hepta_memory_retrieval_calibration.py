#!/usr/bin/env python3
"""Calibrate retrieval admission candidates and compare fixed ablations without enabling production."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

Q32_ONE = 1 << 32
MAX_ROWS = 5_000_000
MAX_POLICIES = 4_096
PARTITIONS = ("calibration", "holdout")
STANDARD_SYSTEMS = (
    "lexical",
    "owner_rrf",
    "hnmf_no_recurrence",
    "hnmf_no_inhibition",
    "hnmf_full",
)
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
DIGEST64 = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}\Z")
ROW_FIELDS = {
    "sample_id",
    "query_group",
    "query_digest",
    "partition",
    "risk_stratum",
    "system",
    "event_time_micros",
    "target_should_recall",
    "selected",
    "output_correct",
    "output_harmful",
    "source_current",
    "score_q32",
    "ood_q32",
    "distinct_channels",
    "contradiction",
}
DATASET_FIELDS = {
    "schema",
    "source_head",
    "source_tree",
    "dataset_id",
    "policy_sha256",
    "annotation_protocol_digest",
    "vector_channel_enabled",
    "system_configuration_digests",
    "rows",
}
POLICY_FIELDS = {
    "schema",
    "policy_id",
    "baseline_system",
    "required_systems",
    "risk_strata",
    "minimum_groups_per_partition_stratum",
    "vector_channel_enabled",
    "threshold_grid",
    "limits",
}


class CalibrationError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CalibrationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path):
    with Path(path).open("rb") as stream:
        data = stream.read(128 * 1024 * 1024 + 1)
    if len(data) > 128 * 1024 * 1024:
        raise CalibrationError("calibration input exceeds 128 MiB")

    def invalid_constant(value):
        raise CalibrationError(f"invalid JSON number: {value}")

    return json.loads(
        data,
        object_pairs_hook=strict_object,
        parse_constant=invalid_constant,
    )


def integer(value, name, minimum=0, maximum=(1 << 63) - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise CalibrationError(
            f"{name} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise CalibrationError(f"{name} must be Boolean")
    return value


def exact_keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise CalibrationError(f"{name} must contain exactly {sorted(expected)}")
    return value


def token(value, name):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise CalibrationError(f"{name} must be a bounded canonical token")
    return value


def digest64(value, name):
    if not isinstance(value, str) or not DIGEST64.fullmatch(value):
        raise CalibrationError(f"{name} must be a lowercase SHA-256 digest")
    return value


def exact_sha(value, name):
    if not isinstance(value, str) or not SHA40.fullmatch(value):
        raise CalibrationError(f"{name} must be an exact lowercase Git SHA")
    return value


def unique_sequence(value, name, minimum_length=1, maximum_length=64):
    if not isinstance(value, list) or not minimum_length <= len(value) <= maximum_length:
        raise CalibrationError(
            f"{name} must be an array of {minimum_length}..{maximum_length} values"
        )
    if len(set(value)) != len(value):
        raise CalibrationError(f"{name} contains duplicates")
    return value


def bind_source(root: Path, head: str):
    """Bind the actual clean checkout rather than trusting caller labels."""
    exact_sha(head, "head")

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise CalibrationError(f"source observation failed: git {args[0]}")
        return result.stdout.strip()

    if git("rev-parse", "HEAD") != head:
        raise CalibrationError("calibration source head is not the current checkout")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise CalibrationError("calibration source checkout is not clean")
    tree = exact_sha(git("rev-parse", "HEAD^{tree}"), "tree")
    parents = git("show", "-s", "--format=%P", "HEAD").split()
    for parent in parents:
        exact_sha(parent, "parent")
    return {"commit": head, "tree": tree, "parents": parents}


def validate_policy(document):
    exact_keys(document, POLICY_FIELDS, "calibration policy")
    if document.get("schema") != "hepta.memory-retrieval.calibration-policy.v1":
        raise CalibrationError("unsupported calibration policy schema")
    token(document.get("policy_id"), "policy_id")
    required = unique_sequence(document.get("required_systems"), "required_systems")
    required = [token(value, "required system") for value in required]
    missing = sorted(set(STANDARD_SYSTEMS).difference(required))
    if missing:
        raise CalibrationError(f"required ablation systems are missing: {missing}")
    baseline = token(document.get("baseline_system"), "baseline_system")
    if baseline not in required:
        raise CalibrationError("baseline_system is not a required system")
    strata = unique_sequence(document.get("risk_strata"), "risk_strata", 1, 32)
    strata = [token(value, "risk stratum") for value in strata]
    minimum = integer(
        document.get("minimum_groups_per_partition_stratum"),
        "minimum_groups_per_partition_stratum",
        100,
        1_000_000,
    )
    if boolean(document.get("vector_channel_enabled"), "vector_channel_enabled"):
        raise CalibrationError(
            "this calibration contract refuses Vector until a qualified text encoder/index owner exists"
        )

    grid = exact_keys(
        document.get("threshold_grid"),
        {
            "minimum_total_score_q32",
            "maximum_ood_q32",
            "minimum_distinct_channels",
        },
        "threshold_grid",
    )
    score_values = unique_sequence(
        grid["minimum_total_score_q32"], "minimum_total_score_q32", 1, 64
    )
    ood_values = unique_sequence(grid["maximum_ood_q32"], "maximum_ood_q32", 1, 64)
    channel_values = unique_sequence(
        grid["minimum_distinct_channels"], "minimum_distinct_channels", 1, 8
    )
    score_values = sorted(
        integer(value, "minimum_total_score_q32", 0, Q32_ONE)
        for value in score_values
    )
    ood_values = sorted(
        integer(value, "maximum_ood_q32", 0, Q32_ONE) for value in ood_values
    )
    channel_values = sorted(
        integer(value, "minimum_distinct_channels", 1, 8)
        for value in channel_values
    )
    policy_count = len(score_values) * len(ood_values) * len(channel_values)
    if policy_count > MAX_POLICIES:
        raise CalibrationError("threshold grid exceeds 4096 candidate policies")

    limits = exact_keys(
        document.get("limits"),
        {
            "false_accept_ppm_of_groups",
            "harmful_accept_ppm_of_groups",
            "false_abstain_ppm_of_positive_groups",
        },
        "limits",
    )
    checked_limits = {
        key: integer(value, f"limits.{key}", 0, 1_000_000)
        for key, value in limits.items()
    }
    return {
        "policy_id": document["policy_id"],
        "required_systems": required,
        "baseline_system": baseline,
        "risk_strata": strata,
        "minimum_groups": minimum,
        "scores": score_values,
        "oods": ood_values,
        "channels": channel_values,
        "limits": checked_limits,
    }


def validate_row(row, index, systems, strata):
    exact_keys(row, ROW_FIELDS, f"row[{index}]")
    sample_id = token(row["sample_id"], f"row[{index}].sample_id")
    group = token(row["query_group"], f"row[{index}].query_group")
    query_digest = digest64(row["query_digest"], f"row[{index}].query_digest")
    partition = row["partition"]
    if partition not in PARTITIONS:
        raise CalibrationError(f"row[{index}].partition is invalid")
    risk = token(row["risk_stratum"], f"row[{index}].risk_stratum")
    if risk not in strata:
        raise CalibrationError(f"row[{index}] uses undeclared risk stratum")
    system = token(row["system"], f"row[{index}].system")
    if system not in systems:
        raise CalibrationError(f"row[{index}] uses undeclared system")
    event_time = integer(
        row["event_time_micros"], f"row[{index}].event_time_micros", 1
    )
    target_should_recall = boolean(
        row["target_should_recall"], f"row[{index}].target_should_recall"
    )
    selected = boolean(row["selected"], f"row[{index}].selected")
    output_correct = boolean(
        row["output_correct"], f"row[{index}].output_correct"
    )
    output_harmful = boolean(
        row["output_harmful"], f"row[{index}].output_harmful"
    )
    source_current = boolean(
        row["source_current"], f"row[{index}].source_current"
    )
    contradiction = boolean(
        row["contradiction"], f"row[{index}].contradiction"
    )
    score = integer(row["score_q32"], f"row[{index}].score_q32", 0, Q32_ONE)
    ood = integer(row["ood_q32"], f"row[{index}].ood_q32", 0, Q32_ONE)
    channels = integer(
        row["distinct_channels"], f"row[{index}].distinct_channels", 0, 8
    )
    if not selected and (output_correct or output_harmful):
        raise CalibrationError("an unselected result cannot be labeled correct or harmful")
    if output_harmful and output_correct:
        raise CalibrationError("a harmful output cannot also be labeled correct")
    if output_correct and not target_should_recall:
        raise CalibrationError("a correct selected recall requires a positive target")
    return {
        "sample_id": sample_id,
        "query_group": group,
        "query_digest": query_digest,
        "partition": partition,
        "risk_stratum": risk,
        "system": system,
        "event_time_micros": event_time,
        "target_should_recall": target_should_recall,
        "selected": selected,
        "output_correct": output_correct,
        "output_harmful": output_harmful,
        "source_current": source_current,
        "score_q32": score,
        "ood_q32": ood,
        "distinct_channels": channels,
        "contradiction": contradiction,
    }


def validate_dataset(document, policy_document, policy, head, tree):
    exact_keys(document, DATASET_FIELDS, "calibration dataset")
    if document.get("schema") != "hepta.memory-retrieval.calibration-input.v1":
        raise CalibrationError("unsupported calibration dataset schema")
    if document.get("source_head") != head or document.get("source_tree") != tree:
        raise CalibrationError("calibration dataset does not bind the observed source")
    token(document.get("dataset_id"), "dataset_id")
    digest64(document.get("annotation_protocol_digest"), "annotation_protocol_digest")
    expected_policy_sha = hashlib.sha256(canonical(policy_document)).hexdigest()
    if document.get("policy_sha256") != expected_policy_sha:
        raise CalibrationError("dataset does not bind the exact calibration policy")
    if boolean(document.get("vector_channel_enabled"), "dataset.vector_channel_enabled"):
        raise CalibrationError("dataset claims an unqualified Vector channel")

    configurations = document.get("system_configuration_digests")
    if not isinstance(configurations, dict) or set(configurations) != set(
        policy["required_systems"]
    ):
        raise CalibrationError(
            "system_configuration_digests must exactly bind every required system"
        )
    for system, value in configurations.items():
        token(system, "system configuration name")
        digest64(value, f"system_configuration_digests.{system}")

    rows = document.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise CalibrationError("rows must be a bounded nonempty array")
    checked = [
        validate_row(
            row,
            index,
            set(policy["required_systems"]),
            set(policy["risk_strata"]),
        )
        for index, row in enumerate(rows)
    ]

    sample_ids = set()
    pair_keys = set()
    group_metadata = {}
    digest_partition = {}
    calibration_times = []
    holdout_times = []
    for row in checked:
        if row["sample_id"] in sample_ids:
            raise CalibrationError("duplicate sample_id")
        sample_ids.add(row["sample_id"])
        pair = (row["query_group"], row["system"])
        if pair in pair_keys:
            raise CalibrationError("duplicate query_group/system row")
        pair_keys.add(pair)
        metadata = (
            row["query_digest"],
            row["partition"],
            row["risk_stratum"],
            row["event_time_micros"],
            row["target_should_recall"],
        )
        previous = group_metadata.setdefault(row["query_group"], metadata)
        if previous != metadata:
            raise CalibrationError(
                "query group metadata or target label differs across systems"
            )
        previous_partition = digest_partition.setdefault(
            row["query_digest"], row["partition"]
        )
        if previous_partition != row["partition"]:
            raise CalibrationError("query digest leaks across calibration and holdout")
        if row["partition"] == "calibration":
            calibration_times.append(row["event_time_micros"])
        else:
            holdout_times.append(row["event_time_micros"])

    if not calibration_times or not holdout_times:
        raise CalibrationError("both calibration and holdout partitions are required")
    if max(calibration_times) >= min(holdout_times):
        raise CalibrationError(
            "future holdout must begin strictly after every calibration observation"
        )

    required_systems = set(policy["required_systems"])
    group_systems = {}
    group_risk_partition = {}
    for row in checked:
        group_systems.setdefault(row["query_group"], set()).add(row["system"])
        group_risk_partition[row["query_group"]] = (
            row["partition"],
            row["risk_stratum"],
        )
    for group, systems in group_systems.items():
        if systems != required_systems:
            raise CalibrationError(
                f"query group {group} does not contain the complete paired system set"
            )

    counts = {}
    for partition, risk in group_risk_partition.values():
        counts[(partition, risk)] = counts.get((partition, risk), 0) + 1
    for partition in PARTITIONS:
        for risk in policy["risk_strata"]:
            if counts.get((partition, risk), 0) < policy["minimum_groups"]:
                raise CalibrationError(
                    f"insufficient {partition}/{risk} paired query groups"
                )
    return checked


def ceiling_ppm(numerator, denominator):
    if denominator == 0:
        return 0
    return (numerator * 1_000_000 + denominator - 1) // denominator


def admitted(row, candidate):
    return (
        row["selected"]
        and row["source_current"]
        and row["score_q32"] > 0
        and row["score_q32"] >= candidate["minimum_total_score_q32"]
        and row["ood_q32"] <= candidate["maximum_ood_q32"]
        and row["distinct_channels"] >= candidate["minimum_distinct_channels"]
        and not row["contradiction"]
    )


def summarize(rows, candidate):
    groups = len(rows)
    positives = sum(row["target_should_recall"] for row in rows)
    accepted = 0
    correct_accept = 0
    false_accept = 0
    harmful_accept = 0
    false_abstain = 0
    stale_rejected = 0
    contradiction_rejected = 0
    for row in rows:
        is_admitted = admitted(row, candidate)
        is_correct = is_admitted and row["output_correct"]
        accepted += is_admitted
        correct_accept += is_correct
        false_accept += is_admitted and not row["output_correct"]
        harmful_accept += is_admitted and row["output_harmful"]
        false_abstain += row["target_should_recall"] and not is_correct
        stale_rejected += row["selected"] and not row["source_current"]
        contradiction_rejected += (
            row["selected"] and row["source_current"] and row["contradiction"]
        )
    return {
        "groups": groups,
        "positive_groups": positives,
        "accepted_count": accepted,
        "correct_accept_count": correct_accept,
        "false_accept_count": false_accept,
        "harmful_accept_count": harmful_accept,
        "false_abstain_count": false_abstain,
        "stale_rejected_count": stale_rejected,
        "contradiction_rejected_count": contradiction_rejected,
        "accepted_ppm_of_groups": ceiling_ppm(accepted, groups),
        "correct_accept_ppm_of_groups": ceiling_ppm(correct_accept, groups),
        "false_accept_ppm_of_groups": ceiling_ppm(false_accept, groups),
        "harmful_accept_ppm_of_groups": ceiling_ppm(harmful_accept, groups),
        "false_abstain_ppm_of_positive_groups": ceiling_ppm(
            false_abstain, positives
        ),
    }


def candidate_policies(policy):
    for score in policy["scores"]:
        for ood in policy["oods"]:
            for channels in policy["channels"]:
                yield {
                    "minimum_total_score_q32": score,
                    "maximum_ood_q32": ood,
                    "minimum_distinct_channels": channels,
                    "abstain_on_contradiction": True,
                    "vector_channel_enabled": False,
                }


def within_limits(summary, limits):
    return all(summary[name] <= limit for name, limit in limits.items())


def evaluate_candidate(rows, candidate, risk_strata):
    overall = summarize(rows, candidate)
    strata = {
        risk: summarize(
            [row for row in rows if row["risk_stratum"] == risk], candidate
        )
        for risk in risk_strata
    }
    return {"overall": overall, "risk_strata": strata}


def feasible(evaluation, limits):
    return within_limits(evaluation["overall"], limits) and all(
        within_limits(summary, limits)
        for summary in evaluation["risk_strata"].values()
    )


def selection_key(candidate, evaluation):
    overall = evaluation["overall"]
    return (
        -overall["correct_accept_count"],
        overall["harmful_accept_count"],
        overall["false_accept_count"],
        overall["false_abstain_count"],
        -candidate["minimum_total_score_q32"],
        candidate["maximum_ood_q32"],
        -candidate["minimum_distinct_channels"],
    )


def calibrate(document, policy_document, head, tree):
    exact_sha(head, "head")
    exact_sha(tree, "tree")
    policy = validate_policy(policy_document)
    rows = validate_dataset(document, policy_document, policy, head, tree)
    by_system_partition = {
        (system, partition): [
            row
            for row in rows
            if row["system"] == system and row["partition"] == partition
        ]
        for system in policy["required_systems"]
        for partition in PARTITIONS
    }

    systems = []
    selected_by_system = {}
    status = "candidate_generated"
    candidates = tuple(candidate_policies(policy))
    for system in policy["required_systems"]:
        calibration_rows = by_system_partition[(system, "calibration")]
        options = []
        for candidate in candidates:
            evaluation = evaluate_candidate(
                calibration_rows, candidate, policy["risk_strata"]
            )
            if feasible(evaluation, policy["limits"]):
                options.append((selection_key(candidate, evaluation), candidate, evaluation))
        if not options:
            status = "no_feasible_candidate"
            systems.append(
                {
                    "system": system,
                    "selected_policy": None,
                    "calibration": None,
                    "holdout": None,
                    "descriptive_delta_from_baseline": None,
                }
            )
            continue
        _, candidate, calibration_evaluation = min(options, key=lambda item: item[0])
        holdout_evaluation = evaluate_candidate(
            by_system_partition[(system, "holdout")],
            candidate,
            policy["risk_strata"],
        )
        selected_by_system[system] = (
            candidate,
            calibration_evaluation,
            holdout_evaluation,
        )
        systems.append(
            {
                "system": system,
                "selected_policy": candidate,
                "calibration": calibration_evaluation,
                "holdout": holdout_evaluation,
                "descriptive_delta_from_baseline": None,
            }
        )

    baseline = selected_by_system.get(policy["baseline_system"])
    if baseline is not None:
        baseline_holdout = baseline[2]["overall"]
        delta_fields = (
            "accepted_ppm_of_groups",
            "correct_accept_ppm_of_groups",
            "false_accept_ppm_of_groups",
            "harmful_accept_ppm_of_groups",
            "false_abstain_ppm_of_positive_groups",
        )
        for system in systems:
            if system["holdout"] is None:
                continue
            current = system["holdout"]["overall"]
            system["descriptive_delta_from_baseline"] = {
                field: current[field] - baseline_holdout[field]
                for field in delta_fields
            }

    return {
        "schema": "hepta.memory-retrieval.calibration-receipt.v1",
        "source_head": head,
        "source_tree": tree,
        "dataset_id": document["dataset_id"],
        "dataset_sha256": hashlib.sha256(canonical(document)).hexdigest(),
        "policy_id": policy["policy_id"],
        "policy_sha256": hashlib.sha256(canonical(policy_document)).hexdigest(),
        "annotation_protocol_digest": document["annotation_protocol_digest"],
        "system_configuration_digests": document["system_configuration_digests"],
        "selection_partition": "calibration",
        "holdout_used_for_selection": False,
        "future_holdout": True,
        "rate_rounding": "ceiling_ppm",
        "baseline_system": policy["baseline_system"],
        "limits": policy["limits"],
        "status": status,
        "systems": systems,
        "vector_channel_enabled": False,
        "candidatePolicyOnly": True,
        "causalUtilityProved": False,
        "productionPolicyApproved": False,
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }


def retain(receipt, directory: Path):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = canonical(receipt)
    path = directory / f"{hashlib.sha256(data).hexdigest()}.json"
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise CalibrationError("existing content-addressed receipt differs") from None
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = bind_source(args.root, args.head)
        policy = load(args.policy)
        receipt = calibrate(
            load(args.dataset),
            policy,
            args.head,
            source["tree"],
        )
        if bind_source(args.root, args.head) != source:
            raise CalibrationError("source changed during calibration")
        receipt["source_observation"] = source
        path = retain(receipt, args.output_dir)
        print(path)
        return 0 if receipt["status"] == "candidate_generated" else 1
    except (
        CalibrationError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"memory.retrieval calibration refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
