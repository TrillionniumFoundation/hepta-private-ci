#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content)


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-supervisor/src/robrix_protocol.rs",
    '''            SupervisordPayload::MutationAccepted { .. }
            | SupervisordPayload::ReleaseSelection { .. }
            | SupervisordPayload::ProductionMutationStatus { .. } => {
''',
    '''            SupervisordPayload::Diagnostics(_)
            | SupervisordPayload::MutationAccepted { .. }
            | SupervisordPayload::ReleaseSelection { .. }
            | SupervisordPayload::ProductionMutationStatus { .. } => {
''',
)

replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    '''use crate::ProductionMutationState;
use crate::ProductionRecoveryDecision;
''',
    '''use crate::ProductionMutationState;
use crate::ProductionMutationStatus;
use crate::ProductionRecoveryDecision;
''',
)

replace_once(
    "codex-rs/hepta-supervisor/src/signed_intent.rs",
    '''    publish::publish_with_context("signed_intent", &temp, &final_path)?;
''',
    '''    crate::durable_publish::publish_with_context("signed_intent", &temp, &final_path)?;
''',
)

replace_once(
    "codex-rs/hepta-supervisor/src/recovery_diagnostics.rs",
    '''    if current.is_some_and(|release| {
        release != transaction.source_release && release != transaction.target_release
    }) || transaction.phase != ReleaseTransactionPhase::RecoveryRequired
''',
    '''    if current.is_some_and(|release| {
        release != transaction.source_release.as_str()
            && release != transaction.target_release.as_str()
    }) || transaction.phase != ReleaseTransactionPhase::RecoveryRequired
''',
)

print("runtime.supervisor compile fixups applied")
