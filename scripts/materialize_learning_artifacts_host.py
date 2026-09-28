#!/usr/bin/env python3
"""One-shot exact-source finalizer for the learning.artifacts host.

The script is intentionally narrow and fails when its reviewed source identities
or any replacement context drift. The workflow removes this file and itself
before committing the materialized source.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLICATION = ROOT / "codex-rs/hepta-learning-artifacts/src/owner/publication_coordination.rs"
OBSERVABILITY = ROOT / "codex-rs/hepta-learning-artifacts/src/observability.rs"


def git_blob(path: Path) -> str:
    return subprocess.check_output(
        ["git", "hash-object", str(path.relative_to(ROOT))],
        cwd=ROOT,
        text=True,
    ).strip()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_publication() -> None:
    expected = "4a4b5bb2fccb3309afe2477259f94f270f2dc949"
    actual = git_blob(PUBLICATION)
    if actual != expected:
        raise SystemExit(f"publication source drift: expected {expected}, got {actual}")
    text = PUBLICATION.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """        let phase = if service.recovery_required().is_some() {
            ArtifactOwnerRuntimePhaseV1::Recovering
        } else {
            ArtifactOwnerRuntimePhaseV1::Ready
        };
""",
        """        let phase = if service.durable_drain_requested() {
            ArtifactOwnerRuntimePhaseV1::Draining
        } else if service.recovery_required().is_some() {
            ArtifactOwnerRuntimePhaseV1::Recovering
        } else {
            ArtifactOwnerRuntimePhaseV1::Ready
        };
""",
        "startup phase",
    )
    text = replace_once(
        text,
        "error_response(error.code(), &error.to_string()).into_bytes(),",
        "error_response(error.operational_code(), &error.to_string()).into_bytes(),",
        "stable persisted error",
    )
    text = replace_once(
        text,
        """    pub fn mark_stopped(&self, now: u64) -> Result<(), ArtifactOwnerCommandError> {
        *self
            .phase
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
            ArtifactOwnerRuntimePhaseV1::Stopped;
        self.persist_status(now, "listener stopped and writer fence is being released")
    }
""",
        """    pub fn mark_stopped(&self, now: u64) -> Result<(), ArtifactOwnerCommandError> {
        {
            let service = self
                .service
                .lock()
                .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
            if !service.is_drained() {
                return Err(ArtifactOwnerCommandError::InvalidState);
            }
        }
        *self
            .phase
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
            ArtifactOwnerRuntimePhaseV1::Stopped;
        self.persist_status(now, "listener stopped after durable owner drain")
    }
""",
        "stopped transition",
    )
    text = replace_once(
        text,
        """            ArtifactOwnerActionV1::Shutdown => {
                require_empty_payload(&request.payload)?;
                *self
                    .phase
                    .lock()
                    .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
                    ArtifactOwnerRuntimePhaseV1::Draining;
                self.shutdown_requested.store(true, Ordering::Release);
                self.persist_status(now, "authenticated graceful shutdown requested")?;
""",
        """            ArtifactOwnerActionV1::Shutdown => {
                require_empty_payload(&request.payload)?;
                self.service
                    .lock()
                    .map_err(|_| ArtifactOwnerCommandError::Poisoned)?
                    .begin_drain_durable()?;
                *self
                    .phase
                    .lock()
                    .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
                    ArtifactOwnerRuntimePhaseV1::Draining;
                self.shutdown_requested.store(true, Ordering::Release);
                self.persist_status(now, "authenticated durable shutdown requested")?;
""",
        "durable shutdown",
    )
    text = replace_once(
        text,
        "pub const fn code(&self) -> &'static str {",
        "pub fn code(&self) -> &'static str {",
        "non-const stable code",
    )
    text = replace_once(
        text,
        '            Self::Service(_) => "owner_service",',
        "            Self::Service(error) => error.stable_code(),",
        "service error class",
    )
    PUBLICATION.write_text(text, encoding="utf-8")


def patch_observability() -> None:
    expected = "5eb202dbef475269abacb84058da7b51b5d3b6c5"
    actual = git_blob(OBSERVABILITY)
    if actual != expected:
        raise SystemExit(f"observability source drift: expected {expected}, got {actual}")
    text = OBSERVABILITY.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "let micros = elapsed.as_micros().min(u128::from(u64::MAX)) as u64;",
        "let micros = u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX);",
        "checked duration conversion",
    )
    text = replace_once(
        text,
        """        let target = samples
            .saturating_mul(percent)
            .saturating_add(99)
            .checked_div(100)
            .unwrap_or(samples)
            .max(1);
""",
        """        let target = samples.saturating_mul(percent).div_ceil(100).max(1);
""",
        "percentile target",
    )
    text = replace_once(
        text,
        "checked_add(&self.pending_erasure_bytes, bytes).map(|_| ())",
        """checked_add(&self.pending_erasure_bytes, bytes)?;
        Ok(())""",
        "erasure reservation",
    )
    text = replace_once(
        text,
        """        let lease = metrics.track_pinned_bytes(128).expect("pin");
        metrics.reserve_erasure_bytes(64).expect("reserve erasure");
""",
        """        let lease = match metrics.track_pinned_bytes(128) {
            Ok(lease) => lease,
            Err(error) => panic!("pin accounting failed: {error:?}"),
        };
        assert_eq!(metrics.reserve_erasure_bytes(64), Ok(()));
""",
        "test setup accounting",
    )
    text = replace_once(
        text,
        """        lease.release().expect("release pin");
        metrics.complete_erasure_bytes(64).expect("complete erasure");
""",
        """        assert_eq!(lease.release(), Ok(()));
        assert_eq!(metrics.complete_erasure_bytes(64), Ok(()));
""",
        "test completion accounting",
    )
    OBSERVABILITY.write_text(text, encoding="utf-8")


def main() -> None:
    patch_publication()
    patch_observability()


if __name__ == "__main__":
    main()
