#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1))


path = "codex-rs/hepta-agentd/src/exact_context_delivery.rs"

# A durable pre-send without a durable terminal is indeterminate after restart.
# Never recreate an in-memory active lease and silently resend it.
replace_once(
    path,
    "        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);\n"
    "        if let Some(existing) = state.staged.get(&key) {",
    "        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);\n"
    "        if state\n"
    "            .durable\n"
    "            .has_unresolved_for_turn(thread_id, turn_id)\n"
    "        {\n"
    "            return Err(ExactContextDeliveryError::RecoveryRequired);\n"
    "        }\n"
    "        if let Some(existing) = state.staged.get(&key) {",
)
replace_once(
    path,
    "        let compiled = {\n"
    "            let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);\n"
    "            state\n"
    "                .staged",
    "        let compiled = {\n"
    "            let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);\n"
    "            if state\n"
    "                .durable\n"
    "                .terminals\n"
    "                .contains_key(&request.attempt.attempt_id)\n"
    "            {\n"
    "                return Err(ExactContextDeliveryError::Conflict(\n"
    "                    \"terminal attempt cannot be dispatched again\",\n"
    "                ));\n"
    "            }\n"
    "            if state\n"
    "                .durable\n"
    "                .has_unresolved_attempt(&request.attempt.attempt_id)\n"
    "            {\n"
    "                return Err(ExactContextDeliveryError::RecoveryRequired);\n"
    "            }\n"
    "            state\n"
    "                .staged",
)

# Duplicate terminal callbacks are accepted only when the exact normalized
# runtime observation is byte-identical to the already durable terminal.
replace_once(
    path,
    "        let active = {\n"
    "            let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);\n"
    "            state\n"
    "                .active\n"
    "                .get(&terminal.attempt.attempt_id)\n"
    "                .cloned()\n"
    "                .ok_or(ExactContextDeliveryError::MissingActiveAttempt)?\n"
    "        };",
    "        let terminal_observation_digest = terminal_observation_digest(&terminal)?;\n"
    "        let active = {\n"
    "            let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);\n"
    "            if let Some(active) = state.active.get(&terminal.attempt.attempt_id) {\n"
    "                active.clone()\n"
    "            } else if let Some(existing) = state\n"
    "                .durable\n"
    "                .terminals\n"
    "                .get(&terminal.attempt.attempt_id)\n"
    "            {\n"
    "                return if existing.terminal_observation_digest\n"
    "                    == terminal_observation_digest.into_array()\n"
    "                {\n"
    "                    Ok(())\n"
    "                } else {\n"
    "                    Err(ExactContextDeliveryError::Conflict(\n"
    "                        \"duplicate terminal observation differs from durable receipt\",\n"
    "                    ))\n"
    "                };\n"
    "            } else if state\n"
    "                .durable\n"
    "                .has_unresolved_attempt(&terminal.attempt.attempt_id)\n"
    "            {\n"
    "                return Err(ExactContextDeliveryError::RecoveryRequired);\n"
    "            } else {\n"
    "                return Err(ExactContextDeliveryError::MissingActiveAttempt);\n"
    "            }\n"
    "        };",
)
replace_once(
    path,
    "        let stored = StoredTerminal::new(\n"
    "            &terminal.attempt.attempt_id,\n"
    "            &receipt,",
    "        let stored = StoredTerminal::new(\n"
    "            &terminal,\n"
    "            &receipt,",
)
replace_once(
    path,
    "            if let Some(existing_active) = state.active.get(&attempt_id) {\n"
    "                if existing_active.final_request_proof != active.final_request_proof\n"
    "                    || existing_active.intent != active.intent\n"
    "                {\n"
    "                    return Err(ExactContextDeliveryError::Conflict(\n"
    "                        \"attempt id already has different active evidence\",\n"
    "                    ));\n"
    "                }\n"
    "                return Ok(());\n"
    "            }\n"
    "        }",
    "            if let Some(existing_active) = state.active.get(&attempt_id) {\n"
    "                if existing_active.final_request_proof != active.final_request_proof\n"
    "                    || existing_active.intent != active.intent\n"
    "                {\n"
    "                    return Err(ExactContextDeliveryError::Conflict(\n"
    "                        \"attempt id already has different active evidence\",\n"
    "                    ));\n"
    "                }\n"
    "                return Ok(());\n"
    "            }\n"
    "            return if state.durable.terminals.contains_key(&attempt_id) {\n"
    "                Err(ExactContextDeliveryError::Conflict(\n"
    "                    \"terminal attempt cannot be re-armed\",\n"
    "                ))\n"
    "            } else {\n"
    "                Err(ExactContextDeliveryError::RecoveryRequired)\n"
    "            };\n"
    "        }",
)

