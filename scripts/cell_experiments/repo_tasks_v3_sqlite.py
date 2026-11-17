"""Stateful development adapter for the retained ACT-2 SQLite destination.

The destination supplies prescribed payloads. These scenarios test primitive
action sequencing, not model-generated SQL, new users, or held-out ability.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time
import types


SOURCE_SHA256 = "ca4bfe52b1fe9344cf05fbd18713877af6cd77cc57f4877c9addb5321a2b04c4"
ACTIONS = ("inspect", "stage", "apply", "stop")
FIXTURES = (
    Path(__file__).resolve().parents[2] / "qualification/cell-experiments-v3-20261116"
)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def write_new(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


class DevelopmentSession:
    """Own one fresh SQLite file across bounded actor actions."""

    def __init__(self, task_id, output, fixtures=FIXTURES):
        fixtures = Path(fixtures)
        manifest_path = fixtures / "tasks/sqlite-dev-v3/task-development-sqlite.json"
        manifest = json.loads(manifest_path.read_text())
        matching = [task for task in manifest["tasks"] if task["task_id"] == task_id]
        if len(matching) != 1:
            raise ValueError("expected exactly one declared development task")
        self.spec = matching[0]
        if self.spec["split"] != "development" or self.spec["confirmation_eligible"]:
            raise ValueError("adapter accepts exposed development tasks only")
        source = fixtures / "source-records/act2_sqlite_destination.py.txt"
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
            raise ValueError("pinned SQLite destination source hash mismatch")
        self.provider = types.ModuleType("retained_act2_sqlite_destination")
        exec(compile(raw, str(source), "exec"), self.provider.__dict__)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.task = {**self.spec["environment"], "id": task_id}
        self.started = time.perf_counter_ns()
        write_new(self.output / "TASK.json", self.spec)
        self.destination = self.provider.Destination(
            self.output / "destination.db", self.task
        )
        self.decisions = 0
        self.maximum_decisions = 24
        self.closed = False
        self.result = None

    def observation(self):
        view = self.destination.view
        return {
            "visible_readback": None if view is None else dict(view),
            "last_action": self.destination.last,
            "primitive_calls": self.destination.calls,
            "primitive_budget": self.destination.budget,
            "decisions_remaining": max(0, self.maximum_decisions - self.decisions),
            "state_persists_between_actions": True,
            "payloads_supplied_by_destination": True,
        }

    def step(self, action):
        if self.closed:
            raise RuntimeError("session already finished")
        if not isinstance(action, str):
            raise TypeError("primitive action must be a string")
        self.decisions += 1
        calls_before = self.destination.calls
        writes_before = self.destination.writes
        applies_before = self.destination.applies
        row = {
            "decision": self.decisions,
            "action": action,
            "before": self.observation(),
        }
        terminal_reason = None
        claimed = False
        if action not in ACTIONS:
            row["error"] = "unknown_action"
        elif action == "stop":
            claimed = bool(self.destination.view and self.destination.view["complete"])
            terminal_reason = "actor_stop"
        else:
            try:
                getattr(self.destination, action)()
            except self.provider.BudgetExhausted:
                row["error"] = "primitive_budget_exhausted"
                terminal_reason = "primitive_budget_exhausted"
        if terminal_reason is None and self.decisions >= self.maximum_decisions:
            terminal_reason = "decision_budget_exhausted"
        row["after"] = self.observation()
        row["elapsed_ns"] = time.perf_counter_ns() - self.started
        row["execution_summary"] = {
            "verifier_identity": "act2-sqlite-destination@0584b3344f70ed51d9e09224e105bfa4d1a4635f",
            "primitive_calls_delta": self.destination.calls - calls_before,
            "write_transactions_delta": self.destination.writes - writes_before,
            "applied_effects_delta": self.destination.applies - applies_before,
            "repository_patch_verifier": False,
            "subprocess_started": False,
            "same_process_sqlite": True,
        }
        with (self.output / "ACTIONS.jsonl").open("ab") as stream:
            stream.write(canonical(row) + b"\n")
            stream.flush()
        result = self.finish(claimed, terminal_reason) if terminal_reason else None
        return {
            "action_receipt": row,
            "observation": self.observation(),
            "result": result,
        }

    def finish(self, claimed=False, reason="caller_finished_without_stop"):
        if self.closed:
            return self.result
        score = self.destination.score(claimed)
        self.result = {
            "schema": "hepta.sqlite-development-execution.v3",
            "task_id": self.spec["task_id"],
            "lineage_id": self.spec["lineage_id"],
            "source_group_id": self.spec["source_group_id"],
            "split": "development",
            "success": bool(
                score["complete"] and claimed and score["duplicate_effects"] == 0
            ),
            "terminal_reason": reason,
            "decisions": self.decisions,
            "actual_sqlite_execution": True,
            "destination_source_sha256": SOURCE_SHA256,
            "events": list(self.destination.events),
            "business_result": score,
            "wall_ns": time.perf_counter_ns() - self.started,
            "independent_source_count_added": 0,
            "new_user_count_added": 0,
            "confirmation_qualified": False,
            "external_evaluator_authenticated": False,
            "model_generated_payload": False,
            "native_cell_adoption": False,
        }
        write_new(self.output / "RESULT.json", self.result)
        self.closed = True
        return self.result


def run_actions(task_id, actions, output, fixtures=FIXTURES):
    session = DevelopmentSession(task_id, output, fixtures)
    try:
        for action in actions:
            outcome = session.step(action)
            if outcome["result"] is not None:
                return outcome["result"]
        return session.finish()
    finally:
        if not session.closed:
            session.finish(reason="caller_exception")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--actions-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    args = parser.parse_args()
    actions = json.loads(args.actions_file.read_text())
    if (
        not isinstance(actions, list)
        or len(actions) > 24
        or not all(isinstance(a, str) for a in actions)
    ):
        raise ValueError(
            "actions-file must contain at most 24 primitive action strings"
        )
    print(
        json.dumps(
            run_actions(args.task_id, actions, args.output, args.fixtures),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
