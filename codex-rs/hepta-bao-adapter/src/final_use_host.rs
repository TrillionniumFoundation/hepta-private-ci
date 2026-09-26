//! Trusted host composition for the Bao final-use consumer.
//!
//! Product code enters the Bao secret-use boundary through this host rather
//! than passing an arbitrary closure directly to `BaoClient`. The signed
//! request's `consumer_id` must resolve to one statically registered callback,
//! the exact grant must have an independent operator approval, and revocation
//! updates are accepted only through an independently pinned signed feed.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseControlError;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationReceipt;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::BaoAuthBusAdmission;
use crate::BaoAuthBusError;
use crate::BaoAuthBusEvidenceProvider;
use crate::BaoClient;
use crate::BaoClientError;
use crate::BaoReadRequest;
use crate::BaoSecretReceipt;
use crate::{
    BaoConsumptionOperationV1, BaoConsumptionStateV1, DurableLeaseRegistryV1, LeaseRegistryErrorV1,
};

/// Independently approved operation inputs; dependencies remain host-owned.
#[derive(Clone, Copy)]
pub struct BaoApprovedReadV1<'a> {
    pub admission: &'a BaoAuthBusAdmission,
    pub grant: &'a SignedFinalUseGrant,
    pub approval: &'a SignedFinalUseApproval,
    pub request: &'a BaoReadRequest,
}

pub type BaoOperationConsumerCallback =
    Arc<dyn Fn(&str, [u8; 32], &[u8]) -> Result<(), ()> + Send + Sync + 'static>;
pub type BaoConsumerObserverCallback =
    Arc<dyn Fn(&str, [u8; 32]) -> Result<BaoConsumerObservationV1, ()> + Send + Sync + 'static>;

/// Durable observation of the original consumer effect.
///
/// The legacy `NotApplied` value remains conservative and cannot release quota.
/// `NotAppliedWithEvidence` is the terminal negative outcome: the enrolled
/// observer must return a nonzero immutable evidence digest for the original
/// operation identity and semantic digest.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoConsumerObservationV1 {
    Succeeded,
    NotApplied,
    NotAppliedWithEvidence { evidence_sha256: [u8; 32] },
    Unknown,
}

pub type BaoConsumerCallback = Arc<dyn Fn(&[u8]) -> Result<(), ()> + Send + Sync + 'static>;

#[derive(Clone)]
pub struct RegisteredBaoConsumer {
    id: String,
    callback: BaoConsumerCallback,
    configuration_sha256: Option<[u8; 32]>,
    operation_callback: Option<BaoOperationConsumerCallback>,
    observer: Option<BaoConsumerObserverCallback>,
}

impl fmt::Debug for RegisteredBaoConsumer {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RegisteredBaoConsumer")
            .field("id", &self.id)
            .field("callback", &"[TRUSTED CALLBACK]")
            .finish()
    }
}

impl RegisteredBaoConsumer {
    pub fn new(id: String, callback: BaoConsumerCallback) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) {
            return Err(BaoFinalUseHostError::InvalidConsumerId);
        }
        Ok(Self {
            id,
            callback,
            configuration_sha256: None,
            operation_callback: None,
            observer: None,
        })
    }

    /// A product registration must bind its immutable implementation/configuration
    /// identity and provide an operation-bound observer for restart reconciliation.
    pub fn for_operations(
        id: String,
        configuration_sha256: [u8; 32],
        callback: BaoOperationConsumerCallback,
        observer: BaoConsumerObserverCallback,
    ) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) || configuration_sha256 == [0; 32] {
            return Err(BaoFinalUseHostError::InvalidConsumerConfiguration);
        }
        Ok(Self {
            id,
            callback: Arc::new(|_| Err(())),
            configuration_sha256: Some(configuration_sha256),
            operation_callback: Some(callback),
            observer: Some(observer),
        })
    }

    pub fn id(&self) -> &str {
        &self.id
    }
}

