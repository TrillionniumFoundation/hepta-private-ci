"""Run one complete organ sequence with task-trained native SNN stopping."""

import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np

from experiments.adaptive_neuron_v2.learning.network import (
    model_payload as neural_payload,
)
from .build import verify_build
from .common import (
    Native,
    charge,
    digest,
    encoder_proof,
    open_request,
    permit,
    sha,
    write,
)
from .reference import Reference, compare


def verify_checkpoint(model_path, checkpoint_path):
    model = json.loads(Path(model_path).read_text())
    checkpoint = json.loads(Path(checkpoint_path).read_text())
    family = "standard" if checkpoint["arm"] == "standard" else "first_passage"
    parameters = {
        key: np.asarray(value) for key, value in checkpoint["parameters"].items()
    }
    expected = neural_payload(
        parameters, np.asarray(checkpoint["raw_theta"]), family, sha(checkpoint_path)
    )
    if model["neural"] != expected:
        raise ValueError("Native readout differs from the task-trained checkpoint")
    return model, checkpoint


def episode(
    binary, root, organ, model, calibration, policy, specification, account_sequence=0
):
    started, parent_start = time.perf_counter_ns(), time.process_time_ns()
    context = tuple(specification["context"])
    case, truth = specification["case"], int(specification["truth"])
    observations = [int(value) for value in specification["observations"]]
    if (
        truth not in (-1, 1)
        or len(observations) != context[2]
        or any(value not in (-1, 1) for value in observations)
    ):
        raise ValueError("Malformed complete exogenous stream")
    request = open_request(
        case,
        organ,
        model,
        calibration,
        policy,
        context,
        specification["budget"],
        account_sequence=account_sequence,
    )
    payload = json.loads(Path(model).read_text())
    native = Native(binary, root)
    processes, all_rows, outputs = [], [], []
    try:
        opened = native.call({"command": "Open", "request": request})
        reference = Reference(
            payload, context, policy, opened["status"]["initial_account"]
        )
        for index, value in enumerate(observations):
            observation = {
                "event_id": f"observation.{index}",
                "value": value,
                "elapsed": index + 1,
                "evidence_digest": digest(
                    [
                        "adaptive-neuron.causal-observation.v2",
                        specification["stream_id"],
                        index,
                        value,
                    ]
                ),
            }
            output = native.call({"command": "Observe", "observation": observation})
            expected = reference.observe(value)
            compare(output["readout"], expected)
            outputs.append(output)
            if index == 0:
                retry = native.call({"command": "Observe", "observation": observation})
                if (
                    retry["native_transition_executed"]
                    or retry["actual_resource_work"] != 0
                ):
                    raise AssertionError(
                        "An exact retry consumed neural or resource work"
                    )
                if not output["terminal"]:
                    status = native.call({"command": "Close"})
                    all_rows.extend(native.rows)
                    processes.append(native.close())
                    native = Native(binary, root)
                    restored = native.call({"command": "Resume", "request": request})
                    if restored["status"] != status:
                        raise AssertionError(
                            "Cold recovery changed the owner, SNN or credit state"
                        )
            if output["terminal"]:
                break
        else:
            raise AssertionError("Deadline did not terminate the native task")
        decision = (
            "abstain" if output["native_abstain"] else output["readout"]["action"]
        )
        signed = {"positive": 1, "negative": -1, "abstain": 0}[decision]
        reward = float(signed * truth) if signed else 0.05
        outcome_digest = digest(
            [
                "adaptive-neuron.observed-outcome.v2",
                specification["stream_id"],
                truth,
                signed,
                reward,
            ]
        )
        settled = native.call(
            {"command": "Settle", "reward": reward, "outcome_digest": outcome_digest}
        )
        settlement = json.loads(settled["record"]["payload_json"])
        expected_settlement = reference.settle(specification["budget"], reward)
        compare(
            {
                "balance": settlement["after_balance"],
                "price": settlement["after_price"],
            },
            expected_settlement,
        )
        retry = native.call(
            {"command": "Settle", "reward": reward, "outcome_digest": outcome_digest}
        )
        if not retry["duplicate_settlement_ignored"] or retry["new_credit_records"]:
            raise AssertionError("Settlement retry changed resource credit twice")
        native.call(
            {
                "command": "Observe",
                "observation": {
                    "event_id": "after-terminal",
                    "value": 1,
                    "elapsed": len(outputs) + 1,
                    "evidence_digest": digest([case, "rejected-terminal-observation"]),
                },
            },
            expect_error=True,
        )
        terminal_status = native.call({"command": "Close"})
        all_rows.extend(native.rows)
        processes.append(native.close())
        native = None
        actual = len(outputs)
        metrics = {
            "observations": actual,
            "avoided_later_observations": context[2] - actual,
            "decision": decision,
            "reward": reward,
            "utility": reward - actual * context[1],
            "covered": signed != 0,
            "correct": signed == truth,
            "native_fallbacks": sum(bool(row["native_abstain"]) for row in outputs),
            "applied_readouts": sum(not row["native_abstain"] for row in outputs),
            "actual_resource_work": reference.work,
            "actual_spikes": reference.spikes,
            "actual_snn_cell_updates": reference.cells,
            "price_used": reference.price,
            "shadow_price_before": reference.initial["price"],
            "shadow_price_after": expected_settlement["price"],
            "balance_before": reference.initial["balance"],
            "balance_after": expected_settlement["balance"],
            "balance_overflow": settlement["balance_overflow"],
            "budget_forced_abstention": bool(
                output["readout"]["budget_forced_abstention"]
            ),
        }
        files = {
            p.name: {"sha256": sha(p), "bytes": p.stat().st_size}
            for p in sorted((root / case).iterdir())
            if p.is_file()
        }
        result = {
            "schema": "hepta.adaptive-neuron.native-episode.v2",
            "case": case,
            "organ": organ,
            "specification": specification,
            "request": request,
            "initial_account": reference.initial,
            "model_sha256": sha(model),
            "binary_sha256": sha(binary),
            "metrics": metrics,
            "terminal_status": terminal_status,
            "settlement": settled,
            "work": charge(all_rows),
            "processes": processes,
            "rpc": all_rows,
            "raw_files": files,
            "parent_cpu_ns": time.process_time_ns() - parent_start,
            "wall_ns": time.perf_counter_ns() - started,
            "python_native_prefixes_verified": actual,
        }
        write(root / case / "EPISODE.json", result)
        return {
            "case": case,
            "episode_sha256": sha(root / case / "EPISODE.json"),
            "metrics": metrics,
            "work": result["work"],
            "processes": processes,
            "wall_ns": result["wall_ns"],
            "parent_cpu_ns": result["parent_cpu_ns"],
        }
    except Exception:
        if native is not None:
            all_rows.extend(native.rows)
            try:
                processes.append(native.close())
            except Exception as error:
                processes.append({"close_error": repr(error)})
        write(
            root / f"{case}.FAILED.json",
            {
                "rpc": all_rows,
                "processes": processes,
                "completed_prefix": outputs,
                "wall_ns": time.perf_counter_ns() - started,
                "parent_cpu_ns": time.process_time_ns() - parent_start,
            },
        )
        raise


