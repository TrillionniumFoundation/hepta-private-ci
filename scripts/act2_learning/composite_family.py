"""Alternating real file/browser goals; no atomic cross-owner commit claim."""

from pathlib import Path
import time

from browser_family import BrowserDestination
from file_family import FileDestination
from sqlite_destination import BudgetExhausted


class CompositeDestination:
    """Route the original next goal using only fresh child observations."""

    def __init__(self, path, task, browser):
        if len(task["goals"]) < 2:
            raise ValueError("mixed task requires at least two goals")
        self.started = time.perf_counter_ns()
        self.task, self.budget = task, 6 * len(task["goals"]) + 6
        self.view, self.last, self.failed_reads = None, "start", 0
        self.events, self.children, self.indices = [], {}, {}
        self.closed, self.cleanup_ns = False, 0
        try:
            for offset, family in enumerate(("filesystem", "browser")):
                indices = list(range(offset, len(task["goals"]), 2))
                subtask = dict(
                    task,
                    id=task["id"] + "/component/" + family,
                    goals=[task["goals"][index] for index in indices],
                    family=family,
                    composition=len(indices),
                    parent_task_id=task["id"],
                    parent_goal_indices=indices,
                )
                self.indices[family] = indices
                destination = (
                    FileDestination(Path(path) / family, subtask)
                    if offset == 0
                    else BrowserDestination(Path(path) / family, subtask, browser)
                )
                self.children[family] = destination
            self.setup_ns = time.perf_counter_ns() - self.started
        except Exception:
            self.close()
            raise

    @property
    def calls(self):
        return sum(child.calls for child in self.children.values())

    @property
    def lost_replies(self):
        return sum(child.lost_replies for child in self.children.values())

    def _reserve(self, costs):
        """Fail before any child call, including before the first of two reads."""
        if self.calls + sum(costs.values()) > self.budget or any(
            self.children[name].calls + cost > self.children[name].budget
            for name, cost in costs.items()
        ):
            raise BudgetExhausted()

    def inspect(self):
        self._reserve({family: 1 for family in self.children})
        before = self.calls
        observations = {
            family: child.inspect() for family, child in self.children.items()
        }
        self.last = "inspect"
        if any(view is None for view in observations.values()):
            self.view = None
            self.failed_reads += 1
        else:
            next_indices = []
            matched = 0
            for family, view in observations.items():
                size, index, count = (
                    len(self.indices[family]),
                    view["index"],
                    view["matched"],
                )
                if (
                    type(index) is not int
                    or type(count) is not int
                    or not 0 <= index <= size
                    or not 0 <= count <= size
                    or type(view["complete"]) is not bool
                    or view["complete"] != (index == size)
                    or view["complete"] != (count == size)
                    or index > count
                    or type(view["staged"]) is not bool
                ):
                    raise ValueError("invalid child observation")
                matched += count
                if index < size:
                    next_indices.append((self.indices[family][index], family))
            global_index, family = (
                min(next_indices) if next_indices else (len(self.task["goals"]), None)
            )
            self.view = {
                "complete": not next_indices,
                "index": global_index,
                "matched": matched,
                "staged": observations[family]["staged"] if family else False,
            }
            self.failed_reads = 0
        self.events.append(
            {
                "action": "inspect",
                "primitive_calls": self.calls - before,
                "observation": self.view,
                "child_observations": observations,
                "at_ns": time.perf_counter_ns() - self.started,
            }
        )
        return self.view

    def ensure(self):
        if self.view is None or self.view["complete"]:
            self.inspect()
            return
        global_index = self.view["index"]
        if type(global_index) is not int or not 0 <= global_index < len(
            self.task["goals"]
        ):
            raise ValueError("invalid global goal index")
        family = "filesystem" if global_index % 2 == 0 else "browser"
        child = self.children[family]
        if (
            child.view is None
            or child.view["index"] != global_index // 2
            or child.view["complete"]
        ):
            raise ValueError("child observation no longer matches global next goal")
        self._reserve({family: 1 if child.view["staged"] else 2})
        before = self.calls
        child.ensure()
        if child.view is None:
            self.view = None
        self.last = "ensure"
        self.events.append(
            {
                "action": "ensure",
                "family": family,
                "global_index": global_index,
                "primitive_calls": self.calls - before,
                "at_ns": time.perf_counter_ns() - self.started,
            }
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        before = time.perf_counter_ns()
        try:
            for child in reversed(list(self.children.values())):
                child.close()
        finally:
            self.cleanup_ns = time.perf_counter_ns() - before

    def score(self, claimed):
        try:
            rows = {
                family: child.score(claimed) for family, child in self.children.items()
            }
        finally:
            self.close()
        complete = all(row["complete"] for row in rows.values())
        records = [
            dict(record, family=family, global_key=self.indices[family][record["key"]])
            for family, row in rows.items()
            for record in row["effect_records"]
        ]
        summed = (
            "primitive_calls",
            "owner_requests",
            "independent_oracle_queries",
            "lost_replies",
            "effect_count",
            "duplicate_effects",
            "dom_actions",
            "network_requests",
            "network_failures",
            "browser_control_calls",
            "http_requests",
            "readback_queries",
            "acknowledged_write_transactions",
        )
        return {
            **{key: sum(row.get(key, 0) for row in rows.values()) for key in summed},
            "complete": complete,
            "partial": any(row["partial"] for row in rows.values()),
            "claimed_success": claimed,
            "false_success": bool(claimed and not complete),
            "effect_records": records,
            "events": self.events,
            "children": rows,
            "duration_ns": time.perf_counter_ns() - self.started,
            "setup_ns": self.setup_ns,
            "cleanup_ns": self.cleanup_ns
            + sum(row.get("cleanup_ns", 0) for row in rows.values()),
            "real_browser_executed": rows["browser"]["real_browser_executed"],
            "scope": "alternating filesystem and real browser effects; same UID; no atomic cross-owner commit",
        }