/// Host-selected composition of final-use authority, independent approval,
/// authenticated revocation distribution and a closed consumer registry.
pub struct BaoFinalUseHost {
    authority: FinalUseAuthority,
    approval_verifier: FinalUseApprovalVerifier,
    revocation_verifier: FinalUseRevocationFeedVerifier,
    clock: Arc<dyn AuthorityClock>,
    revocation_fresh_until_unix_ms: Mutex<u64>,
    consumers: BTreeMap<String, RegisteredBaoConsumer>,
}

impl fmt::Debug for BaoFinalUseHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoFinalUseHost")
            .field("authority", &self.authority)
            .field("approval_verifier", &self.approval_verifier)
            .field("revocation_verifier", &self.revocation_verifier)
            .field("consumer_count", &self.consumers.len())
            .finish()
    }
}

impl BaoFinalUseHost {
    pub fn new(
        authority: FinalUseAuthority,
        approval_verifier: FinalUseApprovalVerifier,
        revocation_verifier: FinalUseRevocationFeedVerifier,
        clock: Arc<dyn AuthorityClock>,
        consumers: impl IntoIterator<Item = RegisteredBaoConsumer>,
    ) -> Result<Self, BaoFinalUseHostError> {
        let mut registry = BTreeMap::new();
        for consumer in consumers {
            if registry.insert(consumer.id.clone(), consumer).is_some() {
                return Err(BaoFinalUseHostError::DuplicateConsumer);
            }
        }
        if registry.is_empty() {
            return Err(BaoFinalUseHostError::EmptyConsumerRegistry);
        }
        Ok(Self {
            authority,
            approval_verifier,
            revocation_verifier,
            clock,
            revocation_fresh_until_unix_ms: Mutex::new(0),
            consumers: registry,
        })
    }

    pub fn consumer_count(&self) -> usize {
        self.consumers.len()
    }

    fn ensure_revocation_fresh(&self) -> Result<(), BaoFinalUseHostError> {
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        let fresh_until = *self
            .revocation_fresh_until_unix_ms
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        if fresh_until == 0 || now_unix_ms >= fresh_until {
            return Err(BaoFinalUseHostError::StaleRevocationFeed);
        }
        Ok(())
    }

    fn approved_consumer(
        &self,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        consumer_id: &str,
    ) -> Result<BaoConsumerCallback, BaoFinalUseHostError> {
        self.ensure_revocation_fresh()?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        self.consumers
            .get(consumer_id)
            .map(|consumer| consumer.callback.clone())
            .ok_or(BaoFinalUseHostError::UnregisteredConsumer)
    }

    /// Apply one independently signed revocation head. The feed signature is
    /// checked before the durable authority owner sees the head; the authority
    /// itself enforces epoch/revision monotonicity and same-epoch superset rules.
    pub fn apply_revocation_update(
        &self,
        update: &SignedFinalUseRevocationUpdate,
    ) -> Result<FinalUseRevocationReceipt, BaoFinalUseHostError> {
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        let receipt = self
            .revocation_verifier
            .apply(&self.authority, update, now_unix_ms)
            .map_err(BaoFinalUseHostError::Control)?;
        let mut fresh_until = self
            .revocation_fresh_until_unix_ms
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        *fresh_until = receipt.valid_until_unix_ms();
        Ok(receipt)
    }

    /// Registered final-use boundary without quota composition. This remains a
    /// bounded source integration path; product callers that reserve quota must
    /// use `consume_kv_v2_with_authbus` below.
    pub async fn consume_kv_v2(
        &self,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoReadRequest,
    ) -> Result<BaoSecretReceipt, BaoFinalUseHostError> {
        let consumer = self.approved_consumer(grant, approval, &request.consumer_id)?;
        match client
            .consume_kv_v2_guarded(
                &self.authority,
                grant,
                request,
                |_| Ok(()),
                move |secret, _receipt| {
                    self.ensure_revocation_fresh()?;
                    consumer(secret).map_err(|()| {
                        BaoFinalUseHostError::Client(BaoClientError::ConsumerIndeterminate)
                    })
                },
            )
            .await
            .map_err(BaoFinalUseHostError::Client)?
        {
            Ok(receipt) => Ok(receipt),
            Err(error) => Err(error),
        }
    }

