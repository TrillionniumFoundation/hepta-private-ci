"""Research serving protocol with one trusted authority and offline replicas.

GitHub's same-run artifact transport is the trust root; hashes do not authenticate
hostile jobs. Replicas compute candidates, never externally release answers. The
authority's final transaction is the freshness point. This is not consensus,
remote attestation, physical-host failover, or erasure of retained model bytes.
"""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import stat
import struct


MAX_BYTES = 64 * 1024 * 1024
ARRAY_NAMES = ("head.bias", "head.weight", "hidden.bias", "hidden.weight")


class Denied(RuntimeError):
    """An untrusted, stale, or incomplete request cannot become an answer."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise Denied("missing, linked, or oversized JSON file")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Denied("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(path.read_text(), object_pairs_hook=unique)
    canonical(value)  # Reject NaN/infinity, including inside unused metadata.
    return value


def write_json(path, value):
    path = Path(path)
    pending = path.with_name(path.name + ".pending")
    with pending.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def seal_bundle(source, target, binding):
    """Copy an existing learned checkpoint; never synthesize a replacement."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=False)
    inventory = []
    for name in ("model.json", "probes.json"):
        read_json(source / name)
        shutil.copyfile(source / name, target / name)
        inventory.append(dict(path=name, sha256=file_digest(target / name),
                              bytes=(target / name).stat().st_size))
    manifest = dict(schema="hepta.memory.federation.bundle.v1", binding=binding,
                    files=inventory)
    checkpoint = digest(manifest)
    write_json(target / "bundle.json", dict(manifest, checkpoint=checkpoint))
    verify_bundle(target, binding, checkpoint)
    return checkpoint


def verify_bundle(path, binding, checkpoint):
    path = Path(path)
    if path.is_symlink() or not path.is_dir() or any(p.is_symlink() for p in path.parents):
        raise Denied("bundle path is absent or linked")
    if {p.name for p in path.iterdir()} != {"model.json", "probes.json", "bundle.json"}:
        raise Denied("unexpected serving bundle inventory")
    if any(not stat.S_ISREG(p.lstat().st_mode) for p in path.iterdir()):
        raise Denied("nonregular bundle entry")
    manifest = read_json(path / "bundle.json")
    unsigned = {k: v for k, v in manifest.items() if k != "checkpoint"}
    if (manifest.get("schema") != "hepta.memory.federation.bundle.v1" or
            manifest.get("binding") != binding or manifest.get("checkpoint") != checkpoint or
            digest(unsigned) != checkpoint):
        raise Denied("checkpoint or task binding mismatch")
    inventory = [dict(path=n, sha256=file_digest(path / n), bytes=(path / n).stat().st_size)
                 for n in ("model.json", "probes.json")]
    if manifest["files"] != inventory or sum(x["bytes"] for x in inventory) > MAX_BYTES:
        raise Denied("checkpoint bytes differ or exceed transport budget")
    return manifest


