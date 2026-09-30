#!/usr/bin/env python3
"""Corrected wrapper for independent quarantine-resolution authority epochs.

The original migration intentionally uses exact textual assertions. Two wire
structs shared the same adjacent `authority_epoch/resolution_sequence` fields,
so this wrapper first performs the two structurally qualified replacements and
then delegates every remaining transformation to the reviewed migration.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "scripts/runtime-codex-quarantine-authority-fixup.py"


def load_original():
    spec = importlib.util.spec_from_file_location(
        "runtime_codex_quarantine_authority_fixup",
        ORIGINAL,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load quarantine authority migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qualified_protocol(text: str, original) -> str:
    resolution_old = '''pub struct QuarantineResolutionV1 {
    pub schema_version: u32,
    pub signer_id: String,
    pub resolution_id: String,
    pub operation_id: String,
    pub quarantine_revision: u64,
    pub quarantine_record_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub dispatch_sha256: [u8; 32],
    pub evidence_set_sha256: [u8; 32],
    pub authority_epoch: u64,
    pub resolution_sequence: u64,
'''
    resolution_new = '''pub struct QuarantineResolutionV1 {
    pub schema_version: u32,
    pub signer_id: String,
    pub resolution_id: String,
    pub operation_id: String,
    pub quarantine_revision: u64,
    pub quarantine_record_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub dispatch_sha256: [u8; 32],
    pub evidence_set_sha256: [u8; 32],
    /// Original final-use/effect authority epoch bound by quarantine.
    pub authority_epoch: u64,
    /// Independent resolution authority epoch; never inferred from the effect epoch.
    pub resolution_authority_epoch: u64,
    /// Monotonic key epoch inside the independent resolution authority.
    pub resolution_key_epoch: u64,
    pub resolution_sequence: u64,
'''
    if resolution_old in text:
        if text.count(resolution_old) != 1:
            raise RuntimeError("resolution authority: ambiguous resolution record")
        text = text.replace(resolution_old, resolution_new, 1)
    elif "pub resolution_authority_epoch: u64" not in text:
        raise RuntimeError("resolution authority: resolution record anchor absent")

    frontier_old = '''pub struct QuarantineResolutionFrontierV1 {
    pub authority_epoch: u64,
    pub resolution_sequence: u64,
'''
    frontier_new = '''pub struct QuarantineResolutionFrontierV1 {
    pub authority_epoch: u64,
    pub key_epoch: u64,
    pub resolution_sequence: u64,
'''
    if frontier_old in text:
        if text.count(frontier_old) != 1:
            raise RuntimeError("resolution authority: ambiguous frontier record")
        text = text.replace(frontier_old, frontier_new, 1)
    elif "pub key_epoch: u64" not in text:
        raise RuntimeError("resolution authority: frontier record anchor absent")

    # Both generic legacy field pairs are now absent, so the original exact
    # migration safely treats these steps as already applied and performs the
    # remaining verifier, SQLite, frontier and negative-test changes.
    return original.protocol(text)


def main() -> None:
    original = load_original()
    path = ROOT / "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs"
    text = path.read_text(encoding="utf-8")
    text = qualified_protocol(text, original)
    text = original.durable_store(text)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