    /// The single durable product ingress. Only a newly committed `Claimed`
    /// identity may execute. Exact retries of an incomplete identity are routed
    /// to reconciliation and never redispatch blindly.
    pub async fn consume_kv_v2_with_authbus<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        read: BaoApprovedReadV1<'_>,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let BaoApprovedReadV1 {
            admission,
            grant,
            approval,
            request,
        } = read;
        self.approved_consumer(grant, approval, &request.consumer_id)
            .map_err(BaoProductHostError::Host)?;
        let registration = self
            .consumers
            .get(&request.consumer_id)
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        let configuration = registration
            .configuration_sha256
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        if request.consumer_configuration_sha256 != Some(configuration) {
            return Err(BaoProductHostError::ConsumerProfileRequired);
        }
        let callback = registration
            .operation_callback
            .clone()
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        let binding = client
            .binding(request)
            .map_err(|error| BaoProductHostError::Host(BaoFinalUseHostError::Client(error)))?;
        let effect = client
            .authbus_effect_digest(request, &admission.operation_id)
            .map_err(|error| BaoProductHostError::Host(BaoFinalUseHostError::Client(error)))?;
        let semantics = serde_json::to_vec(&(
            "hepta.bao.durable-product.v2",
            effect.as_array(),
            admission.policy_revision,
            admission.quota_key.as_str(),
            admission.expected_quota_revision,
            admission.amount,
            admission.expires_at_ms,
            grant,
            approval,
            configuration,
        ))
        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::InvalidInput))?;
        let semantic_sha256 = Digest32::of_bytes(&semantics).into_array();
        let operation_id = admission.operation_id.as_str();
        let operation = BaoConsumptionOperationV1 {
            operation_id: operation_id.to_owned(),
            semantic_sha256,
            effect_sha256: effect.into_array(),
            request_sha256: binding.request_sha256,
            consumer_id: request.consumer_id.clone(),
            consumer_configuration_sha256: configuration,
            amount: admission.amount,
            reservation_id: None,
            state: BaoConsumptionStateV1::Claimed,
            receipt: None,
            terminal_kind: None,
            terminal_code: None,
            terminal_evidence_sha256: None,
            terminal_observed_cost: None,
        };
        let existing = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .claim_consumption(operation)
            .map_err(BaoProductHostError::Store)?;
        if let Some(existing) = existing {
            return match existing.state {
                BaoConsumptionStateV1::Succeeded => existing.receipt.ok_or(
                    BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState),
                ),
                BaoConsumptionStateV1::Failed => {
                    Err(BaoProductHostError::TerminalFailure(existing))
                }
                _ => Err(BaoProductHostError::OutcomePending(existing)),
            };
        }

        let result = crate::authbus_saga::consume_kv_v2_with_authbus_saga(
            client,
            authbus,
            crate::BaoAuthorizedReadV1 {
                admission,
                authority: &self.authority,
                grant,
                request,
            },
            evidence,
            |reservation| {
                registry
                    .lock()
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .mark_consumption_reserved(
                        operation_id,
                        reservation.reservation_id.as_str().to_owned(),
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable reservation commit failed"))
            },
            |reservation| {
                registry
                    .lock()
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .mark_consumption_dispatch_fenced(
                        operation_id,
                        reservation.reservation_id.as_str(),
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable dispatch fence commit failed"))
            },
            |error, terminal| {
                let code = provider_failure_code(error).ok_or(BaoAuthBusError::Evidence(
                    "nonterminal provider error classified terminal",
                ))?;
                registry
                    .lock()
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .record_provider_failure(
                        operation_id,
                        code,
                        terminal.into_array(),
                        admission.amount,
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable provider terminal commit failed"))
            },
            |receipt| {
                registry
                    .lock()
                    .map_err(|_| ())?
                    .enter_consumption(operation_id, receipt.clone())
                    .map_err(|_| ())
            },
            |secret, _receipt| {
                self.ensure_revocation_fresh().map_err(|_| ())?;
                let result = callback(operation_id, semantic_sha256, secret);
                registry
                    .lock()
                    .map_err(|_| ())?
                    .observe_consumption(operation_id, result.is_ok())
                    .map_err(|_| ())?;
                result
            },
        )
        .await;
        match result {
            Ok(_) => registry
                .lock()
                .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                .settle_consumption(operation_id)
                .map_err(BaoProductHostError::Store),
            Err(BaoAuthBusError::Provider(_)) => {
                let row = registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .settle_consumption_failure(operation_id)
                    .map_err(BaoProductHostError::Store)?;
                Err(BaoProductHostError::TerminalFailure(row))
            }
            Err(error @ BaoAuthBusError::Indeterminate { .. }) => {
                let _ = registry.lock().map(|mut owner| {
                    let _ = owner.mark_consumption_indeterminate(operation_id);
                });
                Err(BaoProductHostError::AuthBus(error))
            }
            Err(error) => {
                if let Some(terminal) = self
                    .close_unreserved_failure_if_proved(authbus, registry, operation_id, &error)
                    .await?
                {
                    Err(BaoProductHostError::TerminalFailure(terminal))
                } else {
                    Err(BaoProductHostError::AuthBus(error))
                }
            }
        }
    }

    async fn close_unreserved_failure_if_proved(
        &self,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        operation_id: &str,
        error: &BaoAuthBusError,
    ) -> Result<Option<BaoConsumptionOperationV1>, BaoProductHostError> {
        let operation = StableId::new(operation_id.to_owned())
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState))?;
        if authbus
            .reservation_by_operation(&operation)
            .await
            .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
            .is_some()
        {
            return Ok(None);
        }
        let row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        if row.state != BaoConsumptionStateV1::Claimed {
            return Ok(None);
        }
        let evidence = Digest32::of_bytes(
            format!("hepta.bao.pre-reservation.v1:{operation_id}:{error:?}").as_bytes(),
        );
        let terminal = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .record_consumption_abort(
                operation_id,
                false,
                "no_reservation",
                evidence.into_array(),
            )
            .map_err(BaoProductHostError::Store)?;
        Ok(Some(terminal))
    }

    /// Reconcile the original consumer and AuthBus operation identity. This
    /// method never fetches a secret and never invokes the consumer effect.
    pub async fn reconcile_consumption<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        operation_id: &str,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let mut row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        if row.state == BaoConsumptionStateV1::Succeeded {
            return row.receipt.ok_or(BaoProductHostError::Store(
                LeaseRegistryErrorV1::CorruptState,
            ));
        }
        if row.state == BaoConsumptionStateV1::Failed {
            return Err(BaoProductHostError::TerminalFailure(row));
        }
        let registration = self
            .consumers
            .get(&row.consumer_id)
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        if registration.configuration_sha256 != Some(row.consumer_configuration_sha256) {
            return Err(BaoProductHostError::ConsumerProfileRequired);
        }
        let stable_operation = StableId::new(operation_id.to_owned())
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState))?;
        let reservation = match row.reservation_id.as_deref() {
            Some(value) => {
                let reservation_id = StableId::new(value.to_owned()).map_err(|_| {
                    BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState)
                })?;
                Some(
                    authbus
                        .reservation(&reservation_id)
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?,
                )
            }
            None => authbus
                .reservation_by_operation(&stable_operation)
                .await
                .map_err(|error| BaoProductHostError::AuthBus(error.into()))?,
        };
        let Some(mut reservation) = reservation else {
            if matches!(
                row.state,
                BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
            ) {
                let terminal = abort_evidence(&row, "no_reservation", None);
                let terminal = registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .record_consumption_abort(
                        operation_id,
                        false,
                        "no_reservation",
                        terminal,
                    )
                    .map_err(BaoProductHostError::Store)?;
                return Err(BaoProductHostError::TerminalFailure(terminal));
            }
            return Err(BaoProductHostError::OutcomePending(row));
        };
        validate_reservation(&row, &reservation)?;
        {
            let mut owner = registry
                .lock()
                .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?;
            owner
                .mark_consumption_reserved(
                    operation_id,
                    reservation.reservation_id.as_str().to_owned(),
                )
                .map_err(BaoProductHostError::Store)?;
            match reservation.state {
                ReservationState::DispatchAttempted | ReservationState::Indeterminate => {
                    owner
                        .mark_consumption_dispatch_fenced(
                            operation_id,
                            reservation.reservation_id.as_str(),
                        )
                        .map_err(BaoProductHostError::Store)?;
                    if reservation.state == ReservationState::Indeterminate {
                        owner
                            .mark_consumption_indeterminate(operation_id)
                            .map_err(BaoProductHostError::Store)?;
                    }
                }
                _ => {}
            }
            row = owner
                .consumption_result(operation_id)
                .map_err(BaoProductHostError::Store)?;
        }

        match reservation.state {
            ReservationState::Held => {
                if !matches!(
                    row.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    return Err(BaoProductHostError::Store(
                        LeaseRegistryErrorV1::ObservationMismatch,
                    ));
                }
                let time = authbus
                    .observe_trusted_time_attestation(
                        &evidence.trusted_time().map_err(BaoProductHostError::AuthBus)?,
                    )
                    .await
                    .map_err(|error| BaoProductHostError::AuthBus(error.into()))?;
                reservation = if time.wall_time_ms() >= reservation.expires_at_ms {
                    authbus
                        .reconcile_expired_reservation(
                            &reservation.reservation_id,
                            reservation.revision,
                            time,
                        )
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
                } else {
                    authbus
                        .cancel_reservation(
                            &reservation.reservation_id,
                            reservation.revision,
                            time,
                        )
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
                };
                let code = match reservation.state {
                    ReservationState::Expired => "reservation_expired",
                    ReservationState::Cancelled => "reservation_cancelled",
                    _ => {
                        return Err(BaoProductHostError::Store(
                            LeaseRegistryErrorV1::ObservationMismatch,
                        ));
                    }
                };
                let terminal = abort_evidence(&row, code, Some(&reservation));
                let terminal = registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .record_consumption_abort(operation_id, true, code, terminal)
                    .map_err(BaoProductHostError::Store)?;
                return Err(BaoProductHostError::TerminalFailure(terminal));
            }
            ReservationState::Cancelled | ReservationState::Expired => {
                if matches!(
                    row.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    let code = if reservation.state == ReservationState::Expired {
                        "reservation_expired"
                    } else {
                        "reservation_cancelled"
                    };
                    let terminal = abort_evidence(&row, code, Some(&reservation));
                    let terminal = registry
                        .lock()
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .record_consumption_abort(operation_id, true, code, terminal)
                        .map_err(BaoProductHostError::Store)?;
                    return Err(BaoProductHostError::TerminalFailure(terminal));
                }
            }
            ReservationState::Released => {
                if matches!(
                    row.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    let terminal = abort_evidence(&row, "reservation_released", Some(&reservation));
                    let terminal = registry
                        .lock()
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .record_consumption_abort(
                            operation_id,
                            true,
                            "reservation_released",
                            terminal,
                        )
                        .map_err(BaoProductHostError::Store)?;
                    return Err(BaoProductHostError::TerminalFailure(terminal));
                }
            }
            ReservationState::DispatchAttempted
            | ReservationState::Indeterminate
            | ReservationState::Settled => {}
        }

        row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        if matches!(
            row.state,
            BaoConsumptionStateV1::DeliveryPrepared | BaoConsumptionStateV1::Indeterminate
        ) && row.receipt.is_some()
        {
            let observer = registration
                .observer
                .as_ref()
                .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
            match observer(operation_id, row.semantic_sha256) {
                Ok(BaoConsumerObservationV1::Succeeded) => registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .observe_consumption(operation_id, true)
                    .map_err(BaoProductHostError::Store)?,
                Ok(BaoConsumerObservationV1::NotAppliedWithEvidence { evidence_sha256 }) => {
                    registry
                        .lock()
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .observe_consumption_not_applied(operation_id, evidence_sha256)
                        .map_err(BaoProductHostError::Store)?;
                }
                Ok(BaoConsumerObservationV1::NotApplied | BaoConsumerObservationV1::Unknown)
                | Err(()) => return Err(BaoProductHostError::OutcomePending(row)),
            }
        }

        row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        match row.state {
            BaoConsumptionStateV1::ConsumerSucceeded
            | BaoConsumptionStateV1::ProviderFailed
            | BaoConsumptionStateV1::ConsumerNotApplied => {
                settle_terminal_row(authbus, registry, row, reservation, evidence).await
            }
            BaoConsumptionStateV1::Succeeded => row.receipt.ok_or(
                BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState),
            ),
            BaoConsumptionStateV1::Failed => {
                Err(BaoProductHostError::TerminalFailure(row))
            }
            _ => Err(BaoProductHostError::OutcomePending(row)),
        }
    }
}

