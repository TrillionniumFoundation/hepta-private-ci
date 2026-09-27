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
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


write(
    "codex-rs/hepta-agentd/src/intelligence_closed_loop.rs",
    dedent(r'''
    //! Optional product-owned closure of an already admitted canonical run.
    //!
    //! Agentd owns only composition and lifecycle. A configured host reuses the
    //! sole runtime.codex/App Server execution spine and the sole learning-ledger
    //! writer. Request bytes cannot install this host or supply its evidence
    //! factories.

    use std::future::Future;
    use std::pin::Pin;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use crate::AgentdError;
    use crate::AgentdIntelligenceAdmittedOutcomeV1;

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    pub enum AgentdIntelligenceClosedLoopDispositionV1 {
        Terminal,
        Indeterminate,
        Blocked,
    }

    impl AgentdIntelligenceClosedLoopDispositionV1 {
        #[must_use]
        pub const fn objective_disposition(self) -> &'static str {
            match self {
                Self::Terminal => "canonical_terminal",
                Self::Indeterminate => "canonical_indeterminate",
                Self::Blocked => "canonical_blocked",
            }
        }
    }

    #[derive(Clone, Debug, Eq, PartialEq)]
    pub struct AgentdIntelligenceClosedLoopReceiptV1 {
        pub run_id: String,
        pub decision_operation_id: StableId,
        pub outcome_operation_id: Option<StableId>,
        pub provider_terminal_digest: Option<Digest32>,
        pub disposition: AgentdIntelligenceClosedLoopDispositionV1,
    }

    pub trait AgentdIntelligenceClosedLoopHostV1: Send + Sync {
        fn owner_generation(&self) -> u64;

        fn execute<'a>(
            &'a self,
            admitted: AgentdIntelligenceAdmittedOutcomeV1,
        ) -> Pin<
            Box<
                dyn Future<Output = Result<AgentdIntelligenceClosedLoopReceiptV1, AgentdError>>
                    + Send
                    + 'a,
            >,
        >;
    }
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod intelligence_ingress;\n",
    "mod intelligence_closed_loop;\nmod intelligence_ingress;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use intelligence_ingress::AgentdIntelligenceInvocationProviderV1;\n",
    "pub use intelligence_closed_loop::AgentdIntelligenceClosedLoopDispositionV1;\npub use intelligence_closed_loop::AgentdIntelligenceClosedLoopHostV1;\npub use intelligence_closed_loop::AgentdIntelligenceClosedLoopReceiptV1;\npub use intelligence_ingress::AgentdIntelligenceInvocationProviderV1;\n",
)

replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "    intelligence_learning_runtime: Option<crate::AgentdIntelligenceLearningRuntimeConfigV1>,\n}\n",
    "    intelligence_learning_runtime: Option<crate::AgentdIntelligenceLearningRuntimeConfigV1>,\n    intelligence_closed_loop_host:\n        Option<std::sync::Arc<dyn crate::AgentdIntelligenceClosedLoopHostV1>>,\n}\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "            intelligence_learning_runtime: None,\n        })\n",
    "            intelligence_learning_runtime: None,\n            intelligence_closed_loop_host: None,\n        })\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "    pub(crate) fn take_intelligence_learning_runtime(\n        &mut self,\n    ) -> Option<crate::AgentdIntelligenceLearningRuntimeConfigV1> {\n        self.intelligence_learning_runtime.take()\n    }\n\n    pub fn identity(&self) -> &AgentdIdentity {\n",
    dedent(r'''
        pub(crate) fn take_intelligence_learning_runtime(
            &mut self,
        ) -> Option<crate::AgentdIntelligenceLearningRuntimeConfigV1> {
            self.intelligence_learning_runtime.take()
        }

        /// Install the product host that closes an admitted run through the
        /// existing physical execution and learning owners. The complete
        /// canonical and learning profiles must already be present.
        pub fn with_intelligence_closed_loop_host(
            mut self,
            host: std::sync::Arc<dyn crate::AgentdIntelligenceClosedLoopHostV1>,
        ) -> Result<Self, AgentdError> {
            if self.intelligence_product_runner.is_none()
                || self.intelligence_invocation_provider.is_none()
                || self.intelligence_learning_runtime.is_none()
            {
                return Err(AgentdError::Invalid(
                    "intelligence closed loop requires canonical runner, provider and learning runtime"
                        .to_string(),
                ));
            }
            if self.intelligence_closed_loop_host.is_some() {
                return Err(AgentdError::Invalid(
                    "intelligence closed-loop host already configured".to_string(),
                ));
            }
            let expected_generation = self
                .identity
                .spawn_generation
                .checked_add(1)
                .ok_or_else(|| AgentdError::Invalid("Agentd running generation overflow".to_string()))?;
            if host.owner_generation() != expected_generation {
                return Err(AgentdError::GenerationFenced(format!(
                    "intelligence closed-loop host generation {} does not match expected Running generation {expected_generation}",
                    host.owner_generation()
                )));
            }
            self.intelligence_closed_loop_host = Some(host);
            Ok(self)
        }

        pub(crate) fn intelligence_closed_loop_host(
            &self,
        ) -> Option<std::sync::Arc<dyn crate::AgentdIntelligenceClosedLoopHostV1>> {
            self.intelligence_closed_loop_host.clone()
        }

        pub fn identity(&self) -> &AgentdIdentity {
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    "    pub(crate) intelligence_invocation:\n        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,\n",
    "    pub(crate) intelligence_invocation:\n        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,\n    pub(crate) intelligence_closed_loop:\n        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceClosedLoopHostV1>>,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    "            intelligence_invocation: std::sync::OnceLock::new(),\n",
    "            intelligence_invocation: std::sync::OnceLock::new(),\n            intelligence_closed_loop: std::sync::OnceLock::new(),\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    "        let invocation = provider.build(&self.identity, record)?;\n        invocation.validate(&self.identity, record)?;\n",
    "        let invocation = runner\n            .build_invocation_bounded(\n                Arc::clone(provider),\n                self.identity.clone(),\n                record.clone(),\n            )\n            .await\n            .map_err(|error| {\n                AgentdError::Protocol(format!(\n                    \"canonical intelligence invocation failed: {error}\"\n                ))\n            })?;\n        invocation.validate(&self.identity, record)?;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    "    /// Revalidate a durable run-start record against the current owner trust,\n",
    dedent(r'''
        /// Execute an already admitted canonical run through the configured
        /// product closure. Generation is checked before and after external work;
        /// a successor generation never inherits the old host's authority.
        pub(crate) async fn execute_canonical_intelligence(
            &self,
            admitted: crate::AgentdIntelligenceAdmittedOutcomeV1,
        ) -> Result<Option<crate::AgentdIntelligenceClosedLoopReceiptV1>, AgentdError> {
            let Some(host) = self.intelligence_closed_loop.get() else {
                return Ok(None);
            };
            self.refresh_generation()?;
            let before = self.current_generation()?;
            if before != host.owner_generation() {
                self.mark_fenced();
                return Err(AgentdError::GenerationFenced(format!(
                    "intelligence closed-loop host generation {} does not match current generation {before}",
                    host.owner_generation()
                )));
            }
            let receipt = host.execute(admitted).await?;
            self.refresh_generation()?;
            let after = self.current_generation()?;
            if after != before {
                self.mark_fenced();
                return Err(AgentdError::GenerationFenced(
                    "Agentd generation changed during intelligence closed-loop execution"
                        .to_string(),
                ));
            }
            Ok(Some(receipt))
        }

        /// Revalidate a durable run-start record against the current owner trust,
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-agentd/src/runtime.rs",
    "    let intelligence_invocation = config.intelligence_invocation_provider();\n",
    "    let intelligence_invocation = config.intelligence_invocation_provider();\n    let intelligence_closed_loop = config.intelligence_closed_loop_host();\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/runtime.rs",
    "    if let Some(current) = retrieval_context {\n",
    dedent(r'''
        if let Some(host) = intelligence_closed_loop {
            state.intelligence_closed_loop.set(host).map_err(|_| {
                AgentdError::Invalid("intelligence closed-loop host already attached".to_string())
            })?;
        }
        if let Some(current) = retrieval_context {
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-agentd/src/objective_runtime.rs",
    dedent(r'''
                    Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready { .. }) => {
                        "canonical_ready"
                    }
    ''').lstrip(),
    dedent(r'''
                    Some(outcome @ crate::AgentdIntelligenceAdmittedOutcomeV1::Ready { .. }) => {
                        match agentd.execute_canonical_intelligence(outcome).await? {
                            Some(receipt) => receipt.disposition.objective_disposition(),
                            None => "canonical_ready",
                        }
                    }
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    InvalidWorkerPolicy,\n    Run(crate::AgentRunError),\n",
    "    InvalidWorkerPolicy,\n    Invocation(String),\n    Run(crate::AgentRunError),\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "    pub async fn prepare(\n",
    dedent(r'''
        /// Build the host-owned seven-owner invocation inside the same bounded,
        /// independently supervised worker pool as cognition. Dropping the
        /// request future cannot free the permit or disarm the watchdog.
        pub(crate) async fn build_invocation_bounded(
            &self,
            provider: Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>,
            identity: crate::AgentdIdentity,
            record: codex_hepta_learning_ledger::RunStartRecordV1,
        ) -> Result<crate::AgentdIntelligenceInvocationV1, AgentdIntelligenceProductError> {
            let run_identity = crate::AgentdIntelligenceRunIdentityV1::from_run_start(
                &identity,
                &record,
            )
            .map_err(|error| AgentdIntelligenceProductError::Invocation(error.to_string()))?;
            let now = wall_clock_ms()?;
            let remaining_ms = run_identity
                .deadline_ms
                .checked_sub(now)
                .filter(|value| *value != 0)
                .ok_or(AgentdIntelligenceProductError::RunIdentityMismatch)?;
            let mut worker = self.spawn_owner_work(move || provider.build(&identity, &record))?;
            let joined = match timeout(Duration::from_millis(remaining_ms), &mut worker.handle).await {
                Ok(value) => value,
                Err(_) => {
                    worker.mark_timed_out();
                    worker.handle.abort();
                    self.telemetry.record_request_timeout();
                    self.arm_hard_timeout_exit(Arc::clone(&worker.finished));
                    return Err(AgentdIntelligenceProductError::TimedOut);
                }
            };
            match joined {
                Ok(Ok(invocation)) => Ok(invocation),
                Ok(Err(error)) => Err(AgentdIntelligenceProductError::Invocation(error.to_string())),
                Err(_) => {
                    self.telemetry.record_worker_crash();
                    Err(AgentdIntelligenceProductError::WorkerCrashed)
                }
            }
        }

        pub async fn prepare(
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_intelligence_product.rs",
    "    use codex_hepta_agentd::AgentdIntelligenceAdmittedOutcomeV1;\n",
    "    use codex_hepta_agentd::AgentdError;\n    use codex_hepta_agentd::AgentdIntelligenceAdmittedOutcomeV1;\n    use codex_hepta_agentd::AgentdIntelligenceClosedLoopDispositionV1;\n    use codex_hepta_agentd::AgentdIntelligenceClosedLoopHostV1;\n    use codex_hepta_agentd::AgentdIntelligenceClosedLoopReceiptV1;\n",
)

with (ROOT / "codex-rs/hepta-infer-worker-host/src/native_intelligence_product.rs").open(
    "a", encoding="utf-8"
) as handle:
    handle.write(
        dedent(r'''

        /// Host-owned production of authenticated learning requests. Implementors
        /// read current evidence/trust from their owners; request bytes cannot
        /// provide this object.
        pub trait NativeIntelligenceProductEvidenceFactoryV1: Send + Sync {
            fn decision(
                &self,
                prepared: &PreparedAgentdIntelligenceRunV1,
            ) -> NativeIntelligenceProductResult<AgentdIntelligenceDecisionAppendV1>;

            fn outcome(
                &self,
                prepared: &PreparedAgentdIntelligenceRunV1,
                terminal: &RunReceipt,
                execution: &NativeRunOutput,
            ) -> NativeIntelligenceProductResult<AgentdIntelligenceOutcomeAppendV1>;
        }

        /// Executable host installed into Agentd after the canonical runner,
        /// invocation provider and learning runtime have been composed.
        pub struct ConfiguredNativeIntelligenceProductHostV1 {
            product: NativeIntelligenceProductHostV1,
            control: tokio::sync::Mutex<DurableInferenceControl>,
            maximum_in_flight: usize,
            owner_generation: u64,
            evidence: Arc<dyn NativeIntelligenceProductEvidenceFactoryV1>,
            cancellation: CancellationToken,
        }

        impl ConfiguredNativeIntelligenceProductHostV1 {
            pub fn new(
                product: NativeIntelligenceProductHostV1,
                control: DurableInferenceControl,
                maximum_in_flight: usize,
                owner_generation: u64,
                evidence: Arc<dyn NativeIntelligenceProductEvidenceFactoryV1>,
                cancellation: CancellationToken,
            ) -> NativeIntelligenceProductResult<Self> {
                if maximum_in_flight == 0 || maximum_in_flight > 256 || owner_generation == 0 {
                    return Err("invalid native intelligence product capacity or generation".into());
                }
                Ok(Self {
                    product,
                    control: tokio::sync::Mutex::new(control),
                    maximum_in_flight,
                    owner_generation,
                    evidence,
                    cancellation,
                })
            }
        }

        impl AgentdIntelligenceClosedLoopHostV1 for ConfiguredNativeIntelligenceProductHostV1 {
            fn owner_generation(&self) -> u64 {
                self.owner_generation
            }

            fn execute<'a>(
                &'a self,
                admitted: AgentdIntelligenceAdmittedOutcomeV1,
            ) -> std::pin::Pin<
                Box<
                    dyn std::future::Future<
                            Output = Result<AgentdIntelligenceClosedLoopReceiptV1, AgentdError>,
                        > + Send
                        + 'a,
                >,
            > {
                Box::pin(async move {
                    let (run_id, decision_request) = match &admitted {
                        AgentdIntelligenceAdmittedOutcomeV1::Ready { prepared, .. } => {
                            let run_id = prepared.run_snapshot().run_id;
                            let request = self.evidence.decision(prepared).map_err(|error| {
                                AgentdError::Protocol(format!(
                                    "intelligence Decision evidence factory failed: {error}"
                                ))
                            })?;
                            (run_id, request)
                        }
                        AgentdIntelligenceAdmittedOutcomeV1::Abstained
                        | AgentdIntelligenceAdmittedOutcomeV1::SlowPath => {
                            return Err(AgentdError::Invalid(
                                "non-ready intelligence outcome entered physical closure".to_string(),
                            ));
                        }
                    };
                    let evidence = Arc::clone(&self.evidence);
                    let cancellation = self.cancellation.child_token();
                    let mut control = self.control.lock().await;
                    let product = self
                        .product
                        .execute(
                            &mut control,
                            NativeAdmission {
                                request_id: run_id.clone(),
                                maximum_in_flight: self.maximum_in_flight,
                            },
                            admitted,
                            decision_request,
                            &cancellation,
                            move |prepared, terminal, execution| {
                                evidence.outcome(prepared, terminal, execution)
                            },
                        )
                        .await
                        .map_err(|error| {
                            AgentdError::Protocol(format!(
                                "native intelligence product closure failed: {error}"
                            ))
                        })?;
                    let provider_terminal_digest = if product.execution.terminal_observed {
                        Some(native_provider_terminal_digest_v1(&product.execution).map_err(
                            |error| {
                                AgentdError::Protocol(format!(
                                    "native terminal digest failed: {error}"
                                ))
                            },
                        )?)
                    } else {
                        None
                    };
                    let outcome_operation_id = product
                        .outcome
                        .as_ref()
                        .map(|receipt| receipt.operation_id.clone());
                    let disposition = if product.outcome.is_some() {
                        AgentdIntelligenceClosedLoopDispositionV1::Terminal
                    } else {
                        AgentdIntelligenceClosedLoopDispositionV1::Indeterminate
                    };
                    Ok(AgentdIntelligenceClosedLoopReceiptV1 {
                        run_id,
                        decision_operation_id: product.decision.operation_id,
                        outcome_operation_id,
                        provider_terminal_digest,
                        disposition,
                    })
                })
            }
        }
        ''')
    )