def infer(path, binding, checkpoint):
    """Independently decode root's actual learned f32 checkpoint, using f64 math."""
    verify_bundle(path, binding, checkpoint)
    model, probes = (read_json(Path(path) / name) for name in ("model.json", "probes.json"))
    if model.get("schema") != "hepta.memory.numpy-mlp.v12" or model.get("activation") != "relu":
        raise Denied("unsupported learned model")
    d, h, o = (model[k] for k in ("dimension", "hidden", "output"))
    if any(type(x) is not int for x in (d, h, o)) or not (1 <= d <= 384 and 1 <= h <= 256 and 1 <= o <= 4096):
        raise Denied("model dimension bound")
    shapes = {"hidden.weight": [h, d], "hidden.bias": [h], "head.weight": [o, h], "head.bias": [o]}
    if set(model["arrays"]) != set(shapes):
        raise Denied("model tensor inventory mismatch")
    arrays, checksum = {}, hashlib.sha256()
    for name in ARRAY_NAMES:
        item, shape = model["arrays"][name], shapes[name]
        raw = bytes.fromhex(item["f32le_hex"])
        if item["shape"] != shape or len(raw) != math.prod(shape) * 4:
            raise Denied("model tensor shape mismatch")
        values = struct.unpack("<" + "f" * math.prod(shape), raw)
        if not all(math.isfinite(v) for v in values):
            raise Denied("nonfinite parameter")
        checksum.update(canonical([name, shape, "float32"]))
        checksum.update(raw)
        arrays[name] = values
    if checksum.hexdigest() != model["parameter_sha256"] or probes["model_parameter_sha256"] != checksum.hexdigest():
        raise Denied("model parameter identity mismatch")
    if probes.get("schema") != "hepta.memory.v12.probes.v1" or not 1 <= len(probes["inputs"]) <= 128:
        raise Denied("unsupported or unbounded probe batch")
    outputs = []
    for x in probes["inputs"]:
        if len(x) != d or not all(type(v) in (int, float) and math.isfinite(v) for v in x):
            raise Denied("invalid model input")
        hidden = []
        for j in range(h):
            value = arrays["hidden.bias"][j]
            for k in range(d):
                value += float(x[k]) * arrays["hidden.weight"][j * d + k]
            hidden.append(max(0.0, value))
        row = []
        for j in range(o):
            value = arrays["head.bias"][j]
            for k in range(h):
                value += hidden[k] * arrays["head.weight"][j * h + k]
            row.append(value)
        outputs.append(row)
    error = compare_outputs(outputs, probes["expected_logits"], probes["tolerance"])
    # Recheck after compute: mutation while reading cannot be sealed as a result.
    verify_bundle(path, binding, checkpoint)
    return dict(logits=outputs, parameter_sha256=checksum.hexdigest(),
                max_abs_error=error, query_sha256=digest(probes["inputs"]))


def compare_outputs(actual, expected, tolerance):
    atol, rtol = tolerance["atol"], tolerance["rtol"]
    if not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1e-4 for v in (atol, rtol)):
        raise Denied("unsupported numerical tolerance")
    if len(actual) != len(expected) or any(len(a) != len(e) for a, e in zip(actual, expected)):
        raise Denied("output shape mismatch")
    maximum = 0.0
    for row, target in zip(actual, expected):
        for value, wanted in zip(row, target):
            if not math.isfinite(value) or not math.isfinite(wanted) or not math.isclose(value, wanted, abs_tol=atol, rel_tol=rtol):
                raise Denied("actual learned output does not match frozen probes")
            maximum = max(maximum, abs(value - wanted))
    return maximum


