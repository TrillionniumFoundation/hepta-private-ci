#!/usr/bin/env python3
"""Idempotent corrections for generated quarantine/cleanup storage code."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str, marker: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old in text:
        text = text.replace(old, new, 1)
    elif marker not in text:
        raise RuntimeError(f"{path}: missing {marker}")
    target.write_text(text, encoding="utf-8")


def replace_all(path: str, old: str, new: str, marker: str) -> None:
    """Replace every legacy occurrence while remaining safe to rerun.

    The terminal-outbox migration embeds both an input and output Rust block.
    Earlier nonce hardening changed the live source before that migration runs,
    so both embedded blocks must advance together or the migration ceases to be
    idempotent and the materializer cannot reach ordinary source publication.
    """

    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old in text:
        text = text.replace(old, new)
    elif marker not in text:
        raise RuntimeError(f"{path}: missing {marker}")
    target.write_text(text, encoding="utf-8")


def main() -> None:
    # The maintainer follow-up executes before terminal-outbox and replaces the
    # live-process nonce initializer. Keep the later migration's embedded
    # legacy/output blocks synchronized with that hardened source spelling.
    replace_all(
        "scripts/runtime-codex-terminal-outbox-migration.py",
        '''        let mut abort_nonce = [0_u8; 32];
        rand::rng().fill_bytes(&mut abort_nonce);
''',
        '''        // Generated for each live process; never a source-embedded cryptographic value.
        let abort_nonce: [u8; 32] = rand::random();
''',
        "let abort_nonce: [u8; 32] = rand::random();",
    )
    replace(
        "codex-rs/hepta-infer-worker-host/src/native_execution.rs",
        '''        let cleanup_store = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "durable cleanup store open",
            crate::native_cleanup_store::NativeCleanupStore::open(
                &cleanup_root.join("runtime-codex-cleanup-v1.sqlite3"),
                self.config.agent_id.to_string(),
                self.config.generation,
            ),
        )
''',
        '''        let cleanup_store_path = cleanup_root.join("runtime-codex-cleanup-v1.sqlite3");
        let cleanup_store = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "durable cleanup store open",
            crate::native_cleanup_store::NativeCleanupStore::open(
                &cleanup_store_path,
                self.config.agent_id.to_string(),
                self.config.generation,
            ),
        )
''',
        "let cleanup_store_path =",
    )
    replace(
        "codex-rs/hepta-infer-worker-host/src/native_execution.rs",
        '''        model_id: output.model.clone(),
        provider_id: output.model_provider.clone(),
''',
        '''        model_id: format!("model:{}", Digest32::of_bytes(output.model.as_bytes())),
        provider_id: format!(
            "provider:{}",
            Digest32::of_bytes(output.model_provider.as_bytes())
        ),
''',
        'model_id: format!("model:{}"',
    )
    replace(
        "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs",
        '''        resolution.resolution_id = "resolution:replay".to_string();
        assert!(store
            .verify_and_commit_resolution(
                resolution.signer_id.clone(),
                key.verifying_key().to_bytes(),
                &signed,
                2_000,
            )
            .await
            .is_err());
''',
        '''        assert!(store
            .verify_and_commit_resolution(
                resolution.signer_id.clone(),
                key.verifying_key().to_bytes(),
                &signed,
                2_000,
            )
            .await
            .is_err());
''',
        "verify_and_commit_resolution(\n                resolution.signer_id.clone()",
    )


if __name__ == "__main__":
    main()
