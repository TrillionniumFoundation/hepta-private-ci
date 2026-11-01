"""Transactional cursors and deterministic owner retries for finite research runs.

The SQLite database is the single local durable authority. This does not provide
distributed fencing, authenticated storage, external exactly-once RPC, or Rust
production ownership. Parent-requested SIGKILL follows a flushed transition.
"""

import argparse
import hashlib
import json
import os
import signal
import sqlite3
from pathlib import Path

from ..addressed_decision_r15_20261101.execution import PATTERNS, price
from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory, Planner
from ..addressed_decision_r15_20261101.world import make_episode
from ..support_retention_r16_20261101.compression import AnchoredPackedMemory, BlockLaw
from ..support_retention_r16_20261101.execution import AnchoredPlanner


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Store:
    """A local single-writer sequence with atomic state and effect receipts."""

    def __init__(self, path, config=None):
        existed = Path(path).exists()
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        if not existed:
            if config is None:
                raise ValueError("A new store requires the immutable run configuration")
            self.db.executescript("CREATE TABLE config (body TEXT, sha TEXT); "
                                 "CREATE TABLE state (sequence INTEGER, body TEXT, sha TEXT); "
                                 "CREATE TABLE history (sequence INTEGER PRIMARY KEY, event TEXT, sha TEXT);")
            self.db.execute("INSERT INTO config VALUES (?,?)", (canonical(config), digest(config)))
            self.db.commit()
        row = self.db.execute("SELECT body,sha FROM config").fetchone()
        if row is None or digest(json.loads(row[0])) != row[1]:
            raise ValueError("Run configuration checksum mismatch")
        self.config = json.loads(row[0])
        if config is not None and self.config != config:
            raise ValueError("Wrong model, owner, or run configuration")

    def load(self):
        row = self.db.execute("SELECT sequence,body,sha FROM state").fetchone()
        if row is None:
            return None
        sequence, body, sha = row
        state = json.loads(body)
        if digest(state) != sha:
            raise ValueError("Durable state checksum mismatch")
        history = self.db.execute("SELECT sequence,sha FROM history ORDER BY sequence").fetchall()
        if [r[0] for r in history] != list(range(sequence + 1)) or history[-1][1] != sha:
            raise ValueError("Missing or stale state history")
        return sequence, state

    def commit(self, expected, state, event):
        self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT sequence FROM state").fetchone()
        current = -1 if row is None else row[0]
        if current != expected:
            self.db.rollback()
            raise ValueError("Stale sequence replay")
        sha, sequence = digest(state), current + 1
        self.db.execute("DELETE FROM state")
        self.db.execute("INSERT INTO state VALUES (?,?,?)", (sequence, canonical(state), sha))
        self.db.execute("INSERT INTO history VALUES (?,?,?)", (sequence, event, sha))
        self.db.commit()
        return sequence


