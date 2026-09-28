#!/usr/bin/env python3
"""Activate schema-3 terminal-only recovery on the materialized V3 Agentd source."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_one_of(path: str, variants: tuple[str, ...], new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    matches = [(old, text.count(old)) for old in variants if text.count(old)]
    if len(matches) != 1 or matches[0][1] != 1:
        detail = ", ".join(str(count) for _, count in matches) or "none"
        raise SystemExit(f"{path}: expected one compatible anchor, found {detail}")
    old = matches[0][0]
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


exact = "codex-rs/hepta-agentd/src/exact_context_delivery.rs"
replace(
    exact,
    "use codex_hepta_context_compiler::ContextDeliveryPreparationV2;\n"
    "use codex_hepta_context_compiler::ContextDeliveryReceiptV2;",
    "use codex_hepta_context_compiler::ContextDeliveryPreparationV2;\n"
    "use codex_hepta_context_compiler::ContextDeliveryReceiptV2;\n"
    "use codex_hepta_context_compiler::ContextDeliveryRecoveryBindingV2;",
)
replace(
    exact,
    "use codex_hepta_context_compiler::observe_final_provider_delivery_v2;\n"
    "use codex_hepta_context_compiler::prove_final_provider_request_v2;",
    "use codex_hepta_context_compiler::build_delivery_recovery_binding_v2;\n"
    "use codex_hepta_context_compiler::observe_final_provider_delivery_v2;\n"
    "use codex_hepta_context_compiler::observe_recovered_final_provider_delivery_v2;\n"
    "use codex_hepta_context_compiler::prove_final_provider_request_v2;",
)
replace(exact, "const EXACT_DELIVERY_SCHEMA: u32 = 2;", "const EXACT_DELIVERY_SCHEMA: u32 = 3;")
replace(
    exact,
    "const MAX_DURABLE_STATE_BYTES: u64 = 4 * 1024 * 1024;",
    "const MAX_DURABLE_STATE_BYTES: u64 = 16 * 1024 * 1024;\n"
    "const MAX_RECOVERY_ARCHIVE_BYTES: usize = 64 * 1024;",
)

replace_one_of(
    exact,
    (
        '''        let intent = provider_intent(&request.attempt)?;
        check_send_time(now_unix_ms, current_unix_ms()?, request.attachment.deadline_ms)?;
        let pre_send = StoredPreSend::new(
            &request, &fresh, &final_request_proof, &intent, now_unix_ms,
        )?;
''',
        '''        let intent = provider_intent(&request.attempt)?;
        check_send_time(
            now_unix_ms,
            current_unix_ms()?,
            request.attachment.deadline_ms,
        )?;
        let pre_send =
            StoredPreSend::new(&request, &fresh, &final_request_proof, &intent, now_unix_ms)?;
''',
    ),
    '''        let intent = provider_intent(&request.attempt)?;
        let recovery = build_delivery_recovery_binding_v2(
            &fresh.preparation,
            &compiled.attachment,
            &compiled.serialized_context,
            &compiled.model_profile,
            &final_request_proof,
            &intent,
        )
        .map_err(|_| ExactContextDeliveryError::InvalidProof)?;
        check_send_time(
            now_unix_ms,
            current_unix_ms()?,
            request.attachment.deadline_ms,
        )?;
        let pre_send = StoredPreSend::new(
            &request,
            &fresh,
            &final_request_proof,
            &intent,
            &recovery,
            now_unix_ms,
        )?;
''',
)

replace(
    exact,
    '''        self.store.ensure_available()?;
        let terminal_observation_digest = terminal_observation_digest(&terminal)?;
        let active = {
''',
    '''        self.store.ensure_available()?;
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
''',
)

replace(
    exact,
    "    fn commit_pre_send(\n",
    '''    fn observe_recovered_terminal(
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
        let receipt = ProviderInvocationReceipt::new(
            recovery.provider_intent().clone(),
            provider_terminal(terminal.terminal.clone())?,
        );
        receipt
            .validate()
            .map_err(ExactContextDeliveryError::Domain)?;
        let verifier = ExactProviderDeliveryVerifier::new(
            recovery.provider_intent().clone(),
            recovery.final_request_proof_digest(),
            terminal.observed_unix_ms,
        );
        let context_receipt = observe_recovered_final_provider_delivery_v2(
            &recovery,
            stable_id(format!(
                "context-delivery:{}",
                Digest32::of_bytes(terminal.attempt.attempt_id.as_bytes())
            ))?,
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

    fn commit_pre_send(
''',
)

replace(
    exact,
    '''    segment_map_digest: [u8; 32],
    recorded_unix_ms: u64,
}

impl StoredPreSend {
    fn new(
        request: &PromptRuntimeFinalRequestV2,
        fresh: &PreparedPromptDeliveryV3,
        proof: &FinalProviderRequestProofV2,
        intent: &ProviderInvocationIntent,
        recorded_unix_ms: u64,
    ) -> Result<Self, ExactContextDeliveryError> {
        Ok(Self {
''',
    '''    segment_map_digest: [u8; 32],
    recorded_unix_ms: u64,
    #[serde(default)]
    recovery_binding_digest: [u8; 32],
    #[serde(default)]
    recovery_archive: Option<Vec<u8>>,
}

impl StoredPreSend {
    fn new(
        request: &PromptRuntimeFinalRequestV2,
        fresh: &PreparedPromptDeliveryV3,
        proof: &FinalProviderRequestProofV2,
        intent: &ProviderInvocationIntent,
        recovery: &ContextDeliveryRecoveryBindingV2,
        recorded_unix_ms: u64,
    ) -> Result<Self, ExactContextDeliveryError> {
        let recovery_archive = recovery
            .canonical_archive_bytes()
            .map_err(|_| ExactContextDeliveryError::InvalidProof)?;
        if recovery_archive.is_empty() || recovery_archive.len() > MAX_RECOVERY_ARCHIVE_BYTES {
            return Err(ExactContextDeliveryError::Capacity);
        }
        Ok(Self {
''',
)
replace(
    exact,
    '''            segment_map_digest: proof.segment_map_digest().into_array(),
            recorded_unix_ms,
        })
''',
    '''            segment_map_digest: proof.segment_map_digest().into_array(),
            recorded_unix_ms,
            recovery_binding_digest: recovery.binding_digest().into_array(),
            recovery_archive: Some(recovery_archive),
        })
''',
)
replace(
    exact,
    '''            segment_map_digest: [10; 32],
            recorded_unix_ms: 12,
        }
''',
    '''            segment_map_digest: [10; 32],
            recorded_unix_ms: 12,
            recovery_binding_digest: [0; 32],
            recovery_archive: None,
        }
''',
)

terminal = "codex-rs/hepta-agentd/src/exact_context_delivery/terminal_state.rs"
replace(
    terminal,
    '''        EXACT_DELIVERY_SCHEMA => return Ok(()),
        1 if state.observations.is_empty() => {}
''',
    '''        EXACT_DELIVERY_SCHEMA => return Ok(()),
        2 => {
            state.schema = EXACT_DELIVERY_SCHEMA;
            return Ok(());
        }
        1 if state.observations.is_empty() => {}
''',
)
replace_one_of(
    terminal,
    (
        '''        for digest in [pre_send.provider_intent_digest, pre_send.registry_snapshot_digest,
            pre_send.final_use_materialization_digest, pre_send.preparation_digest,
            pre_send.final_request_proof_digest, pre_send.provider_request_digest,
            pre_send.provider_wire_semantic_digest, pre_send.tokenizer_identity_digest,
            pre_send.tokenization_receipt_digest, pre_send.segment_map_digest]
        {
            if digest == [0; 32] { return Err(ExactContextDeliveryError::CorruptState); }
        }
''',
        '''        for digest in [
            pre_send.provider_intent_digest,
            pre_send.registry_snapshot_digest,
            pre_send.final_use_materialization_digest,
            pre_send.preparation_digest,
            pre_send.final_request_proof_digest,
            pre_send.provider_request_digest,
            pre_send.provider_wire_semantic_digest,
            pre_send.tokenizer_identity_digest,
            pre_send.tokenization_receipt_digest,
            pre_send.segment_map_digest,
        ] {
            if digest == [0; 32] {
                return Err(ExactContextDeliveryError::CorruptState);
            }
        }
''',
        '''        for digest in [pre_send.provider_intent_digest, pre_send.authority_snapshot_digest,
            pre_send.preparation_binding_digest, pre_send.preparation_digest,
            pre_send.final_request_proof_digest, pre_send.provider_request_digest,
            pre_send.provider_wire_semantic_digest, pre_send.tokenizer_identity_digest,
            pre_send.tokenization_receipt_digest, pre_send.segment_map_digest]
        {
            if digest == [0; 32] { return Err(ExactContextDeliveryError::CorruptState); }
        }
''',
    ),
    '''        for digest in [
            pre_send.provider_intent_digest,
            pre_send.authority_snapshot_digest,
            pre_send.preparation_binding_digest,
            pre_send.preparation_digest,
            pre_send.final_request_proof_digest,
            pre_send.provider_request_digest,
            pre_send.provider_wire_semantic_digest,
            pre_send.tokenizer_identity_digest,
            pre_send.tokenization_receipt_digest,
            pre_send.segment_map_digest,
        ] {
            if digest == [0; 32] {
                return Err(ExactContextDeliveryError::CorruptState);
            }
        }
        match &pre_send.recovery_archive {
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
''',
)
