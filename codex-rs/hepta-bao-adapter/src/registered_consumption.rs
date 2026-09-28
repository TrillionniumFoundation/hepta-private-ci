//! Registered forward admission and execution; the durable owner remains shared.
use super::*;

impl BaoFinalUseHost {
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
        let _timing = self.metrics.request_timer();
        let BaoApprovedReadV1 {
            admission,
            grant,
            approval,
            request,
        } = read;
        admission.validate().map_err(|error| {
            BaoProductHostError::Host(BaoFinalUseHostError::Client(error))
        })?;
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
        let _execution = crate::lease_lifecycle::lock_owner(registry)
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .enter_consumption_execution(operation_id)
            .map_err(BaoProductHostError::Store)?;
        let operation = BaoConsumptionOperationV1 {
            operation_id: operation_id.to_owned(),
            semantic_sha256,
            effect_sha256: effect.into_array(),
            request_sha256: binding.request_sha256,
            consumer_id: request.consumer_id.clone(),
            consumer_configuration_sha256: configuration,
            amount: admission.amount,
            created_at_unix_ms: Some(self.clock.now_unix_ms().map_err(|error| BaoProductHostError::Host(BaoFinalUseHostError::Trust(error)))?),
            reservation_id: None,
            state: BaoConsumptionStateV1::Claimed,
            receipt: None,
            terminal_kind: None,
            terminal_code: None,
            terminal_evidence_sha256: None,
            terminal_observed_cost: None,
        };
        let existing = crate::lease_lifecycle::lock_owner(registry)
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
            crate::authbus_saga::BaoSagaHooks {
            reserved: |reservation: &QuotaReservation| {
                crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .mark_consumption_reserved(
                        operation_id,
                        reservation.reservation_id.as_str().to_owned(),
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable reservation commit failed"))
            },
            dispatch_fenced: |reservation: &QuotaReservation| {
                crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .mark_consumption_dispatch_fenced(
                        operation_id,
                        reservation.reservation_id.as_str(),
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable dispatch fence commit failed"))
            },
            provider_terminal: |error, terminal: Digest32| {
                let code = provider_failure_code(error).ok_or(BaoAuthBusError::Evidence(
                    "nonterminal provider error classified terminal",
                ))?;
                crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .record_provider_failure(
                        operation_id,
                        code,
                        terminal.into_array(),
                        admission.amount,
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable provider terminal commit failed"))
            },
            prepare_delivery: |receipt: &BaoSecretReceipt| {
                crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| ())?
                    .enter_consumption(operation_id, receipt.clone())
                    .map_err(|_| ())
            },
            consumer: |secret: &[u8], _receipt: &BaoSecretReceipt| {
                self.ensure_revocation_fresh().map_err(|_| ())?;
                let result = callback(operation_id, semantic_sha256, secret);
                crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| ())?
                    .observe_consumption(operation_id, result.is_ok())
                    .map_err(|_| ())?;
                result
            },
            },
        )
        .await;
        match result {
            Ok(_) => crate::lease_lifecycle::lock_owner(registry)
                .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                .settle_consumption(operation_id)
                .map_err(BaoProductHostError::Store),
            Err(crate::authbus_saga::BaoSagaError::ProviderTerminal) => {
                let row = crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .settle_consumption_failure(operation_id)
                    .map_err(BaoProductHostError::Store)?;
                Err(BaoProductHostError::TerminalFailure(row))
            }
            Err(crate::authbus_saga::BaoSagaError::AfterDispatch(error)) => {
                let _ = crate::lease_lifecycle::lock_owner(registry).map(|mut owner| {
                    let _ = owner.mark_consumption_indeterminate(operation_id);
                });
                Err(BaoProductHostError::AuthBus(error))
            }
            Err(crate::authbus_saga::BaoSagaError::BeforeDispatch(error)) => {
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
        let row = crate::lease_lifecycle::lock_owner(registry)
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id).map_err(BaoProductHostError::Store)?;
        if row.state != BaoConsumptionStateV1::Claimed {
            return Ok(None);
        }
        if authbus.seal_unreserved_operation(&operation, Digest32::from_array(row.effect_sha256))
            .await.map_err(|error| BaoProductHostError::AuthBus(error.into()))?.is_some() {
            return Ok(None);
        }
        let evidence = Digest32::of_bytes(
            format!("hepta.bao.pre-reservation.v1:{operation_id}:{error:?}").as_bytes(),
        );
        let terminal = crate::lease_lifecycle::lock_owner(registry)
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .record_consumption_abort(
                operation_id,
                crate::lease_lifecycle::BaoAbortStage::BeforeReservation,
                "no_reservation",
                evidence.into_array(),
            )
            .map_err(BaoProductHostError::Store)?;
        Ok(Some(terminal))
    }

}
