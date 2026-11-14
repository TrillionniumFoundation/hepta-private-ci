//! Private qualification composition for the entry-aware CognitiveStore owner.
//! No runtime registration or production clock/trust provisioning occurs here.

use std::sync::Arc;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_bao_adapter::BAO_DURABLE_OPERATION_DESTINATION;
use codex_hepta_bao_adapter::BaoAuthBusEvidenceProvider;
use codex_hepta_bao_adapter::BaoClient;
use codex_hepta_bao_adapter::BaoDurableAuthBusAdmission;
use codex_hepta_bao_adapter::BaoFinalUseHost;
use codex_hepta_bao_adapter::BaoReadRequest;
use codex_hepta_cognitive_store::ProductionDispatchFuture;
use codex_hepta_cognitive_store::ProductionDispatchRequest;
use codex_hepta_cognitive_store::ProductionEntryDispatchRequest;
use codex_hepta_cognitive_store::ProductionEntryOutboxTarget;
use codex_hepta_cognitive_store::ProductionTargetOutcome;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// External per-operation policy and independently signed provider evidence.
/// This interface never receives a signing key or creates an owner entry.
trait BaoOperationProvisioner: Send + Sync {
    fn provision(
        &self,
        request: &ProductionDispatchRequest,
        binding: &FinalUseBinding,
    ) -> Result<BaoOperationInputs, String>;
}

struct BaoOperationInputs {
    admission: BaoDurableAuthBusAdmission,
    grant: SignedFinalUseGrant,
    approval: SignedFinalUseApproval,
    evidence: Box<dyn BaoAuthBusEvidenceProvider + Send>,
}

struct BaoOperationTarget {
    client: Arc<BaoClient>,
    registered_host: Arc<BaoFinalUseHost>,
    authbus: Arc<AuthBusAuthorityHost>,
    provisioner: Arc<dyn BaoOperationProvisioner>,
}

// Private state cannot escape as another provider-execution API. It stays bound
// to this concrete target, and the request/operation identity cannot be changed
// after quota preparation. Dropping it performs no asynchronous refund.
struct PreparedBaoOperation {
    read: BaoReadRequest,
    dispatched: QuotaReservation,
    inputs: BaoOperationInputs,
}

fn indeterminate(reason: impl Into<String>) -> ProductionTargetOutcome {
    ProductionTargetOutcome::Indeterminate {
        reason: reason.into(),
    }
}

impl BaoOperationTarget {
    fn read_request(
        &self,
        request: &ProductionDispatchRequest,
        operation_id: &str,
    ) -> Result<(BaoReadRequest, FinalUseBinding), String> {
        if request.occurrence_key != operation_id
            || request.idempotency_key != operation_id
            || request.operation_destination_id != BAO_DURABLE_OPERATION_DESTINATION
            || request.payload_sha256.as_str()
                != Digest32::of_bytes(request.payload_json.as_bytes()).to_string()
        {
            return Err("Bao durable request identity mismatch".into());
        }
        let read: BaoReadRequest = serde_json::from_str(&request.payload_json)
            .map_err(|_| "invalid Bao operation payload")?;
        let binding = self
            .client
            .binding(&read)
            .map_err(|error| error.to_string())?;
        if request.operation_subject_id != binding.subject_id
            || request.operation_scope_sha256.as_str()
                != Digest32::from_array(binding.scope_sha256).to_string()
        {
            return Err("Bao subject/scope mismatch".into());
        }
        Ok((read, binding))
    }

