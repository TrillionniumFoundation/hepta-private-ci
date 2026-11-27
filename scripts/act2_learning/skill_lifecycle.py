"""Controlled in-process skill lifecycle; no product authority or restart claim."""

from dataclasses import asdict, dataclass
import hashlib
import json
import time

from file_family import FileDestination


def goals_digest(goals):
    return hashlib.sha256(
        json.dumps(
            goals, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class SkillContract:
    task_id: str
    version: int
    goals_digest: str
    deadline_ns: int
    max_retries: int


class LifecycleDestination(FileDestination):
    """Constrain original FileOwner calls; a model never changes owner permission.

    The absolute monotonic deadline belongs to this process/boot only. Pausing
    does not extend it. Checks cannot interrupt an already entered owner call.
    Read-only reconciliation remains available after every mutation fence.
    """

    def __init__(self, path, task, contract, clock=time.monotonic_ns):
        self.clock, self.lifecycle_started = clock, clock()
        if type(self.lifecycle_started) is not int or self.lifecycle_started < 0:
            raise ValueError("invalid lifecycle monotonic clock")
        self.contract = contract
        if (
            not isinstance(contract, SkillContract)
            or not isinstance(task.get("id"), str)
            or not 0 < len(task["id"]) <= 512
            or type(task.get("version")) is not int
            or task["version"] not in (1, 2)
            or not isinstance(task.get("goals"), list)
            or not 1 <= len(task["goals"]) <= 64
            or any(
                not isinstance(g, str) or not 0 < len(g) <= 4096 for g in task["goals"]
            )
            or contract.task_id != task["id"]
            or type(contract.version) is not int
            or contract.version != task["version"]
            or contract.goals_digest != goals_digest(task["goals"])
            or type(contract.deadline_ns) is not int
            or contract.deadline_ns <= 0
            or type(contract.max_retries) is not int
            or not 0 <= contract.max_retries <= 64
        ):
            raise ValueError("skill contract or startup parameters mismatch")
        super().__init__(path, task)
        self.task = self.owner.task
        (self.owner.path / "contract.json").write_text(
            json.dumps(asdict(contract), sort_keys=True) + "\n"
        )
        self.state, self.paused, self.expired = "RUNNING", False, False
        self.pause_count, self.repair_count = 0, 0
        self.retry_key, self.retry_counts, self.unresolved = None, {}, set()
        self.last_clock = self.lifecycle_started
        self._refresh()

    def _refresh(self):
        now = self.clock()
        if type(now) is not int or now < self.last_clock:
            raise ValueError("lifecycle monotonic clock regressed")
        self.last_clock = now
        self.expired = self.expired or now >= self.contract.deadline_ns
        if self.expired:
            self.state = "DEADLINE"
        elif self.state != "RETRY_EXHAUSTED":
            self.state = "PAUSED" if self.paused else "RUNNING"
        return now

    def _may_mutate(self, action):
        self._refresh()
        if self.state != "RUNNING":
            self.events.append({"action": action, "blocked": self.state})
            return False
        if (
            self.task["id"] != self.contract.task_id
            or self.task["version"] != self.contract.version
            or goals_digest(self.task["goals"]) != self.contract.goals_digest
        ):
            raise ValueError("skill parameters changed")
        return True

    def pause(self):
        self._refresh()
        if not self.paused:
            self.pause_count += 1
        self.paused = True
        self._refresh()

    def resume(self):
        self.paused = False
        self._refresh()

    def inspect(self):
        self._refresh()
        self.view = None  # A failing read must not retain a prior success observation.
        result = super().inspect()
        if result is not None:
            self.unresolved = {key for key in self.unresolved if key >= result["index"]}
        return result

    def ensure(self):
        if not self._may_mutate("ensure"):
            return
        if self.view is None or self.view["complete"]:
            self.inspect()
            return
        key = self.view["index"]
        if key in self.unresolved:
            self.events.append({"action": "ensure", "blocked": "UNRESOLVED_ORIGINAL"})
            self.inspect()
            return
        goal, version = self.task["goals"][key], self.task["version"]
        staged = self.view["staged"]
        self.view = None  # A pre-mutation observation is never a completion receipt.
        if not staged:
            if not self._may_mutate("stage"):
                return
            self._charge("stage")
            self.events[-1]["reply"] = self.owner.stage(key, goal, version)
        if not self._may_mutate("apply"):
            return
        retry = self.retry_key == key
        if retry and self.retry_counts.get(key, 0) >= self.contract.max_retries:
            self.state = "RETRY_EXHAUSTED"
            self.events.append({"action": "apply", "blocked": self.state})
            return
        self._charge("apply")
        if retry:
            self.repair_count += 1
            self.retry_counts[key] = self.retry_counts.get(key, 0) + 1
        self.unresolved.add(key)
        reply = self.owner.apply(key, goal, self.task["id"] + ":" + str(key), version)
        self.events[-1]["reply"] = None if reply["ack_lost"] else reply
        if reply["ack_lost"]:
            self.lost_replies += 1
        elif reply["status"] == "retryable_precommit":
            self.unresolved.remove(key)
            self.retry_key = key
            if self.retry_counts.get(key, 0) >= self.contract.max_retries:
                self.state = "RETRY_EXHAUSTED"
        elif reply["status"] in ("applied", "deduplicated"):
            self.unresolved.remove(key)
            self.retry_key = None
        # Unclassified replies stay unresolved; only inspect may advance them.
        self.last = "ensure"

    def score(self, claimed):
        self._refresh()
        confirmed = bool(self.view and self.view["complete"])
        result = super().score(bool(claimed and confirmed))
        return {
            **result,
            "success_proposed": bool(claimed),
            "effect_knowledge": "UNKNOWN"
            if self.view is None
            else ("CONFIRMED_COMPLETE" if confirmed else "CONFIRMED_INCOMPLETE"),
            "state": self.state,
            "reconciliation_allowed": True,
            "pause_count": self.pause_count,
            "repair_count": self.repair_count,
            "end_to_end_ns": self._refresh() - self.lifecycle_started,
            "contract": asdict(self.contract),
            "full_lifetime_cost_qualified": False,
        }
