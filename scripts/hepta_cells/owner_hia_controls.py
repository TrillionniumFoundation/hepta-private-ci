"""Cold-open controls on copies of actually executed native joint records.

No native image or tool is invoked here. Mutations affect only fresh copies;
the source database members and each rejected copy must retain their bytes.
"""

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from .component_types import CellError, PendingExecution, _bounded_json
from .hia_component import HiaCellComponent
from .lifecycle import CellOwner


def _members(path):
    return {
        suffix: hashlib.sha256(Path(str(path) + suffix).read_bytes()).hexdigest()
        for suffix in ("", "-wal", "-shm", "-journal")
        if Path(str(path) + suffix).exists()
    }


def _copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=False)
    for suffix in _members(source):
        shutil.copy2(Path(str(source) + suffix), Path(str(target) + suffix))


def _save(path, value):
    with path.open("x") as stream:
        stream.write(
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )


def _json(db, column, change):
    value = json.loads(
        db.execute("SELECT " + column + " FROM hia_cell_calls").fetchone()[0]
    )
    change(value)
    db.execute("UPDATE hia_cell_calls SET " + column + "=?", (_bounded_json(value),))


def _both_outputs(db):
    _json(db, "inner_result", lambda value: value["output"].update(cursor=2))
    _json(db, "result", lambda value: value["output"]["cell"].update(cursor=2))


def _receipt_type(db):
    value = json.loads(db.execute("SELECT receipt FROM intents").fetchone()[0])
    value["output"]["cell"]["cursor"] = True
    db.execute("UPDATE intents SET receipt=?", (_bounded_json(value),))


def _pending_sequence(db):
    _json(db, "binding", lambda value: value.update(sequence=2))
    _json(
        db, "result", lambda value: value["output"]["hia"]["binding"].update(sequence=2)
    )
    _state(db, 24, (2).to_bytes(8, "little"))


def _cancel_intent_before_native(db):
    state = db.execute("SELECT state FROM hia_cell_calls").fetchone()[0]
    if int.from_bytes(state[184:192], "little") != 0:
        raise AssertionError("pre-native cancellation control requires a zero flag")
    db.execute(
        "INSERT INTO cancellations SELECT partition,request,identity FROM hia_cell_calls"
    )


def _wrong_cancel_intent_before_native(db):
    _cancel_intent_before_native(db)
    db.execute("UPDATE cancellations SET identity=?", ("0" * 64,))


def _wrong_cancel_intent_without_native_call(db):
    _wrong_cancel_intent_before_native(db)
    db.execute("DELETE FROM hia_cell_calls")


def _state(db, offset, data):
    state = bytearray(db.execute("SELECT state FROM hia_cell_calls").fetchone()[0])
    state[offset : offset + len(data)] = data
    db.execute("UPDATE hia_cell_calls SET state=?", (bytes(state),))
    if db.execute("SELECT result FROM hia_cell_calls").fetchone()[0] is not None:
        # Retain the copied hash consistency so that the native ABI check,
        # rather than a stale duplicate JSON hash, has to reject the damage.
        _json(
            db,
            "result",
            lambda value: value["output"]["hia"].update(
                native_state_sha256=hashlib.sha256(state).hexdigest()
            ),
        )


def _logical(db):
    return {
        table: [list(row) for row in db.execute(query)]
        for table, query in {
            "cells": "SELECT sequence,remaining FROM cells ORDER BY partition",
            "intents": "SELECT request,status,reserved,receipt FROM intents ORDER BY partition,request",
            "calls": "SELECT request,phase,hex(state),inner_result,result FROM hia_cell_calls ORDER BY partition,request",
            "cancellations": "SELECT partition,request,identity FROM cancellations ORDER BY partition,request",
        }.items()
    }


class _NoNativeExecution:
    def __init__(self, native):
        self.native, self.attempts = native, 0

    def binding_from_dict(self, value):
        return self.native.binding_from_dict(value)

    def recover(self, *args, **kwargs):
        self.attempts += 1
        raise AssertionError(
            "readback reached native execution before identity rejection"
        )

    resume = recover


