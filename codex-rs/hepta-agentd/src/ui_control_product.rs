use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::AuthPolicyStore;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_operations::OperationContextV1;
use codex_hepta_operations::OperationKey;
use codex_hepta_operations::OperationState;
use codex_hepta_operations::OutboxIntent;
use codex_hepta_operations::ReconciliationOutcome;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::ui_control_wire::UiControlEffectKind;
use crate::ui_control_wire::UiControlWireError;
use crate::ui_control_wire::VerifiedUiControlRequest;
use crate::ui_control_wire::verify_ui_control_request;

const OUTBOX_LEASE_MS: u64 = 30_000;

pub(crate) struct UiControlProductCommand {
    pub method: String,
    pub request_json: Vec<u8>,
    pub auth_message: SignedMessage,
    pub policy_revision: Revision,
    pub final_use_grant: SignedFinalUseGrant,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct UiControlEffectRequest {
    pub operation_id: StableId,
    pub semantic_digest: Digest32,
    pub effect: UiControlEffectKind,
    pub action_id: StableId,
    pub resource_id: StableId,
    pub expected_revision: Revision,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum UiControlDriverObservation {
    Accepted { receipt_digest: Digest32 },
    Terminal {
        outcome: ReconciliationOutcome,
        outcome_digest: Digest32,
    },
    NotContacted { proof_digest: Digest32 },
    Indeterminate { reason_digest: Digest32 },
}

pub(crate) trait UiControlEffectDriver: Send {
    fn dispatch(&mut self, request: &UiControlEffectRequest) -> UiControlDriverObservation;
    fn reconcile(&mut self, request: &UiControlEffectRequest) -> UiControlDriverObservation;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum UiControlGatewayDisposition {
    Pending {
        operation_id: StableId,
        semantic_digest: Digest32,
        acknowledgement_digest: Digest32,
    },
    Terminal {
        operation_id: StableId,
        semantic_digest: Digest32,
        outcome: ReconciliationOutcome,
        outcome_digest: Digest32,
    },
    RequiresReconciliation {
        operation_id: StableId,
        semantic_digest: Digest32,
    },
}

#[derive(Debug)]
pub(crate) enum UiControlProductError {
    Wire(UiControlWireError),
    Authentication(String),
    Policy(String),
    Denied,
    Durable(String),
    Authority(String),
    DriverUnavailable,
    Clock,
    Corrupt(&'static str),
}

impl fmt::Display for UiControlProductError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Wire(error) => error.fmt(f),
            Self::Authentication(message) => write!(f, "ui.control authentication failed: {message}"),
            Self::Policy(message) => write!(f, "ui.control policy failed: {message}"),
            Self::Denied => f.write_str("ui.control policy denied the operation"),
            Self::Durable(message) => write!(f, "ui.control durable state failed: {message}"),
            Self::Authority(message) => write!(f, "ui.control final-use authority failed: {message}"),
            Self::DriverUnavailable => f.write_str("ui.control destination driver unavailable"),
            Self::Clock => f.write_str("ui.control clock unavailable"),
            Self::Corrupt(message) => write!(f, "ui.control durable state corrupt: {message}"),
        }
    }
}

impl std::error::Error for UiControlProductError {}

impl From<UiControlWireError> for UiControlProductError {
    fn from(value: UiControlWireError) -> Self {
        Self::Wire(value)
    }
}

pub(crate) struct UiControlProductGateway {
    evidence: HeptaEvidenceStore,
    policy: AuthPolicyStore,
    operations: DurableOperationStore,
    final_use: FinalUseAuthority,
    agent_id: StableId,
    owner_generation: Generation,
    driver: Arc<Mutex<Box<dyn UiControlEffectDriver>>>,
}

impl UiControlProductGateway {
    pub(crate) fn new(
        evidence: HeptaEvidenceStore,
        policy: AuthPolicyStore,
        operations: DurableOperationStore,
        final_use: FinalUseAuthority,
        agent_id: StableId,
        owner_generation: Generation,
        driver: Box<dyn UiControlEffectDriver>,
    ) -> Self {
        Self {
            evidence,
            policy,
            operations,
            final_use,
            agent_id,
            owner_generation,
            driver: Arc::new(Mutex::new(driver)),
        }
    }

