"""Research-only FastCell ActionIR boundary.

This module deliberately stops before compilation or external effects. A Cell can
produce a typed, bounded proposal; the host can validate and receipt it. Native
bytes, pointers, credentials, syscalls, and device launch parameters are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping


class FastCellRejected(ValueError):
    pass


ALLOWED_OPS = frozenset(
    {
        "ui.focus",
        "ui.click",
        "ui.type",
        "fs.read_bounded",
        "http.request_bounded",
    }
)
FORBIDDEN_KEYS = frozenset(
    {
        "native_bytes",
        "raw_pointer",
        "syscall",
        "credential",
        "gpu_launch",
        "arbitrary_path",
    }
)
MAX_ARGUMENT_BYTES = 4096
MAX_SCOPE_ITEMS = 16


@dataclass(frozen=True)
class ActionIR:
    operation: str
    arguments: Mapping[str, Any]
    capability_scope: tuple[str, ...]
    expected_output_schema: str
    generation: str
    authority: str = "DENY_ALL"

    def canonical(self) -> bytes:
        payload = {
            "schema": "hepta.fastcell.action-ir.v1",
            "operation": self.operation,
            "arguments": self.arguments,
            "capability_scope": list(self.capability_scope),
            "expected_output_schema": self.expected_output_schema,
            "generation": self.generation,
            "authority": self.authority,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


def validate_action(action: ActionIR) -> dict[str, Any]:
    if action.authority != "DENY_ALL":
        raise FastCellRejected("research FastCell authority must remain DENY_ALL")
    if action.operation not in ALLOWED_OPS:
        raise FastCellRejected("operation is not in the research allowlist")
    if not action.generation or len(action.generation) > 128:
        raise FastCellRejected("invalid generation")
    if not action.expected_output_schema or len(action.expected_output_schema) > 128:
        raise FastCellRejected("invalid output schema")
    if not action.capability_scope or len(action.capability_scope) > MAX_SCOPE_ITEMS:
        raise FastCellRejected("invalid capability scope")
    if any(not isinstance(item, str) or not item for item in action.capability_scope):
        raise FastCellRejected("capability scope must contain nonempty strings")
    unknown = FORBIDDEN_KEYS.intersection(action.arguments)
    if unknown:
        raise FastCellRejected("raw execution material is forbidden: " + sorted(unknown)[0])
    encoded = json.dumps(action.arguments, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise FastCellRejected("arguments exceed the bounded research envelope")
    return {
        "schema": "hepta.fastcell.validation-receipt.v1",
        "action_digest": action.digest(),
        "operation": action.operation,
        "generation": action.generation,
        "capability_scope": list(action.capability_scope),
        "compilation_permitted": False,
        "external_effect_permitted": False,
        "authority": "DENY_ALL",
    }


def propose_action(
    operation: str,
    arguments: Mapping[str, Any],
    capability_scope: tuple[str, ...],
    expected_output_schema: str,
    generation: str,
) -> dict[str, Any]:
    return validate_action(
        ActionIR(
            operation=operation,
            arguments=arguments,
            capability_scope=capability_scope,
            expected_output_schema=expected_output_schema,
            generation=generation,
        )
    )