async fn settle_terminal_row<E: BaoAuthBusEvidenceProvider>(
    authbus: &AuthBusAuthorityHost,
    registry: &Mutex<DurableLeaseRegistryV1>,
    row: BaoConsumptionOperationV1,
    reservation: QuotaReservation,
    evidence: &mut E,
) -> Result<BaoSecretReceipt, BaoProductHostError> {
    let terminal = Digest32::from_array(row.terminal_evidence_sha256.ok_or(
        BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState),
    )?);
    let (status, observed_cost, success) = match row.state {
        BaoConsumptionStateV1::ConsumerSucceeded => {
            (SettlementStatus::Completed, row.amount, true)
        }
        BaoConsumptionStateV1::ProviderFailed => (
            SettlementStatus::Completed,
            row.terminal_observed_cost.ok_or(BaoProductHostError::Store(
                LeaseRegistryErrorV1::CorruptState,
            ))?,
            false,
        ),
        BaoConsumptionStateV1::ConsumerNotApplied => (SettlementStatus::Rejected, 0, false),
        _ => {
            return Err(BaoProductHostError::Store(
                LeaseRegistryErrorV1::InvalidTransition,
            ));
        }
    };
    let expected_terminal_state = match status {
        SettlementStatus::Completed => ReservationState::Settled,
        SettlementStatus::Rejected => ReservationState::Released,
    };
    if matches!(reservation.state, ReservationState::Settled | ReservationState::Released) {
        if reservation.state != expected_terminal_state
            || reservation.terminal_evidence != Some(terminal)
            || reservation.observed_cost != Some(observed_cost)
        {
            return Err(BaoProductHostError::Store(
                LeaseRegistryErrorV1::ObservationMismatch,
            ));
        }
    } else {
        if !matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) {
            return Err(BaoProductHostError::OutcomePending(row));
        }
        crate::https_consumer::settle_observed(
            authbus,
            evidence,
            &reservation,
            status,
            observed_cost,
            terminal,
            if success { row.receipt.clone() } else { None },
        )
        .await
        .map_err(BaoProductHostError::AuthBus)?;
    }
    let mut owner = registry
        .lock()
        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?;
    if success {
        owner
            .settle_consumption(&row.operation_id)
            .map_err(BaoProductHostError::Store)
    } else {
        let terminal = owner
            .settle_consumption_failure(&row.operation_id)
            .map_err(BaoProductHostError::Store)?;
        Err(BaoProductHostError::TerminalFailure(terminal))
    }
}

