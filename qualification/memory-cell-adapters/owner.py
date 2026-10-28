"""Research Python owner: actual SQLite reads, typed ports and bounded execution.

Source values are accessible only to the explicit-retrieval comparator. Parameter
arms fetch source identity/status and exact events/exceptions, never fact values.
This adapter owner has not been installed as a native Hepta model profile.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import sqlite3
import time

from runtime_contract import ENTITIES, WORKFLOWS, canonical, decode_bits, execute_program, source_id


def create(path, rows):
    if Path(path).exists():
        raise FileExistsError(path)
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE sources(kind TEXT, idx INTEGER, identity TEXT, version INTEGER, active INTEGER,
                           payload TEXT, PRIMARY KEY(kind,idx));
      CREATE TABLE events(entity INTEGER, sequence INTEGER, value INTEGER, identity TEXT,
                          PRIMARY KEY(entity,sequence));
      CREATE TABLE exceptions(entity INTEGER PRIMARY KEY, reason TEXT, identity TEXT);
      CREATE TABLE execution_log(sequence INTEGER PRIMARY KEY, request TEXT, result TEXT);
    """)
    for row in rows:
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)", (row["kind"], row["index"], row["source_id"], row["version"], 1, json.dumps(row["value"])))
    for i in range(8):
        for sequence in (0, 1):
            value = (3*i + 5*sequence) % 17
            db.execute("INSERT INTO events VALUES(?,?,?,?)", (i, sequence, value, source_id("event", i, sequence)))
    db.execute("INSERT INTO exceptions VALUES(?,?,?)", (7, "manual hold: source authority requires no action", source_id("exception", 7)))
    db.commit()
    db.close()


