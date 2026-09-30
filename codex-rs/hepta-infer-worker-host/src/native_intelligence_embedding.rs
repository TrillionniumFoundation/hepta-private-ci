//! Product embedding for the existing authenticated ObjectiveStart completion.
//! It uses the existing native journal/driver and independent learning sources;
//! it does not install keys, create authority, or start another execution spine.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIntelligenceAdmittedOutcomeV1;
use codex_hepta_agentd::AgentdIntelligenceDecisionAppendV1;
use codex_hepta_agentd::AgentdIntelligenceExecutionHostV1;
use codex_hepta_agentd::AgentdIntelligenceExecutionSummaryV1;
use codex_hepta_agentd::AgentdIntelligenceOutcomeAppendV1;
use codex_hepta_agentd::PreparedAgentdIntelligenceRunV1;
use codex_hepta_agentd::RunReceipt;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;
use tokio::sync::Mutex;
use tokio::sync::Semaphore;
use tokio_util::sync::CancellationToken;

use crate::native_app_server::NativeAdmission;
use crate::native_app_server::NativeRunOutput;
use crate::native_intelligence_product::NativeIntelligenceProductHostV1;
use crate::native_intelligence_product::NativeIntelligenceProductResult;

/// Reads authenticated evidence from existing owners. Implementations cannot
/// replace the observed run or physical output; the product host rechecks both
/// and LedgerWriter verifies the independent identities and exact signed bytes.
pub trait NativeIntelligenceEvidenceSourceV1: Send + Sync {
    fn decision(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
    ) -> NativeIntelligenceProductResult<AgentdIntelligenceDecisionAppendV1>;

    fn outcome(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        terminal: &RunReceipt,
        output: &NativeRunOutput,
    ) -> NativeIntelligenceProductResult<AgentdIntelligenceOutcomeAppendV1>;
}

/// One bounded embedding owns one existing native control journal. Competing
/// ingress requests fail Busy rather than creating an unbounded queue or a
/// replacement operation identity. Another journal requires another owner.
pub struct NativeIntelligenceProductEmbeddingV1 {
    host: NativeIntelligenceProductHostV1,
    control: Mutex<DurableInferenceControl>,
    evidence: Arc<dyn NativeIntelligenceEvidenceSourceV1>,
    evidence_slots: Arc<Semaphore>,
    running_generation: u64,
    cancellation: CancellationToken,
}

impl NativeIntelligenceProductEmbeddingV1 {
    pub fn new(
        host: NativeIntelligenceProductHostV1,
        control: DurableInferenceControl,
        evidence: Arc<dyn NativeIntelligenceEvidenceSourceV1>,
        running_generation: u64,
        cancellation: CancellationToken,
    ) -> Result<Self, AgentdError> {
        if running_generation == 0 {
            return Err(AgentdError::Invalid(
                "zero execution generation".to_string(),
            ));
        }
        Ok(Self {
            host,
            control: Mutex::new(control),
            evidence,
            evidence_slots: Arc::new(Semaphore::new(4)),
            running_generation,
            cancellation,
        })
    }
}

async fn owner_evidence<T: Send + 'static>(
    slots: Arc<Semaphore>,
    read: impl FnOnce() -> NativeIntelligenceProductResult<T> + Send + 'static,
) -> NativeIntelligenceProductResult<T> {
    let permit = slots
        .try_acquire_owned()
        .map_err(|_| "evidence workers busy")?;
    let worker = tokio::task::spawn_blocking(move || {
        let _permit = permit;
        read()
    });
    // Dropping or timing out the receiver never releases a live worker's slot.
    tokio::time::timeout(Duration::from_secs(30), worker)
        .await
        .map_err(|_| "evidence source timed out")?
        .map_err(|_| "evidence source worker failed")?
}

impl AgentdIntelligenceExecutionHostV1 for NativeIntelligenceProductEmbeddingV1 {
    fn owner_generation(&self) -> u64 {
        self.running_generation
    }

    fn execute<'a>(
        &'a self,
        admitted: AgentdIntelligenceAdmittedOutcomeV1,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<AgentdIntelligenceExecutionSummaryV1, AgentdError>>
                + Send
                + 'a,
        >,
    > {
        Box::pin(async move {
            if self.cancellation.is_cancelled() {
                return Err(AgentdError::Protocol(
                    "execution host is stopping".to_string(),
                ));
            }
            let (AgentdIntelligenceAdmittedOutcomeV1::Ready {
                prepared,
                run_receipt,
            }
            | AgentdIntelligenceAdmittedOutcomeV1::ReconciliationRequired {
                prepared,
                run_receipt,
            }) = &admitted
            else {
                return Err(AgentdError::Invalid("non-selected execution".to_string()));
            };
            if run_receipt.generation != self.running_generation {
                return Err(AgentdError::GenerationFenced(
                    "physical host generation".to_string(),
                ));
            }
            let run_id = run_receipt.run_id.clone();
            let mut control = self.control.try_lock().map_err(|_| {
                AgentdError::Protocol(
                    "native execution journal busy; retry the same run".to_string(),
                )
            })?;
            let source = Arc::clone(&self.evidence);
            let prepared = prepared.clone();
            let decision = owner_evidence(Arc::clone(&self.evidence_slots), move || {
                source.decision(&prepared)
            })
            .await
            .map_err(product_error)?;
            let receipt = self
                .host
                .execute(
                    &mut control,
                    NativeAdmission {
                        request_id: run_id.clone(),
                        maximum_in_flight: 1,
                    },
                    admitted,
                    decision,
                    &self.cancellation,
                    |prepared, terminal, output| {
                        let prepared = prepared.clone();
                        let terminal = terminal.clone();
                        let output = output.clone();
                        let source = Arc::clone(&self.evidence);
                        owner_evidence(Arc::clone(&self.evidence_slots), move || {
                            source.outcome(&prepared, &terminal, &output)
                        })
                    },
                )
                .await
                .map_err(product_error)?;
            // The digest reports the actual observation, including Indeterminate;
            // it does not upgrade an acknowledgement or fabricate terminality.
            let bytes = serde_json::to_vec(&receipt.execution)
                .map_err(|error| AgentdError::Protocol(error.to_string()))?;
            Ok(AgentdIntelligenceExecutionSummaryV1 {
                run_id,
                terminal_observed: receipt.execution.terminal_observed,
                outcome_acknowledged: !receipt.reconciliation_required,
                observation_digest: Digest32::of_bytes(&bytes),
            })
        })
    }
}

fn product_error(error: Box<dyn std::error::Error + Send + Sync>) -> AgentdError {
    AgentdError::Protocol(format!("canonical product execution: {error}"))
}