# Durable state helpers make unresolved attempts explicit and auditable.
state_helpers = r'''

impl StoredExactDeliveryState {
    fn has_unresolved_attempt(&self, attempt_id: &str) -> bool {
        self.pre_sends.contains_key(attempt_id) && !self.terminals.contains_key(attempt_id)
    }

    fn has_unresolved_for_turn(&self, thread_id: &str, turn_id: &str) -> bool {
        self.pre_sends.iter().any(|(attempt_id, record)| {
            record.thread_id == thread_id
                && record.turn_id == turn_id
                && !self.terminals.contains_key(attempt_id)
        })
    }
}
'''
replace_once(
    path,
    "const fn exact_delivery_schema() -> u32 {\n"
    "    EXACT_DELIVERY_SCHEMA\n"
    "}\n",
    "const fn exact_delivery_schema() -> u32 {\n"
    "    EXACT_DELIVERY_SCHEMA\n"
    "}\n" + state_helpers,
)

# Persist a canonical digest of the exact runtime terminal so callback retries
# can be idempotent without rebuilding in-memory proof objects.
replace_once(
    path,
    "struct StoredTerminal {\n"
    "    attempt_id: String,\n"
    "    provider_receipt_digest: [u8; 32],",
    "struct StoredTerminal {\n"
    "    attempt_id: String,\n"
    "    terminal_observation_digest: [u8; 32],\n"
    "    provider_receipt_digest: [u8; 32],",
)
replace_once(
    path,
    "    fn new(\n"
    "        attempt_id: &str,\n"
    "        provider_receipt: &ProviderInvocationReceipt,",
    "    fn new(\n"
    "        runtime_terminal: &PromptRuntimeFinalTerminalV2,\n"
    "        provider_receipt: &ProviderInvocationReceipt,",
)
replace_once(
    path,
    "        Ok(Self {\n"
    "            attempt_id: attempt_id.to_owned(),\n"
    "            provider_receipt_digest:",
    "        Ok(Self {\n"
    "            attempt_id: runtime_terminal.attempt.attempt_id.clone(),\n"
    "            terminal_observation_digest: terminal_observation_digest(runtime_terminal)?\n"
    "                .into_array(),\n"
    "            provider_receipt_digest:",
)
replace_once(
    path,
    "                || record.provider_receipt_digest == [0; 32]\n"
    "                || record.context_delivery_receipt_digest == [0; 32]",
    "                || record.terminal_observation_digest == [0; 32]\n"
    "                || record.provider_receipt_digest == [0; 32]\n"
    "                || record.context_delivery_receipt_digest == [0; 32]",
)

terminal_digest_fn = r'''

fn terminal_observation_digest(
    terminal: &PromptRuntimeFinalTerminalV2,
) -> Result<Digest32, ExactContextDeliveryError> {
    let intent = provider_intent(&terminal.attempt)?;
    let provider_terminal = provider_terminal(terminal.terminal.clone())?;
    let receipt = ProviderInvocationReceipt::new(intent, provider_terminal);
    let mut bytes = b"hepta.context-runtime-terminal-observation.v2".to_vec();
    bytes.extend_from_slice(
        &receipt
            .canonical_wire_bytes()
            .map_err(ExactContextDeliveryError::Domain)?,
    );
    bytes.extend_from_slice(terminal.attachment.context_attachment_digest.as_array());
    bytes.extend_from_slice(terminal.attachment.context_payload_digest.as_array());
    bytes.extend_from_slice(&terminal.observed_unix_ms.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}
'''
replace_once(
    path,
    "fn exact_attempt_from_intent(\n",
    terminal_digest_fn + "\nfn exact_attempt_from_intent(\n",
)

replace_once(
    path,
    "    MissingPreSendEvidence,\n    Conflict(&'static str),",
    "    MissingPreSendEvidence,\n"
    "    RecoveryRequired,\n"
    "    Conflict(&'static str),",
)
replace_once(
    path,
    "            Self::MissingPreSendEvidence => \"context_delivery_v2_pre_send_evidence_missing\",\n"
    "            Self::Conflict(_) => \"context_delivery_v2_conflict\",",
    "            Self::MissingPreSendEvidence => \"context_delivery_v2_pre_send_evidence_missing\",\n"
    "            Self::RecoveryRequired => \"context_delivery_v2_recovery_required\",\n"
    "            Self::Conflict(_) => \"context_delivery_v2_conflict\",",
)