class Authority:
    """Only this trusted controller releases results; workers cannot grant epochs."""

    def __init__(self, path, binding, *, expected_anchor=None, initial=None):
        self.path, self.binding = Path(path), binding
        if self.path.is_symlink() or (expected_anchor is not None and file_digest(path) != expected_anchor):
            raise Denied("authority snapshot rollback or substitution")
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        if initial is not None:
            self.db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1), epoch INTEGER, owner TEXT, checkpoint TEXT, valid INTEGER);
                CREATE TABLE grants(id TEXT PRIMARY KEY, body TEXT NOT NULL, consumed INTEGER NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY, kind TEXT, body TEXT, parent TEXT, digest TEXT);
            """)
            with self.transaction():
                for key, value in {"binding": binding, "probes": initial["probes"]}.items():
                    self.db.execute("INSERT INTO metadata VALUES (?,?)", (key, canonical(value).decode()))
                self.db.execute("INSERT INTO state VALUES (1,1,'source',?,1)", (initial["checkpoint"],))
                self.event("bootstrap", dict(binding=binding, probes=initial["probes"], state=self.state()))
        try:
            # Recover a coherent cut, including the projections used for grants
            # and revocation. A valid event hash chain alone is insufficient.
            with self.transaction():
                self._verify_replay()
        except BaseException:
            self.db.close()
            raise

    def _verify_replay(self):
        parent = "0" * 64
        state, metadata, grants = None, None, {}
        for sequence, row in enumerate(self.db.execute("SELECT * FROM events ORDER BY seq"), 1):
            body = json.loads(row["body"])
            expected = digest(dict(seq=sequence, kind=row["kind"], body=body, parent=parent))
            if (row["seq"] != sequence or row["parent"] != parent or row["digest"] != expected or
                    canonical(body).decode() != row["body"]):
                raise Denied("authority event history is corrupt")
            parent = row["digest"]
            kind = row["kind"]
            if kind == "bootstrap":
                if sequence != 1 or set(body) != {"binding", "probes", "state"}:
                    raise Denied("unsupported authority bootstrap history")
                state = body["state"]
                if state != dict(epoch=1, owner="source", checkpoint=state.get("checkpoint"), valid=1):
                    raise Denied("authority bootstrap state is invalid")
                metadata = {"binding": canonical(body["binding"]).decode(),
                            "probes": canonical(body["probes"]).decode()}
                if body["binding"] != self.binding:
                    raise Denied("authority belongs to another task")
                probes = body["probes"]
            elif state is None:
                raise Denied("authority lacks bootstrap history")
            elif kind == "issue":
                ticket = dict(schema="hepta.memory.federation.read.v1", binding=self.binding,
                              grant=body.get("grant"), node=body.get("node"), permission="read",
                              epoch=state["epoch"], checkpoint=state["checkpoint"],
                              query_sha256=digest(probes["inputs"]))
                if not state["valid"] or body != ticket or not ticket["grant"] or ticket["grant"] in grants:
                    raise Denied("authority issued an invalid or duplicate grant")
                grants[ticket["grant"]] = dict(body=canonical(ticket).decode(), consumed=0)
            elif kind == "release":
                grant = grants.get(body.get("grant"))
                ticket = json.loads(grant["body"]) if grant else {}
                if (not state["valid"] or not grant or grant["consumed"] or
                        ticket["epoch"] != state["epoch"] or ticket["checkpoint"] != state["checkpoint"] or
                        body != dict(released=True, epoch=state["epoch"], node=ticket["node"],
                                     result_sha256=body.get("result_sha256"), checkpoint=state["checkpoint"],
                                     grant=ticket["grant"], ticket_sha256=digest(ticket))):
                    raise Denied("authority release history reuses or mismatches a grant")
                grant["consumed"] = 1
            elif kind == "migrate":
                prepared = body.get("prepared", {})
                grant = grants.get(prepared.get("read_grant"))
                ticket = json.loads(grant["body"]) if grant else {}
                after = dict(epoch=state["epoch"] + 1, owner=prepared.get("node"),
                             checkpoint=state["checkpoint"], valid=1)
                if (not state["valid"] or not grant or not grant["consumed"] or
                        ticket["epoch"] != state["epoch"] or ticket["checkpoint"] != state["checkpoint"] or
                        ticket["node"] != after["owner"] or after["owner"] == state["owner"] or
                        prepared != dict(binding=self.binding, node=after["owner"], epoch=state["epoch"],
                                         checkpoint=state["checkpoint"], read_grant=ticket["grant"],
                                         verified_checkpoint=True) or
                        prepared["verified_checkpoint"] is not True or
                        body != dict(before=state, after=after, prepared=prepared)):
                    raise Denied("authority migration history lacks a released preparation")
                state = after
            elif kind == "revoke":
                after = dict(epoch=state["epoch"] + 1, owner=state["owner"],
                             checkpoint=state["checkpoint"], valid=0)
                if not state["valid"] or body != after:
                    raise Denied("authority revocation history is invalid")
                state = after
            else:
                raise Denied("unsupported authority event")
        actual_metadata = {row["key"]: row["value"] for row in self.db.execute("SELECT * FROM metadata")}
        actual_grants = {row["id"]: dict(body=row["body"], consumed=row["consumed"])
                         for row in self.db.execute("SELECT * FROM grants")}
        if state is None or state != self.state() or metadata != actual_metadata or grants != actual_grants:
            raise Denied("authority state, metadata or grants disagree with committed history")

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def state(self):
        return dict(self.db.execute("SELECT epoch,owner,checkpoint,valid FROM state WHERE id=1").fetchone())

    def event(self, kind, body):
        previous = self.db.execute("SELECT seq,digest FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, parent = (previous["seq"] + 1, previous["digest"]) if previous else (1, "0" * 64)
        checksum = digest(dict(seq=seq, kind=kind, body=body, parent=parent))
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (seq, kind, canonical(body).decode(), parent, checksum))

    def issue(self, node):
        with self.transaction():
            state = self.state()
            if not state["valid"]:
                raise Denied("revoked checkpoint")
            probes = json.loads(self.db.execute("SELECT value FROM metadata WHERE key='probes'").fetchone()[0])
            ticket = dict(schema="hepta.memory.federation.read.v1", binding=self.binding,
                          grant=secrets.token_hex(16), node=node, permission="read",
                          epoch=state["epoch"], checkpoint=state["checkpoint"], query_sha256=digest(probes["inputs"]))
            self.db.execute("INSERT INTO grants VALUES (?,?,0)", (ticket["grant"], canonical(ticket).decode()))
            self.event("issue", ticket)
            return ticket

    def release(self, candidate):
        with self.transaction():
            ticket, state = candidate["ticket"], self.state()
            grant = self.db.execute("SELECT body,consumed FROM grants WHERE id=?", (ticket.get("grant"),)).fetchone()
            if not grant or grant["consumed"] or json.loads(grant["body"]) != ticket:
                raise Denied("unknown, altered, or replayed read grant")
            if (not state["valid"] or ticket["epoch"] != state["epoch"] or
                    ticket["checkpoint"] != state["checkpoint"] or candidate["node"] != ticket["node"] or
                    candidate["output"]["query_sha256"] != ticket["query_sha256"]):
                raise Denied("read failed final epoch/checkpoint/node/query fence")
            probes = json.loads(self.db.execute("SELECT value FROM metadata WHERE key='probes'").fetchone()[0])
            if candidate["output"]["parameter_sha256"] != probes["model_parameter_sha256"]:
                raise Denied("result has wrong parameter identity")
            compare_outputs(candidate["output"]["logits"], probes["expected_logits"], probes["tolerance"])
            self.db.execute("UPDATE grants SET consumed=1 WHERE id=?", (ticket["grant"],))
            receipt = dict(released=True, epoch=state["epoch"], node=ticket["node"],
                           result_sha256=digest(candidate["output"]), checkpoint=state["checkpoint"],
                           grant=ticket["grant"], ticket_sha256=digest(ticket))
            self.event("release", receipt)
            return receipt

    def authorize_write(self, node, epoch, checkpoint):
        state = self.state()
        if not state["valid"] or (state["owner"], state["epoch"], state["checkpoint"]) != (node, epoch, checkpoint):
            raise Denied("writer is revoked, read-only, or fenced")
        return state

    def migrate(self, target, *, expected_epoch, expected_owner, prepared):
        with self.transaction():
            state = self.authorize_write(expected_owner, expected_epoch, prepared["checkpoint"])
            grant = self.db.execute("SELECT body,consumed FROM grants WHERE id=?", (prepared.get("read_grant"),)).fetchone()
            proof = json.loads(grant["body"]) if grant else {}
            expected_preparation = dict(binding=self.binding, node=target, epoch=expected_epoch,
                                        checkpoint=state["checkpoint"], read_grant=prepared.get("read_grant"),
                                        verified_checkpoint=True)
            if (prepared != expected_preparation or target == expected_owner or
                    prepared["verified_checkpoint"] is not True or
                    not grant or not grant["consumed"] or proof["node"] != target or
                    proof["epoch"] != expected_epoch or proof["checkpoint"] != state["checkpoint"]):
                raise Denied("migration preparation does not match active transaction")
            self.db.execute("UPDATE state SET epoch=epoch+1,owner=? WHERE id=1", (target,))
            self.event("migrate", dict(before=state, after=self.state(), prepared=prepared))
            return self.state()

    def revoke(self, checkpoint):
        with self.transaction():
            if checkpoint != self.state()["checkpoint"] or not self.state()["valid"]:
                raise Denied("checkpoint is not active")
            self.db.execute("UPDATE state SET epoch=epoch+1,valid=0 WHERE id=1")
            self.event("revoke", self.state())
            return self.state()
