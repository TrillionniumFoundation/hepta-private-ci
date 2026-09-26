#!/usr/bin/env python3
"""Synthesize the additive durable-neuron Agentd product path.

This script is intentionally exact: every replacement must match once. It is used
in a read-only Actions worktree to compile the candidate before the generated
source files are committed. It never writes a branch or treats generated output
as qualification evidence.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_product() -> None:
    path = ROOT / "codex-rs/hepta-agentd/src/intelligence_product.rs"
    text = path.read_text()

    text = replace_once(
        text,
        'pub use evaluation::intelligence_evaluation_binding_payload_v2;\n\nuse std::collections::BTreeMap;',
        'pub use evaluation::intelligence_evaluation_binding_payload_v2;\n\n#[path = "neuron_product.rs"]\nmod neuron_product;\n\nuse std::collections::BTreeMap;',
        "register neuron product module",
    )

    text = replace_once(
        text,
        '    neural_previous: Option<Option<SparseCheckpoint>>,\n    prompt_request: Option<OptimizationRequest>,',
        '    neural_previous: Option<Option<SparseCheckpoint>>,\n    durable_neuron: Option<crate::AgentdNeuronInvocationV1>,\n    neuron_admission: Option<neuron_product::NeuronStageAdmission>,\n    prompt_request: Option<OptimizationRequest>,',
        "add durable neuron owner slots",
    )

    text = replace_once(
        text,
        '            neural_previous: Some(value.neural_previous),\n            prompt_request: Some(value.prompt_request),',
        '            neural_previous: Some(value.neural_previous),\n            durable_neuron: None,\n            neuron_admission: None,\n            prompt_request: Some(value.prompt_request),',
        "initialize durable neuron owner slots",
    )

    text = replace_once(
        text,
        '    fn reject(stage: CanonicalStageV1, label: &\'static str) -> CanonicalPortFailureV1 {',
        '''    fn install_durable_neuron(\n        &mut self,\n        invocation: crate::AgentdNeuronInvocationV1,\n        admission: neuron_product::NeuronStageAdmission,\n    ) {\n        self.durable_neuron = Some(invocation);\n        self.neuron_admission = Some(admission);\n    }\n\n    fn reject(stage: CanonicalStageV1, label: &\'static str) -> CanonicalPortFailureV1 {''',
        "install durable neuron owner",
    )

    marker = '''    fn collect_neural_signal(\n        &mut self,\n        input: &CanonicalPortInputV1,\n    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {\n        let config = Self::take(&mut self.neural_config, input.stage, "neural config")?;'''
    replacement = '''    fn collect_neural_signal(\n        &mut self,\n        input: &CanonicalPortInputV1,\n    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {\n        if let Some(invocation) = self.durable_neuron.take() {\n            let admission = self\n                .neuron_admission\n                .as_mut()\n                .ok_or_else(|| Self::reject(input.stage, "neuron admission missing"))?;\n            let started = Instant::now();\n            admission\n                .begin_stage(input.budget_micros)\n                .map_err(|error| {\n                    neuron_product::failure(\n                        input.stage,\n                        &codex_hepta_neuron::NeuronRuntimeError::Admission(error),\n                    )\n                })?;\n            let result = invocation\n                .execute(input, admission)\n                .map_err(|error| neuron_product::failure(input.stage, &error))?;\n            Self::within_budget(input, started)?;\n            if result.signal.abstain\n                || result.tick.abstain\n                || result.signal.authority.grants_any()\n            {\n                return Err(neuron_product::failure(\n                    input.stage,\n                    &codex_hepta_neuron::NeuronRuntimeError::InvalidCalibration,\n                ));\n            }\n            let intuition = self\n                .intuition\n                .as_mut()\n                .ok_or_else(|| Self::reject(input.stage, "intuition consumer missing"))?;\n            intuition.request.state_digest = result.tick.checkpoint_after;\n            return Self::receipt(\n                input,\n                "neuron.runtime",\n                result.tick.checkpoint_after,\n                CanonicalPortDecisionV1::Continue,\n            );\n        }\n\n        let config = Self::take(&mut self.neural_config, input.stage, "neural config")?;'''
    text = replace_once(text, marker, replacement, "route durable neuron owner")

    path.write_text(text)


def patch_runner() -> None:
    path = ROOT / "codex-rs/hepta-agentd/src/intelligence_product_runner.rs"
    text = path.read_text()

    old_prepare = '''    pub async fn prepare(\n        &self,\n        coordinator: &crate::AgentRunCoordinator,\n        request: CanonicalIntelligenceRunRequestV1,\n        inputs: AgentdIntelligenceOwnerInputsV1,\n    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {\n        let composition = coordinator.composition().clone();\n        self.prepare_for_composition(&composition, request, inputs)\n            .await\n    }\n'''
    new_prepare = old_prepare + '''\n    /// Execute the canonical composition through the long-lived durable Neuron\n    /// owner. The invocation is opaque and can only be produced by the owner\n    /// handle; request bytes cannot supply sparse drives or bypass admission.\n    pub async fn prepare_with_neuron(\n        &self,\n        coordinator: &crate::AgentRunCoordinator,\n        request: CanonicalIntelligenceRunRequestV1,\n        inputs: AgentdIntelligenceOwnerInputsV1,\n        neuron: crate::AgentdNeuronInvocationV1,\n    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {\n        let composition = coordinator.composition().clone();\n        self.prepare_for_composition_with_neuron(&composition, request, inputs, neuron)\n            .await\n    }\n'''
    text = replace_once(text, old_prepare, new_prepare, "add durable prepare entry")

    old_header = '''    pub async fn prepare_for_composition(\n        &self,\n        composition: &crate::RuntimeComposition,\n        request: CanonicalIntelligenceRunRequestV1,\n        mut inputs: AgentdIntelligenceOwnerInputsV1,\n    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {\n        let candidate_ids = request'''
    new_header = '''    pub async fn prepare_for_composition(\n        &self,\n        composition: &crate::RuntimeComposition,\n        request: CanonicalIntelligenceRunRequestV1,\n        inputs: AgentdIntelligenceOwnerInputsV1,\n    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {\n        self.prepare_for_composition_inner(composition, request, inputs, None)\n            .await\n    }\n\n    pub async fn prepare_for_composition_with_neuron(\n        &self,\n        composition: &crate::RuntimeComposition,\n        request: CanonicalIntelligenceRunRequestV1,\n        inputs: AgentdIntelligenceOwnerInputsV1,\n        neuron: crate::AgentdNeuronInvocationV1,\n    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {\n        self.prepare_for_composition_inner(composition, request, inputs, Some(neuron))\n            .await\n    }\n\n    async fn prepare_for_composition_inner(\n        &self,\n        composition: &crate::RuntimeComposition,\n        request: CanonicalIntelligenceRunRequestV1,\n        mut inputs: AgentdIntelligenceOwnerInputsV1,\n        mut durable_neuron: Option<crate::AgentdNeuronInvocationV1>,\n    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {\n        if durable_neuron.as_ref().is_some_and(|neuron| {\n            !neuron.matches_run(&request.run_id, request.snapshot.body_generation().get())\n        }) {\n            return Err(AgentdIntelligenceProductError::RunStartBinding);\n        }\n        let candidate_ids = request'''
    text = replace_once(text, old_header, new_header, "add durable composition entry")

    text = replace_once(
        text,
        '''        let timeout_micros = request.budget.total_micros.min(\n            u64::try_from(crate::control_budget::OWNER_PREPARATION_TIMEOUT.as_micros())\n                .map_err(|_| AgentdIntelligenceProductError::Clock)?,\n        );\n        let started_ms = wall_clock_ms()?;''',
        '''        let timeout_micros = request.budget.total_micros.min(\n            u64::try_from(crate::control_budget::OWNER_PREPARATION_TIMEOUT.as_micros())\n                .map_err(|_| AgentdIntelligenceProductError::Clock)?,\n        );\n        let cancellation = tokio_util::sync::CancellationToken::new();\n        let _cancel_on_drop = cancellation.clone().drop_guard();\n        let neuron_deadline = Instant::now()\n            .checked_add(Duration::from_micros(timeout_micros))\n            .ok_or(AgentdIntelligenceProductError::Clock)?;\n        let started_ms = wall_clock_ms()?;''',
        "create durable neuron stage fence",
    )

    old_worker = '''        let mut worker = self.spawn_owner_work(move || {\n            let mut ports = AgentdOwnerPortsV1::new(\n                inputs,\n                evaluation_session,\n                intuition_host,\n                intuition_current,\n                agent_id,\n                generation,\n                FileBackedFreshnessOracleV1::new(\n                    authority_file.clone(),\n                    authority_verifier.clone(),\n                ),\n            );\n            let mut oracle = FileBackedFreshnessOracleV1::new(authority_file, authority_verifier);'''
    new_worker = '''        let neuron_stage = durable_neuron.take().map(|invocation| {\n            (\n                invocation,\n                neuron_product::NeuronStageAdmission {\n                    snapshot: snapshot.clone(),\n                    authority_file: authority_file.clone(),\n                    authority_verifier: authority_verifier.clone(),\n                    deadline: neuron_deadline,\n                    cancellation,\n                },\n            )\n        });\n        let mut worker = self.spawn_owner_work(move || {\n            let mut ports = AgentdOwnerPortsV1::new(\n                inputs,\n                evaluation_session,\n                intuition_host,\n                intuition_current,\n                agent_id,\n                generation,\n                FileBackedFreshnessOracleV1::new(\n                    authority_file.clone(),\n                    authority_verifier.clone(),\n                ),\n            );\n            if let Some((invocation, admission)) = neuron_stage {\n                ports.install_durable_neuron(invocation, admission);\n            }\n            let mut oracle = FileBackedFreshnessOracleV1::new(authority_file, authority_verifier);'''
    text = replace_once(text, old_worker, new_worker, "install durable neuron stage")

    path.write_text(text)


def main() -> None:
    patch_product()
    patch_runner()
    print("generated durable neuron Agentd product source")


if __name__ == "__main__":
    main()
