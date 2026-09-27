#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    '#[path = "intelligence_learning_payload.rs"]\nmod payload;\n',
    '#[path = "intelligence_learning_payload.rs"]\nmod payload;\n#[path = "intelligence_learning_exact.rs"]\nmod exact;\n',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/lib.rs",
    "pub mod native_app_server;\n",
    "pub mod native_app_server;\npub mod native_intelligence_product;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;\n",
    "use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;\nuse codex_hepta_intelligence::PreparedPromptDeliveryV1;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    pub prompt_request: OptimizationRequest,\n    pub intuition_request: CalibratedDecisionRequestV1,\n",
    "    pub prompt_request: OptimizationRequest,\n    /// Exact owner-backed prompt/context delivery. Compatibility fixtures may\n    /// leave this absent, but physical product execution is fail-closed without it.\n    pub prompt_delivery: Option<PreparedPromptDeliveryV1>,\n    pub intuition_request: CalibratedDecisionRequestV1,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    '#[path = "intelligence_product_ports.rs"]\nmod owner_ports;\nuse owner_ports::AgentdOwnerPortsV1;\n',
    '#[path = "intelligence_product_ports.rs"]\nmod owner_ports;\n#[path = "intelligence_prompt_binding.rs"]\nmod prompt_binding;\nuse owner_ports::AgentdOwnerPortsV1;\n',
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    run_snapshot: crate::AgentRunSnapshot,\n    context_attachment: crate::AgentContextAttachment,\n}\n\nimpl PreparedAgentdIntelligenceRunV1 {\n",
    "    run_snapshot: crate::AgentRunSnapshot,\n    context_attachment: crate::AgentContextAttachment,\n    prompt_delivery: Option<PreparedPromptDeliveryV1>,\n}\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub struct AgentdIntelligencePhysicalPromptV1 {\n    pub payload: Vec<u8>,\n    pub payload_digest: Digest32,\n    pub attachment_digest: Digest32,\n    pub prompt_stage_digest: Digest32,\n}\n\nimpl PreparedAgentdIntelligenceRunV1 {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    #[must_use]\n    pub fn candidate_ids(&self) -> &[StableId] { &self.candidate_ids }\n}\n",
    "    #[must_use]\n    pub fn candidate_ids(&self) -> &[StableId] { &self.candidate_ids }\n    #[must_use]\n    pub fn prompt_delivery(&self) -> Option<&PreparedPromptDeliveryV1> {\n        self.prompt_delivery.as_ref()\n    }\n    pub fn physical_prompt(\n        &self,\n    ) -> Result<AgentdIntelligencePhysicalPromptV1, CanonicalIntelligenceError> {\n        let delivery = self.prompt_delivery.as_ref().ok_or(\n            CanonicalIntelligenceError::InvalidSnapshot(\"owner-backed prompt delivery\"),\n        )?;\n        let binding = prompt_binding::validate_prompt_delivery_v1(delivery)?;\n        Ok(AgentdIntelligencePhysicalPromptV1 {\n            payload: delivery.serialized_payload.clone(),\n            payload_digest: binding.payload_digest,\n            attachment_digest: binding.context_attachment_digest,\n            prompt_stage_digest: binding.prompt_stage_digest,\n        })\n    }\n}\n",
)
write(
    "codex-rs/hepta-agentd/src/intelligence_prompt_binding.rs",
    dedent(r'''
    //! Exact binding between Prompt Registry realization, context compilation and
    //! the physical App Server payload retained by a prepared intelligence run.

    use std::collections::BTreeSet;

    use codex_hepta_intelligence::PreparedPromptDeliveryV1;
    use codex_hepta_types::Digest32;

    use super::CanonicalIntelligenceError;

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    pub(crate) struct PromptDeliveryBindingV1 {
        pub(crate) prompt_stage_digest: Digest32,
        pub(crate) context_attachment_digest: Digest32,
        pub(crate) payload_digest: Digest32,
    }

    pub(crate) fn validate_prompt_delivery_v1(
        delivery: &PreparedPromptDeliveryV1,
    ) -> Result<PromptDeliveryBindingV1, CanonicalIntelligenceError> {
        delivery
            .materialization
            .validate()
            .map_err(|_| CanonicalIntelligenceError::InvalidSnapshot("prompt materialization"))?;
        delivery
            .serialization_proof
            .validate()
            .map_err(|_| CanonicalIntelligenceError::InvalidSnapshot("prompt serialization proof"))?;

        if delivery.serialized_payload.is_empty() {
            return Err(CanonicalIntelligenceError::InvalidSnapshot(
                "physical prompt payload",
            ));
        }
        let payload_digest = Digest32::of_bytes(&delivery.serialized_payload);
        if delivery.serialized_context.payload() != delivery.serialized_payload.as_slice()
            || delivery.serialized_context.receipt() != &delivery.serialization
            || delivery.serialization.payload_digest() != payload_digest
            || delivery.attachment.payload_digest() != payload_digest
            || delivery.serialization_proof.serialized_payload_digest != payload_digest
            || delivery.serialization_proof.materialization_bundle_digest
                != delivery.materialization.bundle_digest
            || delivery.exercise.receipt_digest.is_zero()
            || delivery.serialization.receipt_digest().is_zero()
            || delivery.attachment.attachment_digest().is_zero()
            || delivery.exercise.authority.grants_any()
            || delivery.serialization.authority().grants_any()
            || delivery.attachment.authority().grants_any()
        {
            return Err(CanonicalIntelligenceError::InvalidSnapshot(
                "prompt/context physical binding",
            ));
        }

        let selected = delivery
            .attachment
            .selected_item_ids()
            .iter()
            .cloned()
            .collect::<BTreeSet<_>>();
        let materialized = delivery
            .materialization
            .payloads
            .iter()
            .map(|value| value.binding.realization_id.clone())
            .collect::<BTreeSet<_>>();
        if selected != materialized {
            return Err(CanonicalIntelligenceError::InvalidSnapshot(
                "prompt realization membership",
            ));
        }

        let mut bytes = b"hepta.agentd.intelligence-prompt-stage.v1\0".to_vec();
        bytes.extend_from_slice(delivery.exercise.receipt_digest.as_array());
        bytes.extend_from_slice(delivery.serialization_proof.proof_digest.as_array());
        bytes.extend_from_slice(delivery.materialization.bundle_digest.as_array());
        bytes.extend_from_slice(delivery.serialization.receipt_digest().as_array());
        bytes.extend_from_slice(delivery.attachment.attachment_digest().as_array());
        bytes.extend_from_slice(payload_digest.as_array());
        Ok(PromptDeliveryBindingV1 {
            prompt_stage_digest: Digest32::of_bytes(&bytes),
            context_attachment_digest: delivery.attachment.attachment_digest(),
            payload_digest,
        })
    }

    pub(crate) fn prompt_conditioned_state_digest_v1(
        neural_digest: Digest32,
        prompt_stage_digest: Digest32,
    ) -> Digest32 {
        let mut bytes = b"hepta.agentd.intelligence-prompt-conditioned-state.v1\0".to_vec();
        bytes.extend_from_slice(neural_digest.as_array());
        bytes.extend_from_slice(prompt_stage_digest.as_array());
        Digest32::of_bytes(&bytes)
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn prompt_conditioned_state_rejects_either_stage_substitution() {
            let neural = Digest32::of_bytes(b"neural");
            let prompt = Digest32::of_bytes(b"prompt");
            let baseline = prompt_conditioned_state_digest_v1(neural, prompt);
            assert_ne!(
                baseline,
                prompt_conditioned_state_digest_v1(Digest32::of_bytes(b"other-neural"), prompt)
            );
            assert_ne!(
                baseline,
                prompt_conditioned_state_digest_v1(neural, Digest32::of_bytes(b"other-prompt"))
            );
        }
    }
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
    "    prompt_request: Option<OptimizationRequest>,\n    intuition_request: Option<CalibratedDecisionRequestV1>,\n",
    "    prompt_request: Option<OptimizationRequest>,\n    prompt_delivery: Option<PreparedPromptDeliveryV1>,\n    intuition_request: Option<CalibratedDecisionRequestV1>,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
    "    utility_output: Option<Digest32>,\n    neural_output: Option<Digest32>,\n",
    "    utility_output: Option<Digest32>,\n    neural_output: Option<Digest32>,\n    prompt_output: Option<Digest32>,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
    "            prompt_request: Some(value.prompt_request),\n            intuition_request: Some(value.intuition_request),\n",
    "            prompt_request: Some(value.prompt_request),\n            prompt_delivery: value.prompt_delivery,\n            intuition_request: Some(value.intuition_request),\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
    "            utility_output: None,\n            neural_output: None,\n",
    "            utility_output: None,\n            neural_output: None,\n            prompt_output: None,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
    dedent(r'''
    fn build_prompt_portfolio(&mut self, input: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.prompt_request, input.stage, "prompt request")?;
        if request.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "prompt objective"));
        }
        if self.neural_output != Some(input.predecessor_digest) {
            return Err(Self::reject(input.stage, "prompt neural predecessor"));
        }
        let started = Instant::now();
        let receipt = optimize(request);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "prompt optimization"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "prompt authority"));
        }
        Self::receipt(input, "prompt.optimizer", receipt.receipt_digest, CanonicalPortDecisionV1::Continue)
    }
    ''').lstrip(),
    dedent(r'''
    fn build_prompt_portfolio(&mut self, input: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.prompt_request, input.stage, "prompt request")?;
        if request.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "prompt objective"));
        }
        if self.neural_output != Some(input.predecessor_digest) {
            return Err(Self::reject(input.stage, "prompt neural predecessor"));
        }
        if let Some(delivery) = self.prompt_delivery.as_ref() {
            let started = Instant::now();
            let binding = prompt_binding::validate_prompt_delivery_v1(delivery)
                .map_err(|_| Self::reject(input.stage, "owner-backed prompt delivery"))?;
            self.within_budget(input, started)?;
            self.prompt_output = Some(binding.prompt_stage_digest);
            return Self::receipt(
                input,
                "prompt.optimizer",
                binding.prompt_stage_digest,
                CanonicalPortDecisionV1::Continue,
            );
        }
        let started = Instant::now();
        let receipt = optimize(request);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "prompt optimization"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "prompt authority"));
        }
        self.prompt_output = Some(receipt.receipt_digest);
        Self::receipt(input, "prompt.optimizer", receipt.receipt_digest, CanonicalPortDecisionV1::Continue)
    }
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
    "        let neural = self.neural_output.ok_or_else(|| Self::reject(input.stage, \"missing actual neural state\"))?;\n        request.state_digest = bind_stage_digest(request.state_digest, neural, input.stage)?;\n",
    "        let neural = self.neural_output.ok_or_else(|| Self::reject(input.stage, \"missing actual neural state\"))?;\n        let prompt = self.prompt_output.ok_or_else(|| Self::reject(input.stage, \"missing actual prompt output\"))?;\n        if input.predecessor_digest != prompt {\n            return Err(Self::reject(input.stage, \"intuition prompt predecessor\"));\n        }\n        let actual_state = if self.prompt_delivery.is_some() {\n            prompt_binding::prompt_conditioned_state_digest_v1(neural, prompt)\n        } else {\n            neural\n        };\n        request.state_digest = bind_stage_digest(request.state_digest, actual_state, input.stage)?;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
    dedent(r'''
    fn compile_context(&mut self, input: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.context_request, input.stage, "context request")?;
        if request.objective_digest != input.objective_digest || request.run_snapshot_digest != input.snapshot_digest {
            return Err(Self::reject(input.stage, "context binding"));
        }
        let started = Instant::now();
        let receipt = compile(request);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "context compile"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "context authority"));
        }
        Self::receipt(input, "context.compiler", receipt.context_digest, CanonicalPortDecisionV1::Continue)
    }
    ''').lstrip(),
    dedent(r'''
    fn compile_context(&mut self, input: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.context_request, input.stage, "context request")?;
        if request.objective_digest != input.objective_digest || request.run_snapshot_digest != input.snapshot_digest {
            return Err(Self::reject(input.stage, "context binding"));
        }
        if let Some(delivery) = self.prompt_delivery.as_ref() {
            let started = Instant::now();
            let binding = prompt_binding::validate_prompt_delivery_v1(delivery)
                .map_err(|_| Self::reject(input.stage, "owner-backed context delivery"))?;
            self.within_budget(input, started)?;
            if self.prompt_output != Some(binding.prompt_stage_digest) {
                return Err(Self::reject(input.stage, "prompt/context substitution"));
            }
            return Self::receipt(
                input,
                "context.compiler",
                binding.context_attachment_digest,
                CanonicalPortDecisionV1::Continue,
            );
        }
        let started = Instant::now();
        let receipt = compile(request);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "context compile"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "context authority"));
        }
        Self::receipt(input, "context.compiler", receipt.context_digest, CanonicalPortDecisionV1::Continue)
    }
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "        let started = Instant::now();\n        let Some(run_identity) = inputs.run_identity.take() else {\n",
    "        let started = Instant::now();\n        let prompt_delivery = inputs.prompt_delivery.clone();\n        let Some(run_identity) = inputs.run_identity.take() else {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "                    envelope, dispatch_proposal_digest, snapshot, candidate_ids,\n                    run_snapshot, context_attachment,\n",
    "                    envelope, dispatch_proposal_digest, snapshot, candidate_ids,\n                    run_snapshot, context_attachment, prompt_delivery,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_prepared_integrity.rs",
    "        if Digest32::of_bytes(&bytes) != self.dispatch_proposal_digest {\n            return Err(CanonicalIntelligenceError::InvalidSnapshot(\"dispatch proposal digest\"));\n        }\n        Ok(())\n",
    "        if Digest32::of_bytes(&bytes) != self.dispatch_proposal_digest {\n            return Err(CanonicalIntelligenceError::InvalidSnapshot(\"dispatch proposal digest\"));\n        }\n        if let Some(delivery) = self.prompt_delivery() {\n            let binding = super::super::prompt_binding::validate_prompt_delivery_v1(delivery)?;\n            if envelope.prompt_receipt_digest != binding.prompt_stage_digest\n                || envelope.context_receipt_digest != binding.context_attachment_digest\n            {\n                return Err(CanonicalIntelligenceError::InvalidSnapshot(\"prompt delivery binding\"));\n            }\n        }\n        Ok(())\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_tests.rs",
    "            prompt_request,\n            intuition_request,\n",
    "            prompt_request,\n            prompt_delivery: None,\n            intuition_request,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use intelligence_product::AgentdIntelligenceProductError;\n",
    "pub use intelligence_product::AgentdIntelligencePhysicalPromptV1;\npub use intelligence_product::AgentdIntelligenceProductError;\n",
)
write(
    "codex-rs/hepta-infer-worker-host/src/native_intelligence_product.rs",
    dedent(r'''
    //! One product composition over the existing Agentd, learning-ledger and App
    //! Server owners.
    //!
    //! Physical prompt bytes are obtained only from the owner-backed prompt
    //! realization/context delivery frozen into the Agentd prepared run. The host
    //! durably acknowledges the exact Decision before model send, uses the sole
    //! App Server path, observes the same Agentd terminal run and then records the
    //! independently authenticated Outcome.

    use std::error::Error as StdError;
    use std::sync::Arc;

    use codex_hepta_agentd::AgentRunPhase;
    use codex_hepta_agentd::AgentRunReceipt;
    use codex_hepta_agentd::AgentdClient;
    use codex_hepta_agentd::AgentdIntelligenceAdmittedOutcomeV1;
    use codex_hepta_agentd::AgentdIntelligenceDecisionAppendV1;
    use codex_hepta_agentd::AgentdIntelligenceLearningDispositionV1;
    use codex_hepta_agentd::AgentdIntelligenceLearningHostV1;
    use codex_hepta_agentd::AgentdIntelligenceLearningReceiptV1;
    use codex_hepta_agentd::AgentdIntelligenceOutcomeAppendV1;
    use codex_hepta_agentd::AgentdIntelligencePhysicalPromptV1;
    use codex_hepta_agentd::PreparedAgentdIntelligenceRunV1;
    use codex_hepta_agentd::RunPhase;
    use codex_hepta_agentd::RunReceipt;
    use codex_hepta_infer_core::durable_control::DurableInferenceControl;
    use codex_hepta_types::Digest32;
    use tokio_util::sync::CancellationToken;

    use crate::native_app_server::AppServerModelDriver;
    use crate::native_app_server::NativeAdmission;
    use crate::native_app_server::NativeIntelligenceRunBinding;
    use crate::native_app_server::NativeRunOutput;

    pub type NativeIntelligenceProductResult<T> =
        std::result::Result<T, Box<dyn StdError + Send + Sync>>;

    #[derive(Clone, Debug)]
    pub struct NativeIntelligenceProductReceiptV1 {
        pub decision: AgentdIntelligenceLearningReceiptV1,
        pub execution: NativeRunOutput,
        pub outcome: Option<AgentdIntelligenceLearningReceiptV1>,
    }

    pub struct NativeIntelligenceProductHostV1 {
        driver: AppServerModelDriver,
        agentd: AgentdClient,
        learning: Arc<AgentdIntelligenceLearningHostV1>,
    }

    impl NativeIntelligenceProductHostV1 {
        #[must_use]
        pub fn new(
            driver: AppServerModelDriver,
            agentd: AgentdClient,
            learning: Arc<AgentdIntelligenceLearningHostV1>,
        ) -> Self {
            Self {
                driver,
                agentd,
                learning,
            }
        }

        pub async fn execute<F>(
            &self,
            control: &mut DurableInferenceControl,
            admission: NativeAdmission,
            admitted: AgentdIntelligenceAdmittedOutcomeV1,
            decision_request: AgentdIntelligenceDecisionAppendV1,
            cancellation: &CancellationToken,
            build_outcome: F,
        ) -> NativeIntelligenceProductResult<NativeIntelligenceProductReceiptV1>
        where
            F: FnOnce(
                &PreparedAgentdIntelligenceRunV1,
                &RunReceipt,
                &NativeRunOutput,
            ) -> NativeIntelligenceProductResult<AgentdIntelligenceOutcomeAppendV1>,
        {
            let (prepared, attached) = match admitted {
                AgentdIntelligenceAdmittedOutcomeV1::Ready {
                    prepared,
                    run_receipt,
                } => (prepared, run_receipt),
                AgentdIntelligenceAdmittedOutcomeV1::Abstained => {
                    return Err("abstained intelligence run has no physical execution".into());
                }
                AgentdIntelligenceAdmittedOutcomeV1::SlowPath => {
                    return Err("slow-path intelligence run requires a different product route".into());
                }
            };
            if admission.request_id != attached.run_id {
                return Err("native admission identity differs from the canonical run".into());
            }
            let physical = prepared.physical_prompt()?;
            let prompt = String::from_utf8(physical.payload.clone())
                .map_err(|_| "owner-backed physical prompt is not UTF-8")?;
            let binding = binding_for_admitted_v1(&prepared, &attached, &physical)?;

            let decision = self
                .learning
                .record_decision_before_dispatch_v1(&prepared, decision_request)
                .await?;
            require_acknowledged("Decision", &decision)?;

            let execution = self
                .driver
                .run_intelligence(control, admission, prompt, None, binding.clone(), cancellation)
                .await?;
            if !execution.terminal_observed {
                return Ok(NativeIntelligenceProductReceiptV1 {
                    decision,
                    execution,
                    outcome: None,
                });
            }
            let terminal = self
                .agentd
                .run_status(binding.run_id.clone())
                .await?
                .ok_or("Agentd terminal receipt disappeared after physical observation")?;
            let terminal = local_terminal_receipt_v1(terminal)?;
            let outcome_request = build_outcome(&prepared, &terminal, &execution)?;
            let outcome = self
                .learning
                .record_outcome_after_terminal_v1(&prepared, outcome_request)
                .await?;
            require_acknowledged("Outcome", &outcome)?;
            Ok(NativeIntelligenceProductReceiptV1 {
                decision,
                execution,
                outcome: Some(outcome),
            })
        }
    }

    pub fn native_provider_terminal_digest_v1(
        output: &NativeRunOutput,
    ) -> NativeIntelligenceProductResult<Digest32> {
        if !output.terminal_observed {
            return Err("provider observation is not terminal".into());
        }
        let mut bytes = b"hepta.runtime.codex.native-terminal.v1\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(output)?);
        Ok(Digest32::of_bytes(&bytes))
    }

    fn binding_for_admitted_v1(
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
        physical: &AgentdIntelligencePhysicalPromptV1,
    ) -> NativeIntelligenceProductResult<NativeIntelligenceRunBinding> {
        let attachment = prepared.context_attachment();
        if receipt.phase != RunPhase::ContextAttached
            || receipt.terminal_observed
            || receipt.run_id != attachment.run_id
            || receipt.context_digest.as_deref() != Some(attachment.context_digest.as_str())
            || receipt.compilation_receipt_digest.as_deref()
                != Some(attachment.compilation_receipt_digest.as_str())
            || attachment.compilation_receipt_digest != prepared.envelope.envelope_digest.to_string()
            || attachment.context_digest != physical.attachment_digest.to_string()
            || prepared.envelope.prompt_receipt_digest != physical.prompt_stage_digest
            || prepared.envelope.context_receipt_digest != physical.attachment_digest
            || Digest32::of_bytes(&physical.payload) != physical.payload_digest
        {
            return Err("admitted intelligence run is not the exact owner-backed ContextAttached envelope".into());
        }
        Ok(NativeIntelligenceRunBinding {
            run_id: receipt.run_id.clone(),
            expected_revision: receipt.revision,
            context_digest: attachment.context_digest,
            envelope_digest: prepared.envelope.envelope_digest.to_string(),
            prompt_digest: physical.payload_digest.to_string(),
        })
    }

    fn require_acknowledged(
        kind: &'static str,
        receipt: &AgentdIntelligenceLearningReceiptV1,
    ) -> NativeIntelligenceProductResult<()> {
        if receipt.disposition != AgentdIntelligenceLearningDispositionV1::Acknowledged
            || receipt.append.is_none()
        {
            return Err(format!(
                "{kind} was not durably acknowledged; physical progression is forbidden"
            )
            .into());
        }
        Ok(())
    }

    fn local_terminal_receipt_v1(
        value: AgentRunReceipt,
    ) -> NativeIntelligenceProductResult<RunReceipt> {
        let phase = match value.phase {
            AgentRunPhase::Admitted => RunPhase::Admitted,
            AgentRunPhase::ContextAttached => RunPhase::ContextAttached,
            AgentRunPhase::Dispatched => RunPhase::Dispatched,
            AgentRunPhase::Cancelling => RunPhase::Cancelling,
            AgentRunPhase::Cancelled => RunPhase::Cancelled,
            AgentRunPhase::Succeeded => RunPhase::Succeeded,
            AgentRunPhase::Failed => RunPhase::Failed,
            AgentRunPhase::Indeterminate => RunPhase::Indeterminate,
        };
        if !value.terminal_observed
            || !matches!(phase, RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed)
        {
            return Err("physical observation lacks a terminal Agentd receipt".into());
        }
        Ok(RunReceipt {
            run_id: value.run_id,
            revision: value.revision,
            phase,
            context_digest: value.context_digest,
            authority_epoch: value.authority_epoch,
            generation: value.generation,
            fence_digest: value.fence_digest,
            deadline_ms: value.deadline_ms,
            cancel_reason: value.cancel_reason,
            cancel_ack_deadline_ms: value.cancel_ack_deadline_ms,
            compilation_receipt_digest: value.compilation_receipt_digest,
            terminal_observed: value.terminal_observed,
            idempotent: value.idempotent,
        })
    }
    ''').lstrip(),
)
