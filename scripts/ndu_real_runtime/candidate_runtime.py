"""Opt-in candidate retention for the existing, frozen receipt actor.

Both experimental arms use the same admission limits. Only ``bounded`` keeps
earlier public observations. Digests are scope/evidence bindings, never model
features. The sidecar records actual offered inputs without receiving labels.
"""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from .candidate_memory import CandidateMemory, CandidateMemoryError, CandidateScope
from .objective import canonical_sha

PROFILE_SCHEMA = "ndu.real.candidate-memory-profile.v1"
AUDIT_SCHEMA = "ndu.real.candidate-audit.v1"
MAX_AUDIT_BYTES = 4 * 1024**2
IDENTITIES = {
    "weights_sha256",
    "parameters_sha256",
    "control_profile_sha256",
    "public_case_sha256",
}


def validate_profile(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "mode", "max_entries", "max_serialized_bytes"}
        or value["schema"] != PROFILE_SCHEMA
        or value["mode"] not in {"current_only", "bounded"}
    ):
        raise ValueError("Explicit bounded candidate-memory profile required")
    CandidateMemory(
        max_entries=value["max_entries"],
        max_serialized_bytes=value["max_serialized_bytes"],
    )
    return dict(value)


def validate_activation(*, start_step, checkpoint_requested, training_exploration):
    if start_step != 0 or checkpoint_requested or training_exploration:
        raise ValueError(
            "Candidate retention requires a fresh frozen actor; training and "
            "checkpoints without the complete candidate pool are unsupported"
        )


class CandidateRuntime:
    def __init__(self, profile, scope, bindings):
        self.profile = validate_profile(profile)
        if not isinstance(scope, CandidateScope):
            raise ValueError("Explicit immutable source scope required")
        if set(bindings) != IDENTITIES or any(
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in bindings.values()
        ):
            raise ValueError("Complete model, control and public-case pins required")
        self.scope, self.bindings = scope, dict(bindings)
        self.profile_sha256 = canonical_sha(self.profile)
        self._pool = CandidateMemory(
            max_entries=self.profile["max_entries"],
            max_serialized_bytes=self.profile["max_serialized_bytes"],
        )
        self._pending, self._last_step, self._previous = None, -1, None

    def offer(self, step, candidates, features):
        if type(step) is not int or step != self._last_step + 1 or self._pending:
            raise ValueError("Each observation needs its original ordered audit")
        if self.profile["mode"] == "current_only":
            self._pool = CandidateMemory(
                max_entries=self.profile["max_entries"],
                max_serialized_bytes=self.profile["max_serialized_bytes"],
            )
        decision = self._pool.observe(self.scope, step, candidates, features)
        if not decision.records:
            raise CandidateMemoryError(
                "Candidate budget admitted no model input", decision.receipt
            )
        offered = [
            {"text": row.text, "bbox": list(row.bbox), "origin": row.origin}
            for row in decision.records
        ]
        vectors = [list(row.features) for row in decision.records]
        self._pending = {
            "step": step,
            "observation_processed": True,
            "raw_candidates": copy.deepcopy(candidates),
            "raw_features_sha256": canonical_sha(features),
            "offered_candidates": copy.deepcopy(offered),
            "offered_features_sha256": canonical_sha(vectors),
            "offered_observed_steps": [row.observed_step for row in decision.records],
            "memory_receipt": asdict(decision.receipt),
        }
        return offered, vectors

    def record(self, directory, state, action, selected_index=None):
        step = state["step"]
        if type(step) is not int or step != self._last_step + 1 or not 0 <= step < 8:
            raise ValueError("Candidate audit step must advance within the episode")
        if self._pending is None:
            if selected_index is not None or action["action"] != "STOP":
                raise ValueError(
                    "An unprocessed observation permits only no-selection STOP"
                )
            observation = {
                "step": step,
                "observation_processed": False,
                "raw_candidates": [],
                "raw_features_sha256": None,
                "offered_candidates": [],
                "offered_features_sha256": None,
                "offered_observed_steps": [],
                "memory_receipt": None,
            }
        else:
            observation = self._pending
            offered = observation["offered_candidates"]
            if (
                observation["step"] != step
                or type(selected_index) is not int
                or not 0 <= selected_index < len(offered)
            ):
                raise ValueError(
                    "Selection is not an index in the actual offered roster"
                )
            if (
                action["action"] == "WRITE_TEXT"
                and action["arguments"].get("text") != offered[selected_index]["text"]
            ):
                raise ValueError(
                    "Text action differs from the actor's selected candidate"
                )
        audit = {
            "schema": AUDIT_SCHEMA,
            "scope": asdict(self.scope),
            "profile": self.profile,
            "profile_sha256": self.profile_sha256,
            **self.bindings,
            **observation,
            "observation": state["observation"],
            "selected_index": selected_index,
            "action": action,
            "previous_audit_sha256": self._previous,
            "scientific_admission": "HOLD",
        }
        raw = (
            json.dumps(
                audit,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode()
        if len(raw) > MAX_AUDIT_BYTES:
            raise ValueError("Candidate audit exceeds its independent byte bound")
        path = Path(directory) / f"candidate-audit-{step:02d}.json"
        with path.open("xb") as stream:
            stream.write(raw)
        digest = hashlib.sha256(raw).hexdigest()
        self._last_step, self._previous, self._pending = step, digest, None
        return {"path": path.name, "sha256": digest, "bytes": len(raw)}


def read_audit(directory, binding, expected):
    """Read one bounded exact sidecar and compare host-owned binding fields."""
    if (
        not isinstance(binding, dict)
        or set(binding) != {"path", "sha256", "bytes"}
        or binding["path"] != f"candidate-audit-{expected['step']:02d}.json"
        or type(binding["bytes"]) is not int
        or not 1 <= binding["bytes"] <= MAX_AUDIT_BYTES
    ):
        raise ValueError("Invalid candidate audit binding")
    path = Path(directory) / binding["path"]
    if path.is_symlink() or not path.is_file():
        raise ValueError("Candidate audit must be a regular direct child")
    with path.open("rb") as stream:
        raw = stream.read(MAX_AUDIT_BYTES + 1)
    if (
        len(raw) != binding["bytes"]
        or hashlib.sha256(raw).hexdigest() != binding["sha256"]
    ):
        raise ValueError("Candidate audit bytes differ from the original receipt")
    value = json.loads(raw)
    canonical = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    if (
        raw != canonical
        or value.get("schema") != AUDIT_SCHEMA
        or value.get("scientific_admission") != "HOLD"
        or any(value.get(key) != item for key, item in expected.items())
    ):
        raise ValueError(
            "Candidate audit differs from the host's original action or scope"
        )
    return value
