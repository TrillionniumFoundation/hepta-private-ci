#!/usr/bin/env python3
"""Closed-world inventory plus supplemental lexical guards; Rust enforces privacy.

Comments and strings are not code. A function's return type is not a struct
literal. Native compile-fail doctests remain mandatory and are not replaced by
this inventory checker.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/modules/auth.authbus/PUBLIC_API_INVENTORY.json"
AUTHBUS = ROOT / "codex-rs/hepta-authbus/src"
HOST_OPERATIONS = {
    "open", "bootstrap", "sync_checkpoint", "enroll_issuer", "rotate_issuer",
    "revoke_issuer", "retire_issuer_epoch", "observe_trusted_time_attestation",
    "message_issuer", "settlement_issuer", "create_policy", "replace_policy",
    "revoke_policy", "retire_policy", "authorize", "create_quota", "replace_quota",
    "reserve", "mark_dispatch_attempted", "mark_indeterminate", "cancel_reservation",
    "reconcile_expired_reservation", "sweep_expired_reservations", "settle",
    "compact_terminal_reservations", "quota_snapshot", "reservation",
    "operational_snapshot", "maintenance_tick",
}


def code_only(text: str) -> str:
    """Mask Rust comments and string/character literals, preserving line offsets."""
    chars = list(text)
    i = 0
    while i < len(text):
        end = i
        if text.startswith("//", i):
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
        elif text.startswith("/*", i):
            end, depth = i + 2, 1
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth += 1
                    end += 2
                elif text.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                raise ValueError("unterminated Rust block comment")
        else:
            raw = re.match(r'(?:br|cr|r)(#*)"', text[i:])
            if raw:
                terminator = '"' + raw.group(1)
                closing = text.find(terminator, i + len(raw.group(0)))
                if closing < 0:
                    raise ValueError("unterminated Rust raw string")
                end = closing + len(terminator)
            elif text[i] == '"':
                end = i + 1
                while end < len(text):
                    if text[end] == "\\":
                        end += 2
                    elif text[end] == '"':
                        end += 1
                        break
                    else:
                        end += 1
            elif text[i] == "'":
                char = re.match(r"'(?:\\(?:u\{[0-9A-Fa-f_]+\}|x[0-9A-Fa-f]{2}|.)|[^'\\\n])'", text[i:])
                if char:
                    end = i + len(char.group(0))
        if end > i:
            for offset in range(i, min(end, len(chars))):
                if chars[offset] != "\n":
                    chars[offset] = " "
            i = end
        else:
            i += 1
    return "".join(chars)


def has_struct_literal(text: str, name: str) -> bool:
    tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|::|->|[^\s]", code_only(text))
    for index, token in enumerate(tokens[:-1]):
        if token != name or tokens[index + 1] != "{":
            continue
        previous = index - 1
        while previous >= 1 and tokens[previous] == "::":
            previous -= 2
        if previous >= 0 and tokens[previous] in {"->", "impl", "struct", "enum", "trait", "union"}:
            continue
        return True
    return False


def rust_sources() -> list[Path]:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "codex-rs"], cwd=ROOT
    ).decode().split("\0")
    return [ROOT / name for name in sorted(tracked) if name.endswith(".rs")]


def verify_boundaries() -> list[str]:
    errors = []
    for path in rust_sources():
        text = path.read_text(encoding="utf-8")
        for name, allowed in [("IssuerRegistration", "signed.rs"),
                              ("SettlementIssuerRegistration", "settlement.rs")]:
            if path != AUTHBUS / allowed and has_struct_literal(text, name):
                errors.append(f"constructible {name}: {path.relative_to(ROOT)}")
        code = code_only(text)
        if re.search(r"\bcodex_hepta_authbus\s*::\s*AuthBusAuthorityStore\b", code) or re.search(
            r"\buse\s+codex_hepta_authbus\s*::[^;]*\bAuthBusAuthorityStore\b", code
        ):
            errors.append(f"external raw authority writer: {path.relative_to(ROOT)}")
    lib = (AUTHBUS / "lib.rs").read_text()
    if "pub(crate) use authority_store::AuthBusAuthorityStore;" not in lib:
        errors.append("raw authority writer is not crate-private")
    if re.search(r"(?m)^pub use authority_store::AuthBusAuthorityStore;", lib):
        errors.append("raw authority writer is publicly re-exported")
    for name, file in [("IssuerRegistration", "signed.rs"),
                       ("SettlementIssuerRegistration", "settlement.rs")]:
        text = code_only((AUTHBUS / file).read_text())
        match = re.search(rf"pub struct {name}\s*\{{(?P<body>.*?)\n\}}", text, re.S)
        if match is None:
            errors.append(f"missing sealed type {name}")
        elif re.search(r"(?m)^\s*pub(?:\([^)]*\))?\s+\w+\s*:", match.group("body")):
            errors.append(f"trusted fields are writable on {name}")
        if re.search(rf"impl\s+(?:std::ops::)?DerefMut\s+for\s+{name}\b", text):
            errors.append(f"mutable trusted view on {name}")
    discovered = set()
    for file in ("host.rs", "operations.rs"):
        discovered.update(re.findall(r"\bpub\s+async\s+fn\s+(\w+)\s*\(",
                                     code_only((AUTHBUS / file).read_text())))
    if HOST_OPERATIONS != discovered:
        errors.append(f"host operation drift: missing={sorted(HOST_OPERATIONS - discovered)}, "
                      f"unexpected={sorted(discovered - HOST_OPERATIONS)}")
    return errors


def inventory() -> dict[str, object]:
    lib = code_only((AUTHBUS / "lib.rs").read_text())
    return {
        "schema": "hepta.authbus.public-api-inventory.v2",
        "module": "auth.authbus",
        "writer": {"type": "AuthBusAuthorityStore", "visibility": "crate_private",
                   "publicMutationHost": "AuthBusAuthorityHost"},
        "sealedRegistrations": [
            {"type": "IssuerRegistration", "source": "codex-rs/hepta-authbus/src/signed.rs",
             "trustedFieldsPublic": False, "construction": ["durable_registry", "private_persisted_registry"]},
            {"type": "SettlementIssuerRegistration", "source": "codex-rs/hepta-authbus/src/settlement.rs",
             "trustedFieldsPublic": False, "construction": ["durable_registry"]},
        ],
        "rootExports": sorted(" ".join(item.split()) for item in re.findall(r"(?m)^pub use ([^;]+);", lib)),
        "hostOperations": sorted(HOST_OPERATIONS),
        "periodicOwner": "AuthBusAuthorityWorker",
        "nativePrivacyContract": "codex-rs/hepta-authbus/SEALED_API.md",
        "inventoryIsNotQualification": True,
        "activation": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    errors = verify_boundaries()
    if errors:
        raise SystemExit("closed-world inventory failed:\n" + "\n".join(errors))
    expected = json.dumps(inventory(), indent=2, sort_keys=True) + "\n"
    if args.write:
        INVENTORY.write_text(expected)
    elif not INVENTORY.exists() or INVENTORY.read_text() != expected:
        raise SystemExit("PUBLIC_API_INVENTORY.json is stale; run scripts/check-authbus-closed-world.py --write")


if __name__ == "__main__":
    main()