    pub(crate) async fn execute(
        &self,
        issuer: &IssuerRegistration,
        command: UiControlProductCommand,
    ) -> Result<UiControlGatewayDisposition, UiControlProductError> {
        let verified = verify_ui_control_request(&command.method, &command.request_json)?;
        let auth_scope = auth_scope_digest(&self.agent_id);
        let auth_receipt = self
            .evidence
            .admit_authbus_message(
                issuer,
                &command.auth_message,
                auth_scope,
                verified.semantic_digest,
            )
            .await
            .map_err(|error| UiControlProductError::Authentication(error.to_string()))?;
        if auth_receipt.authority.grants_any() {
            return Err(UiControlProductError::Corrupt(
                "AuthBus receipt unexpectedly grants authority",
            ));
        }

        let decision = self
            .policy
            .authorize(
                &auth_receipt.subject_id,
                &verified.action_id,
                &verified.resource_id,
                command.policy_revision,
            )
            .await
            .map_err(|error| UiControlProductError::Policy(error.to_string()))?;
        if !decision.allowed {
            return Err(UiControlProductError::Denied);
        }

        if let Some(existing) = self
            .operations
            .get(&verified.operation_id)
            .await
            .map_err(durable)?
        {
            if existing.key.payload_digest != verified.semantic_digest {
                return Err(UiControlProductError::Corrupt(
                    "operation identity reused with changed semantic digest",
                ));
            }
            return Ok(UiControlGatewayDisposition::RequiresReconciliation {
                operation_id: verified.operation_id,
                semantic_digest: verified.semantic_digest,
            });
        }

        self.operations
            .begin(
                OperationKey {
                    id: verified.operation_id.clone(),
                    payload_digest: verified.semantic_digest,
                },
                self.owner_generation,
            )
            .await
            .map_err(durable)?;
        self.operations
            .bind_context(&OperationContextV1 {
                operation_id: verified.operation_id.clone(),
                action_id: verified.action_id.clone(),
                resource_id: verified.resource_id.clone(),
                expected_revision: verified.expected_revision,
                semantic_digest: verified.semantic_digest,
            })
            .await
            .map_err(durable)?;

        let destination_id = destination_id(&self.agent_id)?;
        let effect_scope = effect_scope_digest(&self.agent_id, &verified);
        let effect_payload = effect_payload_digest(&verified, effect_scope);
        let binding = FinalUseBinding {
            subject_id: auth_receipt.subject_id.as_str().to_string(),
            destination_id: destination_id.as_str().to_string(),
            request_sha256: verified.semantic_digest.into_array(),
            scope_sha256: effect_scope.into_array(),
            payload_sha256: effect_payload.into_array(),
        };
        let outbox_id = outbox_id(verified.semantic_digest)?;
        let intent = OutboxIntent {
            intent_id: outbox_id.clone(),
            operation_id: verified.operation_id.clone(),
            destination: destination_id.clone(),
            payload_digest: effect_payload,
        };
        self.operations
            .enqueue_outbox(&intent)
            .await
            .map_err(durable)?;

        let claim_owner = claim_owner(&auth_receipt.message_id)?;
        let now_ms = unix_ms()?;
        self.operations
            .claim_outbox(
                &outbox_id,
                claim_owner.clone(),
                self.owner_generation,
                now_ms,
                OUTBOX_LEASE_MS,
            )
            .await
            .map_err(durable)?;

        let grant_digest = Digest32::of_bytes(
            &command
                .final_use_grant
                .grant
                .signing_bytes()
                .map_err(|error| UiControlProductError::Authority(error.to_string()))?,
        );
        let signature_digest = Digest32::of_bytes(&command.final_use_grant.signature);
        let authorization_witness = Digest32::of_parts(&[
            b"hepta.ui-control.authorization-witness.v1\0",
            auth_receipt.envelope_digest.as_array(),
            decision.decision_digest.as_array(),
            grant_digest.as_array(),
            signature_digest.as_array(),
        ]);
        let authority_generation = Generation::new(command.final_use_grant.grant.authority_epoch)
            .map_err(|error| UiControlProductError::Authority(error.to_string()))?;
        let token = self
            .final_use
            .claim(&command.final_use_grant, &binding)
            .map_err(|error| UiControlProductError::Authority(error.to_string()))?;
        self.operations
            .record_authorized(
                &verified.operation_id,
                authorization_witness,
                authority_generation,
            )
            .await
            .map_err(durable)?;

        let dispatch_digest = Digest32::of_parts(&[
            b"hepta.ui-control.dispatch.v1\0",
            verified.semantic_digest.as_array(),
            effect_scope.as_array(),
            effect_payload.as_array(),
            outbox_id.as_str().as_bytes(),
        ]);
        self.operations
            .record_dispatch(&verified.operation_id, dispatch_digest)
            .await
            .map_err(durable)?;

        let effect_request = effect_request(&verified);
        let driver = Arc::clone(&self.driver);
        let observation = match self.final_use.with_verified_use(token, &binding, || {
            match driver.lock() {
                Ok(mut driver) => driver.dispatch(&effect_request),
                Err(_) => UiControlDriverObservation::Indeterminate {
                    reason_digest: Digest32::of_bytes(b"ui-control-driver-lock-poisoned"),
                },
            }
        }) {
            Ok(observation) => observation,
            Err(error) => {
                let error_text = format!("{error:?}");
                let proof = Digest32::of_parts(&[
                    b"hepta.ui-control.final-use-pre-dispatch-rejection.v1\0",
                    verified.semantic_digest.as_array(),
                    error_text.as_bytes(),
                ]);
                let record = self
                    .operations
                    .observe_terminal(
                        &verified.operation_id,
                        ReconciliationOutcome::NotApplied,
                        proof,
                        self.owner_generation,
                    )
                    .await
                    .map_err(durable)?;
                let outcome_digest = terminal_digest(&record.state)?;
                return Ok(UiControlGatewayDisposition::Terminal {
                    operation_id: verified.operation_id,
                    semantic_digest: verified.semantic_digest,
                    outcome: ReconciliationOutcome::NotApplied,
                    outcome_digest,
                });
            }
        };

        self.apply_driver_observation(
            &verified,
            &outbox_id,
            &claim_owner,
            observation,
            now_ms,
        )
        .await
    }

