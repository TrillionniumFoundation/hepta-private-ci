#!/usr/bin/env python3
"""Apply the inference.control production-convergence source patch.

The script is idempotent and fails closed when the pinned base shape is absent.
The companion payload contains only new Rust source and test files.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import tarfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = Path(__file__).with_name("inference-control-convergence.payload.b64")
PAYLOAD_SHA256 = "c260aff563053d596979858312d433a3b7c45ee5e53b87ce660e758b51acb64a"


def fail(message: str) -> None:
    raise SystemExit(message)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly one base fragment, found {count}")
    return text.replace(old, new, 1)


def patch_file(relative: str, transform: Callable[[str], str]) -> None:
    path = ROOT / relative
    original = path.read_text()
    updated = transform(original)
    if updated != original:
        path.write_text(updated)


def add_serde_derive(text: str, declaration: str) -> str:
    pattern = re.compile(r"#\[derive\(([^)]*)\)\]\n(" + re.escape(declaration) + r")")
    match = pattern.search(text)
    if not match:
        fail(f"missing derive for {declaration}")
    derives = [item.strip() for item in match.group(1).split(",")]
    for item in ("Deserialize", "Serialize"):
        if item not in derives:
            derives.append(item)
    replacement = "#[derive(" + ", ".join(derives) + ")]\n" + match.group(2)
    return text[: match.start()] + replacement + text[match.end() :]


def extract_payload() -> None:
    compressed = base64.b64decode(PAYLOAD.read_text())
    actual = hashlib.sha256(compressed).hexdigest()
    if actual != PAYLOAD_SHA256:
        fail(f"payload digest mismatch: {actual}")
    root = ROOT.resolve()
    with tarfile.open(fileobj=io.BytesIO(compressed), mode="r:gz") as archive:
        for member in archive.getmembers():
            target = (ROOT / member.name).resolve()
            if root not in target.parents and target != root:
                fail(f"unsafe payload member: {member.name}")
        archive.extractall(ROOT, filter="data")


def patch_workspace_manifest(text: str) -> str:
    if 'aes-gcm = "0.10.3"' not in text:
        text = replace_once(
            text,
            '# External\nage = "0.11.1"',
            '# External\naes-gcm = "0.10.3"\nage = "0.11.1"',
            "workspace aes-gcm dependency",
        )
    return text


def patch_core_manifest(text: str) -> str:
    for line in (
        'aes-gcm = { workspace = true }',
        'ed25519-dalek = { workspace = true }',
        'sha2 = { workspace = true }',
    ):
        if line not in text:
            text = replace_once(
                text,
                "[dependencies]\n",
                f"[dependencies]\n{line}\n",
                f"core dependency {line}",
            )
    return text


def patch_lib(text: str) -> str:
    marker = "pub mod durable_control;\n"
    addition = (
        "pub mod control_actor;\n"
        "pub mod operations;\n"
        "pub mod output_store;\n"
        "pub mod production_contracts;\n"
    )
    if addition not in text:
        text = replace_once(text, marker, marker + addition, "core module exports")
    return text


def patch_durable(text: str) -> str:
    if "use std::collections::BTreeSet;" not in text:
        text = replace_once(text, "use std::collections::BTreeMap;\n", "use std::collections::BTreeMap;\nuse std::collections::BTreeSet;\n", "durable BTreeSet import")
    if "use serde::Deserialize;" not in text:
        text = replace_once(text, "use std::path::PathBuf;\n", "use std::path::PathBuf;\n\nuse serde::Deserialize;\nuse serde::Serialize;\n", "durable serde imports")
    if '#[path = "durable_lifecycle.rs"]' not in text:
        text = replace_once(text, '#[path = "native_control.rs"]\npub mod native;\n', '#[path = "native_control.rs"]\npub mod native;\n#[path = "durable_lifecycle.rs"]\nmod lifecycle;\npub use lifecycle::CompactionReceiptV1;\npub use lifecycle::JournalHealthV1;\n', "durable lifecycle module")
    for declaration in ("pub enum RequestState {", "pub struct InferenceRequest {", "pub struct Reservation {", "pub struct Assignment {", "pub struct TerminalObservation {", "pub struct RequestRecord {"):
        text = add_serde_derive(text, declaration)
    if "InvalidSignature," not in text:
        text = replace_once(text, "    WriterUnavailable,\n", "    WriterUnavailable,\n    InvalidSignature,\n    InjectedFailure(&'static str),\n", "durable production errors")
    if "_owner_lock: File," not in text:
        text = replace_once(text, "pub struct DurableInferenceControl {\n    path: PathBuf,\n", "pub struct DurableInferenceControl {\n    path: PathBuf,\n    _owner_lock: File,\n    checkpoint_generation: u64,\n    archive_head_sha256: Option<String>,\n    retired_request_digests: BTreeSet<String>,\n", "durable lifecycle fields")
    if "let owner_lock = lifecycle::open_stable_lock(&path)?;" not in text:
        text = replace_once(text, "        if let Some(parent) = path.parent() {\n            fs::create_dir_all(parent)?;\n        }\n", "        if let Some(parent) = path.parent() {\n            fs::create_dir_all(parent)?;\n        }\n        let owner_lock = lifecycle::open_stable_lock(&path)?;\n        lifecycle::recover_incomplete_compaction(&path)?;\n", "durable stable owner lock")
    if "let mut checkpoint_generation = 0_u64;" not in text:
        text = replace_once(text, "        let mut records = BTreeMap::new();\n        let mut native = native::NativeJournal::default();\n", "        let mut records = BTreeMap::new();\n        let mut native = native::NativeJournal::default();\n        let mut checkpoint_generation = 0_u64;\n        let mut archive_head_sha256 = None;\n        let mut retired_request_digests = BTreeSet::new();\n        let mut seen_event = false;\n", "durable checkpoint replay state")
    old_replay = """            if let Some(json) = line.strip_prefix(native::JOURNAL_PREFIX) {
                native.replay(json)?;
            } else {
                apply_event(&mut records, &decode_event(line)?, /*replay*/ true)?;
            }
            if records.len() + native.records.len() > capacity
                || records.keys().any(|id| native.records.contains_key(id))
            {
                return Err(Error::CapacityExceeded);
            }
