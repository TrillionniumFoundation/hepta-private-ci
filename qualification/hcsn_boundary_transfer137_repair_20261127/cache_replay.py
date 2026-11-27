"""Strict receipt replay, with no residual evaluator or live-root fallback.

The complete original CI artifact and causal input closure are bound before
this class is constructed. Old receipts are preserved byte for byte. Their
wall_seconds describe the original work, never newly executed inverse work.
"""
import hashlib
import json
import math
from pathlib import Path
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    raw = Path(path).read_bytes()
    if len(raw) != expected["bytes"] or sha(raw) != expected["sha256"]:
        raise ValueError("cached original evidence identity differs: " + Path(path).name)
    return raw


def float_hex(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("finite, non-boolean bound scalar required")
    return float(value).hex()


def descriptor_hex(detail):
    if set(detail) != {"role", "slow_tick", "sender", "boundary", "reference_z"}:
        raise ValueError("exact cached descriptor key set required")
    for key in ("role", "slow_tick", "sender"):
        if type(detail[key]) is not int:
            raise ValueError("typed cached role/tick/sender required")
    return dict(role=detail["role"], slow_tick=detail["slow_tick"], sender=detail["sender"],
        boundary_hex=float_hex(detail["boundary"]), reference_z_hex=float_hex(detail["reference_z"]))


class CachedInverse:
    def __init__(self, binding, directory, ledger, output, write):
        self.binding, self.directory = binding, Path(directory)
        self.ledger, self.output, self.write = ledger, Path(output), write
        self.ordinal, self.pending, self.returned = 0, None, 0
        if len(binding["roots"]) != 24 or [r["ordinal"] for r in binding["roots"]] != list(range(24)):
            raise ValueError("exactly 24 ordered original roots required")
        self.receipts = []
        for row in binding["roots"]:
            raw = checked(self.directory/row["root_receipt"]["path"], row["root_receipt"])
            receipt = json.loads(raw)
            if (receipt["status"] != "ROOT_CERTIFIED_REAL_SURROGATE"
                    or receipt["domain_complete"] is not True
                    or receipt["selected_root"] != 0 or len(receipt["all_roots"]) != 1
                    or float_hex(receipt["z"]) != row["root_float_hex"]):
                raise ValueError("original unique complete root condition differs")
            self.receipts.append(receipt)

    def start(self, detail):
        self.ledger.check_time()
        if self.pending is not None or self.ordinal >= 24:
            raise ValueError("cached inverse order, overlap or repeated lookup differs")
        row = self.binding["roots"][self.ordinal]
        if descriptor_hex(detail) != row["descriptor"]:
            raise ValueError("recomputed fixed-program descriptor differs from old exact inputs")
        self.ledger.charge("cached_inverse_targets")
        self.ledger.event("cached_inverse_lookup_started", ordinal=self.ordinal,
            descriptor=row["descriptor"], old_root_sha256=row["root_receipt"]["sha256"],
            new_root_solver_calls=0)
        self.pending = self.ordinal

    def __call__(self, boundary, absolute, theta, reference_z, constants, deadline):
        started = time.monotonic()
        self.ledger.check_time()
        if self.pending != self.ordinal or self.ordinal >= 24:
            raise ValueError("cached inverse called without one exact prior descriptor")
        if type(deadline) not in (float, int) or not math.isfinite(deadline) or time.monotonic() >= deadline:
            raise ValueError("new cached-program resource deadline exhausted")
        row = self.binding["roots"][self.ordinal]
        actual = {name: float_hex(value) for name, value in
            (("boundary", boundary), ("absolute", absolute), ("theta", theta), ("reference_z", reference_z))}
        if actual != row["mathematical_inputs_float_hex"]:
            raise ValueError("a scalar input differs from its original root closure")
        actual_constants = {name: float_hex(value) for name, value in vars(constants).items()}
        if actual_constants != self.binding["constants_float_hex"]:
            raise ValueError("physical constant names or exact derived bits differ")
        # Re-read the original receipt at use, preserving its old numerical
        # certificate and timing. No new residual or partition is evaluated.
        receipt = json.loads(checked(self.directory/row["root_receipt"]["path"], row["root_receipt"]))
        witness = dict(schema="hepta.exact-root-cache-replay.v1", ordinal=self.ordinal,
            old_receipt_sha256=row["root_receipt"]["sha256"], original_ledger_line=row["original_ledger_line"],
            original_ledger_line_sha256=row["original_ledger_line_sha256"], mathematical_inputs_float_hex=actual,
            constants_float_hex=actual_constants, returned_root_float_hex=float_hex(receipt["z"]),
            new_root_solver_calls=0, new_residual_evaluations=0,
            current_cache_lookup_wall_seconds=time.monotonic()-started,
            old_root_timing_not_added_as_new_work=True)
        self.write(self.output/("cached_root_%02d.json" % self.ordinal), witness)
        self.ledger.event("cached_inverse_returned", ordinal=self.ordinal,
            old_root_sha256=row["root_receipt"]["sha256"], evidence=witness)
        self.ordinal += 1
        self.returned += 1
        self.pending = None
        return receipt

    def verify_complete(self):
        if self.ordinal != 24 or self.returned != 24 or self.pending is not None:
            raise ValueError("cached root sequence incomplete")