    pub(crate) async fn reconcile(
        &self,
        operation_id: &StableId,
    ) -> Result<UiControlGatewayDisposition, UiControlProductError> {
        let record = self
            .operations
            .get(operation_id)
            .await
            .map_err(durable)?
            .ok_or(UiControlProductError::Corrupt("operation is missing"))?;
        let context = self
            .operations
            .get_context(operation_id)
            .await
            .map_err(durable)?
            .ok_or(UiControlProductError::Corrupt(
                "operation reconciliation context is missing",
            ))?;
        if record.key.payload_digest != context.semantic_digest {
            return Err(UiControlProductError::Corrupt(
                "operation and reconciliation context digest mismatch",
            ));
        }
        if let Some((outcome, digest)) = terminal_outcome(&record.state) {
            return Ok(UiControlGatewayDisposition::Terminal {
                operation_id: operation_id.clone(),
                semantic_digest: context.semantic_digest,
                outcome,
                outcome_digest: digest,
            });
        }
        if matches!(
            record.state,
            OperationState::Pending | OperationState::Authorized { .. }
        ) {
            let proof = Digest32::of_parts(&[
                b"hepta.ui-control.no-dispatch-record.v1\0",
                context.semantic_digest.as_array(),
                &record.revision.get().to_be_bytes(),
            ]);
            let terminal = self
                .operations
                .observe_terminal(
                    operation_id,
                    ReconciliationOutcome::NotApplied,
                    proof,
                    self.owner_generation,
                )
                .await
                .map_err(durable)?;
            return Ok(UiControlGatewayDisposition::Terminal {
                operation_id: operation_id.clone(),
                semantic_digest: context.semantic_digest,
                outcome: ReconciliationOutcome::NotApplied,
                outcome_digest: terminal_digest(&terminal.state)?,
            });
        }

        let effect = effect_from_context(&context)?;
        let request = UiControlEffectRequest {
            operation_id: operation_id.clone(),
            semantic_digest: context.semantic_digest,
            effect,
            action_id: context.action_id.clone(),
            resource_id: context.resource_id.clone(),
            expected_revision: context.expected_revision,
        };
        let observation = self
            .driver
            .lock()
            .map_err(|_| UiControlProductError::DriverUnavailable)?
            .reconcile(&request);
        match observation {
            UiControlDriverObservation::Terminal {
                outcome,
                outcome_digest,
            } => {
                self.operations
                    .observe_terminal(
                        operation_id,
                        outcome,
                        outcome_digest,
                        self.owner_generation,
                    )
                    .await
                    .map_err(durable)?;
                Ok(UiControlGatewayDisposition::Terminal {
                    operation_id: operation_id.clone(),
                    semantic_digest: context.semantic_digest,
                    outcome,
                    outcome_digest,
                })
            }
            UiControlDriverObservation::NotContacted { proof_digest } => {
                self.operations
                    .observe_terminal(
                        operation_id,
                        ReconciliationOutcome::NotApplied,
                        proof_digest,
                        self.owner_generation,
                    )
                    .await
                    .map_err(durable)?;
                Ok(UiControlGatewayDisposition::Terminal {
                    operation_id: operation_id.clone(),
                    semantic_digest: context.semantic_digest,
                    outcome: ReconciliationOutcome::NotApplied,
                    outcome_digest: proof_digest,
                })
            }
            UiControlDriverObservation::Accepted { .. }
            | UiControlDriverObservation::Indeterminate { .. } => {
                Ok(UiControlGatewayDisposition::RequiresReconciliation {
                    operation_id: operation_id.clone(),
                    semantic_digest: context.semantic_digest,
                })
            }
        }
    }

