#!/usr/bin/env python3
"""Wire raw-free compiler recovery evidence into Agentd durable reconciliation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one recovery anchor, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


exact = "codex-rs/hepta-agentd/src/exact_context_delivery.rs"
replace_once(
    exact,
    "use codex_hepta_context_compiler::ContextDeliveryPreparationV2;\n"
    "use codex_hepta_context_compiler::ContextDeliveryReceiptV2;",
    "use codex_hepta_context_compiler::ContextDeliveryPreparationV2;\n"
    "use codex_hepta_context_compiler::ContextDeliveryReceiptV2;\n"
    "use codex_hepta_context_compiler::ContextDeliveryRecoveryBindingV2;",
)
replace_once(
    exact,
    "use codex_hepta_context_compiler::observe_final_provider_delivery_v2;\n"
    "use codex_hepta_context_compiler::prove_final_provider_request_v2;",
    "use codex_hepta_context_compiler::build_delivery_recovery_binding_v2;\n"
    "use codex_hepta_context_compiler::observe_final_provider_delivery_v2;\n"
    "use codex_hepta_context_compiler::observe_recovered_final_provider_delivery_v2;\n"
    "use codex_hepta_context_compiler::prove_final_provider_request_v2;",
)
replace_once(exact, "const EXACT_DELIVERY_SCHEMA: u32 = 2;", "const EXACT_DELIVERY_SCHEMA: u32 = 3;")
replace_once(
    exact,
    "const MAX_DURABLE_STATE_BYTES: u64 = 4 * 1024 * 1024;",
    "const MAX_DURABLE_STATE_BYTES: u64 = 16 * 1024 * 1024;\n"
    "const MAX_RECOVERY_ARCHIVE_BYTES: usize = 64 * 1024;",
)

old_pre_send = '''        let intent = provider_intent(&request.attempt)?;
        check_send_time(now_unix_ms, current_unix_ms()?, request.attachment.deadline_ms)?;
        let pre_send = StoredPreSend::new(
            &request, &fresh, &final_request_proof, &intent, now_unix_ms,
        )?;
'''
new_pre_send = '''        let intent = provider_intent(&request.attempt)?;
        let recovery = build_delivery_recovery_binding_v2(
            &fresh.preparation,
            &compiled.attachment,
            &compiled.serialized_context,
            &compiled.model_profile,
            &final_request_proof,
            &intent,
        )
        .map_err(|_| ExactContextDeliveryError::InvalidProof)?;
        check_send_time(now_unix_ms, current_unix_ms()?, request.attachment.deadline_ms)?;
        let pre_send = StoredPreSend::new(
            &request,
            &fresh,
            &final_request_proof,
            &intent,
            &recovery,
            now_unix_ms,
        )?;
'''
replace_once(exact, old_pre_send, new_pre_send)

# A no-active unresolved attempt may be terminally reconciled only when the new
# raw-free recovery archive is present. Legacy digest-only records remain
# RecoveryRequired.
old_terminal_start = '''        self.store.ensure_available()?;
        let terminal_observation_digest = terminal_observation_digest(&terminal)?;
        let active = {
'''
new_terminal_start = '''        self.store.ensure_available()?;
        let terminal_observation_digest = terminal_observation_digest(&terminal)?;
        let recovery_archive = {
            let state = self
                .state
                .lock()
                .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
            if state.active.contains_key(&terminal.attempt.attempt_id) {
                None
            } else if state
                .durable
                .has_unresolved_attempt(&terminal.attempt.attempt_id)
            {
                Some(
                    state
                        .durable
                        .pre_sends
                        .get(&terminal.attempt.attempt_id)
                        .and_then(|record| record.recovery_archive.clone())
                        .ok_or(ExactContextDeliveryError::RecoveryRequired)?,
                )
            } else {
                None
            }
        };
        if let Some(archive) = recovery_archive {
            return self.observe_recovered_terminal(
                terminal,
                terminal_observation_digest,
                &archive,
            );
        }
        let active = {
'''
replace_once(exact, old_terminal_start, new_terminal_start)

insert_before_commit = '''    fn commit_pre_send(
'''
recovery_method = '''    fn observe_recovered_terminal(
        &self,
        terminal: PromptRuntimeFinalTerminalV2,
        terminal_observation_digest: Digest32,
        archive: &[u8],
    ) -> Result<(), ExactContextDeliveryError> {
        let recovery = ContextDeliveryRecoveryBindingV2::reopen_canonical_archive(archive)
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        exact_attempt_from_intent(recovery.provider_intent(), &terminal.attempt)?;
        if terminal.attachment.context_attachment_digest != recovery.attachment_digest()
            || terminal.attachment.context_payload_digest != recovery.payload_digest()
        {
            return Err(ExactContextDeliveryError::Conflict(
                "recovered terminal does not match durable context identity",
            ));
        }
        let provider_terminal = provider_terminal(terminal.terminal.clone())?;
        let receipt = ProviderInvocationReceipt::new(
            recovery.provider_intent().clone(),
            provider_terminal,
        );
        receipt
            .validate()
            .map_err(ExactContextDeliveryError::Domain)?;
        let verifier = ExactProviderDeliveryVerifier::new(
            recovery.provider_intent().clone(),
            recovery.final_request_proof_digest(),
            terminal.observed_unix_ms,
        );
        let delivery_id = stable_id(format!(
            "context-delivery:{}",
            Digest32::of_bytes(terminal.attempt.attempt_id.as_bytes())
        ))?;
        let context_receipt = observe_recovered_final_provider_delivery_v2(
            &recovery,
            delivery_id,
            &receipt,
            &verifier,
            terminal.observed_unix_ms,
        )
        .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        let stored = StoredTerminal {
            observation_version: 3,
            provider_receipt: Some(receipt.clone()),
            attempt_id: terminal.attempt.attempt_id.clone(),
            terminal_observation_digest: terminal_observation_digest.into_array(),
            provider_receipt_digest: Digest32::of_bytes(
                &receipt
                    .canonical_wire_bytes()
                    .map_err(ExactContextDeliveryError::Domain)?,
            )
            .into_array(),
            context_delivery_receipt_digest: context_receipt.receipt_digest().into_array(),
            final_request_proof_digest: recovery.final_request_proof_digest().into_array(),
            disposition: format!("{:?}", context_receipt.disposition()),
            observed_unix_ms: terminal.observed_unix_ms,
        };
        self.commit_terminal(&terminal.attempt.attempt_id, stored)
    }

'''
replace_once(exact, insert_before_commit, recovery_method + insert_before_commit)

replace_once(
    exact,
    "    recorded_unix_ms: u64,\n}",
    "    recorded_unix_ms: u64,\n"
    "    #[serde(default)]\n"
    "    recovery_binding_digest: [u8; 32],\n"
    "    #[serde(default)]\n"
    "    recovery_archive: Option<Vec<u8>>,\n}",
)
replace_once(
    exact,
    "        intent: &ProviderInvocationIntent,\n        recorded_unix_ms: u64,",
    "        intent: &ProviderInvocationIntent,\n"
    "        recovery: &ContextDeliveryRecoveryBindingV2,\n"
    "        recorded_unix_ms: u64,",
)
replace_once(
    exact,
    "    ) -> Result<Self, ExactContextDeliveryError> {\n        Ok(Self {",
    "    ) -> Result<Self, ExactContextDeliveryError> {\n"
    "        let recovery_archive = recovery\n"
    "            .canonical_archive_bytes()\n"
    "            .map_err(|_| ExactContextDeliveryError::InvalidProof)?;\n"
    "        if recovery_archive.is_empty()\n"
    "            || recovery_archive.len() > MAX_RECOVERY_ARCHIVE_BYTES\n"
    "        {\n"
    "            return Err(ExactContextDeliveryError::Capacity);\n"
    "        }\n"
    "        Ok(Self {",
)
replace_once(
    exact,
    "            recorded_unix_ms,\n        })",
    "            recorded_unix_ms,\n"
    "            recovery_binding_digest: recovery.binding_digest().into_array(),\n"
    "            recovery_archive: Some(recovery_archive),\n"
    "        })",
)

# Update the inline legacy fixture so schema-2 history remains expressible.
replace_once(
    exact,
    "            recorded_unix_ms: 12,\n        }",
    "            recorded_unix_ms: 12,\n"
    "            recovery_binding_digest: [0; 32],\n"
    "            recovery_archive: None,\n"
    "        }",
)

terminal_state = "codex-rs/hepta-agentd/src/exact_context_delivery/terminal_state.rs"
replace_once(
    terminal_state,
    "        EXACT_DELIVERY_SCHEMA => return Ok(()),\n        1 if state.observations.is_empty() => {}",
    "        EXACT_DELIVERY_SCHEMA => return Ok(()),\n"
    "        2 => {\n"
    "            state.schema = EXACT_DELIVERY_SCHEMA;\n"
    "            return Ok(());\n"
    "        }\n"
    "        1 if state.observations.is_empty() => {}",
)

validation_anchor = '''        for digest in [pre_send.provider_intent_digest, pre_send.registry_snapshot_digest,
            pre_send.final_use_materialization_digest, pre_send.preparation_digest,
            pre_send.final_request_proof_digest, pre_send.provider_request_digest,
            pre_send.provider_wire_semantic_digest, pre_send.tokenizer_identity_digest,
            pre_send.tokenization_receipt_digest, pre_send.segment_map_digest]
        {
            if digest == [0; 32] { return Err(ExactContextDeliveryError::CorruptState); }
        }
'''
validation_replacement = validation_anchor + '''        match &pre_send.recovery_archive {
            Some(archive) => {
                if archive.is_empty() || archive.len() > MAX_RECOVERY_ARCHIVE_BYTES
                    || pre_send.recovery_binding_digest == [0; 32]
                {
                    return Err(ExactContextDeliveryError::CorruptState);
                }
                let recovery = ContextDeliveryRecoveryBindingV2::reopen_canonical_archive(archive)
                    .map_err(|_| ExactContextDeliveryError::CorruptState)?;
                if recovery.binding_digest().into_array() != pre_send.recovery_binding_digest
                    || recovery.final_request_proof_digest().into_array()
                        != pre_send.final_request_proof_digest
                    || recovery.provider_request_digest().into_array()
                        != pre_send.provider_request_digest
                    || recovery.provider_wire_semantic_digest().into_array()
                        != pre_send.provider_wire_semantic_digest
                    || Digest32::of_bytes(
                        &recovery
                            .provider_intent()
                            .canonical_wire_bytes()
                            .map_err(|_| ExactContextDeliveryError::CorruptState)?,
                    )
                    .into_array()
                        != pre_send.provider_intent_digest
                {
                    return Err(ExactContextDeliveryError::CorruptState);
                }
            }
            None if pre_send.recovery_binding_digest == [0; 32] => {}
            None => return Err(ExactContextDeliveryError::CorruptState),
        }
'''
replace_once(terminal_state, validation_anchor, validation_replacement)
