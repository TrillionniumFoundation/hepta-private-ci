"""Read-only source-truth and cost annex; imports no execution or grading code.

This annex is authored after the execution code was sealed, before reading its
held results. Its author also contributed runner/transport code, so the result
is an independent calculation, not a third-party implementation audit.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_identity(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("not an admitted regular file: " + str(path))
    value = path.read_bytes()
    return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}


def load(path):
    return json.loads(Path(path).read_bytes())


class Audit:
    def __init__(self):
        self.checks, self.failure_count, self.failures = 0, 0, []

    def check(self, condition, message):
        self.checks += 1
        if not condition:
            self.failure_count += 1
            if len(self.failures) < 100:
                self.failures.append(message)


def read_source(run, case, audit):
    folder, cutoff = run / case["path"], case["source_cut"]
    source_path = folder / "source.sqlite"
    audit.check(
        file_identity(source_path) == case["files"]["source.sqlite"],
        "source file differs: " + case["path"],
    )
    snapshot_path = (
        folder / "artifacts" / "snapshots" / (case["snapshot_digest"] + ".json")
    )
    bundle = load(snapshot_path)
    audit.check(
        digest(bundle) == case["snapshot_digest"],
        "snapshot identity differs: " + case["path"],
    )
    connection = sqlite3.connect(
        source_path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    )
    connection.row_factory = sqlite3.Row
    try:
        clock = connection.execute("SELECT seq FROM clock WHERE id=1").fetchone()[0]
        raw_rows = [
            dict(row)
            for row in connection.execute("SELECT * FROM records ORDER BY seq")
        ]
        revoked = [
            dict(row)
            for row in connection.execute("SELECT * FROM revocations ORDER BY seq")
        ]
    finally:
        connection.close()
    audit.check(
        clock == cutoff == bundle["source_cut"], "source cut differs: " + case["path"]
    )
    rows, indexes = {}, defaultdict(list)
    for raw in raw_rows:
        identity = raw["source_id"]
        value = json.loads(raw["payload"])
        metadata = {
            key: val for key, val in raw.items() if key not in {"source_id", "payload"}
        }
        audit.check(
            digest(value) == raw["value_digest"], "payload digest differs: " + identity
        )
        audit.check(
            digest(metadata) == identity, "source metadata digest differs: " + identity
        )
        audit.check(0 < raw["seq"] <= cutoff, "source sequence outside admitted cut")
        row = {**metadata, "source_id": identity, "value": value}
        rows[identity] = row
        indexes[(row["scope"], row["entity"], row["kind"])].append(row)
    frontier = {
        "scope": case["scope"],
        "cut": cutoff,
        "records": [
            row["source_id"]
            for row in raw_rows
            if row["scope"] == case["scope"] and row["seq"] <= cutoff
        ],
        "revoked": [row["source_id"] for row in revoked if row["seq"] <= cutoff],
    }
    audit.check(
        digest(frontier) == bundle["source_frontier"],
        "source frontier differs: " + case["path"],
    )
    for items in indexes.values():
        items.sort(key=lambda row: (row["effective_at"], row["seq"]))
    return {
        "rows": rows,
        "indexes": indexes,
        "revoked": {row["source_id"] for row in revoked},
        "bundle": bundle,
        "entities": sorted(
            {row["entity"] for row in raw_rows if row["scope"] == case["scope"]}
        ),
    }


def resolve(source, scope, entity, kind, at):
    possible = [
        row
        for row in source["indexes"].get((scope, entity, kind), [])
        if row["effective_at"] <= at
    ]
    if not possible:
        raise ValueError("no source for an executed typed read")
    row = possible[-1]
    if row["source_id"] in source["revoked"]:
        raise ValueError("selected source is revoked; no fallback allowed")
    return row


def source_answer(source, request, operation, *, shuffled=False):
    if operation is None:
        return None, []
    scope, entity = request["scope"], request["entity"]
    dependencies = []

    def read(kind, at):
        addressed = entity
        if shuffled and kind in ("semantic", "procedure"):
            addresses = sorted(source["bundle"]["supports"][kind])
            addressed = addresses[(addresses.index(entity) + 1) % len(addresses)]
        row = resolve(source, scope, addressed, kind, at)
        dependencies.append(row["source_id"])
        return row["value"]

    if operation == "current":
        value = read("event", 2**53 - 1)
    elif operation == "history":
        value = read("event", request["at"])
    elif operation == "semantic":
        value = read("semantic", 2**53 - 1)
    elif operation == "procedure":
        value = read("procedure", 2**53 - 1)
    elif operation == "change":
        value = read("event", 2**53 - 1) - read("event", request["since"])
    elif operation == "apply":
        event = read("event", 2**53 - 1)
        semantic = read("semantic", 2**53 - 1)
        program = read("procedure", 2**53 - 1)
        factor, bias, limit = semantic["factor"], program["bias"], program["limit"]
        opcode = program["opcode"]
        if opcode == "identity":
            value = event
        elif opcode == "add_bias":
            value = event + bias
        elif opcode == "multiply":
            value = event * factor
        elif opcode == "affine":
            value = event * factor + bias
        elif opcode == "clamp":
            value = event * factor + bias
            if value < -limit:
                value = -limit
            if value > limit:
                value = limit
        else:
            raise ValueError("unregistered source procedure")
    else:
        raise ValueError("unregistered requested operation")
    return value, list(dict.fromkeys(dependencies))


def audit(run, freeze_path, admitted_freeze, held):
    run, held = Path(run).resolve(), Path(held).resolve()
    complete_path = run / "evaluation" / "COMPLETE.json"
    if not complete_path.is_file():
        raise ValueError("formal evaluation is incomplete; do not open raw/held")
    complete = load(complete_path)
    if (
        file_identity(freeze_path)["sha256"] != admitted_freeze
        or complete["freeze_sha256"] != admitted_freeze
    ):
        raise ValueError("completion/freeze identity differs")
    freeze = load(freeze_path)
    if (
        file_identity(run / "PREPARED.json") != freeze["prepared"]
        or file_identity(run / "execution_plan.json") != freeze["plan"]
    ):
        raise ValueError("preparation or plan differs from frozen evidence")
    records_path, costs_path = (
        run / "evaluation" / "records.jsonl",
        run / "evaluation" / "COSTS.json",
    )
    if (
        file_identity(records_path) != complete["records"]
        or file_identity(costs_path) != complete["costs"]
    ):
        raise ValueError("raw records or cost ledger differ from completed evidence")
    # Only completion-admitted evidence is read from this point onward.
    if (
        file_identity(held / "SEAL.json")["sha256"] != freeze["held_seal_sha256"]
        or file_identity(held / "queries.json")["sha256"]
        != freeze["held_queries_sha256"]
    ):
        raise ValueError("held evidence differs from the pre-exposure seal")
    corpus = load(held / "queries.json")
    queries = {row["id"]: (index, row) for index, row in enumerate(corpus)}
    prepared, plan, costs = (
        load(run / "PREPARED.json"),
        load(run / "execution_plan.json"),
        load(costs_path),
    )
    checker, cases = Audit(), {}
    for case in prepared["cases"]:
        key = (case["seed"], case["domain"])
        source = read_source(run, case, checker)
        checker.check(
            source["bundle"]["router_digest"]
            == prepared["routers"][str(case["seed"])]["manifest_sha256"],
            "bundle/router mismatch",
        )
        checker.check(
            len(source["entities"]) == plan["memory_entities_per_domain"],
            "entity inventory differs",
        )
        cases[key] = (case, source)
    totals, seen, exact_routed_abstentions = (
        defaultdict(lambda: defaultdict(float)),
        set(),
        0,
    )
    count = 0
    with records_path.open() as records:
        for line in records:
            row = json.loads(line)
            count += 1
            index, query = queries[row["template_id"]]
            case, source = cases[(row["seed"], row["domain"])]
            request = row["request"]
            key = (row["seed"], row["domain"], row["arm"], row["template_id"])
            label = "/".join(str(item) for item in key)
            checker.check(key not in seen, "duplicate record: " + label)
            seen.add(key)
            checker.check(
                row["gold_operation"] == query["operation"],
                "held operation differs: " + label,
            )
            checker.check(
                request["scope"] == case["scope"], "request scope differs: " + label
            )
            checker.check(
                request["entity"]
                == source["entities"][(index + case["seed"]) % len(source["entities"])],
                "request entity assignment differs: " + label,
            )
            checker.check(
                request["at"] == plan["time_contract"]["at"]
                and request["since"] == plan["time_contract"]["since"],
                "request dates differ: " + label,
            )
            expected_text = query["text"].format(
                entity=request["entity"], at=request["at"], since=request["since"]
            )
            checker.check(
                request["text"] == expected_text
                and row["request_sha256"] == digest(request),
                "request wording or binding differs: " + label,
            )
            value, sources = source_answer(source, request, query["operation"])
            checksum = None if value is None else digest(value)
            checker.check(
                row["expected_value_digest"] == checksum
                and canonical(row["expected_value"]) == canonical(value),
                "independent expected value differs: " + label,
            )
            checker.check(
                row["expected_sources"] == sources,
                "independent expected sources differ: " + label,
            )
            if row["accepted"]:
                executed, bound_sources = source_answer(
                    source,
                    request,
                    row["actual_operation"],
                    shuffled=row["arm"] == "parameter_shuffled",
                )
                checker.check(
                    row["actual_sources"] == bound_sources,
                    "executed source binding differs: " + label,
                )
                checker.check(
                    row["source_versions_valid"]
                    and row["generation"] == source["bundle"]["generation"]
                    and row["snapshot_digest"] == case["snapshot_digest"],
                    "accepted source generation differs: " + label,
                )
                if row["arm"] == "exact_same_router":
                    checker.check(
                        canonical(row["actual_value"]) == canonical(executed),
                        "exact reader differs from executed source operation: " + label,
                    )
            else:
                checker.check(
                    row["actual_value"] is None
                    and not row["actual_sources"]
                    and not row["actual_cell_digests"],
                    "failed read retains partial answer/dependencies: " + label,
                )
                exact_routed_abstentions += (
                    row["arm"] == "exact_same_router"
                    and row["actual_operation"] is not None
                )
            total = totals[key[:3]]
            total["rows"] += 1
            total["read_wall_seconds"] += row["latency_seconds"]
            for name in (
                "rpc_bytes",
                "rpc_attempts",
                "read_attempts",
                "validation_attempts",
            ):
                total[name] += row["transport"][name]
    checker.check(
        count == complete["rows"] == plan["expected_records"] == costs["record_count"],
        "formal record count differs",
    )
    planned = {
        (seed, domain, arm)
        for seed in plan["seeds"]
        for domain in plan["domains"]
        for arm in plan["full_arms"]
    }
    checker.check(set(totals) == planned, "formal case/arm coverage differs")
    checker.check(
        len(costs["cases"]) == len(cases)
        and {(case["seed"], case["domain"]) for case in costs["cases"]} == set(cases),
        "cost case inventory differs",
    )
    for case in costs["cases"]:
        checker.check(
            set(case["arms"]) == set(plan["full_arms"]), "cost arm inventory differs"
        )
        deployments = case["deployment"]["deployments"]
        checker.check(
            len({item["pid"] for item in deployments}) == 6
            and len({item["source_inode"] for item in deployments}) == 6,
            "deployment is not six independent process/disk copies",
        )
        for item in deployments:
            total_bytes = sum(info["bytes"] for info in item["files"].values())
            checker.check(
                total_bytes == item["required_snapshot_bytes"],
                "deployment byte inventory differs",
            )
            if item["reader_kind"] == "exact":
                checker.check(
                    not item["has_parameter_objects"]
                    and not any(
                        name.startswith("artifacts/objects/") for name in item["files"]
                    ),
                    "exact reader was charged parameter objects",
                )
        for arm, reported in case["arms"].items():
            actual = totals[(case["seed"], case["domain"], arm)]
            checker.check(set(reported) == set(actual), "cost metric inventory differs")
            checker.check(
                actual["rows"] == plan["templates"], "case/arm template count differs"
            )
            for name, value in reported.items():
                checker.check(
                    math.isclose(actual[name], value, rel_tol=1e-12, abs_tol=1e-9),
                    "cost ledger disagrees with raw rows: " + name,
                )
    return {
        "schema": "hepta.memory.v6.independent-source-annex.v1",
        "audit_passed": checker.failure_count == 0,
        "checks": checker.checks,
        "failure_count": checker.failure_count,
        "failures_first_100": checker.failures,
        "rows": count,
        "cases": len(cases),
        "case_arms": len(totals),
        "source_records": sum(len(source["rows"]) for _, source in cases.values()),
        "exact_routed_abstentions": exact_routed_abstentions,
        "records": complete["records"],
        "freeze_sha256": admitted_freeze,
        "annex_source": file_identity(__file__),
        "cost_totals": {
            name: sum(row[name] for row in totals.values())
            for name in (
                "rows",
                "read_wall_seconds",
                "rpc_bytes",
                "rpc_attempts",
                "read_attempts",
                "validation_attempts",
            )
        },
        "limitations": [
            "This independently recomputes source truth and recorded accounting, not neural predictions or historical timing/OS traffic.",
            "The author also implemented runner/transport; this is not a third-party audit.",
            "Frozen source records are synthetic experimental truth, not externally verified real-world facts.",
            "Encoder, development, replay, structure search and transfer costs require their separate ledgers.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run, args.freeze, args.freeze_sha256, args.held)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                name: result[name]
                for name in (
                    "audit_passed",
                    "checks",
                    "failure_count",
                    "rows",
                    "cases",
                    "case_arms",
                )
            }
        )
    )
    raise SystemExit(0 if result["audit_passed"] else 1)


if __name__ == "__main__":
    main()
