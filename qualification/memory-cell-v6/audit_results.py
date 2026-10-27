"""Independent standard-library audit of V6's recorded language experiment.

No training, router, cell, executor or grading module is imported. Expected
numeric digests and provenance are supplied by the experiment's sealed grader;
this audit verifies comparisons and accounting, not the historical truth of
those supplied gold values, process isolation, wall clocks or all operating I/O.
"""

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random


OPERATIONS = {"current", "history", "semantic", "procedure", "change", "apply"}
FULL_ARMS = {"parameter_actual", "exact_same_router"}
_SPEC = importlib.util.spec_from_file_location(
    "v6_audit_transport", Path(__file__).with_name("audit_transport.py")
)
_TRANSPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_TRANSPORT)
TRANSPORT_COUNTS = _TRANSPORT.COUNTS


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def value_digest(value):
    if value is None:
        return None
    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )


def load_held(directory):
    directory = Path(directory)
    seal = json.loads((directory / "SEAL.json").read_text())
    for name, identity in seal["files"].items():
        path = directory / name
        if path.is_symlink() or path.parent != directory:
            raise ValueError("held seal path is not a direct regular file")
        payload = path.read_bytes()
        if len(payload) != identity["bytes"] or sha256(payload) != identity["sha256"]:
            raise ValueError("held file differs from its seal: " + name)
    corpus = json.loads((directory / "queries.json").read_text())
    queries = {row["id"]: row for row in corpus}
    if len(corpus) != seal["templates"] or len(queries) != len(corpus):
        raise ValueError("held count or identities differ")
    return queries, json.loads((directory / "PROTOCOL.json").read_text()), seal


def wilson(successes, total):
    if total == 0:
        return None
    z = 1.959963984540054
    p = successes / total
    divisor = 1 + z * z / total
    center = (p + z * z / (2 * total)) / divisor
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total**2)) / divisor
    return [max(0.0, center - half), min(1.0, center + half)]


def summarize(rows, protocol):
    known = [row for row in rows if row["gold_operation"] is not None]
    unsupported = [row for row in rows if row["gold_operation"] is None]
    correct = sum(row["audit_success"] for row in known)
    false_accepts = sum(row["accepted"] for row in unsupported)
    routed_ood = sum(row["router_accepted"] for row in unsupported)
    coverage = correct / len(known) if known else None
    risk = routed_ood / len(unsupported) if unsupported else None
    return {
        "known": len(known),
        "correct_known_acceptance": correct,
        "known_coverage": coverage,
        "known_wilson95_descriptive": wilson(correct, len(known)),
        "known_wrong_acceptance": sum(
            row["accepted"] and not row["audit_success"] for row in known
        ),
        "unsupported": len(unsupported),
        "false_unsupported_acceptance": routed_ood,
        "unsupported_final_acceptance": false_accepts,
        "unsupported_acceptance_rate": risk,
        "unsupported_wilson95_descriptive": wilson(routed_ood, len(unsupported)),
        "unsupported_routed_despite_contract": routed_ood,
        "joint_gate": bool(
            coverage is not None
            and risk is not None
            and coverage >= protocol["gate_correct_known_acceptance_minimum"]
            and risk <= protocol["gate_unsupported_acceptance_maximum"]
        ),
    }


def family_interval(rows, *, known):
    by_template = defaultdict(list)
    families = {}
    for row in rows:
        if (row["gold_operation"] is not None) != known:
            continue
        by_template[row["template_id"]].append(
            float(row["audit_success"] if known else row["router_accepted"])
        )
        families[row["template_id"]] = row["query_family"]
    blocks = defaultdict(list)
    for template, outcomes in by_template.items():
        blocks[families[template]].append(sum(outcomes) / len(outcomes))
    if not blocks:
        return None
    groups = list(blocks.values())
    rng = random.Random(627104)
    bootstrap = []
    for _ in range(2000):
        sample = [x for _ in groups for x in rng.choice(groups)]
        bootstrap.append(sum(sample) / len(sample))
    bootstrap.sort()
    return {
        "templates": len(by_template),
        "families": len(groups),
        "template_mean": sum(sum(v) / len(v) for v in by_template.values())
        / len(by_template),
        "percentile95": [bootstrap[49], bootstrap[1949]],
        "resamples": 2000,
        "interpretation": "descriptive family-block resampling; no population guarantee",
    }


