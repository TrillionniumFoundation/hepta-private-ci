"""Controlled real SQLite destination; no Hepta/production authority is claimed."""

import hashlib
import sqlite3
import time
from contextlib import closing


SCHEMAS = (("items", "item_key", "value", "revision"),
           ("objects", "object_key", "content", "generation"),
           ("documents", "doc_id", "body", "version"),
           ("records", "record_id", "payload", "sequence"))


class BudgetExhausted(Exception):
    pass


class Destination:
    def __init__(self, path, task):
        self.started = time.perf_counter_ns()
        self.path, self.task = path, task
        self.table, self.key, self.value, self.rev = SCHEMAS[task["schema"]]
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute(f"CREATE TABLE {self.table} ({self.key} TEXT PRIMARY KEY, {self.value} TEXT, {self.rev} INTEGER)")
        self.db.execute("CREATE TABLE staged (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE TABLE applied (operation TEXT PRIMARY KEY, payload TEXT)")
        self.db.execute("CREATE TABLE effects (key TEXT, value TEXT)")
        for i, goal in enumerate(task["goals"]):
            initial = goal if task["fault"] == "already_partial" and i % 2 == 0 else "old"
            self.db.execute(f"INSERT INTO {self.table} VALUES (?, ?, 0)", (str(i), initial))
            if task["fault"] == "prestaged" and i % 2 == 0:
                self.db.execute("INSERT INTO staged VALUES (?, ?)", (str(i), goal))
        self.db.commit()
        self.calls = self.reads = self.writes = self.applies = self.lost_replies = 0
        self.oracle_queries = 0
        self.failed_reads = 0
        self.budget = 6 * len(task["goals"]) + 6
        self.view = None
        self.last = "start"
        self.events = []
        self.complete_ns = 0 if self._oracle()["complete"] else None
        self.setup_ns = time.perf_counter_ns() - self.started

    def _charge(self, action):
        if self.calls >= self.budget:
            raise BudgetExhausted()
        self.calls += 1
        self.events.append({"action": action, "at_ns": time.perf_counter_ns() - self.started})

    def inspect(self):
        self._charge("inspect")
        self.reads += 1
        self.last = "inspect"
        if self.task["fault"] == "opaque_after_apply" and self.applies:
            self.view = None
            self.failed_reads += 1
            self.events[-1]["observation"] = None
            return None
        # The actor's observation is a fresh independent read-only connection.
        with closing(sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)) as reader:
            actual = dict(reader.execute(f"SELECT {self.key}, {self.value} FROM {self.table}"))
            staged = dict(reader.execute("SELECT key, value FROM staged"))
        matched = [actual[str(i)] == goal for i, goal in enumerate(self.task["goals"])]
        index = next((i for i, yes in enumerate(matched) if not yes), len(matched))
        self.view = {"complete": all(matched), "index": index, "matched": sum(matched),
                     "staged": index < len(matched) and staged.get(str(index)) == self.task["goals"][index]}
        self.failed_reads = 0
        self.events[-1]["observation"] = self.view.copy()
        return self.view

    def stage(self):
        self._charge("stage")
        self.last = "stage"
        index = self.view["index"] if self.view else 0
        if index == len(self.task["goals"]):
            return
        self.db.execute("INSERT INTO staged VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(index), self.task["goals"][index]))
        self.db.commit()
        self.writes += 1

    def apply(self):
        self._charge("apply")
        self.last = "apply"
        index = self.view["index"] if self.view else 0
        if index == len(self.task["goals"]):
            return
        goal, key = self.task["goals"][index], str(index)
        operation = self.task["id"] + ":" + key
        payload = hashlib.sha256(goal.encode()).hexdigest()
        staged = self.db.execute("SELECT value FROM staged WHERE key=?", (key,)).fetchone()
        prior = self.db.execute("SELECT payload FROM applied WHERE operation=?", (operation,)).fetchone()
        if prior is not None:
            assert prior[0] == payload
            return
        if staged != (goal,):
            return
        with self.db:
            self.db.execute(f"UPDATE {self.table} SET {self.value}=?, {self.rev}={self.rev}+1 WHERE {self.key}=?", (goal, key))
            self.db.execute("INSERT INTO applied VALUES (?, ?)", (operation, payload))
            self.db.execute("INSERT INTO effects VALUES (?, ?)", (key, goal))
        self.writes += 1
        self.applies += 1
        if self.complete_ns is None and self._oracle()["complete"]:
            self.complete_ns = time.perf_counter_ns() - self.started
        if self.task["fault"] == "lost_reply" and self.applies == 1:
            self.lost_replies += 1
            self.view = None

    def ensure(self):
        if not (self.view and self.view["staged"]):
            self.stage()
        self.apply()
        self.last = "ensure"

    def _oracle(self):
        # This scorer never feeds policy features, labels or online completion.
        self.oracle_queries += 1
        with closing(sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)) as oracle:
            actual = dict(oracle.execute(f"SELECT {self.key}, {self.value} FROM {self.table}"))
            effects = list(oracle.execute("SELECT key, value FROM effects"))
        return {"complete": all(actual[str(i)] == goal for i, goal in enumerate(self.task["goals"])),
                "partial": any(actual[str(i)] == goal for i, goal in enumerate(self.task["goals"])),
                "duplicate_effects": len(effects) - len({key for key, _ in effects})}

    def score(self, claimed):
        observed = self._oracle()
        self.db.close()
        duration = time.perf_counter_ns() - self.started
        return {**observed, "claimed_success": claimed, "unknown": not claimed,
                "goal_label_available": True,
                "duration_ns": duration, "completion_ns": self.complete_ns,
                "setup_ns": self.setup_ns,
                "right_censored": self.complete_ns is None, "primitive_calls": self.calls,
                "readback_queries": self.reads, "write_transactions": self.writes,
                "independent_oracle_queries": self.oracle_queries,
                "applied_effects": self.applies, "lost_replies": self.lost_replies,
                "database_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest()}
