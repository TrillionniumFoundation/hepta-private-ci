"""Train and infer with the bounded text/image prototype.

Dynamic finite-model checkpoints have a different state contract and cannot
authorize native deployment. A dynamic request retains the fixed fallback.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

from .delivery import read_delivery
from .lifecycle import CostLedger, Limits


def bounded_bytes(path, maximum, expected=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Input is outside the bounded regular-file profile")
    raw = path.read_bytes()
    if len(raw) > maximum or (
        expected is not None and hashlib.sha256(raw).hexdigest() != expected
    ):
        raise ValueError("Input size or SHA256 differs")
    return raw


def main():
    started, parent_cpu = time.perf_counter(), time.process_time()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--output", required=True)
    training.add_argument("--seed", type=int, default=41)
    training.add_argument("--steps", type=int, default=12)
    infer = commands.add_parser("infer")
    infer.add_argument("--weights", required=True)
    infer.add_argument("--weights-sha256", required=True)
    infer.add_argument("--binary", required=True)
    infer.add_argument("--binary-sha256", required=True)
    infer.add_argument("--text", required=True)
    infer.add_argument("--image", required=True)
    infer.add_argument("--output", required=True)
    infer.add_argument(
        "--policy",
        choices=("encoder-only", "static-quota", "fixed-steps", "dynamic"),
        default="static-quota",
    )
    infer.add_argument("--wall-seconds", type=float, default=30)
    readback = commands.add_parser("read-delivery")
    readback.add_argument("--output", required=True)
    readback.add_argument("--identity", required=True)
    args = parser.parse_args()
    if args.command == "read-delivery":
        print(
            json.dumps(
                read_delivery(args.output, expected_identity=args.identity),
                sort_keys=True,
            )
        )
        return 0

    import torch

    torch.set_num_threads(1)
    output = Path(args.output)
    if output.exists():
        raise ValueError("Output directory already exists")
    if args.command == "train":
        from .generator_training import train

        baseline, candidate, report = train(seed=args.seed, steps=args.steps)
        output.mkdir(parents=True)
        (output / "baseline.heptapk").write_bytes(baseline)
        (output / "candidate.heptapk").write_bytes(candidate)
        (output / "training.json").write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "candidate_sha256": report["candidate_sha256"],
                    "scope": report["scope"],
                    "production_update": "no-update",
                }
            )
        )
        return 0
    from .native import NativeSession, encode_input

    execution_receipt = output.with_name(output.name + ".execution.json")
    if execution_receipt.exists() or execution_receipt.is_symlink():
        raise ValueError("Execution receipt already exists")
    ledger = CostLedger(Limits(32 * 1024 * 1024, 16, args.wall_seconds, 3, 1))
    with ledger.operation("observation"):
        weights = bounded_bytes(args.weights, 64 * 1024 * 1024, args.weights_sha256)
        bounded_bytes(args.binary, 64 * 1024 * 1024, args.binary_sha256)
        image = bounded_bytes(args.image, 1_048_576)
        ledger.retain("checkpoint-packet", len(weights))
        ledger.retain("input-payload", len(image) + len(args.text.encode()))
        public = encode_input(args.text, image)
        ledger.retain(
            "public-tensor-payload",
            sum(t.numel() * t.element_size() for t in public.values()),
        )
    session = NativeSession(
        weights, args.binary, public, wall_seconds=args.wall_seconds, ledger=ledger
    )
    ledger.retain("candidate-state", len(session.native_state))
    ledger.retain("public-wire-payload", len(session.public_bytes))
    effective = "static-quota" if args.policy == "dynamic" else args.policy
    schedules = {
        "encoder-only": (),
        "static-quota": ("text", "image"),
        "fixed-steps": ("both", "text", "image"),
    }
    for modality in schedules[effective]:
        session.repair(modality)
        ledger.retain("candidate-state", len(session.native_state))
    result = session.finish(submit=True, output=output)
    result = read_delivery(output, expected_identity=result["delivery"]["identity"])
    ledger.retain("candidate-state", len(session.native_state))
    ledger.retain("committed-prefix", len(session.prefix))
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result.update(
        requested_policy=args.policy,
        effective_policy=effective,
        dynamic_admitted=False,
        fallback_reason="native state/semantic calibration and measured future net-gain absent"
        if args.policy == "dynamic"
        else None,
        cost_ledger=ledger.summary(),
        whole_cli_wall_seconds=time.perf_counter() - started,
        whole_cli_parent_cpu_seconds=time.process_time() - parent_cpu,
        whole_cli_child_cpu_seconds=child_after.ru_utime
        + child_after.ru_stime
        - child_before.ru_utime
        - child_before.ru_stime,
        accounting="whole CLI and ledger clocks overlap; child CPU is separate; do not sum overlapping wall clocks",
        residency_scope="logical named payload bytes; Python/Torch/native heap and RSS are not fully inventoried",
        complete_real_resource_accounting=False,
    )
    with execution_receipt.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                **{
                    k: result[k]
                    for k in (
                        "requested_policy",
                        "effective_policy",
                        "production_update",
                    )
                },
                "delivery_identity": result["delivery"]["identity"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
