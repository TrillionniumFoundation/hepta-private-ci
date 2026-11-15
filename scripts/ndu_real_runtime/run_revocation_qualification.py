"""MEM7 post-update revocation campaign using fresh public retrieval processes.

This isolates revocation from update: a snapshot and rebuilt dependency chain
must be readable immediately before the revoke. All evidence is synthetic and
same-authority; this does not measure an agent, neural benefit or effect fencing.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .episodic_memory import EpisodicStore, digest
from .episodic_retrieval import verify_read_receipt
from .run_episodic_qualification import pin, write


SOURCES = ["source-address", "source-route", "source-summary", "source-contact"]
SCENARIOS = [
    "live_updated_fact",
    "snapshot_current_fact",
    "snapshot_active_chain",
    "restricted_dependency_closure",
    "snapshot_off",
    "snapshot_retrieval_off",
    "snapshot_delivery_off",
    "revoked_live_fact",
    "revoked_snapshot_fact",
    "revoked_snapshot_bm25",
    "revoked_snapshot_uniform",
    "revoked_snapshot_icl",
    "unrelated_snapshot_fact",
    "unrelated_live_fact",
]


def mutate(root, phase):
    """Commit a mutation batch and exit before any successor reader starts."""
    store = EpisodicStore(
        root / "authority.sqlite",
        namespace="owner-a",
        max_records=32,
        max_serialized_bytes=65536,
        create=phase == "learn",
    )
    records, operation = {}, None
    if phase in {"learn", "update"}:
        address = "Cedar Street" if phase == "learn" else "Maple Street"
        inputs = [
            ("fact", SOURCES[0], "address", f"Address is {address}.", []),
            ("route", SOURCES[1], "route", f"Route to {address}.", ["fact"]),
            ("summary", SOURCES[2], "memo", f"Dispatch to {address}.", ["route"]),
        ]
        if phase == "learn":
            inputs.append(
                ("contact", SOURCES[3], "contact", "Contact Harbor desk.", [])
            )
        for name, source, key, text, dependencies in inputs:
            records[name] = store.put(
                source,
                key,
                text,
                provenance={
                    "source_uri": f"fixture://mem7/{phase}/{name}",
                    "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "source_version": phase,
                    "episode_id": f"{phase}-{name}",
                },
                dependencies=[records[value]["record_id"] for value in dependencies],
            )
        if phase == "update":
            operation = store.export_snapshot(root / "after-update.json")
    elif phase == "revoke":
        operation = store.revoke(SOURCES[0], "address")
    else:
        raise ValueError("unknown mutation phase")
    write(
        root / f"{phase}.response.json",
        {
            "phase": phase,
            "pid": os.getpid(),
            "records": records,
            "operation": operation,
            "view": store.view(),
        },
    )


def run(output, source_commit=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    repository = Path(__file__).resolve().parents[2]
    sources = [
        Path(__file__),
        *(
            Path(__file__).with_name(name)
            for name in (
                "episodic_memory.py",
                "episodic_retrieval.py",
                "episodic_receipt.py",
                "run_episodic_qualification.py",
            )
        ),
    ]
    plan = {
        "schema": "hepta.mem7.revocation-plan.v1",
        "source_commit": source_commit,
        "source_pins": [pin(path, repository) for path in sources],
        "scenarios": SCENARIOS,
        "fixture_data": "synthetic",
        "sequence": [
            "learn",
            "update_and_rebuild_chain",
            "snapshot",
            "verify_snapshot_readable",
            "revoke",
            "read_same_snapshot",
        ],
        "reader": "ndu_real_runtime.episodic_retrieval public CLI",
        "model_calls": 0,
        "scientific_acceptance": "HOLD",
        "independent_trust_domain": False,
        "full_owner_cold_recovery": False,
        "deletion_scope": "logical read exclusion; snapshot bytes remain",
    }
    write(output / "PLAN.json", plan)
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(repository / "scripts") + os.pathsep + str(repository),
    }
    mutations, rows = [], []

    def launch(name, arguments):
        command = [sys.executable, "-B", "-m", *arguments]
        with (output / f"{name}.stdout.json").open("xb") as stdout:
            with (output / f"{name}.stderr.txt").open("xb") as stderr:
                begin = time.perf_counter()
                process = subprocess.Popen(
                    command, cwd=repository, env=env, stdout=stdout, stderr=stderr
                )
                try:
                    code = process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    code = 124
        receipt = {
            "argv": command,
            "pid": process.pid,
            "returncode": code,
            "wall_seconds_with_startup": time.perf_counter() - begin,
            "stdout": pin(output / f"{name}.stdout.json", output),
            "stderr": pin(output / f"{name}.stderr.txt", output),
        }
        write(output / f"{name}.process.json", receipt)
        if code:
            raise RuntimeError(f"{name} failed with exit {code}; logs retained")
        return receipt

    def mutation(phase):
        receipt = launch(
            phase,
            [
                "ndu_real_runtime.run_revocation_qualification",
                "--mutate",
                str(output),
                "--phase",
                phase,
            ],
        )
        path = output / f"{phase}.response.json"
        receipt.update(
            phase=phase, response=pin(path, output), writer_exited_before_readers=True
        )
        mutations.append(receipt)
        return json.loads(path.read_bytes())

    def check(
        name,
        expected_ids,
        *,
        snapshot=True,
        key="address",
        strategy="exact_kv",
        mode="on",
        allowed_sources=None,
        expected_rejections=None,
    ):
        allowed_sources = SOURCES if allowed_sources is None else allowed_sources
        args = [
            "ndu_real_runtime.episodic_retrieval",
            "--namespace",
            "owner-a",
            "--session",
            f"fresh-{name}",
            "--mode",
            mode,
            "--strategy",
            strategy,
            "--key",
            key,
            "--query",
            "Maple contact",
            "--limit",
            "8",
            "--max-context-bytes",
            "4096",
            "--seed",
            "11",
        ]
        if mode != "off":
            args.extend(["--store", str(output / "authority.sqlite")])
        if snapshot:
            args.extend(["--snapshot", str(output / "after-update.json")])
        for source in allowed_sources:
            args.extend(["--source", source])
        write(output / f"{name}.request.json", {"argv": args})
        receipt = launch(name, args)
        result = json.loads((output / f"{name}.stdout.json").read_bytes())
        read_receipt = result["receipt"]
        view = read_receipt["view_receipt"]
        expected_request = {
            "session_id": f"fresh-{name}",
            "mode": mode,
            "strategy": strategy,
            "source_ids": sorted(allowed_sources),
            "query_sha256": digest({"query": "Maple contact", "key": key}),
            "limit": 8,
            "max_context_bytes": 4096,
            "replay_seed": 11,
        }
        request_bound = all(
            read_receipt.get(k) == v for k, v in expected_request.items()
        )
        passed = (
            verify_read_receipt(result)
            and request_bound
            and sorted(result["receipt"]["delivered_ids"]) == sorted(expected_ids)
            and (
                expected_rejections is None
                or view["snapshot_rejections"] == expected_rejections
            )
        )
        row = {
            "scenario": name,
            "passed": passed,
            "process": receipt,
            "request": pin(output / f"{name}.request.json", output),
            "expected_ids": expected_ids,
            "request_bound": request_bound,
            "receipt": result["receipt"],
        }
        rows.append(row)
        return row

    initial = mutation("learn")
    updated = mutation("update")
    active = updated["records"]
    contact = initial["records"]["contact"]["record_id"]
    affected = [record["record_id"] for record in active.values()]
    all_ids = [contact, *affected]
    snapshot_pin = pin(output / "after-update.json", output)
    check("live_updated_fact", [active["fact"]["record_id"]], snapshot=False)
    before = check(
        "snapshot_current_fact", [active["fact"]["record_id"]], expected_rejections=0
    )
    chain = check(
        "snapshot_active_chain", all_ids, strategy="icl", expected_rejections=0
    )
    check(
        "restricted_dependency_closure",
        [],
        key="memo",
        allowed_sources=[SOURCES[1], SOURCES[2]],
        expected_rejections=0,
    )
    check("snapshot_off", [], mode="off")
    check("snapshot_retrieval_off", [], mode="retrieval_off")
    check("snapshot_delivery_off", [], mode="delivery_off")
    revoked = mutation("revoke")
    check("revoked_live_fact", [], snapshot=False)
    after = check("revoked_snapshot_fact", [], expected_rejections=3)
    for name, strategy in (
        ("bm25", "bm25"),
        ("uniform", "uniform_replay"),
        ("icl", "icl"),
    ):
        check(
            f"revoked_snapshot_{name}",
            [contact],
            strategy=strategy,
            expected_rejections=3,
        )
    check("unrelated_snapshot_fact", [contact], key="contact", expected_rejections=3)
    check("unrelated_live_fact", [contact], key="contact", snapshot=False)
    before_view, after_view = (r["receipt"]["view_receipt"] for r in (before, after))
    invariants = {
        "same_snapshot_bytes": snapshot_pin
        == pin(output / "after-update.json", output),
        "same_snapshot_receipt": before_view["snapshot_sha256"]
        == after_view["snapshot_sha256"],
        "same_authority": before_view["authority_id"] == after_view["authority_id"],
        "revoke_advances_one_generation": after_view["authority_generation"]
        == before_view["authority_generation"] + 1,
        "chain_active_immediately_before_revoke": chain["passed"],
        "exact_three_revocations": revoked["operation"]["status"] == "revoked"
        and set(revoked["operation"]["affected_ids"]) == set(affected),
        "source_pins_unchanged": plan["source_pins"]
        == [pin(p, repository) for p in sources],
        "scenario_order_matches_plan": [r["scenario"] for r in rows] == SCENARIOS,
    }
    report = {
        "schema": "hepta.mem7.revocation-report.v1",
        "plan": pin(output / "PLAN.json", output),
        "rows": rows,
        "mutations": mutations,
        "invariants": invariants,
        "passed_scenarios": sum(row["passed"] for row in rows),
        "planned_scenarios": len(SCENARIOS),
        "fresh_read_processes": len(rows),
        "exited_writer_processes": len(mutations),
        "status": "PASS"
        if all(invariants.values()) and all(r["passed"] for r in rows)
        else "FAIL",
        "wall_seconds": time.perf_counter() - started,
        "model_calls": 0,
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
        "real_successor_task_benefit": False,
        "full_owner_cold_recovery": False,
        "external_effect_fencing": False,
        "independent_trust_domain": False,
        "complete_cost_coverage": False,
        "deletion_scope": plan["deletion_scope"],
    }
    write(output / "REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--mutate", type=Path)
    parser.add_argument("--phase", choices=["learn", "update", "revoke"])
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    if args.mutate:
        if args.phase is None:
            parser.error("--phase is required with --mutate")
        mutate(args.mutate, args.phase)
        return 0
    report = run(args.output, args.source_commit)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "passed_scenarios", "scientific_acceptance")
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
