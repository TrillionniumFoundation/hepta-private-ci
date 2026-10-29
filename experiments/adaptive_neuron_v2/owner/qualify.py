"""Development-only qualification of trained owner readouts and resource credit."""

import argparse
import json
from pathlib import Path
import resource
import shutil
import time

from .audit import audit_organ, reconstruct
from .common import Native, charge, model_payload, permit, sha, write
from .run import run_organ, verify_checkpoint


def qualify(binary, destination, neural, checkpoint):
    """Keep every natural trace and failure; never consume scientific seeds."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    rows, negative = [], []
    try:
        if not json.loads(Path(checkpoint).read_text()).get("development_only"):
            raise ValueError(
                "Qualification requires a separately marked development checkpoint"
            )
        model = destination / "MODEL.json"
        write(model, model_payload(json.loads(Path(neural).read_text())))
        source = Path(checkpoint).resolve()
        verify_checkpoint(model, source)
        episodes = [
            {
                "case": f"case.{i:04d}",
                "context": [0.6, 0.01, 8],
                "budget": 3.0,
                "observations": [1, -1, 1, 1, -1, -1, 1, 1],
                "truth": 1,
                "stream_id": ["adaptive-v2-development", i],
            }
            for i in range(4)
        ]
        for readout in ("snn", "raw_belief_dp", "raw_belief_myopic"):
            for credit in ("off", "frozen", "live"):
                name = f"{readout}.{credit}"
                policy = {"readout": readout, "credit": credit}
                plan = {"organ": name, "policy": policy, "episodes": episodes}
                directory = destination / name
                run = run_organ(
                    binary,
                    directory,
                    name,
                    model,
                    source,
                    policy,
                    episodes,
                    development=True,
                )
                audit = audit_organ(
                    binary, directory, expected_plan=plan, development=True
                )
                if readout != "snn" and any(
                    e["metrics"]["actual_snn_cell_updates"]
                    or e["metrics"]["actual_spikes"]
                    for e in run["episodes"]
                ):
                    raise AssertionError(
                        "Raw reference was incorrectly charged spiking work"
                    )
                rows.append(
                    {
                        "name": name,
                        "index_sha256": sha(directory / "INDEX.json"),
                        "audit_sha256": sha(directory / "AUDIT.json"),
                        "metrics": [e["metrics"] for e in run["episodes"]],
                        "native_replayed": audit["episodes_verified"],
                    }
                )
        by_name = {row["name"]: row for row in rows}
        live, frozen = by_name["snn.live"]["metrics"], by_name["snn.frozen"]["metrics"]
        if (
            live[0]["shadow_price_after"] == live[0]["shadow_price_before"]
            or live[1]["price_used"] != live[0]["shadow_price_after"]
        ):
            raise AssertionError(
                "Measured resource/outcome feedback did not reach the next task"
            )
        if [e["observations"] for e in live] == [e["observations"] for e in frozen]:
            raise AssertionError(
                "Development fixture did not demonstrate a stopping-trajectory effect of live credit"
            )
        original = destination / "snn.off"
        original_plan = json.loads((original / "PLAN.json").read_text())
        expected = json.loads((original / "case.0000/EPISODE.json").read_text())
        native = Native(Path(binary).resolve(), original)
        try:
            native.call({"command": "Resume", "request": expected["request"]})
            native.call(
                {
                    "command": "Settle",
                    "reward": expected["metrics"]["reward"],
                    "outcome_digest": "a" * 64,
                },
                expect_error=True,
            )
            conflicting = dict(expected["rpc"][1]["request"]["observation"])
            conflicting["value"] *= -1
            native.call(
                {"command": "Observe", "observation": conflicting}, expect_error=True
            )
            native.call({"command": "Close"})
        finally:
            process = native.close()
            negative.append(
                {
                    "check": "conflicting outcome and observation retries",
                    "rpc": native.rows,
                    "work": charge(native.rows),
                    "process": process,
                }
            )
        wrong_model = json.loads(model.read_text())
        wrong_model["neural"]["bias"] += 0.01
        altered = destination / "ALTERED_MODEL.json"
        write(altered, wrong_model)
        try:
            verify_checkpoint(altered, source)
        except ValueError:
            negative.append(
                {"check": "checkpoint/profile alteration", "rejected": True}
            )
        else:
            raise AssertionError("Altered trained profile was admitted")
        wrong_plan = json.loads(json.dumps(original_plan))
        wrong_plan["episodes"] = list(reversed(wrong_plan["episodes"]))
        try:
            reconstruct(original, wrong_plan)
        except ValueError:
            negative.append(
                {"check": "independent roster disagreement", "rejected": True}
            )
        else:
            raise AssertionError("Changed expected roster was admitted")
        recovery = destination / "recovery_copy"
        shutil.copytree(original, recovery)
        (recovery / "RESEARCH_PERMIT.json").unlink()
        permit(recovery)
        active = recovery / "organ.snn.off.active.json"
        write(active, {"case": "case.0000"})
        request = dict(expected["request"])
        request.update(
            model=str(recovery / "MODEL.json"),
            calibration=str(recovery / "CALIBRATION.json"),
        )
        before = sha(recovery / "organ.snn.off.jsonl")
        native = Native(Path(binary).resolve(), recovery)
        try:
            native.call({"command": "Resume", "request": request})
            if active.exists():
                raise AssertionError(
                    "Committed settlement left its stale reservation locked"
                )
            native.call({"command": "Close"})
        finally:
            process = native.close()
            negative.append(
                {
                    "check": "settlement append before reservation release recovery",
                    "rpc": native.rows,
                    "work": charge(native.rows),
                    "process": process,
                }
            )
        if sha(recovery / "organ.snn.off.jsonl") != before:
            raise AssertionError(
                "Reservation reconciliation credited the account again"
            )
        (recovery / "organ.snn.off.jsonl").unlink()
        native = Native(Path(binary).resolve(), recovery)
        try:
            native.call({"command": "Resume", "request": request}, expect_error=True)
            request.update(case="case.next", expected_account_sequence=2)
            native.call({"command": "Open", "request": request}, expect_error=True)
        finally:
            process = native.close()
            negative.append(
                {
                    "check": "lost resource account rejects old and new tasks",
                    "rpc": native.rows,
                    "work": charge(native.rows),
                    "process": process,
                }
            )
        overflow_episodes = [
            dict(
                episodes[0],
                case=f"case.{i:04d}",
                context=[0.75, 0.04, 8],
                budget=7.0,
                observations=[1] * 8,
                stream_id=["overflow-development", i],
            )
            for i in range(4)
        ]
        policy = {"readout": "raw_belief_dp", "credit": "live"}
        overflow = destination / "overflow"
        run = run_organ(
            binary,
            overflow,
            "overflow",
            model,
            source,
            policy,
            overflow_episodes,
            development=True,
        )
        audit_organ(
            binary,
            overflow,
            expected_plan={
                "organ": "overflow",
                "policy": policy,
                "episodes": overflow_episodes,
            },
            development=True,
        )
        if not any(e["metrics"]["balance_overflow"] > 0 for e in run["episodes"]):
            raise AssertionError("Balance cap overflow was not accounted")
        rows.append(
            {
                "name": "overflow",
                "index_sha256": sha(overflow / "INDEX.json"),
                "audit_sha256": sha(overflow / "AUDIT.json"),
                "metrics": [e["metrics"] for e in run["episodes"]],
                "native_replayed": 4,
            }
        )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "schema": "hepta.adaptive-neuron.owner-qualification.v2",
            "passed": True,
            "development_only": True,
            "binary_sha256": sha(binary),
            "checkpoint_sha256": sha(source),
            "runs": rows,
            "negative_and_recovery_checks": negative,
            "wall_ns": time.perf_counter_ns() - started,
            "parent_cpu_ns": time.process_time_ns() - cpu,
            "child_cpu_seconds": after.ru_utime
            + after.ru_stime
            - children.ru_utime
            - children.ru_stime,
        }
        write(destination / "QUALIFICATION.json", result)
        return result
    except Exception as error:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write(
            destination / "FAILED_QUALIFICATION.json",
            {
                "error": repr(error),
                "completed_runs": rows,
                "negative_checks": negative,
                "wall_ns": time.perf_counter_ns() - started,
                "parent_cpu_ns": time.process_time_ns() - cpu,
                "child_cpu_seconds": after.ru_utime
                + after.ru_stime
                - children.ru_utime
                - children.ru_stime,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "destination", "neural", "checkpoint"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = qualify(
        args.binary.resolve(), args.destination, args.neural, args.checkpoint
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "passed",
                    "development_only",
                    "binary_sha256",
                    "wall_ns",
                    "parent_cpu_ns",
                    "child_cpu_seconds",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