    async fn prepare(
        &self,
        request: &ProductionDispatchRequest,
        operation_id: StableId,
    ) -> Result<PreparedBaoOperation, String> {
        let (read, binding) = self.read_request(request, operation_id.as_str())?;
        let mut inputs = self.provisioner.provision(request, &binding)?;
        let admission = &inputs.admission;
        if admission.policy_revision == 0
            || admission.expected_quota_revision == 0
            || admission.amount == 0
            || admission.expires_at_ms == 0
        {
            return Err("invalid Bao quota admission".into());
        }
        let port = self.authbus.execution();
        let observed = inputs
            .evidence
            .trusted_time()
            .map_err(|error| error.to_string())?;
        let time = port
            .observe_trusted_time_attestation(&observed)
            .await
            .map_err(|error| error.to_string())?;
        let principal = StableId::new(binding.subject_id).map_err(|error| error.to_string())?;
        let action = StableId::new("action:bao-read").map_err(|error| error.to_string())?;
        let scope = Digest32::from_array(binding.scope_sha256);
        let decision = port
            .authorize(
                &principal,
                &action,
                scope,
                admission.policy_revision,
                time.clone(),
            )
            .await
            .map_err(|error| error.to_string())?;
        let effect_digest = self
            .client
            .authbus_effect_digest(&read, &operation_id)
            .map_err(|error| error.to_string())?;
        let reserved = port
            .reserve(
                &decision,
                ReservationRequest {
                    quota_key: admission.quota_key.clone(),
                    operation_id,
                    amount: admission.amount,
                    effect_digest,
                    expected_quota_revision: admission.expected_quota_revision,
                    expires_at_ms: admission.expires_at_ms,
                },
                time,
            )
            .await
            .map_err(|error| error.to_string())?;
        let observed = inputs
            .evidence
            .trusted_time()
            .map_err(|error| error.to_string())?;
        let time = port
            .observe_trusted_time_attestation(&observed)
            .await
            .map_err(|error| error.to_string())?;
        let dispatched = port
            .mark_dispatch_attempted(
                &reserved.reservation_id,
                reserved.revision,
                effect_digest,
                time,
            )
            .await
            .map_err(|error| error.to_string())?;
        Ok(PreparedBaoOperation {
            read,
            dispatched,
            inputs,
        })
    }

    async fn execute(&self, mut prepared: PreparedBaoOperation) -> ProductionTargetOutcome {
        let port = self.authbus.execution();
        let provider = self
            .registered_host
            .consume_kv_v2(
                &self.client,
                &prepared.inputs.grant,
                &prepared.inputs.approval,
                &prepared.read,
            )
            .await;
        let receipt = match provider {
            Ok(receipt) => receipt,
            Err(error) => {
                if let Ok(observed) = prepared.inputs.evidence.trusted_time()
                    && let Ok(time) = port.observe_trusted_time_attestation(&observed).await
                {
                    let _ = port
                        .mark_indeterminate(
                            &prepared.dispatched.reservation_id,
                            prepared.dispatched.revision,
                            time,
                        )
                        .await;
                }
                return indeterminate(format!("registered Bao outcome pending: {error}"));
            }
        };
        let settlement = async {
            let encoded = serde_json::to_vec(&receipt).map_err(|error| error.to_string())?;
            let observed = prepared
                .inputs
                .evidence
                .trusted_time()
                .map_err(|error| error.to_string())?;
            let time = port
                .observe_trusted_time_attestation(&observed)
                .await
                .map_err(|error| error.to_string())?;
            let signed = prepared
                .inputs
                .evidence
                .settlement_evidence(
                    &prepared.dispatched,
                    SettlementStatus::Completed,
                    prepared.inputs.admission.amount,
                    Digest32::of_bytes(&encoded),
                    time.wall_time_ms(),
                )
                .map_err(|error| error.to_string())?;
            port.settle(&signed, time)
                .await
                .map_err(|error| error.to_string())?;
            Ok::<(), String>(())
        }
        .await;
        match settlement {
            Ok(()) => indeterminate(
                "Bao delivery and signed AuthBus settlement observed; independent operation terminal proof required",
            ),
            Err(error) => {
                indeterminate(format!("Bao delivered; signed settlement pending: {error}"))
            }
        }
    }
}

impl ProductionEntryOutboxTarget for BaoOperationTarget {
    fn destination_id(&self) -> &str {
        BAO_DURABLE_OPERATION_DESTINATION
    }

    fn dispatch<'a>(
        &'a self,
        carrier: ProductionEntryDispatchRequest,
    ) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            let ProductionEntryDispatchRequest { request, entry } = carrier;
            let operation_id = match StableId::new(entry.operation_id()) {
                Ok(id) => id,
                Err(error) => return indeterminate(error.to_string()),
            };
            let prepared = match self.prepare(&request, operation_id).await {
                Ok(prepared) => prepared,
                Err(error) => return indeterminate(format!("Bao preparation rejected: {error}")),
            };
            // Final owner validation occurs AFTER every preparation await. The
            // private active guard spans provider I/O, registered delivery and
            // signed settlement. Cancellation leaves both durable owners held
            // for reconciliation, never a fabricated NotApplied/refund result.
            match entry.with_entry(&request, || self.execute(prepared)).await {
                Ok(outcome) => outcome,
                Err(error) => indeterminate(format!("Bao owner entry rejected: {error}")),
            }
        })
    }
}

#[path = "bao_operation_target_tests.rs"]
mod tests;