def audit_records(raw_rows, queries, protocol, execution_plan=None):
    failures = []
    checks = 0

    def check(condition, explanation):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(explanation)

    rows, identities = [], set()
    cases = defaultdict(list)
    for index, original in enumerate(raw_rows):
        row = dict(original)
        prefix = f"record {index}: "
        template = row.get("template_id", row.get("id"))
        row["template_id"] = template
        if template not in queries:
            check(False, prefix + "unknown held template")
            continue
        gold = queries[template]
        required = {
            "seed",
            "domain",
            "arm",
            "language",
            "query_family",
            "gold_operation",
            "actual_operation",
            "accepted",
            "expected_value",
            "actual_value",
            "expected_value_digest",
            "actual_value_digest",
            "expected_sources",
            "actual_sources",
            "source_versions_valid",
            "value_correct",
            "source_correct",
            "snapshot_digest",
            "router_digest",
            "model_digest",
            "latency_seconds",
            "rpc_bytes",
            "hops",
            "status",
            "prediction_kind",
        }
        missing = required - row.keys()
        check(not missing, prefix + "missing fields " + repr(sorted(missing)))
        if missing:
            continue
        valid_booleans = all(
            type(row[k]) is bool
            for k in (
                "accepted",
                "source_versions_valid",
                "value_correct",
                "source_correct",
            )
        )
        check(valid_booleans, prefix + "invalid boolean field")
        if not valid_booleans:
            continue
        check(
            row["gold_operation"] == gold["operation"],
            prefix + "gold operation differs from held label",
        )
        check(
            row["language"] == gold["language"], prefix + "language differs from held"
        )
        check(
            row["query_family"] == gold["family"], prefix + "family differs from held"
        )
        check(
            row["actual_operation"] in OPERATIONS | {None},
            prefix + "unknown actual operation",
        )
        check(
            isinstance(row["expected_sources"], list)
            and isinstance(row["actual_sources"], list),
            prefix + "provenance is not ordered lists",
        )
        identity = (row["seed"], row["domain"], row["arm"], template)
        check(identity not in identities, prefix + "duplicate case/template")
        identities.add(identity)
        for field in ("snapshot_digest", "router_digest", "model_digest"):
            digest = row[field]
            check(
                isinstance(digest, str)
                and len(digest) == 64
                and all(c in "0123456789abcdef" for c in digest),
                prefix + "invalid " + field,
            )
        for field in ("expected_value_digest", "actual_value_digest"):
            digest = row[field]
            check(
                digest is None
                or (
                    isinstance(digest, str)
                    and len(digest) == 64
                    and all(c in "0123456789abcdef" for c in digest)
                ),
                prefix + "invalid " + field,
            )
        for field in ("expected_value", "actual_value"):
            try:
                digest = value_digest(row[field])
            except (TypeError, ValueError):
                check(False, prefix + "invalid canonical value " + field)
            else:
                check(
                    row[field + "_digest"] == digest,
                    prefix + "raw value digest differs: " + field,
                )
        for field in ("latency_seconds", "rpc_bytes", "hops"):
            value = row[field]
            check(
                type(value) in (int, float) and math.isfinite(value) and value >= 0,
                prefix + "invalid resource measurement " + field,
            )
        check(
            type(row["rpc_bytes"]) is int and type(row["hops"]) is int,
            prefix + "noninteger byte/hop count",
        )
        row["audit_transport"] = _TRANSPORT.check_row(row, prefix, check)
        value_correct = (
            row["expected_value_digest"] is not None
            and row["actual_value_digest"] == row["expected_value_digest"]
        )
        source_correct = (
            bool(row["expected_sources"])
            and row["actual_sources"] == row["expected_sources"]
        )
        check(
            row["value_correct"] == value_correct,
            prefix + "value correctness flag disagrees",
        )
        check(
            row["source_correct"] == source_correct,
            prefix + "provenance correctness flag disagrees",
        )
        if row["accepted"]:
            check(
                row["actual_operation"] is not None,
                prefix + "accepted without an operation",
            )
            check(
                row["actual_value_digest"] is not None,
                prefix + "accepted without a value",
            )
        row["router_accepted"] = row.get(
            "router_accepted", row["actual_operation"] is not None
        )
        check(
            type(row["router_accepted"]) is bool, prefix + "invalid router acceptance"
        )
        check(
            row["router_accepted"] == (row["actual_operation"] is not None),
            prefix + "router decision contradicts operation",
        )
        row["audit_success"] = bool(
            row["gold_operation"] is not None
            and row["accepted"]
            and row["actual_operation"] == row["gold_operation"]
            and value_correct
            and source_correct
            and row["source_versions_valid"]
        )
        rows.append(row)
        cases[identity[:3]].append(row)

    full_arms = FULL_ARMS
    if execution_plan is not None:
        seeds, domains, full_arms = (
            execution_plan[name] for name in ("seeds", "domains", "full_arms")
        )
        check(
            bool(seeds) and len(seeds) == len(set(seeds)),
            "empty or duplicate planned seeds",
        )
        check(
            bool(domains) and len(domains) == len(set(domains)),
            "empty or duplicate planned domains",
        )
        check(
            bool(full_arms) and len(full_arms) == len(set(full_arms)),
            "empty or duplicate planned arms",
        )
        planned = {
            (seed, domain, arm)
            for seed in seeds
            for domain in domains
            for arm in full_arms
        }
        check(
            set(cases) == planned,
            "observed seed/domain/arm cases differ from complete frozen execution plan",
        )
    case_reports = []
    for (seed, domain, arm), case_rows in sorted(
        cases.items(), key=lambda item: str(item[0])
    ):
        if arm in full_arms:
            check(
                {row["template_id"] for row in case_rows} == set(queries),
                f"{seed}/{domain}/{arm}: incomplete held set",
            )
        for field in ("snapshot_digest", "router_digest", "model_digest"):
            check(
                len({row[field] for row in case_rows}) == 1,
                f"{seed}/{domain}/{arm}: mixed {field}",
            )
        by_language = {
            language: summarize(
                [row for row in case_rows if row["language"] == language], protocol
            )
            for language in protocol["languages"]
        }
        report = {
            "seed": seed,
            "domain": domain,
            "arm": arm,
            "overall": summarize(case_rows, protocol),
            "languages": by_language,
            "per_operation": {
                operation: summarize(
                    [row for row in case_rows if row["gold_operation"] == operation],
                    protocol,
                )
                for operation in sorted(OPERATIONS)
            },
            "latency_seconds_sum": sum(row["latency_seconds"] for row in case_rows),
            "rpc_bytes_sum": sum(row["rpc_bytes"] for row in case_rows),
            "hops_sum": sum(row["hops"] for row in case_rows),
            "transport_totals": {
                name: sum(row["audit_transport"][name] for row in case_rows)
                for name in TRANSPORT_COUNTS
            }
            if all(row["audit_transport"] is not None for row in case_rows)
            else None,
        }
        report["joint_gate_all_languages"] = report["overall"]["joint_gate"] and all(
            item["joint_gate"] for item in by_language.values()
        )
        case_reports.append(report)

    primary = {
        (row["seed"], row["domain"], row["template_id"]): row
        for row in rows
        if row["arm"] == "parameter_actual"
    }
    exact = {
        (row["seed"], row["domain"], row["template_id"]): row
        for row in rows
        if row["arm"] == "exact_same_router"
    }
    check(bool(primary), "no primary records")
    check(primary.keys() == exact.keys(), "primary/strong comparator case sets differ")
    paired_differences = []
    for key in primary.keys() & exact.keys():
        left, right = primary[key], exact[key]
        for field in (
            "actual_operation",
            "router_digest",
            "snapshot_digest",
            "expected_value_digest",
            "expected_sources",
        ):
            check(
                left[field] == right[field],
                str(key) + ": comparator mismatch in " + field,
            )
        paired_differences.append(
            int(left["audit_success"]) - int(right["audit_success"])
        )
    arms = sorted({row["arm"] for row in rows})
    return {
        "schema": "hepta.memory.v6.independent-results-audit.v1",
        "checks": checks,
        "failures": failures,
        "audit_passed": not failures,
        "rows": len(raw_rows),
        "validated_rows": len(rows),
        "complete_execution_plan_bound": execution_plan is not None,
        "distinct_language_templates": len({row["template_id"] for row in rows}),
        "distinct_language_families": len({row["query_family"] for row in rows}),
        "cases": case_reports,
        "primary_joint_gate": bool(primary)
        and all(
            report["joint_gate_all_languages"]
            for report in case_reports
            if report["arm"] == "parameter_actual"
        ),
        "paired_primary_minus_exact_success_count": sum(paired_differences),
        "paired_primary_exact_rows": len(paired_differences),
        "family_intervals": {
            arm: {
                "known": family_interval(
                    [row for row in rows if row["arm"] == arm], known=True
                ),
                "unsupported": family_interval(
                    [row for row in rows if row["arm"] == arm], known=False
                ),
            }
            for arm in arms
        },
        "limitations": [
            "Gold numeric values/provenance are supplied by the sealed grader, not independently reconstructed source truth.",
            "Process timing, process history and operating-system I/O are not authenticated by record arithmetic.",
            "Synthetic assistant-authored variants, domains and seeds do not establish population generalization.",
            "Resource sums cover recorded reads only; model, training, versions, replay and migration costs need separate ledgers.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path)
    parser.add_argument("--held", type=Path, default=Path(__file__).parent / "held")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    queries, protocol, _ = load_held(args.held)
    payload = args.records.read_bytes()
    raw_rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    plan_payload = args.plan.read_bytes()
    result = audit_records(raw_rows, queries, protocol, json.loads(plan_payload))
    result["records_sha256"] = sha256(payload)
    result["held_seal_sha256"] = sha256((args.held / "SEAL.json").read_bytes())
    result["execution_plan_sha256"] = sha256(plan_payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("checks", "audit_passed", "primary_joint_gate", "rows")
            }
        )
    )
    raise SystemExit(0 if result["audit_passed"] else 1)


if __name__ == "__main__":
    main()