    async fn apply_driver_observation(
        &self,
        verified: &VerifiedUiControlRequest,
        outbox_id: &StableId,
        claim_owner: &StableId,
        observation: UiControlDriverObservation,
        now_ms: u64,
    ) -> Result<UiControlGatewayDisposition, UiControlProductError> {
        match observation {
            UiControlDriverObservation::Accepted { receipt_digest } => {
                if self
                    .operations
                    .acknowledge_outbox(
                        outbox_id,
                        claim_owner,
                        self.owner_generation,
                        receipt_digest,
                        now_ms,
                    )
                    .await
                    .is_err()
                {
                    self.operations
                        .mark_indeterminate(
                            &verified.operation_id,
                            Digest32::of_bytes(b"ui-control-outbox-ack-persistence-failed"),
                        )
                        .await
                        .map_err(durable)?;
                    return Ok(UiControlGatewayDisposition::RequiresReconciliation {
                        operation_id: verified.operation_id.clone(),
                        semantic_digest: verified.semantic_digest,
                    });
                }
                Ok(UiControlGatewayDisposition::Pending {
                    operation_id: verified.operation_id.clone(),
                    semantic_digest: verified.semantic_digest,
                    acknowledgement_digest: receipt_digest,
                })
            }
            UiControlDriverObservation::Terminal {
                outcome,
                outcome_digest,
            } => {
                let _ = self
                    .operations
                    .acknowledge_outbox(
                        outbox_id,
                        claim_owner,
                        self.owner_generation,
                        outcome_digest,
                        now_ms,
                    )
                    .await;
                self.operations
                    .observe_terminal(
                        &verified.operation_id,
                        outcome,
                        outcome_digest,
                        self.owner_generation,
                    )
                    .await
                    .map_err(durable)?;
                Ok(UiControlGatewayDisposition::Terminal {
                    operation_id: verified.operation_id.clone(),
                    semantic_digest: verified.semantic_digest,
                    outcome,
                    outcome_digest,
                })
            }
            UiControlDriverObservation::NotContacted { proof_digest } => {
                self.operations
                    .observe_terminal(
                        &verified.operation_id,
                        ReconciliationOutcome::NotApplied,
                        proof_digest,
                        self.owner_generation,
                    )
                    .await
                    .map_err(durable)?;
                Ok(UiControlGatewayDisposition::Terminal {
                    operation_id: verified.operation_id.clone(),
                    semantic_digest: verified.semantic_digest,
                    outcome: ReconciliationOutcome::NotApplied,
                    outcome_digest: proof_digest,
                })
            }
            UiControlDriverObservation::Indeterminate { reason_digest } => {
                self.operations
                    .mark_indeterminate(&verified.operation_id, reason_digest)
                    .await
                    .map_err(durable)?;
                Ok(UiControlGatewayDisposition::RequiresReconciliation {
                    operation_id: verified.operation_id.clone(),
                    semantic_digest: verified.semantic_digest,
                })
            }
        }
    }
}

fn effect_request(verified: &VerifiedUiControlRequest) -> UiControlEffectRequest {
    UiControlEffectRequest {
        operation_id: verified.operation_id.clone(),
        semantic_digest: verified.semantic_digest,
        effect: verified.effect,
        action_id: verified.action_id.clone(),
        resource_id: verified.resource_id.clone(),
        expected_revision: verified.expected_revision,
    }
}

fn effect_from_context(
    context: &OperationContextV1,
) -> Result<UiControlEffectKind, UiControlProductError> {
    match context.action_id.as_str() {
        "request_retry" => Ok(UiControlEffectKind::Restart),
        "runtime_stop" => Ok(UiControlEffectKind::Stop),
        _ => Err(UiControlProductError::Corrupt(
            "durable operation action is not a supported product effect",
        )),
    }
}

fn auth_scope_digest(agent_id: &StableId) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ui-control.auth-scope.v1\0",
        agent_id.as_str().as_bytes(),
    ])
}