fn validate_reservation(
    row: &BaoConsumptionOperationV1,
    reservation: &QuotaReservation,
) -> Result<(), BaoProductHostError> {
    if reservation.operation_id.as_str() != row.operation_id
        || reservation.amount != row.amount
        || reservation.effect_digest.into_array() != row.effect_sha256
    {
        return Err(BaoProductHostError::Store(
            LeaseRegistryErrorV1::ObservationMismatch,
        ));
    }
    Ok(())
}

fn abort_evidence(
    row: &BaoConsumptionOperationV1,
    code: &str,
    reservation: Option<&QuotaReservation>,
) -> [u8; 32] {
    let reservation_id = reservation
        .map(|value| value.reservation_id.as_str())
        .unwrap_or("");
    let reservation_revision = reservation.map(|value| value.revision).unwrap_or(0);
    Digest32::of_bytes(
        &serde_json::to_vec(&(
            "hepta.bao.abort.v1",
            row.operation_id.as_str(),
            row.semantic_sha256,
            row.effect_sha256,
            code,
            reservation_id,
            reservation_revision,
        ))
        .unwrap_or_default(),
    )
    .into_array()
}

fn provider_failure_code(error: BaoClientError) -> Option<&'static str> {
    match error {
        BaoClientError::ProviderDenied => Some("provider_denied"),
        BaoClientError::ProviderUnavailable => Some("provider_unavailable"),
        BaoClientError::NotFound => Some("not_found"),
        BaoClientError::ResponseTooLarge => Some("response_too_large"),
        BaoClientError::InvalidResponse => Some("invalid_response"),
        BaoClientError::VersionMismatch => Some("version_mismatch"),
        BaoClientError::SecretDigestMismatch => Some("secret_digest_mismatch"),
        BaoClientError::InvalidConfiguration
        | BaoClientError::InvalidRequest
        | BaoClientError::Authority(_)
        | BaoClientError::TransportUnavailable
        | BaoClientError::TimedOut
        | BaoClientError::ConsumerIndeterminate => None,
    }
}

