"""Inspect S0--S5 evidence; never authenticate owners or grant research admission.

The only numerical adapter is a descriptive, paired all-fit-means screen. It
does not establish independence, prospective registration, confidence coverage,
complete resource accounting, evaluator authenticity or scientific benefit.
Exit zero means a review report was produced, including reports of missing data.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import fmean
import subprocess

import hepta_cell_joint_config as joint
import hepta_cell_research_foundation as foundation_adapter
import hepta_cell_research_units as units_adapter


STAGES = {
    "S0": (),
    "S1": ("MEM-1", "CTRL-1", "VERIFY-1"),
    "S2": ("PERC-1", "PRED-1", "ACT-1"),
    "S3": ("CREDIT-1", "HCSN-1", "STABILITY-1"),
    "S4": ("ORG-1",),
    "S5": ("IMPROVER-1",),
}
BASELINES = {
    "MEM-1": ("rag", "rag_uniform_replay", "recurrent"),
    "CTRL-1": ("exact_dp", "fixed", "greedy", "voi", "mpc", "actor_critic"),
    "VERIFY-1": (
        "deterministic_rules",
        "single_step_self_eval",
        "history_statistics",
        "same_budget_vote",
        "fixed_checks",
    ),
    "PERC-1": ("fixed_read", "embedding_retrieval", "heuristic_evidence"),
    "PRED-1": ("one_step", "gru_rssm", "ssm", "finite_mpc"),
    "ACT-1": (
        "deterministic_durable_workflow",
        "manual_dsl",
        "flat_skill",
        "manager_worker",
    ),
    "CREDIT-1": ("bptt", "truncated_bptt", "three_factor"),
    "HCSN-1": ("gru", "ssm", "gradient_temporal"),
    "STABILITY-1": ("replay", "l2", "rank_preserving"),
    "ORG-1": ("fixed_graph_strong_scheduler",),
    "IMPROVER-1": ("frozen_improver",),
}
COST_CATEGORIES = (
    "setup",
    "training",
    "tuning",
    "encoding",
    "inference",
    "critic",
    "planning",
    "verification",
    "retries",
    "failures",
    "recovery",
    "communication",
    "state_io",
    "evaluation",
    "organization",
    "improver_construction",
)
KINDS = {"real", "fixture", "diagnostic", "imagined"}
STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "unknown",
    "pending",
    "censored",
    "rejected",
    "interrupted",
}
HEADER = "schema experiment_id joint_configuration_sha256 protocol_sha256"


def shape(value, fields, schema=None):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError(f"unknown or missing fields: {schema or fields}")
    if schema is not None and value["schema"] != schema:
        raise ValueError(f"unsupported schema: {schema}")


def identity(value):
    if not isinstance(value, str) or re.fullmatch(r"[\w./:@-]{1,128}", value) is None:
        raise ValueError("identity must be a nonempty bounded string")
    return value


def digest(value):
    if not isinstance(value, str) or joint.SHA256.fullmatch(value) is None:
        raise ValueError("a complete lowercase SHA256 is required")
    return value


def number(value):
    if type(value) not in (int, float) or not -1e100 <= value <= 1e100:
        raise ValueError("measurement must be finite and bounded, never boolean")
    return value


def names(value, maximum=4096):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError("identity list is empty or exceeds its bound")
    result = [identity(item) for item in value]
    if len(result) != len(set(result)):
        raise ValueError("duplicated identity")
    return set(result)


class Evidence:
    """Reuse descriptor-relative artifact reads and retain stability witnesses."""

    def __init__(self, descriptor):
        self.descriptor, self.versions, self.document_bytes = descriptor, {}, 0

    def read(self, binding, document=True):
        if len(self.versions) >= 4096:
            raise ValueError("evidence file count exceeds 4096")
        checked, raw, version = joint.read_artifact(
            self.descriptor, binding, retain=document
        )
        name = checked["path"]
        if name in self.versions and self.versions[name] != version:
            raise ValueError("evidence changed during review")
        self.versions[name] = version
        self.document_bytes += len(raw)
        if self.document_bytes > 64 * 1024 * 1024:
            raise ValueError("evidence documents exceed 64 MiB")
        return joint.strict_json(raw) if document else checked

    def finish(self):
        for name, version in self.versions.items():
            with joint.regular_file(self.descriptor, name) as stream:
                if joint.file_fingerprint(os.fstat(stream.fileno())) != version:
                    raise ValueError("evidence path changed during review")


def bound(document, schema, fields, experiment, configuration_sha, protocol_sha):
    shape(document, HEADER + " " + fields, schema)
    if document["experiment_id"] != experiment:
        raise ValueError("evidence names another experiment")
    for key, expected in (
        ("joint_configuration_sha256", configuration_sha),
        ("protocol_sha256", protocol_sha),
    ):
        if digest(document[key]) != expected and expected is not None:
            raise ValueError(f"evidence has a different {key}")


def declare_bindings(document, declarations):
    """Require common claims without treating missing originals as verified."""
    for key, expected in declarations.items():
        claimed = digest(document[key])
        if expected is not None and claimed != expected:
            raise ValueError(f"conflicting declared {key}")
        declarations[key] = claimed


def protocol_specs(protocol, evidence, configuration_sha):
    schema = protocol.get("schema") if isinstance(protocol, dict) else None
    if schema not in {
        "hepta.cell-research-protocol.v1",
        "hepta.cell-research-protocol.v2",
    }:
        raise ValueError("unsupported research protocol schema")
    grouped = schema == "hepta.cell-research-protocol.v2"
    shape(
        protocol,
        "schema joint_configuration_sha256 registration cost_unit experiments",
        schema,
    )
    if (
        digest(protocol["joint_configuration_sha256"]) != configuration_sha
        and configuration_sha is not None
    ):
        raise ValueError("protocol belongs to another joint configuration")
    evidence.read(protocol["registration"], document=False)
    identity(protocol["cost_unit"])
    specs = protocol["experiments"]
    if not isinstance(specs, dict) or not specs or not set(specs) <= BASELINES.keys():
        raise ValueError("protocol contains unknown or missing experiment IDs")
    for experiment, spec in specs.items():
        shape(
            spec,
            "baselines minimum_independent_fits minimum_net_gain retention_floor minimum_cost_fraction_saved maximum_total_cost decision_rule"
            + (" sampling" if grouped else ""),
        )
        baselines = names(spec["baselines"], 32)
        if "candidate" in baselines or not set(BASELINES[experiment]) <= baselines:
            raise ValueError("required strong baselines are missing")
        if (
            type(spec["minimum_independent_fits"]) is not int
            or not 2 <= spec["minimum_independent_fits"] <= 1000
        ):
            raise ValueError("minimum_independent_fits must be between 2 and 1000")
        if (
            number(spec["minimum_net_gain"]) <= 0
            or number(spec["retention_floor"]) > 0
            or not 0 < number(spec["minimum_cost_fraction_saved"]) <= 1
            or number(spec["maximum_total_cost"]) <= 0
            or spec["decision_rule"] != "all_fit_means"
        ):
            raise ValueError("invalid frozen thresholds or unsupported decision rule")
        if grouped:
            units_adapter.sampling_plan(spec["sampling"], evidence)
    return specs


def experiment_review(
    experiment,
    binding,
    evidence,
    spec,
    configuration_sha,
    protocol_sha,
    expected_configuration_sha=None,
    declared_bindings=None,
):
    document = evidence.read(binding)
    schema = document.get("schema") if isinstance(document, dict) else None
    if schema not in {
        "hepta.cell-research-experiment.v1",
        "hepta.cell-research-experiment.v2",
    }:
        raise ValueError("unsupported research experiment schema")
    grouped = schema == "hepta.cell-research-experiment.v2"
    if spec is not None and grouped != ("sampling" in spec):
        raise ValueError("experiment and frozen protocol versions differ")
    bound(
        document,
        schema,
        "evidence_kind registry attempts design" + (" units" if grouped else ""),
        experiment,
        configuration_sha or expected_configuration_sha,
        protocol_sha,
    )
    if declared_bindings is not None:
        declare_bindings(document, declared_bindings)
    if (
        not isinstance(document["evidence_kind"], str)
        or document["evidence_kind"] not in KINDS
    ):
        raise ValueError("unknown evidence kind")
    # Even without a freeze, nested documents must agree with the supplied envelope.
    configuration_pin, protocol_pin = (
        document["joint_configuration_sha256"],
        document["protocol_sha256"],
    )
    registry, attempts, design = [
        evidence.read(document[key]) for key in ("registry", "attempts", "design")
    ]
    bound(
        registry,
        "hepta.cell-attempt-inventory.v1",
        "attempt_ids",
        experiment,
        configuration_pin,
        protocol_pin,
    )
    bound(
        attempts,
        "hepta.cell-research-attempts.v1",
        "rows",
        experiment,
        configuration_pin,
        protocol_pin,
    )
    bound(
        design,
        "hepta.cell-research-design.v1",
        "fit_artifacts common_start_artifacts improver_lineage",
        experiment,
        configuration_pin,
        protocol_pin,
    )
    # V2 separately retains the nonempty planned roster. No observed attempts
    # is a reportable incomplete campaign, not permission to erase that roster.
    registered = (
        set()
        if grouped and registry["attempt_ids"] == []
        else names(registry["attempt_ids"])
    )
    for key in ("fit_artifacts", "common_start_artifacts"):
        if not isinstance(design[key], dict) or len(design[key]) > 4096:
            raise ValueError("invalid design artifact inventory")
        for sha, artifact in design[key].items():
            if evidence.read(artifact, document=False)["sha256"] != digest(sha):
                raise ValueError("design artifact key differs from its bytes")
    lineage = {}
    if (
        not isinstance(design["improver_lineage"], list)
        or len(design["improver_lineage"]) > 128
    ):
        raise ValueError("invalid improver lineage inventory")
    for artifact in design["improver_lineage"]:
        record = evidence.read(artifact)
        shape(record, "schema improver parent", "hepta.cell-improver-lineage.v1")
        child = evidence.read(record["improver"], document=False)["sha256"]
        parent = (
            evidence.read(record["parent"], document=False)["sha256"]
            if record["parent"] is not None
            else None
        )
        if child in lineage or child == parent:
            raise ValueError("duplicate or self-referential improver lineage")
        lineage[child] = parent
    for child in lineage:
        visited = set()
        while child in lineage:
            if child in visited:
                raise ValueError("cyclic improver lineage")
            visited.add(child)
            child = lineage[child]
    rows = attempts["rows"]
    minimum_rows = 0 if grouped else 1
    if not isinstance(rows, list) or not minimum_rows <= len(rows) <= 4096:
        raise ValueError("attempt rows are empty or exceed their bound")
    blockers, counts, seen = set(), Counter(), set()
    units, fits, costs, candidate_artifacts = (
        defaultdict(dict),
        {},
        defaultdict(list),
        set(),
    )
    arms = {"candidate", *spec["baselines"]} if spec is not None else None
    for row in rows:
        shape(
            row,
            "attempt_id arm fit_id fit_sha256 case_id status net_utility retention costs evidence_kind common_start_sha256 improver_sha256",
        )
        attempt, arm, fit, case = [
            identity(row[key]) for key in ("attempt_id", "arm", "fit_id", "case_id")
        ]
        if attempt in seen or (arms is not None and arm not in arms):
            raise ValueError("duplicate attempt identity or unregistered arm")
        seen.add(attempt)
        if (
            not isinstance(row["status"], str)
            or row["status"] not in STATUSES
            or not isinstance(row["evidence_kind"], str)
            or row["evidence_kind"] not in KINDS
        ):
            raise ValueError("unknown attempt status or evidence kind")
        if row["evidence_kind"] != document["evidence_kind"]:
            raise ValueError("attempt evidence kind contradicts its envelope")
        counts[row["status"]] += 1
        if grouped and row["fit_sha256"] is None:
            if row["status"] == "completed":
                raise ValueError("completed attempt requires a fit artifact")
            # Failed launches may have no model output. Keep their original
            # status, outcome and costs without inventing a successful fit.
            blockers.add("UNAVAILABLE_FIT_ARTIFACT")
        else:
            sha = digest(row["fit_sha256"])
            if (
                sha not in design["fit_artifacts"]
                or fits.setdefault((arm, fit), sha) != sha
            ):
                raise ValueError("fit identity is absent or changes its artifact")
            if arm == "candidate":
                candidate_artifacts.add(sha)
        if arm in units[(fit, case)]:
            blockers.add("UNSUPPORTED_RETRY_EPISODE_ADAPTER")
        units[(fit, case)][arm] = row
        if row["status"] in {"unknown", "pending", "censored"}:
            blockers.add("UNRESOLVED_ATTEMPTS")
        for key in ("net_utility", "retention"):
            if row[key] is None:
                blockers.add("UNMEASURED_OUTCOME")
            else:
                number(row[key])
        if not isinstance(row["costs"], dict) or not set(row["costs"]) <= set(
            COST_CATEGORIES
        ):
            raise ValueError("unknown cost categories")
        values = [row["costs"].get(key) for key in COST_CATEGORIES]
        if any(number(value) < 0 for value in values if value is not None):
            raise ValueError("costs must be nonnegative")
        if any(value is None for value in values):
            blockers.add("UNMEASURED_COST")
            costs[arm].append(None)
        else:
            costs[arm].append(math.fsum(values))
        for key in ("common_start_sha256", "improver_sha256"):
            if row[key] is not None:
                digest(row[key])
    if seen != registered:
        raise ValueError("attempt inventory and raw rows have different denominators")
    unit_document, unit_review = None, None
    if grouped:
        unit_document = evidence.read(document["units"])
        bound(
            unit_document,
            "hepta.cell-research-units.v1",
            units_adapter.FIELDS,
            experiment,
            configuration_pin,
            protocol_pin,
        )
        unit_review = units_adapter.review(
            unit_document,
            rows,
            evidence,
            spec["sampling"] if spec is not None else None,
            COST_CATEGORIES,
        )
        blockers.update(unit_review["blockers"])
    totals = {
        arm: None if None in values else math.fsum(values)
        for arm, values in costs.items()
    }
    campaign_total = None if None in totals.values() else math.fsum(totals.values())
    if document["evidence_kind"] != "real":
        blockers.add("NON_REAL_EVIDENCE")
    if configuration_sha is None or protocol_sha is None or spec is None:
        blockers.add("MISSING_FROZEN_BINDING")
    if spec is not None:
        if any(set(unit) != arms for unit in units.values()):
            blockers.add("UNPAIRED_ATTEMPTS")
        candidate_fits = [sha for (arm, _), sha in fits.items() if arm == "candidate"]
        if len(candidate_artifacts) < spec["minimum_independent_fits"] or len(
            candidate_fits
        ) != len(candidate_artifacts):
            blockers.add("INSUFFICIENT_DISTINCT_FIT_ARTIFACTS")
        if campaign_total is not None and campaign_total > spec["maximum_total_cost"]:
            blockers.add("BUDGET_EXCEEDED")
    if experiment == "IMPROVER-1":
        construction = defaultdict(list)
        for row in rows:
            if row["arm"] == "candidate":
                construction[row["improver_sha256"]].append(
                    row["costs"].get("improver_construction")
                )
        if any(
            None in values or math.fsum(values) <= 0 for values in construction.values()
        ):
            blockers.add("IMPROVER_CONSTRUCTION_NOT_RECORDED")
        for unit in units.values():
            starts = {row["common_start_sha256"] for row in unit.values()}
            if (
                len(starts) != 1
                or not starts <= design["common_start_artifacts"].keys()
            ):
                blockers.add("COMMON_START_UNBOUND")
            candidate, baseline = unit.get("candidate"), unit.get("frozen_improver")
            if (
                candidate is None
                or baseline is None
                or baseline["improver_sha256"] not in lineage
                or lineage.get(candidate["improver_sha256"])
                != baseline["improver_sha256"]
            ):
                blockers.add("IMPROVER_LINEAGE_UNBOUND")
    comparisons = {}
    if not blockers:
        for baseline in spec["baselines"]:
            by_fit = defaultdict(list)
            for (fit, _), unit in units.items():
                candidate, control = unit["candidate"], unit[baseline]
                by_fit[fit].append(
                    (
                        candidate["net_utility"] - control["net_utility"],
                        candidate["retention"] - control["retention"],
                    )
                )
            means = (
                units_adapter.balanced_fit_means(
                    units, unit_document["cases"], baseline
                )
                if grouped
                else [
                    tuple(fmean(value[index] for value in values) for index in range(2))
                    for values in by_fit.values()
                ]
            )
            gain, retention = (
                min(values[index] for values in means) for index in range(2)
            )
            saving = (
                1 - totals["candidate"] / totals[baseline]
                if totals[baseline] > 0
                else None
            )
            if saving is not None and not math.isfinite(saving):
                raise ValueError("derived cost fraction is not finite")
            cost_route = (
                experiment in {*STAGES["S3"], *STAGES["S5"]}
                and gain >= 0
                and saving is not None
                and saving >= spec["minimum_cost_fraction_saved"]
            )
            passed = retention >= spec["retention_floor"] and (
                gain >= spec["minimum_net_gain"] or cost_route
            )
            comparisons[baseline] = {
                "minimum_fit_mean_gain": gain,
                "minimum_fit_mean_retention": retention,
                "cost_fraction_saved": saving,
                "descriptive_threshold_met": passed,
            }
    threshold = bool(comparisons) and all(
        row["descriptive_threshold_met"] for row in comparisons.values()
    )
    if comparisons and not threshold:
        blockers.add("DESCRIPTIVE_THRESHOLD_NOT_MET")
    return {
        "mechanical_ready": configuration_sha is not None
        and protocol_sha is not None
        and spec is not None,
        "numerical_screen_ready": threshold,
        "descriptive_threshold_met": threshold,
        "substantive_evidence_ready": False,
        "trusted_review_required": True,
        "independent_training_verified": False,
        "complete_budget_verified": False,
        "evidence_kind_verified": False,
        "matched_budget_verified": False,
        "complete_attempt_inventory_verified": False,
        "protocol_scope": "grouped_units_v2" if grouped else "legacy_v1_descriptive",
        "new_milestone_eligible": False,
        "statistical_units": unit_review,
        "full_cost_records_complete": unit_review["full_cost_recorded"]
        if grouped
        else False,
        "attempt_counts": dict(counts),
        "attempt_denominator": len(rows),
        "distinct_candidate_artifacts": len(candidate_artifacts),
        "observed_cost_totals": totals,
        "observed_campaign_total": campaign_total,
        "comparisons": comparisons,
        "blockers": sorted(
            blockers
            | {"STATISTICAL_ADAPTER_UNSUPPORTED", "EVALUATOR_AUTHENTICITY_UNVERIFIED"}
        ),
    }


def assess(manifest: dict, source_root: Path, artifact_root: Path) -> dict:
    """Check originals and return review readiness, never an admissibility token."""
    shape(
        {key: value for key, value in manifest.items() if key != "inventory"}
        if isinstance(manifest, dict)
        else manifest,
        "schema joint_configuration protocol foundation experiments",
        "hepta.cell-research-review.v1",
    )
    if (
        not isinstance(manifest["experiments"], dict)
        or not set(manifest["experiments"]) <= BASELINES.keys()
    ):
        raise ValueError(
            "unknown experiment IDs; numeric or historical stages are unsupported"
        )
    inventory = manifest.get("inventory", {})
    if not isinstance(inventory, dict) or len(inventory) > 256:
        raise ValueError("invalid evidence inventory")
    missing, results, foundation_ready, configuration, joint_result = (
        [],
        {},
        False,
        None,
        None,
    )
    configuration_sha, protocol_sha, expected_configuration_sha = None, None, None
    foundation_result = None
    declared_bindings = {
        "joint_configuration_sha256": None,
        "protocol_sha256": None,
    }
    with joint.directory_root(artifact_root.resolve(strict=True)) as descriptor:
        evidence = Evidence(descriptor)
        for name, binding in inventory.items():
            identity(name)
            evidence.read(binding, document=False)
        if manifest["joint_configuration"] is None:
            missing.append("MISSING_JOINT_CONFIGURATION")
        else:
            configuration = evidence.read(manifest["joint_configuration"])
            configuration_sha = manifest["joint_configuration"]["sha256"]
            joint_result = joint.verify(configuration, source_root, artifact_root)
            declared_bindings["joint_configuration_sha256"] = configuration_sha
            for binding in [
                *configuration["artifacts"].values(),
                configuration["ci_evidence"],
            ]:
                evidence.read(binding, document=False)
        if manifest["protocol"] is None:
            missing.append("MISSING_PROTOCOL")
            specs = {}
        else:
            protocol = evidence.read(manifest["protocol"])
            protocol_sha = manifest["protocol"]["sha256"]
            specs = protocol_specs(protocol, evidence, configuration_sha)
            expected_configuration_sha = protocol["joint_configuration_sha256"]
            declare_bindings(
                {
                    "joint_configuration_sha256": expected_configuration_sha,
                    "protocol_sha256": protocol_sha,
                },
                declared_bindings,
            )
        if manifest["foundation"] is None:
            missing.append("MISSING_FOUNDATION_EVIDENCE")
        else:
            foundation = evidence.read(manifest["foundation"])
            foundation_result = foundation_adapter.review(
                foundation, evidence, joint_result
            )
            declare_bindings(foundation, declared_bindings)
            foundation_ready = foundation_result["mechanical_ready"]
        for experiment, binding in manifest["experiments"].items():
            if protocol_sha is not None and experiment not in specs:
                raise ValueError("experiment is absent from the frozen protocol")
            results[experiment] = experiment_review(
                experiment,
                binding,
                evidence,
                specs.get(experiment),
                configuration_sha,
                protocol_sha,
                expected_configuration_sha,
                declared_bindings=declared_bindings,
            )
        evidence.finish()
        if configuration is not None and joint.source_identity(
            source_root.resolve(strict=True)
        ) != {
            "commit": configuration["source"]["commit"],
            "tree": configuration["source"]["tree"],
            "index_tree": configuration["source"]["tree"],
        }:
            raise ValueError("source changed during research review")
        evidence.finish()
    stages = {}
    for stage, experiments in STAGES.items():
        blockers = (
            list(missing)
            if stage == "S0"
            else [
                f"MISSING_EXPERIMENT:{item}"
                for item in experiments
                if item not in results
            ]
        )
        if stage == "S0":
            blockers += [
                "OWNER_AUTHENTICATION_ADAPTER_UNSUPPORTED",
                "RECOVERY_ADAPTER_UNSUPPORTED",
            ]
            blockers += (
                ["SUCCESSOR_ADAPTER_UNSUPPORTED"]
                if foundation_result is None
                else foundation_result["blockers"]
            )
        else:
            blockers += sorted(
                {
                    item
                    for experiment in experiments
                    if experiment in results
                    for item in results[experiment]["blockers"]
                }
            )
        stages[stage] = {
            "mechanical_ready": not missing and foundation_ready
            if stage == "S0"
            else all(
                item in results and results[item]["mechanical_ready"]
                for item in experiments
            ),
            "numerical_screen_ready": False
            if stage == "S0"
            else all(
                item in results and results[item]["numerical_screen_ready"]
                for item in experiments
            ),
            "substantive_evidence_ready": False,
            "trusted_review_required": True,
            "blocked_by_prior_stage": list(stages),
            "blockers": blockers,
        }
    return {
        "schema": "hepta.cell-research-review-result.v1",
        "stages": stages,
        "experiments": results,
        "foundation": foundation_result,
        "source": joint_result["source"] if joint_result is not None else None,
        "joint_configuration_sha256": configuration_sha,
        "protocol_sha256": protocol_sha,
        "declared_bindings": declared_bindings,
        "inventory": inventory,
        "research_advancement": False,
        "authority_granted": False,
        "production_qualification": False,
        "preregistration_verified": False,
        "trusted_review_required": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with joint.directory_root(
            args.manifest.parent.resolve(strict=True)
        ) as descriptor:
            with joint.regular_file(descriptor, args.manifest.name) as stream:
                before = joint.file_fingerprint(os.fstat(stream.fileno()))
                raw = stream.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024 or before != joint.file_fingerprint(
                    os.fstat(stream.fileno())
                ):
                    raise ValueError("manifest changed or exceeds 1 MiB")
        if args.output.resolve().is_relative_to(args.source_root.resolve()):
            raise ValueError("review output must be outside the source checkout")
        result = assess(joint.strict_json(raw), args.source_root, args.artifact_root)
        result["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"report_written": True, "research_advancement": False}))
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"report_written": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