# Add focused restart/idempotency state tests and a real subprocess tokenizer
# golden test without mutating global environment variables.
file_path = Path(path)
text = file_path.read_text()
if not text.endswith("}\n"):
    raise SystemExit(f"{path}: unexpected file ending")
extra_tests = r'''

    fn stored_pre_send(thread_id: &str, turn_id: &str, attempt_id: &str) -> super::StoredPreSend {
        super::StoredPreSend {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
            attempt_id: attempt_id.to_owned(),
            provider_intent_digest: [1; 32],
            registry_snapshot_digest: [2; 32],
            final_use_materialization_digest: [3; 32],
            preparation_digest: [4; 32],
            final_request_proof_digest: [5; 32],
            provider_request_digest: [6; 32],
            provider_wire_semantic_digest: [7; 32],
            tokenizer_identity_digest: [8; 32],
            tokenization_receipt_digest: [9; 32],
            token_count: 11,
            segment_map_digest: [10; 32],
            recorded_unix_ms: 12,
        }
    }

    fn stored_terminal(attempt_id: &str) -> super::StoredTerminal {
        super::StoredTerminal {
            attempt_id: attempt_id.to_owned(),
            terminal_observation_digest: [11; 32],
            provider_receipt_digest: [12; 32],
            context_delivery_receipt_digest: [13; 32],
            final_request_proof_digest: [5; 32],
            disposition: "Delivered".to_owned(),
            observed_unix_ms: 14,
        }
    }

    #[test]
    fn unresolved_pre_send_survives_reopen_and_blocks_turn_retry() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (store, mut state) = super::ExactDeliveryStore::open(directory.path()).expect("open");
        state.pre_sends.insert(
            "attempt-a".to_owned(),
            stored_pre_send("thread-a", "turn-a", "attempt-a"),
        );
        store.persist(&state).expect("persist");
        drop(store);

        let (_store, reopened) =
            super::ExactDeliveryStore::open(directory.path()).expect("reopen");
        assert!(reopened.has_unresolved_attempt("attempt-a"));
        assert!(reopened.has_unresolved_for_turn("thread-a", "turn-a"));

        let mut resolved = reopened.clone();
        resolved
            .terminals
            .insert("attempt-a".to_owned(), stored_terminal("attempt-a"));
        assert!(!resolved.has_unresolved_attempt("attempt-a"));
        assert!(!resolved.has_unresolved_for_turn("thread-a", "turn-a"));
        super::validate_stored_state(&resolved).expect("valid resolved state");
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn exact_tokenizer_subprocess_receives_unicode_and_control_bytes() {
        use std::os::unix::fs::PermissionsExt;

        let directory = tempfile::tempdir().expect("tempdir");
        let binary = directory.path().join("tokenizer.py");
        let vocabulary = directory.path().join("vocab.txt");
        std::fs::write(
            &binary,
            "#!/usr/bin/env python3\nimport sys\ndata=sys.stdin.buffer.read()\nprint(len(data))\n",
        )
        .expect("write tokenizer");
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o700))
            .expect("chmod");
        std::fs::write(&vocabulary, b"fixture-vocabulary").expect("write vocab");
        let identity = codex_hepta_context_compiler::FinalRequestTokenizerIdentityV2::new(
            Digest32::of_bytes(b"provider"),
            Digest32::of_bytes(b"model"),
            Digest32::of_bytes(b"declared-tokenizer"),
            super::hash_bounded_file(&binary).expect("binary digest"),
            Digest32::of_bytes(b"fixture-v1"),
            super::hash_bounded_file(&vocabulary).expect("vocab digest"),
            Digest32::of_bytes(b"no-normalization"),
        )
        .expect("identity");
        let tokenizer = super::TokenizerRuntimeConfig {
            binary,
            vocabulary,
            provider_id: "provider".to_owned(),
            model: "model".to_owned(),
            version: "fixture-v1".to_owned(),
            normalization: "no-normalization".to_owned(),
            timeout: std::time::Duration::from_secs(5),
            identity,
        };
        let request = "{\"model\":\"model\",\"input\":\"政策🧪\\ncontrol:\\u0001\"}".as_bytes();
        assert_eq!(
            tokenizer.count(request).await.expect("tokenizer count"),
            u64::try_from(request.len()).expect("length")
        );
    }
'''
text = text[:-2] + extra_tests + "}\n"
file_path.write_text(text)
