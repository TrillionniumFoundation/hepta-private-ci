#!/usr/bin/env python3
"""Keep recovery tests independent from sibling inline-test helpers."""

from pathlib import Path

path = (
    Path(__file__).resolve().parents[1]
    / "codex-rs/hepta-agentd/src/exact_context_delivery/registry_race_tests.rs"
)
text = path.read_text(encoding="utf-8")
old = '''    state.pre_sends.insert(
        "legacy-attempt".to_owned(),
        stored_pre_send("legacy-thread", "legacy-turn", "legacy-attempt"),
    );
'''
new = '''    state.pre_sends.insert(
        "legacy-attempt".to_owned(),
        StoredPreSend {
            thread_id: "legacy-thread".to_owned(),
            turn_id: "legacy-turn".to_owned(),
            attempt_id: "legacy-attempt".to_owned(),
            provider_intent_digest: [1; 32],
            authority_snapshot_digest: [2; 32],
            preparation_binding_digest: [3; 32],
            preparation_digest: [4; 32],
            final_request_proof_digest: [5; 32],
            provider_request_digest: [6; 32],
            provider_wire_semantic_digest: [7; 32],
            tokenizer_identity_digest: [8; 32],
            tokenization_receipt_digest: [9; 32],
            token_count: 11,
            segment_map_digest: [10; 32],
            recorded_unix_ms: 12,
            recovery_binding_digest: [0; 32],
            recovery_archive: None,
        },
    );
'''
if text.count(old) != 1:
    raise SystemExit("legacy recovery fixture anchor drifted")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