fn effect_scope_digest(
    agent_id: &StableId,
    request: &VerifiedUiControlRequest,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ui-control.effect-scope.v1\0",
        agent_id.as_str().as_bytes(),
        request.action_id.as_str().as_bytes(),
        request.resource_id.as_str().as_bytes(),
        &request.expected_revision.get().to_be_bytes(),
    ])
}

fn effect_payload_digest(
    request: &VerifiedUiControlRequest,
    scope: Digest32,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ui-control.effect-payload.v1\0",
        request.semantic_digest.as_array(),
        scope.as_array(),
    ])
}

fn destination_id(agent_id: &StableId) -> Result<StableId, UiControlProductError> {
    let digest = Digest32::of_bytes(agent_id.as_str().as_bytes());
    StableId::new(format!("supervisord:{digest}"))
        .map_err(|_| UiControlProductError::Corrupt("destination identity is invalid"))
}

fn outbox_id(semantic_digest: Digest32) -> Result<StableId, UiControlProductError> {
    StableId::new(format!("uiout:{semantic_digest}"))
        .map_err(|_| UiControlProductError::Corrupt("outbox identity is invalid"))
}

fn claim_owner(message_id: &StableId) -> Result<StableId, UiControlProductError> {
    let digest = Digest32::of_bytes(message_id.as_str().as_bytes());
    StableId::new(format!("uiclaim:{digest}"))
        .map_err(|_| UiControlProductError::Corrupt("claim owner identity is invalid"))
}

fn terminal_outcome(state: &OperationState) -> Option<(ReconciliationOutcome, Digest32)> {
    match state {
        OperationState::Applied { outcome_digest } => {
            Some((ReconciliationOutcome::Applied, *outcome_digest))
        }
        OperationState::NotApplied { outcome_digest } => {
            Some((ReconciliationOutcome::NotApplied, *outcome_digest))
        }
        OperationState::Quarantined { reason_digest } => {
            Some((ReconciliationOutcome::Quarantined, *reason_digest))
        }
        _ => None,
    }
}

fn terminal_digest(state: &OperationState) -> Result<Digest32, UiControlProductError> {
    terminal_outcome(state)
        .map(|(_, digest)| digest)
        .ok_or(UiControlProductError::Corrupt(
            "expected durable terminal operation state",
        ))
}

fn unix_ms() -> Result<u64, UiControlProductError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| UiControlProductError::Clock)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| UiControlProductError::Clock)
}