def run_native_binding_controls(
    source, output, partition, inner, native, candidate_sha256, image_sha256
):
    """Use the live wrapper's independent identity before any native readback."""
    output.mkdir(parents=True, exist_ok=False)
    before_source = _members(source)
    original = output / "original" / "owner.sqlite"
    _copy(source, original)
    results = {}
    for field, offset in (("candidate_sha256", 32), ("cell_sha256", 64)):
        path = output / field / "owner.sqlite"
        _copy(original, path)
        db = sqlite3.connect(path)
        try:
            binding = json.loads(
                db.execute("SELECT binding FROM hia_cell_calls").fetchone()[0]
            )
            changed = ("f" if binding[field] != "f" * 64 else "e") * 64
            _json(db, "binding", lambda value: value.update({field: changed}))
            _state(db, offset, bytes.fromhex(changed))
            db.commit()
        finally:
            db.close()
        _copy(path, path.parent / "raw-before-cold" / "owner.sqlite")
        owner = CellOwner(path)
        guard = _NoNativeExecution(native)
        try:
            component = HiaCellComponent(
                owner,
                inner,
                guard,
                candidate_sha256=candidate_sha256,
                image_sha256=image_sha256,
            )
            prior = _logical(owner.db)
            request = owner.db.execute("SELECT request FROM intents").fetchone()[0]
            error = None
            try:
                owner.reconcile(partition, component, request, component.readback)
            except PendingExecution as failure:
                cause = failure.__cause__
                error = type(cause).__name__ + ": " + str(cause)
            after = _logical(owner.db)
            record = {
                "failure": error,
                "attempted_native_calls": guard.attempts,
                "before": prior,
                "after": after,
            }
            _save(path.parent / "RESULT.json", record)
            if (
                error
                != "CellError: native continuation differs from the frozen wrapper"
                or guard.attempts
                or prior != after
            ):
                raise AssertionError(
                    "readback did not reject the wrong wrapper binding before use"
                )
            results[field] = record
        finally:
            owner.close()
    if _members(source) != before_source:
        raise AssertionError("binding controls changed the original native source")
    result = {
        "status": "NATIVE_WRAPPER_BINDING_CONTROLS_PASS",
        "original_members": before_source,
        "controls": results,
        "native_or_effect_calls": 0,
        "scope": "live wrapper identity rejection; failed readback attempts remain recorded on copies",
    }
    _save(output / "RESULT.json", result)
    return result