def run_organ(
    binary,
    destination,
    organ,
    model_path,
    checkpoint_path,
    policy,
    episodes,
    *,
    source_seal=None,
    build_receipt=None,
    development=False,
):
    started, parent_start = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)
    rows = []
    try:
        if development:
            identity = {"development_only": True}
        else:
            from experiments.adaptive_neuron_v2.provenance import verify

            if source_seal is None or build_receipt is None:
                raise ValueError(
                    "Registered native runs require source seal and build receipt"
                )
            identity = verify(source_seal)
            verify_build(build_receipt, binary, source_seal, identity)
        model, checkpoint = verify_checkpoint(model_path, checkpoint_path)
        if not development and checkpoint.get("development_only"):
            raise ValueError("Development checkpoint cannot enter a scientific run")
        permit(root)
        local_model, local_checkpoint, calibration = (
            root / "MODEL.json",
            root / "TRAINED_CHECKPOINT.json",
            root / "CALIBRATION.json",
        )
        local_model.write_bytes(Path(model_path).read_bytes())
        local_checkpoint.write_bytes(Path(checkpoint_path).read_bytes())
        if build_receipt is not None:
            (root / "BUILD_RECEIPT.json").write_bytes(Path(build_receipt).read_bytes())
        encoder_proof(local_model, calibration)
        plan = {"organ": organ, "policy": policy, "episodes": episodes}
        if len({row["case"] for row in episodes}) != len(episodes):
            raise ValueError("Duplicate registered case identity")
        write(root / "PLAN.json", plan)
        write(
            root / "START.json",
            {
                "source": identity,
                "binary_sha256": sha(binary),
                "model_sha256": sha(local_model),
                "checkpoint_sha256": sha(local_checkpoint),
                "plan_sha256": sha(root / "PLAN.json"),
                "build_receipt_sha256": None
                if build_receipt is None
                else sha(build_receipt),
                "development_only": development,
            },
        )
        for account_sequence, specification in enumerate(episodes):
            rows.append(
                episode(
                    Path(binary).resolve(),
                    root,
                    organ,
                    local_model,
                    calibration,
                    policy,
                    specification,
                    account_sequence,
                )
            )
        account = root / f"organ.{organ}.jsonl"
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "schema": "hepta.adaptive-neuron.organ-run.v2",
            "organ": organ,
            "policy": policy,
            "complete": True,
            "source": identity,
            "episodes": rows,
            "plan_sha256": sha(root / "PLAN.json"),
            "account_sha256": sha(account),
            "account_bytes": account.stat().st_size,
            "parent_cpu_ns": time.process_time_ns() - parent_start,
            "child_cpu_seconds": after.ru_utime
            + after.ru_stime
            - before.ru_utime
            - before.ru_stime,
            "wall_ns": time.perf_counter_ns() - started,
            "development_only": development,
        }
        write(root / "INDEX.json", result)
        return result
    except Exception as error:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write(
            root / "INVALID_ATTEMPT.json",
            {
                "error": repr(error),
                "completed_cases": rows,
                "parent_cpu_ns": time.process_time_ns() - parent_start,
                "child_cpu_seconds": after.ru_utime
                + after.ru_stime
                - before.ru_utime
                - before.ru_stime,
                "wall_ns": time.perf_counter_ns() - started,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "binary",
        "destination",
        "plan",
        "model",
        "checkpoint",
        "source-seal",
        "build-receipt",
    ):
        parser.add_argument(
            "--" + name,
            type=Path,
            required=name not in ("source-seal", "build-receipt"),
        )
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    result = run_organ(
        args.binary,
        args.destination,
        plan["organ"],
        args.model,
        args.checkpoint,
        plan["policy"],
        plan["episodes"],
        source_seal=args.source_seal,
        build_receipt=args.build_receipt,
        development=args.development,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "organ",
                    "complete",
                    "parent_cpu_ns",
                    "child_cpu_seconds",
                    "wall_ns",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
