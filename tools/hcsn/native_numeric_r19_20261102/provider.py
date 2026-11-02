"""Private finite-world owner with transactional billing over a bounded mailbox.

The Rust controller receives public OPEN data and completed ACT observations;
targets are written only to the private scorer ledger. Local files are trusted
host-owned inputs, not a security sandbox or a network authentication scheme.
"""

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from ..addressed_decision_r15_20261101.execution import price
from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode

MAX_WIRE = 16384
MAX_BODY = 4096
MAX_REQUESTS = 1024


class Rejected(ValueError):
    """Expected request rejection; durable state remains unchanged."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def checksum(raw):
    value = 0xCBF29CE484222325
    for byte in raw:
        value = ((value ^ byte) * 0x100000001B3) & ((1 << 64) - 1)
    return value


def seal(body):
    return body + f"CHECK\t{checksum(body.encode()):016x}\n"


def unseal(raw):
    if len(raw) > MAX_WIRE:
        raise Rejected("wire capacity")
    text = raw.decode("utf-8")
    index = text.rfind("CHECK\t")
    if index < 0 or seal(text[:index]) != text:
        raise Rejected("wire checksum")
    return text[:index]


def atomic(path, body):
    raw = body.encode()
    if len(raw) > MAX_WIRE:
        raise Rejected("response capacity")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Provider:
    """One SQLite transaction binds lease/cursor/effect and exact wire reply."""

    def __init__(self, state, config):
        if (len(config["run"]) != 64 or any(c not in "0123456789abcdef" for c in config["run"])
                or config.get("query_count", 6) != 6):
            raise ValueError("Invalid bounded provider configuration")
        self.config = config
        self.law = Law.from_payload(config["model"])
        self.episode = make_episode(self.law, int(config["seed"]), config["domain"])
        self.db = sqlite3.connect(state, timeout=5)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS configuration (body TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS cursor (body TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS replies (id TEXT PRIMARY KEY, hash TEXT NOT NULL, response TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS effects (opid TEXT PRIMARY KEY, semantic TEXT NOT NULL, response TEXT NOT NULL, fee REAL NOT NULL);"
            "CREATE TABLE IF NOT EXISTS scores (query INTEGER PRIMARY KEY, body TEXT NOT NULL);")
        body = canonical(config)
        previous = self.db.execute("SELECT body FROM configuration").fetchone()
        if previous is None:
            self.db.execute("INSERT INTO configuration VALUES (?)", (body,))
            self.db.execute("INSERT INTO cursor VALUES (?)", (canonical(dict(
                generation=0, query=0, step=0, opened=False, fee=0., effects=0)),))
            self.db.commit()
        elif previous[0] != body:
            raise ValueError("Provider configuration identity mismatch")

    def _cursor(self):
        return json.loads(self.db.execute("SELECT body FROM cursor").fetchone()[0])

    def apply(self, request_id, body, inject_storage_failure=False):
        if (not request_id or len(request_id) > 96
                or not all(c.isalnum() or c in "-_" for c in request_id)
                or len(body.encode()) > MAX_BODY or "\n" in body):
            raise Rejected("request identity/capacity")
        fields = body.split("\t")
        if len(fields) < 2 or fields[1] != self.config["run"]:
            raise Rejected("wrong run")
        digest = hashlib.sha256(body.encode()).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state = self._cursor()
            prior = self.db.execute("SELECT hash,response FROM replies WHERE id=?", (request_id,)).fetchone()
            if prior is not None and prior[0] != digest:
                raise Rejected("transport request id conflict")
            if fields[0] != "LEASE":
                if len(fields) < 3 or int(fields[2]) != state["generation"]:
                    raise Rejected("stale owner generation")
            if prior is not None:
                self.db.rollback()
                return prior[1]
            if self.db.execute("SELECT COUNT(*) FROM replies").fetchone()[0] >= MAX_REQUESTS:
                raise Rejected("request capacity")
            response = self._execute(fields, state)
            self.db.execute("UPDATE cursor SET body=?", (canonical(state),))
            self.db.execute("INSERT INTO replies VALUES (?,?,?)", (request_id, digest, response))
            if inject_storage_failure:
                raise OSError(28, "injected storage failure before commit")
            self.db.commit()
            return response
        except BaseException:
            self.db.rollback()
            raise

    def _execute(self, fields, state):
        kind, run = fields[:2]
        if kind == "LEASE" and len(fields) == 2:
            state["generation"] += 1
            return f"LEASE\t{state['generation']}"
        if kind == "CHECK" and len(fields) == 3:
            return "OK"
        if kind == "OPEN" and len(fields) == 4:
            query = int(fields[3])
            if query != state["query"] or not 0 <= query < 6:
                raise Rejected("query order")
            state["opened"] = True
            ep = self.episode
            initial = ",".join(map(str, ep.initial_values)) if query == 0 else "-"
            writes = ",".join(f"{e['key']}:{e['value']}" for e in ep.events_at(query)
                              if e["kind"] == "WRITE") or "-"
            return "\t".join(map(str, ("OPEN", query, int(ep.query_keys[query]),
                float(ep.dts[query]), float(ep.starts[query]), float(ep.deadlines[query]),
                price(ep.seed, query), initial, writes)))
        if kind not in ("ACT", "SUBMIT") or len(fields) != 7:
            raise Rejected("request kind or shape")
        query, step, operation, opid = int(fields[3]), int(fields[4]), fields[5], fields[6]
        if not opid or len(opid) > 160 or any(c in opid for c in "\t\r\n"):
            raise Rejected("logical operation id")
        semantic = canonical([kind, run, query, step, operation, opid])
        previous = self.db.execute("SELECT semantic,response FROM effects WHERE opid=?", (opid,)).fetchone()
        if previous is not None:
            if previous[0] != semantic:
                raise Rejected("logical operation conflict")
            return previous[1]
        if (not state["opened"] or query != state["query"] or step != state["step"]
                or not 0 <= query < 6 or not 0 <= step <= 3):
            raise Rejected("action cursor")
        ep, purchase = self.episode, 0.
        if kind == "ACT":
            if operation not in ("WAIT", "READ", "REFRESH"):
                raise Rejected("unknown action")
            slots = 2 if operation == "REFRESH" else 1
            completed = step + slots
            if completed > 3:
                raise Rejected("deadline overrun")
            at = float(ep.starts[query] + completed * ep.dts[query])
            token = -1
            state["fee"] += .003 * slots * float(ep.dts[query])
            if operation != "WAIT":
                token = ep.observe(int(ep.query_keys[query]), at, operation.lower(), query, completed)
                purchase = (.025 if operation == "READ" else .07) * price(ep.seed, query)
                state["fee"] += purchase
            state["step"] = completed
            response = f"ACT\t{query}\t{completed}\t{token}\t{at!r}\t{round(purchase * 1e6)}\t{opid}"
        else:
            answer = int(operation)
            if not 0 <= answer < 4:
                raise Rejected("invalid submitted answer")
            target = int(ep.target(int(ep.query_keys[query]), float(ep.deadlines[query])))
            score = dict(query=query, answer=answer, target=target, reward=int(answer == target),
                         fee=state["fee"], utility=int(answer == target) - state["fee"],
                         deadline=float(ep.deadlines[query]), world=ep.fingerprint)
            self.db.execute("INSERT INTO scores VALUES (?,?)", (query, canonical(score)))
            state.update(query=query + 1, step=0, opened=False, fee=0.)
            response = f"ACK\t{query}\t{opid}"
        state["effects"] += 1
        self.db.execute("INSERT INTO effects VALUES (?,?,?,?)", (opid, semantic, response, purchase))
        return response


def serve(config_path, state, mailbox, stop, marker):
    mailbox.mkdir(parents=True, exist_ok=True)
    lock = state.with_suffix(".lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    provider = Provider(state, json.loads(config_path.read_text()))
    print("READY", flush=True)
    while not (mailbox / "STOP").exists():
        for path in sorted(mailbox.glob("*.req")):
            raw = path.open("rb").read(MAX_WIRE + 1)
            body = unseal(raw).rstrip("\n").split("\t")
            if len(body) != 3 or body[0] != "REQ" or path.stem != body[1]:
                raise Rejected("request envelope")
            request_id = body[1]
            request = bytes.fromhex(body[2]).decode()
            try:
                response = provider.apply(request_id, request, stop == "storage_failure")
            except (Rejected, ValueError, OverflowError) as error:
                response = f"ERR\t{type(error).__name__}:{error}"
            # Commit uncertainty/OSError intentionally exits before any success reply.
            if stop in ("provider_committed", "lease_committed") and (
                    stop != "lease_committed" or request.startswith("LEASE\t")):
                atomic(marker, "COMMITTED\n")
                while not marker.with_suffix(".release").exists():
                    time.sleep(.005)
            atomic(mailbox / f"{request_id}.resp", seal(f"RESP\t{request_id}\t{response.encode().hex()}\n"))
            path.unlink()
        time.sleep(.001)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("mailbox", type=Path)
    parser.add_argument("stop", choices=("none", "storage_failure", "provider_committed", "lease_committed"))
    parser.add_argument("marker", type=Path)
    args = parser.parse_args()
    serve(args.config, args.state, args.mailbox, args.stop, args.marker)