"""
    new_replay = """            if let Some(json) = line.strip_prefix(lifecycle::CHECKPOINT_PREFIX) {
                if seen_event {
                    return Err(Error::CorruptJournal("checkpoint ordering"));
                }
                let checkpoint = lifecycle::decode_checkpoint(json)?;
                lifecycle::install_checkpoint(checkpoint, &mut records, &mut native, &mut checkpoint_generation, &mut archive_head_sha256, &mut retired_request_digests);
            } else if let Some(json) = line.strip_prefix(native::JOURNAL_PREFIX) {
                native.replay(json)?;
            } else {
                apply_event(&mut records, &decode_event(line)?, /*replay*/ true)?;
            }
            seen_event = true;
            if lifecycle::active_record_count(&records, &native) > capacity
                || records.keys().any(|id| native.records.contains_key(id))
            {
                return Err(Error::CapacityExceeded);
            }
"""
    if new_replay not in text:
        text = replace_once(text, old_replay, new_replay, "durable checkpoint replay")
    if "lifecycle::verify_archive_head(&path, archive_head_sha256.as_deref())?;" not in text:
        text = replace_once(text, "        #[cfg(unix)]\n        {\n            let parent = path\n", "        lifecycle::verify_archive_head(&path, archive_head_sha256.as_deref())?;\n        #[cfg(unix)]\n        {\n            let parent = path\n", "durable archive verification")
    if "_owner_lock: owner_lock," not in text:
        text = replace_once(text, "        Ok(Self {\n            path,\n            file,\n            records,\n            native,\n", "        Ok(Self {\n            path,\n            _owner_lock: owner_lock,\n            checkpoint_generation,\n            archive_head_sha256,\n            retired_request_digests,\n            file,\n            records,\n            native,\n", "durable lifecycle initialization")
    if "self.contains_retired_request_id(&request.request_id)" not in text:
        text = replace_once(text, "        if self.native.records.contains_key(&request.request_id) {\n            return Err(Error::Conflict);\n        }\n        if self.records.len() + self.native.records.len() >= self.capacity {\n            return Err(Error::CapacityExceeded);\n        }\n", "        if self.native.records.contains_key(&request.request_id)\n            || self.contains_retired_request_id(&request.request_id)\n        {\n            return Err(Error::Conflict);\n        }\n        if self.records.len() + self.native.records.len() >= self.capacity {\n            self.compact_journal()?;\n        }\n        if self.active_record_count() >= self.capacity {\n            return Err(Error::CapacityExceeded);\n        }\n", "durable retired-id and active capacity")
    if "self.compact_if_necessary(encoded.len())?;" not in text:
        text = replace_once(text, "        if self.poisoned {\n            return Err(Error::WriterUnavailable);\n        }\n        let next_bytes = self\n", "        if self.poisoned {\n            return Err(Error::WriterUnavailable);\n        }\n        self.compact_if_necessary(encoded.len())?;\n        lifecycle::maybe_failpoint(\"before_append_write\")?;\n        let next_bytes = self\n", "durable append compaction")
    if 'lifecycle::maybe_failpoint("after_append_sync")' not in text:
        text = replace_once(text, "        self.journal_bytes = next_bytes;\n        Ok(())\n", "        if let Err(error) = lifecycle::maybe_failpoint(\"after_append_sync\") {\n            self.poisoned = true;\n            return Err(error);\n        }\n        self.journal_bytes = next_bytes;\n        Ok(())\n", "durable append failpoint")
    return text


def patch_native(text: str) -> str:
    if '#[path = "native_reconciliation.rs"]' not in text:
        text = replace_once(text, 'pub(super) const JOURNAL_PREFIX: &str = "native-v1|";\n', '#[path = "native_reconciliation.rs"]\nmod reconciliation;\n\npub(super) const JOURNAL_PREFIX: &str = "native-v1|";\n', "native reconciliation module")
    text = add_serde_derive(text, "pub(super) struct NativeJournal {")
    if "pub verified_settlement_receipt_sha256: Option<String>," not in text:
        text = replace_once(text, "    pub observation: Option<NativeRunOutput>,\n}\n", "    pub observation: Option<NativeRunOutput>,\n    #[serde(default)]\n    pub verified_settlement_receipt_sha256: Option<String>,\n    #[serde(default)]\n    pub verified_evidence_sequence: u64,\n    #[serde(default)]\n    pub retirement_receipt_sha256: Option<String>,\n}\n", "native evidence fields")
    if "VerifiedObserve {" not in text:
        text = replace_once(text, "    Observe {\n        request_id: String,\n        output: NativeRunOutput,\n    },\n}\n", "    Observe {\n        request_id: String,\n        output: NativeRunOutput,\n    },\n    VerifiedObserve {\n        request_id: String,\n        output: NativeRunOutput,\n        receipt_sha256: String,\n        evidence_sequence: u64,\n    },\n    RetireIndeterminate {\n        request_id: String,\n        receipt_sha256: String,\n    },\n}\n", "native verified event variants")
    if "self.contains_retired_request_id(&request.request_id)" not in text:
        text = replace_once(text, "        if self.records.len() + self.native.records.len() >= self.capacity {\n            return Err(Error::CapacityExceeded);\n        }\n        self.ensure_native_dispatch_space()?;\n", "        if self.contains_retired_request_id(&request.request_id) {\n            return Err(Error::Conflict);\n        }\n        if self.records.len() + self.native.records.len() >= self.capacity {\n            self.compact_journal()?;\n        }\n        if self.active_record_count() >= self.capacity {\n            return Err(Error::CapacityExceeded);\n        }\n        self.ensure_native_dispatch_space()?;\n", "native retired-id and active capacity")
    old_space = """    fn ensure_native_dispatch_space(&self) -> Result<(), Error> {
        // This exclusive owner serializes active calls. Leave room for bounded
        // dispatch/cancel metadata and the next maximal observed output before
        // admitting a new external execution. This is not an archival policy.
        if self.journal_bytes > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }
