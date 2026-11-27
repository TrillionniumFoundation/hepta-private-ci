"""Write-ahead cost accounting for every successful, failed or discarded trial.

Limits are common ceilings, not a claim of matched FLOPs. Wall overruns are
retained. An unclosed operation has unknown physical cost and blocks resume.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import time


class BudgetExhausted(RuntimeError):
    pass


class CostUncertain(RuntimeError):
    pass


@dataclass(frozen=True)
class Budget:
    wall_seconds: float = 30.0
    training_examples: int = 100_000
    encoder_events: int = 1_000_000
    forward_examples: int = 100_000
    backward_examples: int = 100_000
    development_queries: int = 12
    proposals: int = 128

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in asdict(self).values()):
            raise ValueError("all budget ceilings must be positive")


class CostLedger:
    def __init__(self, path, budget, identity, *, started_at=None):
        self.path, self.budget, self.identity = Path(path), budget, identity
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records = []
        self.cost = dict(training_examples=0, encoder_events=0,
                         forward_examples=0, backward_examples=0,
                         development_queries=0, proposals=0, failures=0)
        self.prior_wall, self.tail, self.pending = 0.0, "0" * 64, None
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                record = json.loads(line)
                digest = record.pop("hash")
                if record["previous"] != self.tail or self._hash(record) != digest:
                    raise CostUncertain("cost journal hash chain is invalid")
                if record["identity"] != identity or record["budget"] != asdict(budget):
                    raise ValueError("journal budget or immutable experiment identity changed")
                record["hash"] = digest
                self._consume(record)
        self.started = time.perf_counter()
        self._base_wall = self.prior_wall + (0.0 if started_at is None else self.started - started_at)
        if self.pending is not None:
            raise CostUncertain("interrupted operation: reservation charged, wall cost unknown")

    @staticmethod
    def _hash(record):
        return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False).encode()).hexdigest()

    def _consume(self, record):
        if record["kind"] == "reserve":
            if self.pending is not None:
                raise CostUncertain("overlapping unfinished cost reservations")
            self.pending = record["operation"]
            for key, value in record["charge"].items():
                self.cost[key] += value
        elif record["kind"] == "settle":
            if self.pending != record["operation"]:
                raise CostUncertain("settlement has no matching reservation")
            self.pending = None
            self.prior_wall = max(self.prior_wall, record["cumulative_wall_seconds"])
            self.cost["failures"] += int(record["status"] == "failed")
        elif record["kind"] == "checkpoint_boundary" and self.pending is None:
            self.prior_wall = max(self.prior_wall, record["cumulative_wall_seconds"])
        else:
            raise CostUncertain("unknown or out-of-order cost event")
        self.tail = record["hash"]
        self.records.append(record)

    def _append(self, record):
        record.update(identity=self.identity, budget=asdict(self.budget), previous=self.tail)
        record["hash"] = self._hash(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._consume(record)

    def elapsed(self):
        return self.base_wall + time.perf_counter() - self.started

    @property
    def base_wall(self):
        # The first record of this process must not be counted twice.
        if not hasattr(self, "_base_wall"):
            self._base_wall = self.prior_wall
        return self._base_wall

    @contextmanager
    def operation(self, name, *, training_examples=0, encoder_events=0,
                  forward_examples=0, backward_examples=0,
                  development_queries=0, proposals=0, mandatory=False):
        charge = dict(training_examples=training_examples, encoder_events=encoder_events,
                      forward_examples=forward_examples,
                      backward_examples=backward_examples,
                      development_queries=development_queries, proposals=proposals)
        if any(not isinstance(v, int) or v < 0 for v in charge.values()):
            raise ValueError("cost reservation must be nonnegative integer counts")
        if mandatory and (name != "checkpoint" or any(charge.values())):
            raise ValueError("only a zero-work mandatory checkpoint may exceed a ceiling")
        if not mandatory and (self.elapsed() >= self.budget.wall_seconds or any(
                self.cost[k] + v > getattr(self.budget, k) for k, v in charge.items())):
            raise BudgetExhausted(name)
        operation = len(self.records)
        self._append(dict(kind="reserve", operation=operation, name=name, charge=charge))
        status, error = "completed", None
        try:
            yield
        except BaseException as exc:
            status, error = "failed", type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            self._append(dict(kind="settle", operation=operation, name=name, status=status,
                              error=error, cumulative_wall_seconds=self.elapsed()))

    def snapshot(self):
        return {**self.cost, "wall_seconds": self.elapsed(), "tail": self.tail,
                "records": len(self.records), "pending": self.pending,
                "limits": asdict(self.budget),
                "wall_overrun_seconds": max(0.0, self.elapsed() - self.budget.wall_seconds)}


def summarize_journal(path):
    """Read failed/interrupted work without laundering missing cost into zero."""
    path = Path(path)
    if not path.exists():
        return {"status": "unavailable", "reason": "journal not created"}
    totals, pending, wall, tail = {}, {}, 0.0, "0" * 64
    try:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            recorded_hash = record.pop("hash")
            if record["previous"] != tail or CostLedger._hash(record) != recorded_hash:
                raise ValueError("invalid cost hash chain")
            tail = recorded_hash
            if record["kind"] == "reserve":
                pending[record["operation"]] = record["name"]
                for key, value in record["charge"].items():
                    totals[key] = totals.get(key, 0) + value
            elif record["kind"] == "settle":
                pending.pop(record["operation"])
                wall = max(wall, record["cumulative_wall_seconds"])
                totals["failures"] = totals.get("failures", 0) + int(record["status"] == "failed")
        return {"status": "uncertain" if pending else "settled", "reserved_cost": totals,
                "accounted_wall_seconds": None if pending else wall,
                "accounted_wall_lower_bound_seconds": wall, "unsettled_operations": pending,
                "tail": tail}
    except (ValueError, KeyError) as exc:
        return {"status": "corrupt", "known_reserved_cost": totals,
                "accounted_wall_seconds": None, "reason": str(exc)}