def run_native_damage_controls(samples, output):
    """Preserve actual completed, pending-completed and unknown originals."""
    output.mkdir(parents=True, exist_ok=False)
    before_sources = {name: _members(path) for name, path in samples.items()}
    positive = {}
    positive_cases = [(name, source, None) for name, source in samples.items()]
    positive_cases.append(
        (
            "cancel-intent-before-native",
            samples["pending"],
            _cancel_intent_before_native,
        )
    )
    for name, source, change in positive_cases:
        path = output / ("valid-" + name) / "owner.sqlite"
        _copy(source, path)
        db = sqlite3.connect(path)
        try:
            if change is not None:
                change(db)
                db.commit()
            prior = _logical(db)
            if db.execute("SELECT count(*) FROM hia_cell_calls").fetchone()[0] != 1:
                raise AssertionError(
                    "native controls require one original invocation per sample"
                )
        finally:
            db.close()
        owner = CellOwner(path)
        try:
            after = _logical(owner.db)
        finally:
            owner.close()
        if prior != after:
            raise AssertionError(
                "cold validation changed original native state or owner accounting"
            )
        positive[name] = {"before": prior, "after": after, "status": "PRESERVED"}
    cases = [
        ("paired-json-output", "pending", _both_outputs),
        (
            "copied-binding-boolean",
            "pending",
            lambda db: _json(
                db,
                "result",
                lambda value: value["output"]["hia"]["binding"].update(sequence=True),
            ),
        ),
        (
            "copied-state-boolean",
            "pending",
            lambda db: _json(
                db, "result", lambda value: value["state"].update(cursor=True)
            ),
        ),
        (
            "copied-output-boolean",
            "pending",
            lambda db: _json(
                db, "result", lambda value: value["output"]["cell"].update(cursor=True)
            ),
        ),
        ("receipt-output-boolean", "completed", _receipt_type),
        ("pending-owner-sequence", "pending", _pending_sequence),
    ]
    for name, offset, data in (
        ("magic", 0, bytes(8)),
        ("version", 8, (2).to_bytes(8, "little")),
        ("action", 16, (5).to_bytes(8, "little")),
        ("sequence", 24, (2).to_bytes(8, "little")),
        ("candidate", 32, bytes(32)),
        ("input-length", 160, bytes(8)),
        ("result-limit", 168, (1).to_bytes(8, "little")),
        ("result-length", 176, bytes(8)),
        ("cancel", 184, (2).to_bytes(8, "little")),
        ("result-digest", 192, bytes(32)),
        ("reserved", 224, b"\x01"),
    ):
        cases.append(
            (
                "state-" + name,
                "pending",
                lambda db, offset=offset, data=data: _state(db, offset, data),
            )
        )
    cases.extend(
        [
            (
                "unknown-invented-result-length",
                "unknown",
                lambda db: _state(db, 176, (1).to_bytes(8, "little")),
            ),
            (
                "unknown-invented-result-digest",
                "unknown",
                lambda db: _state(db, 192, b"\x01"),
            ),
            ("cancel-flag-missing", "unknown", lambda db: _state(db, 184, bytes(8))),
            (
                "native-cancel-intent-missing",
                "unknown",
                lambda db: db.execute("DELETE FROM cancellations"),
            ),
            (
                "native-cancel-intent-identity",
                "unknown",
                lambda db: db.execute(
                    "UPDATE cancellations SET identity=?", ("0" * 64,)
                ),
            ),
            (
                "completed-native-cancel-without-intent",
                "pending",
                lambda db: _state(db, 184, (1).to_bytes(8, "little")),
            ),
            (
                "pre-native-cancel-intent-identity",
                "pending",
                _wrong_cancel_intent_before_native,
            ),
            (
                "pre-begin-cancel-intent-identity",
                "pending",
                _wrong_cancel_intent_without_native_call,
            ),
        ]
    )
    results = {}
    for name, sample, change in cases:
        path = output / name / "owner.sqlite"
        _copy(samples[sample], path)
        db = sqlite3.connect(path)
        try:
            change(db)
            db.commit()
        finally:
            db.close()
        _copy(path, path.parent / "raw-before-cold" / "owner.sqlite")
        before = _members(path)
        error = None
        try:
            owner = CellOwner(path)
        except CellError as failure:
            error = str(failure)
        else:
            owner.close()
        after = _members(path)
        record = {
            "source": sample,
            "error": error,
            "before": before,
            "after": after,
            "rejected_unchanged": error is not None and before == after,
        }
        _save(path.parent / "RESULT.json", record)
        if not record["rejected_unchanged"]:
            raise AssertionError(
                "native damage was accepted or altered its retained bytes: " + name
            )
        results[name] = record
    after_sources = {name: _members(path) for name, path in samples.items()}
    if before_sources != after_sources:
        raise AssertionError("native damage controls changed original sources")
    result = {
        "status": "NATIVE_RETAINED_BYTES_CONTROLS_PASS",
        "sources_before": before_sources,
        "sources_after": after_sources,
        "positive_controls": positive,
        "damage_controls": results,
        "native_or_effect_calls": 0,
        "scope": "cold validation of copies; no coherent-whole-store authentication claim",
    }
    _save(output / "RESULT.json", result)
    return result
