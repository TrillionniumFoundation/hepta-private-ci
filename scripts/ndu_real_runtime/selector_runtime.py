"""Bind paired selection to the original candidate audit before host effects."""

import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from .candidate_memory import CandidateScope
from .candidate_runtime import (
    AUDIT_SCHEMA as MEMORY_SCHEMA,
    CandidateRuntime,
    read_audit,
)
from .candidate_selector import BINDINGS, paired_selection, validate_profile
from .objective import canonical_sha

AUDIT_SCHEMA = "ndu.real.candidate-selector-audit.v1"
MAX_AUDIT_BYTES = 4 * 1024**2
EXPECTED = {
    "scope",
    "bindings",
    "profile",
    "profile_sha256",
    "step",
    "observation",
    "action",
    "memory_audit_sha256",
    "previous_audit_sha256",
}
FIELDS = EXPECTED | {
    "schema",
    "observation_processed",
    "receipt",
    "candidates",
    "features",
    "neural_logits",
    "scientific_acceptance",
}
COSTS = {"selection_cpu_seconds", "selection_wall_seconds"}


def _raw(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _read_direct(path):
    """Read one original regular inode; Linux admission forbids following links."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("selector audit must be a regular direct child")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("selector audit descriptor admission failed") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise ValueError("selector audit inode changed during admission")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_AUDIT_BYTES + 1)
        return raw
    finally:
        os.close(descriptor)


def _memory_matches(value, memory):
    if (
        not isinstance(memory, dict)
        or memory.get("schema") != MEMORY_SCHEMA
        or type(memory.get("observation_processed")) is not bool
        or any(
            memory.get(k) != value[k]
            for k in ("scope", "step", "observation", "action", "observation_processed")
        )
        or any(memory.get(k) != v for k, v in value["bindings"].items())
    ):
        raise ValueError("selector and original memory audit identity differ")
    receipt = value["receipt"]
    if not value["observation_processed"]:
        if (
            receipt is not None
            or value["candidates"]
            or value["features"]
            or value["neural_logits"]
            or value["action"]["action"] != "STOP"
            or memory.get("offered_candidates")
            or memory.get("selected_index") is not None
        ):
            raise ValueError("unprocessed STOP claims selector evidence")
        return
    if value["candidates"] != memory.get("offered_candidates") or canonical_sha(
        value["features"]
    ) != memory.get("offered_features_sha256"):
        raise ValueError("selector uses a different original offered support")
    if (
        not isinstance(receipt, dict)
        or receipt.get("selected_index") != memory.get("selected_index")
        or type(memory.get("selected_index")) is not int
    ):
        raise ValueError("selector differs from actual memory selection")
    rebuilt = paired_selection(
        mode=value["profile"]["mode"],
        field=receipt.get("field"),
        scope=CandidateScope(**value["scope"]),
        candidates=value["candidates"],
        features=value["features"],
        neural_logits=value["neural_logits"],
        bindings=value["bindings"],
    )
    if set(receipt) != set(rebuilt) or any(
        receipt[k] != v for k, v in rebuilt.items() if k not in COSTS
    ):
        raise ValueError("paired selector receipt cannot be reconstructed")
    if any(
        type(receipt[k]) not in (int, float)
        or not math.isfinite(receipt[k])
        or receipt[k] < 0
        for k in COSTS
    ):
        raise ValueError("selector costs must be finite nonnegative observations")


class SelectorRuntime:
    def __init__(self, profile, memory_runtime):
        self.profile = validate_profile(profile)
        if type(memory_runtime) is not CandidateRuntime:
            raise ValueError("original candidate memory runtime required")
        self.memory = memory_runtime
        self.scope, self.bindings = memory_runtime.scope, dict(memory_runtime.bindings)
        self.profile_sha256 = canonical_sha(self.profile)
        self._pending, self._last_step, self._previous = None, -1, None

    def select(self, step, field, candidates, features, logits):
        if (
            type(step) is not int
            or not 0 <= step < 8
            or step != self._last_step + 1
            or self._pending is not None
        ):
            raise ValueError("selection must follow its original ordered observation")
        candidates, features, logits = copy.deepcopy((candidates, features, logits))
        receipt = paired_selection(
            mode=self.profile["mode"],
            field=field,
            scope=self.scope,
            candidates=candidates,
            features=features,
            neural_logits=logits,
            bindings=self.bindings,
        )
        self._pending = {
            "step": step,
            "observation_processed": True,
            "receipt": receipt,
            "candidates": candidates,
            "features": features,
            "neural_logits": logits,
        }
        return receipt["selected_index"]

    def record(self, directory, state, action, memory_binding):
        step = state["step"]
        if type(step) is not int or not 0 <= step < 8 or step != self._last_step + 1:
            raise ValueError("selector audit step must advance within the episode")
        memory = read_audit(
            directory,
            memory_binding,
            {
                "scope": asdict(self.scope),
                **self.bindings,
                "step": step,
                "observation": state["observation"],
                "action": action,
                "profile": self.memory.profile,
                "profile_sha256": self.memory.profile_sha256,
            },
        )
        observation = self._pending or {
            "step": step,
            "observation_processed": False,
            "receipt": None,
            "candidates": [],
            "features": [],
            "neural_logits": [],
        }
        if observation["step"] != step:
            raise ValueError("pending selector belongs to a different step")
        value = {
            "schema": AUDIT_SCHEMA,
            "scope": asdict(self.scope),
            "bindings": self.bindings,
            "profile": self.profile,
            "profile_sha256": self.profile_sha256,
            **observation,
            "observation": state["observation"],
            "action": action,
            "memory_audit_sha256": memory_binding["sha256"],
            "previous_audit_sha256": self._previous,
            "scientific_acceptance": "HOLD",
        }
        _memory_matches(value, memory)
        raw = _raw(value)
        if len(raw) > MAX_AUDIT_BYTES:
            raise ValueError("selector audit exceeds independent byte bound")
        path = Path(directory) / f"selector-audit-{step:02d}.json"
        with path.open("xb") as stream:
            stream.write(raw)
        digest = hashlib.sha256(raw).hexdigest()
        self._last_step, self._previous, self._pending = step, digest, None
        return {"path": path.name, "sha256": digest, "bytes": len(raw)}


def read_selector_audit(directory, binding, expected, memory_audit):
    """Require complete host identity, original memory support and recomputed choices."""
    if (
        not isinstance(expected, dict)
        or not EXPECTED <= set(expected) <= FIELDS
        or type(expected["step"]) is not int
        or not 0 <= expected["step"] < 8
    ):
        raise ValueError("complete original host-owned selector identity required")
    if (
        not isinstance(binding, dict)
        or set(binding) != {"path", "sha256", "bytes"}
        or binding["path"] != f"selector-audit-{expected['step']:02d}.json"
        or type(binding["bytes"]) is not int
        or not 1 <= binding["bytes"] <= MAX_AUDIT_BYTES
    ):
        raise ValueError("bounded direct-child selector audit binding required")
    path = Path(directory) / binding["path"]
    raw = _read_direct(path)
    if (
        len(raw) != binding["bytes"]
        or hashlib.sha256(raw).hexdigest() != binding["sha256"]
    ):
        raise ValueError("selector audit bytes differ from original binding")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != FIELDS
        or raw != _raw(value)
        or value["schema"] != AUDIT_SCHEMA
        or value["scientific_acceptance"] != "HOLD"
        or type(value["observation_processed"]) is not bool
        or any(value.get(k) != v for k, v in expected.items())
    ):
        raise ValueError("selector audit differs from original host identity")
    validate_profile(value["profile"])
    CandidateScope(**value["scope"])
    if (
        not isinstance(value["bindings"], dict)
        or set(value["bindings"]) != BINDINGS
        or any(
            not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
            for v in value["bindings"].values()
        )
        or (
            value["previous_audit_sha256"] is not None
            and (
                not isinstance(value["previous_audit_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", value["previous_audit_sha256"]) is None
            )
        )
    ):
        raise ValueError("selector original scope, bindings or chain digest differs")
    if value["profile_sha256"] != canonical_sha(value["profile"]) or any(
        not isinstance(value[k], str) or re.fullmatch(r"[0-9a-f]{64}", value[k]) is None
        for k in ("memory_audit_sha256", "profile_sha256")
    ):
        raise ValueError("selector profile or original memory digest differs")
    _memory_matches(value, memory_audit)
    return value