fn durable(error: impl fmt::Display) -> UiControlProductError {
    UiControlProductError::Durable(error.to_string())
}


#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;
    use std::collections::VecDeque;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    use codex_hepta_authbus::PolicyRevisionDraftV1;
    use codex_hepta_authbus::PolicyRuleV1;
    use codex_hepta_authbus::SignedMessageClaims;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use tempfile::TempDir;

    use super::*;

    const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
    const SEMANTIC: &str =
        "fbdaf3b3aa6869642a07aafbdb0cdba25a3765f32da2f56a7062fdbed8b6ef58";

    fn operation_request(digest: &str) -> Vec<u8> {
        format!(
            r#"{{"connectionGeneration":2,"displayedRevision":4,"intent":{{"action":"request_retry","authorityGranted":false,"directStoreWrite":false,"expectedRevision":7,"kind":"UiOperationProposalV1","operationId":"operation.1","subjectId":"runtime.agentd"}},"operationId":"operation.1","runtimeDigest":"{D1}","runtimeGeneration":3,"schema":"hepta.ui-control.transport-request.v1","semanticDigest":"{digest}","sessionId":"session.1"}}"#
        )
        .into_bytes()
    }

    fn sqlite_config(temp: &TempDir) -> SqliteConfig {
        SqliteConfig::new_for_testing(
            AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp"),
        )
    }

    fn signed_auth(
        agent_id: &StableId,
        semantic: Digest32,
        sequence: u64,
    ) -> (IssuerRegistration, SignedMessage) {
        let key = SigningKey::from_bytes(&[71; 32]);
        let issuer = IssuerRegistration {
            issuer_id: StableId::new("issuer:ui-control").expect("issuer"),
            key_epoch: Generation::new(1).expect("epoch"),
            verifying_key: key.verifying_key(),
            revoked: false,
        };
        let claims = SignedMessageClaims {
            issuer_id: issuer.issuer_id.clone(),
            key_epoch: issuer.key_epoch,
            message_id: StableId::new(format!("message:ui:{sequence}")).expect("message"),
            subject_id: StableId::new("operator.alice").expect("subject"),
            scope_digest: auth_scope_digest(agent_id),
            payload_digest: semantic,
            sequence,
            expires_at_ms: unix_ms().expect("clock") + 60_000,
        };
        let signature = key.sign(&claims.signing_bytes()).to_bytes();
        (issuer, SignedMessage { claims, signature })
    }

    fn signed_final_use(
        authority_key: &SigningKey,
        binding: FinalUseBinding,
        nonce: u8,
    ) -> SignedFinalUseGrant {
        let now = unix_ms().expect("clock");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".to_string(),
            authority_epoch: 9,
            grant_id: format!("ui-control-grant-{nonce}"),
            nonce: [nonce; 32],
            binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = authority_key
            .sign(&grant.signing_bytes().expect("grant bytes"))
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }

    struct ScriptedDriver {
        dispatches: Arc<AtomicUsize>,
        dispatch: VecDeque<UiControlDriverObservation>,
        reconcile: VecDeque<UiControlDriverObservation>,
    }

    impl UiControlEffectDriver for ScriptedDriver {
        fn dispatch(&mut self, _request: &UiControlEffectRequest) -> UiControlDriverObservation {
            self.dispatches.fetch_add(1, Ordering::SeqCst);
            self.dispatch
                .pop_front()
                .expect("scripted dispatch observation")
        }

        fn reconcile(&mut self, _request: &UiControlEffectRequest) -> UiControlDriverObservation {
            self.reconcile
                .pop_front()
                .expect("scripted reconcile observation")
        }
    }

    struct Fixture {
        _temp: TempDir,
        _authority_dir: TempDir,
        gateway: UiControlProductGateway,
        issuer: IssuerRegistration,
        auth_message: SignedMessage,
        final_use: SignedFinalUseGrant,
        operations: DurableOperationStore,
        dispatches: Arc<AtomicUsize>,
    }

    async fn fixture(
        allowed: bool,
        dispatch: UiControlDriverObservation,
        reconcile: UiControlDriverObservation,
    ) -> Fixture {
        let temp = tempfile::tempdir().expect("temp root");
        let evidence = HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("evidence");
        let policy = AuthPolicyStore::open(temp.path()).await.expect("policy");
        let operations = DurableOperationStore::open(temp.path())
            .await
            .expect("operations");
        policy
            .publish_revision(PolicyRevisionDraftV1 {
                revision: Revision::new(1).expect("policy revision"),
                source_digest: Digest32::of_bytes(b"ui-control-policy-source"),
                rules: vec![PolicyRuleV1 {
                    principal_id: StableId::new("operator.alice").expect("principal"),
                    action_id: StableId::new("request_retry").expect("action"),
                    resource_id: StableId::new("runtime.agentd").expect("resource"),
                    allowed,
                }],
            })
            .await
            .expect("publish policy");

        let agent_id = StableId::new("agent.ui-control").expect("agent id");
        let verified =
            verify_ui_control_request("operation/request", &operation_request(SEMANTIC))
                .expect("verified browser request");
        let semantic = verified.semantic_digest;
        let (issuer, auth_message) = signed_auth(&agent_id, semantic, 1);

        let authority_key = SigningKey::from_bytes(&[47; 32]);
        let authority_dir = tempfile::tempdir().expect("authority dir");
        std::fs::set_permissions(
            authority_dir.path(),
            std::fs::Permissions::from_mode(0o700),
        )
        .expect("secure authority dir");
        let final_use_authority = FinalUseAuthority::open_state_dir(
            authority_dir.path(),
            "security-owner".to_string(),
            authority_key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("final use authority");
        let destination = destination_id(&agent_id).expect("destination");
        let scope = effect_scope_digest(&agent_id, &verified);
        let payload = effect_payload_digest(&verified, scope);
        let final_use = signed_final_use(
            &authority_key,
            FinalUseBinding {
                subject_id: "operator.alice".to_string(),
                destination_id: destination.as_str().to_string(),
                request_sha256: semantic.into_array(),
                scope_sha256: scope.into_array(),
                payload_sha256: payload.into_array(),
            },
            5,
        );
        let dispatches = Arc::new(AtomicUsize::new(0));
        let gateway = UiControlProductGateway::new(
            evidence,
            policy,
            operations.clone(),
            final_use_authority,
            agent_id,
            Generation::new(7).expect("owner generation"),
            Box::new(ScriptedDriver {
                dispatches: Arc::clone(&dispatches),
                dispatch: VecDeque::from([dispatch]),
                reconcile: VecDeque::from([reconcile]),
            }),
        );
        Fixture {
            _temp: temp,
            _authority_dir: authority_dir,
            gateway,
            issuer,
            auth_message,
            final_use,
            operations,
            dispatches,
        }
    }

    #[tokio::test]
    async fn authenticated_ack_is_non_terminal_until_independent_reconciliation() {
        let ack = Digest32::of_bytes(b"supervisor-accepted");
        let terminal = Digest32::of_bytes(b"supervisor-terminal");
        let fixture = fixture(
            true,
            UiControlDriverObservation::Accepted {
                receipt_digest: ack,
            },
            UiControlDriverObservation::Terminal {
                outcome: ReconciliationOutcome::Applied,
                outcome_digest: terminal,
            },
        )
        .await;

        let disposition = fixture
            .gateway
            .execute(
                &fixture.issuer,
                UiControlProductCommand {
                    method: "operation/request".to_string(),
                    request_json: operation_request(SEMANTIC),
                    auth_message: fixture.auth_message,
                    policy_revision: Revision::new(1).expect("policy revision"),
                    final_use_grant: fixture.final_use,
                },
            )
            .await
            .expect("execute");
        assert!(matches!(
            disposition,
            UiControlGatewayDisposition::Pending {
                acknowledgement_digest,
                ..
            } if acknowledgement_digest == ack
        ));
        assert_eq!(fixture.dispatches.load(Ordering::SeqCst), 1);

        let operation_id = StableId::new("operation.1").expect("operation");
        let durable = fixture
            .operations
            .get(&operation_id)
            .await
            .expect("durable")
            .expect("record");
        assert!(matches!(durable.state, OperationState::Dispatched { .. }));
        assert!(!durable.state.is_terminal());

        let terminal_disposition = fixture
            .gateway
            .reconcile(&operation_id)
            .await
            .expect("reconcile");
        assert!(matches!(
            terminal_disposition,
            UiControlGatewayDisposition::Terminal {
                outcome: ReconciliationOutcome::Applied,
                outcome_digest,
                ..
            } if outcome_digest == terminal
        ));
        let durable = fixture
            .operations
            .get(&operation_id)
            .await
            .expect("durable")
            .expect("record");
        assert!(matches!(durable.state, OperationState::Applied { .. }));
    }

    #[tokio::test]
    async fn denied_policy_consumes_auth_replay_but_never_claims_effect_or_dispatches() {
        let fixture = fixture(
            false,
            UiControlDriverObservation::Indeterminate {
                reason_digest: Digest32::of_bytes(b"must-not-dispatch"),
            },
            UiControlDriverObservation::Indeterminate {
                reason_digest: Digest32::of_bytes(b"must-not-reconcile"),
            },
        )
        .await;
        let result = fixture
            .gateway
            .execute(
                &fixture.issuer,
                UiControlProductCommand {
                    method: "operation/request".to_string(),
                    request_json: operation_request(SEMANTIC),
                    auth_message: fixture.auth_message,
                    policy_revision: Revision::new(1).expect("policy revision"),
                    final_use_grant: fixture.final_use,
                },
            )
            .await;
        assert!(matches!(result, Err(UiControlProductError::Denied)));
        assert_eq!(fixture.dispatches.load(Ordering::SeqCst), 0);
        assert!(
            fixture
                .operations
                .get(&StableId::new("operation.1").expect("operation"))
                .await
                .expect("durable query")
                .is_none()
        );
    }

    #[tokio::test]
    async fn malformed_browser_semantics_fail_before_auth_replay_is_consumed() {
        let fixture = fixture(
            true,
            UiControlDriverObservation::Accepted {
                receipt_digest: Digest32::of_bytes(b"accepted"),
            },
            UiControlDriverObservation::Indeterminate {
                reason_digest: Digest32::of_bytes(b"still-pending"),
            },
        )
        .await;
        let bad = fixture
            .gateway
            .execute(
                &fixture.issuer,
                UiControlProductCommand {
                    method: "operation/request".to_string(),
                    request_json: operation_request(&"2".repeat(64)),
                    auth_message: signed_auth(
                        &StableId::new("agent.ui-control").expect("agent"),
                        Digest32::from_str(SEMANTIC).expect("semantic"),
                        1,
                    )
                    .1,
                    policy_revision: Revision::new(1).expect("policy revision"),
                    final_use_grant: fixture.final_use,
                },
            )
            .await;
        assert!(matches!(
            bad,
            Err(UiControlProductError::Wire(UiControlWireError::DigestMismatch))
        ));

        let result = fixture
            .gateway
            .execute(
                &fixture.issuer,
                UiControlProductCommand {
                    method: "operation/request".to_string(),
                    request_json: operation_request(SEMANTIC),
                    auth_message: fixture.auth_message,
                    policy_revision: Revision::new(1).expect("policy revision"),
                    final_use_grant: signed_final_use(
                        &SigningKey::from_bytes(&[47; 32]),
                        {
                            let verified = verify_ui_control_request(
                                "operation/request",
                                &operation_request(SEMANTIC),
                            )
                            .expect("verified");
                            let agent = StableId::new("agent.ui-control").expect("agent");
                            let scope = effect_scope_digest(&agent, &verified);
                            FinalUseBinding {
                                subject_id: "operator.alice".to_string(),
                                destination_id: destination_id(&agent)
                                    .expect("destination")
                                    .as_str()
                                    .to_string(),
                                request_sha256: verified.semantic_digest.into_array(),
                                scope_sha256: scope.into_array(),
                                payload_sha256: effect_payload_digest(&verified, scope)
                                    .into_array(),
                            }
                        },
                        6,
                    ),
                },
            )
            .await
            .expect("valid request after rejected wire");
        assert!(matches!(result, UiControlGatewayDisposition::Pending { .. }));
    }
}