class Session:
    """Cold reconstruction receives an owner, never exposes paths to the planner."""

    def __init__(self, config):
        self.config = config
        self.law = BlockLaw.from_payload(config["model"])
        self.owner = Law.from_payload(config["owner_model"])
        self.episode = make_episode(self.owner, config["seed"], config["domain"])
        if self.episode.fingerprint != config["owner_fingerprint"]:
            raise ValueError("Owner world identity mismatch")
        self.memory_type = {"full": BeliefMemory, "anchored": AnchoredPackedMemory}[config["representation"]]
        self.projection = "full" if config["representation"] == "full" else "block"
        self.planner_type = Planner if config["representation"] == "full" else AnchoredPlanner

    def initial(self):
        memory = self.memory_type(self.law, self.episode.initial_values, self.projection)
        return dict(schema="hcsn-r17-owner-cursor-v1", config_sha256=digest(self.config),
                    query=0, current=None, pending=None, queries=[], effects=[],
                    memory=memory.checkpoint(), status="query_boundary")

    def advance(self, state):
        if state.get("config_sha256") != digest(self.config):
            raise ValueError("State belongs to a different run")
        memory = self.memory_type.restore(self.law, state["memory"])
        ep, q = self.episode, state["query"]
        if state["status"] == "done":
            return "done"
        key, dt = int(ep.query_keys[q]), float(ep.dts[q])
        scale = price(ep.seed, q)
        planner = self.planner_type(self.law, dt, .025 * scale, .07 * scale,
                                    projection=self.projection)
        if state["current"] is None:
            if abs(memory.clock - ep.starts[q]) > 1e-10:
                raise ValueError("Owner and resumed memory clocks differ")
            events = ep.events_at(q)
            for event in events:
                if event["kind"] == "WRITE":
                    memory.write(int(event["key"]), int(event["value"]))
                elif event["kind"] != "DISTRACTOR":
                    raise ValueError("Unknown owner event")
            state["current"] = dict(completed=0, fee=0., actions=[], events=events)
            state["status"] = "choose"
            event = "query_open"
        elif state["pending"] is not None:
            pending, current = state["pending"], state["current"]
            if pending["phase"] == "prepared":
                memory.advance(pending["slots"] * dt)
                pending["phase"] = "elapsed"
                event = "elapsed:" + pending["action"]
            elif pending["phase"] == "elapsed":
                pending["token"] = None
                if pending["action"] in ("READ", "REFRESH"):
                    pending["token"] = ep.observe(key, pending["time"], pending["action"].lower(),
                                                  q, pending["step"])
                pending["phase"] = "received"
                event = "received:" + pending["action"]
            elif pending["phase"] == "received":
                if pending["id"] in state["effects"]:
                    raise ValueError("Effect replay")
                if pending["action"] in ("READ", "REFRESH"):
                    memory.observe(key, pending["token"], pending["action"].lower())
                # Preserve the original executor's two successive additions.
                current["fee"] += .003 * pending["slots"] * dt
                if pending["action"] in ("READ", "REFRESH"):
                    current["fee"] += planner.read_cost if pending["action"] == "READ" else planner.refresh_cost
                current["completed"] = pending["step"]
                current["actions"].append(dict(action=pending["action"], step=pending["step"],
                    token=pending["token"], time=pending["time"]))
                state["effects"].append(pending["id"])
                state["pending"], state["status"] = None, "choose"
                event = "applied:" + pending["action"]
            else:
                raise ValueError("Unknown pending phase")
        else:
            current = state["current"]
            remaining = 3 - current["completed"]
            p = memory.materialize(key) if self.config["representation"] == "anchored" else memory.beliefs[key]
            if not remaining:
                action = "STOP"
            elif self.config["policy"] == "value":
                action = planner.choose(p, remaining)
            elif self.config["policy"] == "fixed":
                pattern = PATTERNS[self.config["pattern"]]
                action = pattern[len(current["actions"])] if len(current["actions"]) < len(pattern) else "STOP"
            else:
                raise ValueError("Unknown policy")
            if action == "REFRESH" and remaining < 2:
                action = "STOP"
            if action == "STOP":
                answer = planner.answer(p, remaining)
                memory.advance(remaining * dt)
                target = int(ep.target(key, float(ep.deadlines[q])))
                correct = int(answer == target)
                state["queries"].append(dict(query=q, key=key, dt=dt, deadline=float(ep.deadlines[q]),
                    price_scale=scale, events=current["events"], actions=current["actions"], answer=answer,
                    target=target, reward=correct, fee=current["fee"], utility=correct-current["fee"],
                    submitted_after=current["completed"]*dt, checkpoint_sha256=memory.checkpoint()["sha256"]))
                state["query"], state["current"] = q + 1, None
                state["status"] = "done" if q + 1 == len(ep.query_keys) else "query_boundary"
                event = state["status"]
            else:
                slots = 2 if action == "REFRESH" else 1
                step = current["completed"] + slots
                opid = f"{ep.fingerprint}:{q}:{len(current['actions'])}"
                state["pending"] = dict(id=opid, action=action, slots=slots, step=step,
                                        time=float(ep.starts[q] + step * dt), phase="prepared")
                state["status"] = "pending"
                event = "prepared:" + action
        state["memory"] = memory.checkpoint()
        return event


def worker(path, expected_config_sha, stop_event=None):
    store = Store(path)
    if digest(store.config) != expected_config_sha:
        raise ValueError("Caller expected a different model or owner")
    session = Session(store.config)
    loaded = store.load()
    print(canonical(dict(event="cold_start", pid=os.getpid(),
        model_identity=session.law.identity, owner_fingerprint=session.episode.fingerprint,
        transition_cache_entries=len(session.law._transition_cache),
        event_cache_entries=len(session.law._event_cache),
        loaded_sequence=None if loaded is None else loaded[0])), flush=True)
    if loaded is None:
        state = session.initial()
        sequence = store.commit(-1, state, "initial")
    else:
        sequence, state = loaded
    while state["status"] != "done":
        event = session.advance(state)
        if stop_event == "before:" + event:
            os.kill(os.getpid(), signal.SIGKILL)
        sequence = store.commit(sequence, state, event)
        if stop_event == "after:" + event:
            os.kill(os.getpid(), signal.SIGKILL)
    print(canonical(dict(event="completed", sequence=sequence, state_sha256=digest(state))), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("expected_config_sha")
    parser.add_argument("--stop-event")
    args = parser.parse_args()
    worker(args.database, args.expected_config_sha, args.stop_event)
