"""Full independent Python reconstruction and fresh-process native replay."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

from .build import verify_build
from .common import Native, charge, digest, sha, write
from .reference import Reference, compare
from .run import verify_checkpoint


def account_records(path):
    raw = Path(path).read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("torn resource-account ledger")
    records = []
    for line in raw.splitlines():
        envelope = json.loads(line)
        if (
            hashlib.sha256(envelope["payload_json"].encode()).hexdigest()
            != envelope["record_digest"]
        ):
            raise ValueError("account record hash mismatch")
        records.append((envelope, json.loads(envelope["payload_json"])))
    if not records:
        raise ValueError("missing account header")
    return records


def reconstruct(root, expected_plan):
    """Recompute all outcomes, causal prefixes, resource feedback and stream identities."""
    root = Path(root)
    plan = json.loads((root / "PLAN.json").read_text())
    if plan != expected_plan:
        raise ValueError("organ plan differs from the frozen expected roster")
    index = json.loads((root / "INDEX.json").read_text())
    start = json.loads((root / "START.json").read_text())
    if (
        not index["complete"]
        or index["organ"] != plan["organ"]
        or index["policy"] != plan["policy"]
    ):
        raise ValueError("incomplete or misidentified organ")
    specifications = plan["episodes"]
    names = [row["case"] for row in specifications]
    if (
        not names
        or len(set(names)) != len(names)
        or [row["case"] for row in index["episodes"]] != names
    ):
        raise ValueError("missing, duplicate or reordered episode roster")
    if sorted(p.name for p in root.iterdir() if p.is_dir()) != sorted(names):
        raise ValueError("raw case directories differ from the expected roster")
    if (
        sha(root / "PLAN.json") != index["plan_sha256"]
        or sha(root / "PLAN.json") != start["plan_sha256"]
    ):
        raise ValueError("plan identity mismatch")
    model, checkpoint = verify_checkpoint(
        root / "MODEL.json", root / "TRAINED_CHECKPOINT.json"
    )
    if (
        sha(root / "MODEL.json") != start["model_sha256"]
        or sha(root / "TRAINED_CHECKPOINT.json") != start["checkpoint_sha256"]
    ):
        raise ValueError("trained profile identity mismatch")
    account = root / f"organ.{plan['organ']}.jsonl"
    if (
        sha(account) != index["account_sha256"]
        or account.stat().st_size != index["account_bytes"]
    ):
        raise ValueError("resource account identity mismatch")
    account_rows = account_records(account)
    if len(account_rows) != len(names) + 1:
        raise ValueError("one conserved-credit settlement per episode required")
    header, header_payload = account_rows[0]
    if header_payload != {
        "schema": "hepta.adaptive-neuron.resource-account.v2",
        "organ": plan["organ"],
        "settings": model["credit"],
    }:
        raise ValueError("resource account contract mismatch")
    state = {
        "sequence": 0,
        "balance": model["credit"]["initial_balance"],
        "price": model["credit"]["initial_price"],
        "head": header["record_digest"],
    }
    summary, original_files = [], {}
    for specification, row, (account_envelope, account_payload) in zip(
        specifications, index["episodes"], account_rows[1:]
    ):
        directory = root / specification["case"]
        if sha(directory / "EPISODE.json") != row["episode_sha256"]:
            raise ValueError("episode receipt identity mismatch")
        episode = json.loads((directory / "EPISODE.json").read_text())
        if (
            episode["specification"] != specification
            or episode["organ"] != plan["organ"]
            or episode["model_sha256"] != start["model_sha256"]
            or episode["binary_sha256"] != start["binary_sha256"]
        ):
            raise ValueError("episode changed its stream or model identity")
        for name, identity in episode["raw_files"].items():
            path = directory / name
            if (
                sha(path) != identity["sha256"]
                or path.stat().st_size != identity["bytes"]
            ):
                raise ValueError("raw native evidence identity mismatch")
            original_files[str(path.relative_to(root))] = identity
        compare(episode["initial_account"], state, path="initial account")
        identity = json.loads((directory / "IDENTITY.json").read_text())
        compare(identity["initial_account"], state, path="native account identity")
        if (
            identity["expected_account_sequence"] != state["sequence"]
            or episode["request"]["expected_account_sequence"] != state["sequence"]
        ):
            raise ValueError("Changed organ sequence")
        if (
            identity["model_sha256"] != start["model_sha256"]
            or identity["binary_sha256"] != start["binary_sha256"]
        ):
            raise ValueError("native identity differs from published inputs")
        reference = Reference(
            model, tuple(specification["context"]), plan["policy"], state
        )
        events_raw = (directory / "events.jsonl").read_bytes()
        if not events_raw.endswith(b"\n"):
            raise ValueError("torn event ledger")
        events = [json.loads(line) for line in events_raw.splitlines()]
        if not events:
            raise ValueError("empty applied owner trace")
        for i, event in enumerate(events):
            if i >= len(specification["observations"]):
                raise ValueError("observations after the declared deadline")
            value = specification["observations"][i]
            expected_observation = {
                "event_id": f"observation.{i}",
                "value": value,
                "elapsed": i + 1,
                "evidence_digest": digest(
                    [
                        "adaptive-neuron.causal-observation.v2",
                        specification["stream_id"],
                        i,
                        value,
                    ]
                ),
            }
            if event["observation"] != expected_observation:
                raise ValueError("noncausal or changed evidence stream")
            output = event["output"]
            compare(output["readout"], reference.observe(value))
            if output["terminal"] != (
                output["native_abstain"] or output["readout"]["action"] != "continue"
            ):
                raise ValueError("terminal effect does not match the applied decision")
            if i + 1 < len(events) and output["terminal"]:
                raise ValueError("native work executed after stopping")
        last = events[-1]["output"]
        if not last["terminal"]:
            raise ValueError("unsettled task masquerades as complete")
        action = "abstain" if last["native_abstain"] else last["readout"]["action"]
        signed = {"positive": 1, "negative": -1, "abstain": 0}[action]
        reward = float(signed * specification["truth"]) if signed else 0.05
        expected_outcome = digest(
            [
                "adaptive-neuron.observed-outcome.v2",
                specification["stream_id"],
                specification["truth"],
                signed,
                reward,
            ]
        )
        settlement = json.loads((directory / "SETTLEMENT.json").read_text())
        if (
            settlement["account_record"] != account_envelope
            or settlement["outcome_digest"] != expected_outcome
            or settlement["reward"] != reward
        ):
            raise ValueError("feedback is not the independently observed outcome")
        compare(account_payload["before"], state, path="account predecessor")
        after = reference.settle(specification["budget"], reward)
        compare(
            {
                "balance": account_payload["after_balance"],
                "price": account_payload["after_price"],
            },
            after,
            path="settled account",
        )
        overflow = max(
            0.0,
            state["balance"]
            - reference.work
            + specification["budget"]
            + model["credit"]["kappa"] * reward
            - model["credit"]["balance_cap"],
        )
        compare(account_payload["balance_overflow"], overflow, path="balance overflow")
        if (
            account_payload["case"] != specification["case"]
            or account_payload["organ"] != plan["organ"]
            or account_payload["actual_work"] != reference.work
            or account_payload["reward"] != reward
            or account_payload["budget"] != specification["budget"]
            or account_payload["owner_checkpoint"] != last["checkpoint_after"]
            or account_payload["support_digest"] != settlement["support_digest"]
        ):
            raise ValueError(
                "credit attribution differs from actual owner work/outcome"
            )
        credit = account_payload["native_credit"]
        expected_q32 = round(reward * (1 << 32))
        if (
            credit["native_function"] != "finalize_credit_batch"
            or credit["allocation_count"] != 1
            or credit["conservation_residual_q32"] != 0
            or credit["terminal_outcome_q32"] != expected_q32
            or credit["authority"] != "DENY_ALL"
            or credit["signature_admission"]
            or credit["production_ledger_append"]
        ):
            raise ValueError("native credit scope or conservation changed")
        metrics = {
            "observations": len(events),
            "avoided_later_observations": specification["context"][2] - len(events),
            "decision": action,
            "reward": reward,
            "utility": reward - len(events) * specification["context"][1],
            "covered": signed != 0,
            "correct": signed == specification["truth"],
            "native_fallbacks": sum(
                bool(e["output"]["native_abstain"]) for e in events
            ),
            "applied_readouts": sum(not e["output"]["native_abstain"] for e in events),
            "actual_resource_work": reference.work,
            "actual_spikes": reference.spikes,
            "actual_snn_cell_updates": reference.cells,
            "price_used": reference.price,
            "shadow_price_before": state["price"],
            "shadow_price_after": after["price"],
            "balance_before": state["balance"],
            "balance_after": after["balance"],
            "balance_overflow": overflow,
            "budget_forced_abstention": last["readout"]["budget_forced_abstention"],
        }
        compare(episode["metrics"], metrics, path="episode metrics")
        compare(row["metrics"], metrics, path="index metrics")
        if episode["work"] != charge(episode["rpc"]):
            raise ValueError(
                "runtime accounting does not match the complete RPC ledger"
            )
        if row["work"] != episode["work"] or row["processes"] != episode["processes"]:
            raise ValueError("index omitted runtime costs")
        actual_observations = [
            rpc["response"]["result"]
            for rpc in episode["rpc"]
            if rpc["response"]["ok"]
            and rpc["response"]["result"].get("native_transition_executed")
        ]
        if actual_observations != [event["output"] for event in events]:
            raise ValueError("RPC applied transitions differ from durable events")
        if (
            episode["work"]["owner_ticks"] != len(events)
            or episode["work"]["actual_snn_cell_updates"] != reference.cells
            or episode["work"]["actual_resource_work"] != reference.work
        ):
            raise ValueError("actual work mismatch")
        if any(process["exit_code"] != 0 for process in episode["processes"]):
            raise ValueError("failed process in a claimed complete episode")
        summary.append(
            {
                "case": specification["case"],
                "metrics": metrics,
                "request": episode["request"],
                "outcome_digest": expected_outcome,
                "terminal_status": episode["terminal_status"],
            }
        )
        state = {
            "sequence": state["sequence"] + 1,
            **after,
            "head": account_envelope["record_digest"],
        }
    return {
        "episodes": summary,
        "raw_files": original_files,
        "final_account": state,
        "model": model,
        "checkpoint": checkpoint,
        "start": start,
    }


def audit_organ(
    binary,
    root,
    *,
    source_seal=None,
    expected_plan=None,
    development=False,
    output=None,
):
    started, parent_start = time.perf_counter_ns(), time.process_time_ns()
    before_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    root = Path(root).resolve()
    output = root / "AUDIT.json" if output is None else Path(output)
    if output.exists():
        raise FileExistsError(output)
    audits, all_cost = [], []
    try:
        if development:
            source = {"development_only": True}
            expected_plan = expected_plan or json.loads(
                (root / "PLAN.json").read_text()
            )
        else:
            from experiments.adaptive_neuron_v2.provenance import verify

            if source_seal is None or expected_plan is None:
                raise ValueError(
                    "Independent scientific audit requires the seal and frozen expected plan"
                )
            source = verify(source_seal)
        verified = reconstruct(root, expected_plan)
        if sha(binary) != verified["start"]["binary_sha256"]:
            raise ValueError("Exact historical native executable required")
        if not development:
            if verified["start"]["source"] != source:
                raise ValueError(
                    "Original execution and audit source identities differ"
                )
            if (
                sha(root / "BUILD_RECEIPT.json")
                != verified["start"]["build_receipt_sha256"]
            ):
                raise ValueError("Historical build receipt changed")
            verify_build(root / "BUILD_RECEIPT.json", binary, source_seal, source)
        before_files = {
            str(p.relative_to(root)): sha(p) for p in root.rglob("*") if p.is_file()
        }
        for episode in verified["episodes"]:
            native = Native(Path(binary).resolve(), root)
            request = dict(episode["request"])
            request.update(
                model=str(root / "MODEL.json"),
                calibration=str(root / "CALIBRATION.json"),
            )
            try:
                restored = native.call({"command": "Resume", "request": request})
                if restored["status"] != episode["terminal_status"]:
                    raise AssertionError(
                        "Independent cold recovery changed terminal state"
                    )
                credit = native.call(
                    {
                        "command": "Settle",
                        "reward": episode["metrics"]["reward"],
                        "outcome_digest": episode["outcome_digest"],
                    }
                )
                if (
                    not credit["duplicate_settlement_ignored"]
                    or credit["new_credit_records"]
                ):
                    raise AssertionError("Historical replay credited the organ again")
                native.call({"command": "Close"})
            finally:
                process = native.close()
                work = charge(native.rows)
                audits.append(
                    {
                        "case": episode["case"],
                        "work": work,
                        "process": process,
                        "rpc": native.rows,
                    }
                )
                all_cost.append(work)
        after_files = {
            str(p.relative_to(root)): sha(p) for p in root.rglob("*") if p.is_file()
        }
        if before_files != after_files:
            raise AssertionError("Historical replay changed raw evidence bytes")
        after_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "schema": "hepta.adaptive-neuron.organ-audit.v2",
            "passed": True,
            "source": source,
            "organ": expected_plan["organ"],
            "episodes_verified": len(verified["episodes"]),
            "episode_metrics": [
                {"case": row["case"], "metrics": row["metrics"]}
                for row in verified["episodes"]
            ],
            "final_account": verified["final_account"],
            "raw_file_count": len(before_files),
            "raw_file_hashes": before_files,
            "raw_bytes_unchanged": True,
            "work": {
                key: (max if key.startswith("peak_") else sum)(
                    row[key] for row in all_cost
                )
                for key in all_cost[0]
            },
            "replay": audits,
            "parent_cpu_ns": time.process_time_ns() - parent_start,
            "child_cpu_seconds": after_cpu.ru_utime
            + after_cpu.ru_stime
            - before_cpu.ru_utime
            - before_cpu.ru_stime,
            "wall_ns": time.perf_counter_ns() - started,
            "development_only": development,
        }
        write(output, result)
        return result
    except Exception as error:
        after_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        write(
            output.with_name(output.stem + "_FAILED.json"),
            {
                "error": repr(error),
                "completed_replays": audits,
                "parent_cpu_ns": time.process_time_ns() - parent_start,
                "child_cpu_seconds": after_cpu.ru_utime
                + after_cpu.ru_stime
                - before_cpu.ru_utime
                - before_cpu.ru_stime,
                "wall_ns": time.perf_counter_ns() - started,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "root", "source-seal", "expected-plan", "output"):
        parser.add_argument("--" + name, type=Path, required=name in ("binary", "root"))
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    plan = (
        None
        if args.expected_plan is None
        else json.loads(args.expected_plan.read_text())
    )
    result = audit_organ(
        args.binary,
        args.root,
        source_seal=args.source_seal,
        expected_plan=plan,
        development=args.development,
        output=args.output,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "organ",
                    "passed",
                    "episodes_verified",
                    "parent_cpu_ns",
                    "child_cpu_seconds",
                    "wall_ns",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