"""
    new_space = """    fn ensure_native_dispatch_space(&mut self) -> Result<(), Error> {
        self.compact_if_necessary(2 * super::MAX_JOURNAL_LINE_BYTES)?;
        if self.journal_bytes > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }
"""
    if new_space not in text:
        text = replace_once(text, old_space, new_space, "native dispatch compaction")
    if "verified_settlement_receipt_sha256: None," not in text:
        text = replace_once(text, "                    dispatch_rejection: None,\n                    observation: None,\n", "                    dispatch_rejection: None,\n                    observation: None,\n                    verified_settlement_receipt_sha256: None,\n                    verified_evidence_sequence: 0,\n                    retirement_receipt_sha256: None,\n", "native record initialization")
    old_ids = "            | Event::AbortBeforeEffect { request_id, .. }\n            | Event::Observe { request_id, .. } => request_id,\n"
    new_ids = "            | Event::AbortBeforeEffect { request_id, .. }\n            | Event::Observe { request_id, .. }\n            | Event::VerifiedObserve { request_id, .. }\n            | Event::RetireIndeterminate { request_id, .. } => request_id,\n"
    if new_ids not in text:
        text = replace_once(text, old_ids, new_ids, "native event identity")
    old_arm = """            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
"""
    new_arm = """            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
            Event::VerifiedObserve { output, receipt_sha256, evidence_sequence, .. } => {
                if record.dispatch_rejection.is_some() || evidence_sequence == 0 || evidence_sequence <= record.verified_evidence_sequence {
                    return Err(Error::InvalidTransition);
                }
                super::validate_digest(&receipt_sha256, "verified settlement receipt")?;
                apply_observation(record, output)?;
                record.verified_settlement_receipt_sha256 = Some(receipt_sha256);
                record.verified_evidence_sequence = evidence_sequence;
            }
            Event::RetireIndeterminate { receipt_sha256, .. } => {
                if record.state != NativeReservationState::Indeterminate {
                    return Err(Error::InvalidTransition);
                }
                super::validate_digest(&receipt_sha256, "indeterminate retirement receipt")?;
                record.retirement_receipt_sha256 = Some(receipt_sha256);
                record.state = NativeReservationState::Released;
            }
"""
    if new_arm not in text:
        text = replace_once(text, old_arm, new_arm, "native verified apply")
    return text


def main() -> None:
    extract_payload()
    patch_file("codex-rs/Cargo.toml", patch_workspace_manifest)
    patch_file("codex-rs/hepta-infer-core/Cargo.toml", patch_core_manifest)
    patch_file("codex-rs/hepta-infer-core/src/lib.rs", patch_lib)
    patch_file("codex-rs/hepta-infer-core/src/durable_control.rs", patch_durable)
    patch_file("codex-rs/hepta-infer-core/src/native_control.rs", patch_native)


if __name__ == "__main__":
    main()
