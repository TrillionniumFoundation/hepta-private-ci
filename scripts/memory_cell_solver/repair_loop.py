"""One bounded actual model/edit/gate trajectory; every attempt is retained."""

import argparse
import json
import resource
from pathlib import Path

from edit_protocol import apply_edits, candidate_document
from solver_accounting import model_observations
from solver_admission import verify_request
from solver_common import (
    delta,
    file_identity,
    measurement,
    read_pinned,
    retained_bytes,
    runtime,
    save,
)
from solver_model import Solver
from solver_tasks import evaluate, feedback


def run(request):
    output = Path(request["output"])
    output.mkdir(exist_ok=False)
    save(output / "request.json", request)
    protocol = read_pinned(request["protocol"], request["protocol_sha256"])
    task, original = verify_request(request, protocol)
    model = read_pinned(request["model_manifest"], request["model_manifest_sha256"])
    if (
        request["arm"] not in protocol["arms"]
        or request["task"] not in protocol["task_order"]
    ):
        raise ValueError("unregistered trajectory")
    limits = protocol["trajectory_limits"]
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (limits["self_cpu_seconds"], limits["self_cpu_seconds"] + 5),
    )
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (limits["per_file_bytes"], limits["per_file_bytes"])
    )
    started = measurement()
    save(output / "runtime.json", runtime())
    current, prior_feedback, attempts = dict(original), [], []
    retrieved = read_pinned(request["retrieval"], request["retrieval_sha256"])
    if request["arm"] == "no_history" and retrieved["documents"]:
        raise ValueError("no-history arm received retrieval")
    solver = None
    result = {
        "schema": "hepta.memory-cell.solver-trajectory.v1",
        "task": request["task"],
        "arm": request["arm"],
        "accepted": False,
        "attempts": attempts,
        "prospective_case": False,
        "training_updates": 0,
    }
    try:
        solver = Solver(request["model"], model, protocol, output)
        for index in range(protocol["generation"]["maximum_calls"]):
            if delta(started, measurement())["wall_seconds"] >= limits["wall_seconds"]:
                result["stop_reason"] = "trajectory_wall_budget"
                break
            if retained_bytes(output) >= limits["retained_stop_threshold_bytes"]:
                result["stop_reason"] = "retained_soft_stop_threshold"
                break
            verify_request(request, protocol)
            attempt = {"number": index + 1, "accepted": False}
            attempts.append(attempt)
            directory = output / f"attempt-{index + 1:02d}"
            directory.mkdir()
            try:
                raw, model_receipt = solver.propose(
                    task, current, retrieved["documents"], prior_feedback
                )
                attempt["model"] = model_receipt
                (directory / "model.raw").write_text(raw)
                try:
                    proposed = apply_edits(raw, current, task["allowed_paths"])
                    candidate = candidate_document(proposed, original)
                except (ValueError, TypeError) as error:
                    attempt["proposal_error"] = f"{type(error).__name__}: {error}"
                    prior_feedback.append(attempt["proposal_error"][:6000])
                    continue
                save(directory / "candidate.json", candidate)
                gate = evaluate(
                    request["task"],
                    request["fixture"],
                    directory / "candidate.json",
                    directory / "gate",
                    request["runtime_profile"],
                )
                attempt["gate_result"] = file_identity(directory / "gate/result.json")
                attempt["gate_status"] = gate["status"]
                attempt["accepted"] = gate["accepted"]
                verify_request(request, protocol)
                current = proposed
                prior_feedback.append(feedback(gate, directory / "gate"))
                if retained_bytes(output) >= limits["retained_stop_threshold_bytes"]:
                    result["stop_reason"] = "retained_soft_stop_threshold"
                    break
                if gate["accepted"]:
                    result.update(
                        accepted=True, stop_reason="first_actual_task_success"
                    )
                    break
            except Exception as error:
                attempt["execution_error"] = f"{type(error).__name__}: {error}"
                raise
            finally:
                save(directory / "attempt.json", attempt)
        verify_request(request, protocol)
        result.setdefault("stop_reason", "generation_call_budget")
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        result["stop_reason"] = "execution_failure"
        result["accepted"] = False
    finally:
        if solver is not None:
            try:
                solver.close()
            except Exception as error:
                result.update(
                    accepted=False,
                    integrity_error=str(error),
                    stop_reason="execution_failure",
                )
        result["execution_valid"] = result["stop_reason"] != "execution_failure"
        result["measurements"] = delta(started, measurement())
        result.update(model_observations(output))
        result["retained_bytes_before_result"] = retained_bytes(output)
        result["whole_system_cost_complete"] = False
        result["cost_scope"] = (
            "worker CPU/wall, waited children, logical token usage and retained files; excludes provisioning, host services and physical token-forward attribution"
        )
        result["nested_child_cleanup_qualified"] = False
        save(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--request-sha256", required=True)
    args = parser.parse_args()
    request = read_pinned(args.request, args.request_sha256)
    result = run(request)
    print(json.dumps({k: result.get(k) for k in ("accepted", "stop_reason", "error")}))
    # Failed model proposals are study observations. Integrity/execution failure
    # is separately represented and must not become a successful task result.
    raise SystemExit(0 if result["stop_reason"] != "execution_failure" else 1)