class Owner:
    def __init__(self, path, cells, canonical_features, *, allow_value_reads=False):
        self.db = sqlite3.connect(path)
        self.cells = cells
        self.features = canonical_features
        self.allow_value_reads = allow_value_reads
        self.reads = {"source_status": 0, "explicit_values": 0, "events": 0, "exceptions": 0, "model": 0}
        self.stopped = False
        self.sleeping = {}

    def close(self):
        self.db.close()

    def stop(self):
        self.stopped = True

    def sleep(self, kind):
        if self.stopped:
            raise RuntimeError("owner stopped")
        cell = self.cells.pop(kind)
        self.sleeping[kind] = {"parameter_sha256": cell.parameter_digest(),
                               "source_ids": sorted(cell.source_ids), "base_encoder_sha": cell.base_encoder_sha,
                               "config": asdict(cell.config)}
        return self.sleeping[kind].copy()

    def wake(self, kind, cell):
        if self.stopped:
            raise RuntimeError("owner stopped")
        identity = {"parameter_sha256": cell.parameter_digest(), "source_ids": sorted(cell.source_ids),
                    "base_encoder_sha": cell.base_encoder_sha, "config": asdict(cell.config)}
        if identity != self.sleeping.get(kind):
            raise ValueError("wake checkpoint differs from sleeping version")
        self.cells[kind] = cell
        del self.sleeping[kind]

    def _source(self, kind, index):
        self.reads["source_status"] += 1
        return self.db.execute("SELECT identity,version,active FROM sources WHERE kind=? AND idx=?", (kind, index)).fetchone()

    def memory(self, kind, index):
        if self.stopped:
            return {"status": "owner_stopped", "value": None, "sources": []}
        source = self._source(kind, index)
        if source is None or not source[2]:
            return {"status": "revoked", "value": None, "sources": []}
        if not self.allow_value_reads and kind not in self.cells:
            return {"status": "cell_sleeping", "value": None, "sources": [source[0]]}
        if self.allow_value_reads:
            self.reads["explicit_values"] += 1
            value = json.loads(self.db.execute("SELECT payload FROM sources WHERE kind=? AND idx=?", (kind, index)).fetchone()[0])
        else:
            cell = self.cells[kind]
            if source[0] not in cell.source_ids:
                return {"status": "stale_source", "value": None, "sources": [source[0]]}
            self.reads["model"] += 1
            prediction = cell.predict(self.features[kind][index:index+1])
            value = decode_bits(prediction["bits"][0]) if kind == "semantic" else [int(prediction[f"op{i}"][0]) for i in range(4)]
        return {"status": "read", "value": value, "sources": [source[0]]}

    def execute(self, route, *, max_steps=4):
        began = time.perf_counter_ns()
        if self.stopped:
            return {"status": "owner_stopped", "value": None, "sources": [], "trace": []}
        role, entity, workflow = (route[k] for k in ("role", "entity", "workflow"))
        if role == "unknown":
            return {"status": "abstain", "value": None, "sources": [], "trace": []}
        if role not in ("semantic", "skill", "compose"):
            raise ValueError("unrecognized typed request")
        if role in ("semantic", "compose") and (type(entity) is not int or not 0 <= entity < len(ENTITIES)):
            raise ValueError("invalid entity port")
        if role in ("skill", "compose") and (type(workflow) is not int or not 0 <= workflow < len(WORKFLOWS)):
            raise ValueError("invalid workflow port")
        if role == "semantic":
            result = self.memory("semantic", entity)
        elif role == "skill":
            result = self.memory("skill", workflow)
        else:
            # Exact exception authority is consulted before loading any parameter.
            self.reads["exceptions"] += 1
            exception = self.db.execute("SELECT reason,identity FROM exceptions WHERE entity=?", (entity,)).fetchone()
            if exception:
                result = {"status": "exception_stop", "value": None, "sources": [exception[1]], "trace": []}
            else:
                checked = [(kind, self._source(kind, index)) for kind, index in
                           (("semantic", entity), ("skill", workflow))]
                if not self.allow_value_reads and any(kind not in self.cells for kind, _ in checked):
                    return {"status": "cell_sleeping", "value": None, "sources": [], "trace": [],
                            "wall_ns": time.perf_counter_ns()-began}
                if any(source is None or not source[2] or
                       (not self.allow_value_reads and source[0] not in self.cells[kind].source_ids)
                       for kind, source in checked):
                    return {"status": "missing_or_stale_input", "value": None,
                            "sources": [source[0] for _, source in checked if source is not None],
                            "trace": [], "wall_ns": time.perf_counter_ns()-began}
                semantic = self.memory("semantic", entity)
                skill = self.memory("skill", workflow)
                self.reads["events"] += 1
                event = self.db.execute("SELECT value,identity FROM events WHERE entity=? ORDER BY sequence DESC LIMIT 1", (entity,)).fetchone()
                if semantic["status"] != "read" or skill["status"] != "read" or event is None:
                    result = {"status": "missing_or_stale_input", "value": None,
                              "sources": semantic["sources"] + skill["sources"], "trace": []}
                else:
                    result = execute_program(event[0], semantic["value"], skill["value"], max_steps=max_steps)
                    result["sources"] = [event[1]] + semantic["sources"] + skill["sources"]
                    result["edges"] = ["event.value->skill.input", "semantic.policy->skill.policy", "skill.program->executor"]
        result["wall_ns"] = time.perf_counter_ns() - began
        return result

    def change(self, row):
        self.db.execute("UPDATE sources SET identity=?,version=?,active=1,payload=? WHERE kind=? AND idx=?",
                        (row["source_id"], row["version"], json.dumps(row["value"]), row["kind"], row["index"]))
        self.db.commit()

    def revoke(self, kind, index):
        self.db.execute("UPDATE sources SET active=0 WHERE kind=? AND idx=?", (kind, index))
        self.db.commit()

    def identity(self):
        rows = self.db.execute("SELECT kind,idx,identity,version,active FROM sources ORDER BY kind,idx").fetchall()
        return hashlib.sha256(canonical(rows)).hexdigest()
