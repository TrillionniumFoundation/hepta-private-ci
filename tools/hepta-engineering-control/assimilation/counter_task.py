"""A bounded goal consumer for the existing disposable counter service.

The host retains the immutable task specification and independently retained
frontier. This module owns no database, artifact registry, process or generation.
It is a fixed baseline controller, not a learned policy or a complete Agentd C1.
"""

from dataclasses import dataclass
import hashlib
import json

from .owned_service import DisposableCounterService, ServiceError


@dataclass(frozen=True)
class CounterTask:
    task_id: str
    initial_counter: int
    target_counter: int

    def __post_init__(self):
        if (
            type(self.task_id) is not str or not self.task_id
            or len(self.task_id) > 64 or not self.task_id.isascii() or not self.task_id.isalnum()
            or type(self.initial_counter) is not int or type(self.target_counter) is not int
            or not 0 <= self.initial_counter <= self.target_counter <= 255
            or self.target_counter - self.initial_counter > 32
        ):
            raise ServiceError("invalid_bounded_counter_task")

    def operation_id(self, value: int) -> str:
        if type(value) is not int or not self.initial_counter < value <= self.target_counter:
            raise ServiceError("operation_outside_target_snapshot")
        payload = json.dumps(
            ["counter-task-v1", self.task_id, self.initial_counter, self.target_counter, value],
            separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()


def run_counter_task(service: DisposableCounterService, task: CounterTask) -> dict:
    """Reconcile this task's effects without repeating committed operations.

    Later progress proves historical completion only through this task's exact
    operation history. It does not mean the current counter equals the old
    target. Unknown outcomes still propagate; the host supplies a new client
    and independently retained generation/frontier rather than retrying here.
    """
    effect_count = task.target_counter - task.initial_counter
    if service.sequence + effect_count + 2 > 256:
        raise ServiceError("task_exceeds_remaining_service_budget")
    observed = service.request("query")["counter"]
    if observed < task.initial_counter:
        raise ServiceError("observed_counter_outside_target_snapshot")
    historical_completion = observed > task.target_counter
    if historical_completion and effect_count == 0:
        # No operation identity can establish that an empty task ran earlier.
        raise ServiceError("empty_task_has_no_retained_completion_evidence")
    retained_end = min(observed, task.target_counter)
    for value in range(task.initial_counter + 1, retained_end + 1):
        if service.request("reconcile", task.operation_id(value))["value"] != value:
            raise ServiceError("observed_progress_belongs_to_another_task")
    for value in range(observed + 1, task.target_counter + 1):
        if service.request("step", task.operation_id(value))["value"] != value:
            raise ServiceError("task_effect_differs_from_target_snapshot")
    final = service.request("query")["counter"]
    if final != max(observed, task.target_counter):
        raise ServiceError("task_terminal_counter_changed")
    result = {
        "task_id": task.task_id,
        "initial_counter": task.initial_counter,
        "target_counter": task.target_counter,
        "observed_counter": final,
        "reconciled_effects": retained_end - task.initial_counter,
        "new_effects": max(0, task.target_counter - observed),
        "generation": service.generation,
    }
    if historical_completion:
        result["completion_basis"] = "retained_operation_history"
    return result


def main() -> int:
    import argparse
    from contextlib import closing
    from pathlib import Path
    import sys

    from .owned_service import IndeterminateOperation

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--minimum-counter", type=int, required=True)
    parser.add_argument("--implementation-version", type=int, choices=(1, 2), default=1)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--initial-counter", type=int, required=True)
    parser.add_argument("--target-counter", type=int, required=True)
    args = parser.parse_args()
    try:
        task = CounterTask(args.task_id, args.initial_counter, args.target_counter)
        with closing(DisposableCounterService(
            args.root, args.generation, args.minimum_counter,
            implementation_version=args.implementation_version,
        )) as service:
            service.start()
            result = run_counter_task(service, task)
        print(json.dumps(result, sort_keys=True))
        return 0
    except IndeterminateOperation as error:
        print(f"Unknown outcome; reconcile this task with a new client: {error}", file=sys.stderr)
        return 75
    except (OSError, ServiceError) as error:
        print(f"Counter task rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