fn consumer_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoFinalUseHostError {
    InvalidConsumerId,
    InvalidConsumerConfiguration,
    DuplicateConsumer,
    EmptyConsumerRegistry,
    UnregisteredConsumer,
    StaleRevocationFeed,
    Unavailable,
    Trust(AuthorityTrustError),
    Control(FinalUseControlError),
    Client(BaoClientError),
}

impl fmt::Display for BaoFinalUseHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for BaoFinalUseHostError {}

#[derive(Debug)]
pub enum BaoProductHostError {
    Host(BaoFinalUseHostError),
    AuthBus(BaoAuthBusError),
    Store(LeaseRegistryErrorV1),
    ConsumerProfileRequired,
    OutcomePending(BaoConsumptionOperationV1),
    TerminalFailure(BaoConsumptionOperationV1),
}

impl fmt::Display for BaoProductHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Host(error) => write!(formatter, "host admission failed: {error}"),
            Self::AuthBus(error) => write!(formatter, "AuthBus product path failed: {error}"),
            Self::Store(error) => write!(formatter, "durable operation failed: {error}"),
            Self::ConsumerProfileRequired => {
                formatter.write_str("matching operation-aware consumer profile required")
            }
            Self::OutcomePending(_) => {
                formatter.write_str("original operation requires reconciliation; no redispatch")
            }
            Self::TerminalFailure(row) => write!(
                formatter,
                "original operation reached immutable terminal failure ({})",
                row.terminal_code.as_deref().unwrap_or("unspecified")
            ),
        }
    }
}
impl std::error::Error for BaoProductHostError {}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use ed25519_dalek::SigningKey;

    fn callback() -> BaoConsumerCallback {
        Arc::new(|_| Ok(()))
    }

    #[test]
    fn consumer_registry_is_closed_and_unique() {
        assert_eq!(
            RegisteredBaoConsumer::new("../escape".into(), callback()).unwrap_err(),
            BaoFinalUseHostError::InvalidConsumerId
        );
        let consumer = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
        assert_eq!(consumer.id(), "model-provider");
    }

    #[test]
    fn host_rejects_duplicate_consumer_identity() {
        let directory = tempfile::tempdir().unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let issuer = SigningKey::from_bytes(&[31; 32]);
        let approver = SigningKey::from_bytes(&[32; 32]);
        let distributor = SigningKey::from_bytes(&[33; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            codex_hepta_contracts::FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: Default::default(),
            },
        )
        .unwrap();
        let approval_verifier = FinalUseApprovalVerifier::new(
            "operator-approver".into(),
            approver.verifying_key().to_bytes(),
        )
        .unwrap();
        let revocation_verifier = FinalUseRevocationFeedVerifier::new(
            "revocation-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )
        .unwrap();
        let first = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
        let second = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
        assert_eq!(
            BaoFinalUseHost::new(
                authority,
                approval_verifier,
                revocation_verifier,
                Arc::new(codex_hepta_contracts::SystemAuthorityClock),
                [first, second],
            )
            .unwrap_err(),
            BaoFinalUseHostError::DuplicateConsumer
        );
    }
}
