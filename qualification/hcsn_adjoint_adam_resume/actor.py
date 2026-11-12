"""One fresh numerical actor; complete checkpoint publication is explicit."""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import shutil
import time
import traceback

import numpy as np
import torch

from qualification.hcsn_adjoint_torch.torch_flow import amplitude_flow, CallBudget
from .state import (
    NAMES,
    PROTOCOL,
    capture_rng,
    clones,
    fixture,
    fingerprint,
    gradients,
    load,
    publish,
    restore_rng,
    runtime,
    same,
    sha,
    validate_checkpoint,
    validate_values,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-nonce", required=True)
    parser.add_argument("--geometry", choices=("uniform", "graded"), required=True)
    parser.add_argument(
        "--mode",
        choices=("continuous", "first", "resume", "crash", "reject"),
        required=True,
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--published", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    importlib.import_module("torch._dynamo")  # Preload before seeding/restoring RNG.
    source = json.loads(args.source.read_text())
    before = {name: sha(name) for name in source["source_sha256"]}
    if before != source["source_sha256"]:
        raise ValueError("prefrozen actor source differs")
    frozen_path = Path("qualification/hcsn_adjoint_adam_resume/SOURCE.json")
    if (
        sha(frozen_path) != source["prefrozen_inventory_sha256"]
        or before != json.loads(frozen_path.read_text())["source_sha256"]
    ):
        raise ValueError("remote-prefrozen actor source inventory differs")
    current_runtime = runtime()
    seed = 701 if args.geometry == "uniform" else 907
    random.seed(seed)
    np.random.seed(seed + 1)
    torch.manual_seed(seed + 2)
    model, times, supports, values, base_target, snapshot = fixture(
        args.geometry, args.baseline
    )
    initial = {name: value.clone() for name, value in zip(NAMES, values)}
    budget = CallBudget(forward_limit=3, adjoint_limit=3)
    arrays, records = {}, []
    updates = 0
    completed_updates = 0
    step = 0
    cursor = 0
    parameters = None
    optimizer = None
    checkpoint_before = sha(args.checkpoint) if args.checkpoint else None
    started, cpu = time.perf_counter(), time.process_time()
    published = args.published or args.output / "state.pt"

    def complete(status, error=None, extra=None, exit_code=0):
        for i, row in enumerate(budget.forward_records):
            for j, value in enumerate(row["inputs"]):
                arrays[f"forward{i}_input{j}"] = value
            arrays[f"forward{i}_output"] = row["output"]
        for i, row in enumerate(budget.backward_records):
            arrays[f"backward{i}_cotangent"] = row["cotangent"]
            arrays[f"backward{i}_vjp"] = row["vjp"]
        np.savez_compressed(args.output / "ARRAYS.npz", **arrays)
        result = dict(
            status=status,
            admission_nonce=args.admission_nonce,
            operation_counts_are_invocations=True,
            completed_adam_updates=completed_updates,
            completed_forward_calls=len(budget.forward_records),
            completed_adjoint_calls=len(budget.backward_records),
            error=error,
            geometry=args.geometry,
            mode=args.mode,
            pid=os.getpid(),
            parent_pid=os.getppid(),
            source=source,
            runtime=current_runtime,
            source_before=before,
            source_after={n: sha(n) for n in before},
            records=records,
            logical_step=step,
            cursor=cursor,
            calls=dict(
                forwards=budget.forward_calls,
                adjoints=budget.adjoint_calls,
                adam_updates=updates,
            ),
            forward_journal=[
                {k: v for k, v in row.items() if k not in ("inputs", "output")}
                for row in budget.forward_records
            ],
            backward_journal=[
                {k: v for k, v in row.items() if k not in ("cotangent", "vjp")}
                for row in budget.backward_records
            ],
            input_checkpoint_sha_before=checkpoint_before,
            input_checkpoint_sha_after=sha(args.checkpoint)
            if args.checkpoint
            else None,
            arrays_sha256=sha(args.output / "ARRAYS.npz"),
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu,
            exit_code=exit_code,
            extra=extra,
        )
        path = args.output / "RESULT.json"
        with path.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(
            json.dumps(
                dict(
                    status=status,
                    admission_nonce=args.admission_nonce,
                    operation_counts_are_invocations=True,
                    completed_adam_updates=completed_updates,
                    completed_forward_calls=len(budget.forward_records),
                    completed_adjoint_calls=len(budget.backward_records),
                    pid=os.getpid(),
                    calls=result["calls"],
                    logical_step=step,
                    cursor=cursor,
                    error=error,
                ),
                sort_keys=True,
            ),
            flush=True,
        )
        return result

    try:
        payload = None
        if args.checkpoint:
            payload = load(args.checkpoint)
            try:
                validate_checkpoint(payload, source, current_runtime, snapshot, initial)
            except ValueError as exc:
                if args.mode != "reject":
                    raise
                complete(
                    "REJECTED_BEFORE_FORWARD",
                    dict(type=type(exc).__name__, message=str(exc)),
                    exit_code=42,
                )
                raise SystemExit(42)
        if (
            payload is not None
            and args.mode in ("resume", "crash")
            and payload["step"] != 1
        ):
            raise ValueError("this restoration actor requires a step-one boundary")
        if args.mode == "reject":
            raise ValueError("omit-Adam checkpoint was unexpectedly accepted")
        parameters = [
            torch.nn.Parameter(
                (payload["parameters"][name] if payload else initial[name]).clone()
            )
            for name in NAMES
        ]
        optimizer = torch.optim.Adam(
            parameters,
            lr=1e-4,
            betas=(0.9, 0.999),
            eps=1e-8,
            weight_decay=0,
            foreach=False,
            fused=False,
        )
        if payload:
            optimizer.load_state_dict(payload["adam"])
            step, cursor = payload["step"], payload["cursor"]
            for name, value in zip(NAMES, parameters):
                value.grad = payload["gradients"][name].clone()
            restore_rng(payload["rng"])

        def frame():
            return dict(
                protocol=PROTOCOL,
                source=source,
                runtime=current_runtime,
                original_snapshot=snapshot,
                original_inputs=initial,
                parameters=clones(parameters),
                gradients=gradients(parameters),
                adam=optimizer.state_dict(),
                step=step,
                cursor=cursor,
                rng=capture_rng(),
            )

        def evaluate(label):
            budget.label = label
            optimizer.zero_grad(set_to_none=True)
            py = float(random.random())
            np_value = float(np.random.random())
            noise = 0.001 * torch.randn(
                base_target.shape, dtype=torch.float64
            ) + 0.001 * (py + np_value)
            target = 0.9 * base_target + noise
            previous = clones(parameters)
            output, _ = amplitude_flow(
                model, times, *parameters, supports=supports, budget=budget
            )
            loss = (output - target).square().mean()
            loss.backward()
            if not bool(torch.isfinite(loss)):
                raise ValueError("nonfinite loss")
            gradient = gradients(parameters)
            for i, name in enumerate(NAMES):
                arrays[label + "_before_" + name] = previous[name].numpy()
                arrays[label + "_gradient_" + name] = gradient[name].numpy()
            arrays[label + "_target"] = target.numpy()
            arrays[label + "_output"] = output.detach().numpy()
            row = dict(
                label=label,
                loss=float(loss.detach()),
                python_uniform=py,
                numpy_uniform=np_value,
                gradient=fingerprint(gradient),
                parameters_before=fingerprint(previous),
                cursor=cursor,
            )
            records.append(row)
            return row

        count = 2 if args.mode == "continuous" else 1
        for _ in range(count):
            row = evaluate("step" + str(step + 1))
            if updates >= 2:
                raise ValueError("actor Adam invocation budget exceeded")
            updates += 1
            optimizer.step()
            completed_updates += 1
            step += 1
            cursor += 1
            validate_values(clones(parameters), initial)
            if updates > 2 or step > 2:
                raise ValueError("actor update budget exceeded")
            row["parameters_after"] = fingerprint(clones(parameters))
            row["adam_after"] = fingerprint(optimizer.state_dict())
            for name, value in zip(NAMES, parameters):
                arrays[row["label"] + "_after_" + name] = value.detach().numpy().copy()
            state = frame()
            validate_checkpoint(state, source, current_runtime, snapshot, initial)

            def crash_hook(pending):
                if args.mode != "crash":
                    return
                complete(
                    "EXPECTED_CRASH_BEFORE_REPLACE",
                    extra=dict(
                        published=str(published),
                        published_sha256=sha(published),
                        pending=str(pending),
                        pending_sha256=sha(pending),
                        pending_state=fingerprint(state),
                    ),
                    exit_code=73,
                )
                os._exit(73)

            publish(state, published, crash_hook if args.mode == "crash" else None)
            checkpoint = args.output / f"step{step}.pt"
            shutil.copyfile(published, checkpoint)
            row["checkpoint_path"] = str(checkpoint)
            row["checkpoint_sha256"] = sha(checkpoint)
        canonical = frame()
        if args.mode in ("continuous", "resume"):
            prior_rng = capture_rng()
            prior_gradients = gradients(parameters)
            evaluate("next")
            restore_rng(prior_rng)
            for name, value in zip(NAMES, parameters):
                value.grad = prior_gradients[name].clone()
            if not same(canonical, frame()):
                raise ValueError("next-gradient probe changed canonical state")
        if not same(load(published), canonical):
            raise ValueError("published full logical state differs")
        if budget.forward_calls > 3 or budget.adjoint_calls > 3 or updates > 2:
            raise ValueError("actor cost budget exceeded")
        if before != {n: sha(n) for n in before}:
            raise ValueError("actor source changed")
        complete(
            "PASS",
            extra=dict(
                published=str(published),
                published_sha256=sha(published),
                published_state=fingerprint(canonical),
            ),
        )
    except SystemExit:
        raise
    except Exception as exc:
        complete(
            "HOLD",
            dict(
                type=type(exc).__name__,
                message=str(exc),
                traceback=traceback.format_exc(),
            ),
            exit_code=1,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
