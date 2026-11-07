"""Identity binding and durable single-use confirmation for the existing WSP owner.

This is a local research ledger, not an independent data authority. Reservations
survive process failure, including failures before a result is written.
"""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np


ARMS = ("C", "L", "E", "R", "A", "G", "EG", "J", "M")
FITS = (11, 23, 37, 53, 71)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_identity(path):
    data = Path(path).read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def model_identity(model):
    """Bind stored operators and their actual dependency tables, not just a label."""
    if model["schema"] != "joint-policy-v1" or model["family"] != "renewal":
        raise ValueError("unsupported model class; a new class requires a new contract")
    shapes = {"w1": (48, 85), "b1": (48,), "w2": (4, 48), "b2": (4,)}
    tensors = {}
    for name, shape in shapes.items():
        value = np.asarray(model["network"][name], dtype="<f8")
        if value.shape != shape or not np.isfinite(value).all():
            raise ValueError("tensor map or numeric identity mismatch: " + name)
        tensors[name] = {"shape": list(shape), "dtype": "IEEE754-F64-LE",
                         "layout": "row-major", "sha256": hashlib.sha256(value.tobytes()).hexdigest()}
    core = model["core"]
    for key in ("generators", "tables", "raw", "physical"):
        if key not in core:
            raise ValueError("missing generator/table dependency: " + key)
    return {"canonical_checkpoint_sha256": digest(model), "tensor_map": tensors,
            "tensor_roles": {"w2[0:3],b2[0:3]": "WAIT,READ,REPAIR continuation",
                             "w2[3],b2[3]": "protected Belief logit"},
            "protected_model_sha256": protected_identity(model),
            "core_sha256": digest(core), "generator_sha256": digest(core["generators"]),
            "transition_tables_sha256": digest(core["tables"]),
            "representation_sha256": digest({key: model[key] for key in
                ("coordinates", "confusion", "bank_semantics", "target", "public_dimensions")}),
            "parameter_count": model["parameter_count"],
            "time_contract": "six decision ticks; physical elapsed is the sum of scheduled durations",
            "value_units": "fixed task reward minus read, repair and elapsed-time charges",
            "event_contract": "deadline sign; endpoint bank is not first-passage probability"}


def protected_identity(model):
    protected = json.loads(canonical(model))
    protected["network"]["w2"][:3] = []
    protected["network"]["b2"][:3] = []
    return digest(protected)


def verify_files(root, identities):
    root = Path(root).resolve()
    for name, expected in identities.items():
        target = (root / name).resolve()
        if not target.is_relative_to(root) or file_identity(target) != expected:
            raise ValueError("frozen source/input changed: " + name)


def dual_norm_random(delta, rng):
    """One signed permutation preserves both L2 and Linf before storage rounding."""
    values = np.asarray(delta, dtype=float).ravel()
    shuffled = rng.permutation(values) * rng.choice(np.array([-1., 1.]), len(values))
    return shuffled.reshape(np.asarray(delta).shape)


class Ledger:
    """A frozen candidate cohort consumes each schedule once, including failures."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
              protocol TEXT PRIMARY KEY, candidates TEXT NOT NULL,
              state TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS samples (
              fingerprint TEXT PRIMARY KEY, run TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (
              run TEXT NOT NULL, sample TEXT NOT NULL, fit INTEGER NOT NULL,
              domain TEXT NOT NULL, arm TEXT NOT NULL, state TEXT NOT NULL,
              result TEXT, cpu REAL, wall REAL,
              PRIMARY KEY (run,sample,fit,arm));
        """)

    def freeze(self, protocol, candidates, history):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for fingerprint in sorted(set(history)):
                self.db.execute("INSERT OR IGNORE INTO samples VALUES (?, 'HISTORY')", (fingerprint,))
            self.db.execute("INSERT INTO runs VALUES (?,?,'FROZEN',?)",
                            (protocol, candidates, time.time()))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def reserve(self, protocol, candidates, samples, arms=ARMS):
        """Commit the complete denominator before the first inference call."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT candidates,state FROM runs WHERE protocol=?", (protocol,)).fetchone()
            if row != (candidates, "FROZEN") or not samples or tuple(arms) != ARMS:
                raise ValueError("missing/changed/already-consumed candidate cohort")
            for sample in samples:
                self.db.execute("INSERT INTO samples VALUES (?,?)", (sample["sha256"], protocol))
                for arm in arms:
                    self.db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,'RESERVED',NULL,NULL,NULL)",
                        (protocol, sample["sha256"], sample["fit"], sample["domain"], arm))
            self.db.execute("UPDATE runs SET state='CONSUMED' WHERE protocol=?", (protocol,))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def record(self, protocol, sample, fit, arm, result, cpu, wall, failed=False):
        if not all(math.isfinite(x) and x >= 0 for x in (cpu, wall)):
            raise ValueError("invalid measured cost")
        result_digest = digest(result)
        cursor = self.db.execute("""UPDATE attempts SET state=?,result=?,cpu=?,wall=?
            WHERE run=? AND sample=? AND fit=? AND arm=? AND state='RESERVED'""",
            ("FAILED" if failed else "COMPLETE", result_digest, cpu, wall, protocol, sample, fit, arm))
        if cursor.rowcount != 1:
            raise ValueError("unreserved or already consumed evaluation; retries are forbidden")

    def counts(self, protocol):
        return dict(self.db.execute("SELECT state,count(*) FROM attempts WHERE run=? GROUP BY state", (protocol,)))

    def close(self):
        self.db.execute("PRAGMA wal_checkpoint(FULL)")
        self.db.close()


def quality_gate(contrasts, coverage, unknown_costs):
    """Missing capabilities/costs remain explicit holds, never numerical zeros."""
    benefits = bool(contrasts) and all(row["familywise_interval"][0] > .005 for row in contrasts)
    required = {"main_task", "preservation", "ood", "calibration", "latency", "failures"}
    complete_quality = required.issubset(coverage) and all(coverage.values())
    return {"task_benefit_pass": benefits,
            "complete_quality_pass": complete_quality,
            "full_cost_qualified": not unknown_costs,
            "production_eligible": benefits and complete_quality and not unknown_costs,
            "unmeasured_costs": list(unknown_costs)}
