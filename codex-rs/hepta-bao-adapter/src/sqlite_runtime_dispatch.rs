//! sqlite runtime dispatch implementation.

use super::*;

impl BaoFinalUseHost {
    pub(super) fn product_now(&self) -> Result<u64, BaoProductHostError> {
        self.clock
            .now_unix_ms()
            .map_err(|error| BaoProductHostError::Host(BaoFinalUseHostError::Trust(error)))
    }

    pub(super) async fn consume_kv_v2_with_authbus_sqlite<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        owner: &Arc<SqliteBaoOwnerV1>,
        runtime_config: &BaoSqliteProductRuntimeConfigV1,
        read: BaoApprovedReadV1<'_>,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let execution_owner = &runtime_config.forward_executor_id;
        let execution_lease_ms = runtime_config.forward_execution_lease_ms;
        let BaoApprovedReadV1 {
            admission,
            grant,
            approval,
            request,
        } = read;
        validate_product_admission(admission).map_err(BaoProductHostError::Host)?;
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
        .map_err(|_| BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::InvalidInput))?;
        let semantic_sha256 = Digest32::of_bytes(&semantics).into_array();
        let operation_id = admission.operation_id.as_str().to_owned();
        let operation = BaoConsumptionOperationV1 {
            operation_id: operation_id.clone(),
            semantic_sha256,
            effect_sha256: effect.into_array(),
            request_sha256: binding.request_sha256,
            consumer_id: request.consumer_id.clone(),
            consumer_configuration_sha256: configuration,
            amount: admission.amount,
            reservation_id: None,
            state: BaoConsumptionStateV1::Claimed,
            receipt: None,
            created_revision: 0,
            updated_revision: 0,
            terminal_kind: None,
            terminal_code: None,
            terminal_evidence_sha256: None,
            terminal_observed_cost: None,
        };
        let now_unix_ms = self.product_now()?;
        let execution = owner
            .claim_consumption_for_execution(
                operation,
                now_unix_ms,
                execution_owner,
                execution_lease_ms,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if !execution.claim.inserted {
            return historical_result_or_pending(execution.claim.record.operation);
        }
        let execution_claim = execution.execution.ok_or(BaoProductHostError::SqliteStore(
            SqliteBaoOwnerErrorV1::CorruptState("new forward operation has no execution lease"),
        ))?;

        let result = self
            .execute_claimed_sqlite_consumption(
                client,
                authbus,
                owner,
                &operation_id,
                semantic_sha256,
                callback,
                admission,
                grant,
                request,
                evidence,
            )
            .await;
        release_execution_claim_if_pending(owner, &execution_claim).await;
        result
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) async fn execute_claimed_sqlite_consumption<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        owner: &Arc<SqliteBaoOwnerV1>,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        callback: BaoOperationConsumerCallback,
        admission: &BaoAuthBusAdmission,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let reserved_owner = Arc::clone(owner);
        let reserved_clock = Arc::clone(&self.clock);
        let reserved_operation = operation_id.to_owned();
        let fenced_owner = Arc::clone(owner);
        let fenced_clock = Arc::clone(&self.clock);
        let fenced_operation = operation_id.to_owned();
        let provider_owner = Arc::clone(owner);
        let provider_clock = Arc::clone(&self.clock);
        let provider_operation = operation_id.to_owned();
        let preparation_owner = Arc::clone(owner);
        let preparation_clock = Arc::clone(&self.clock);
        let preparation_operation = operation_id.to_owned();
        let success_owner = Arc::clone(owner);
        let success_clock = Arc::clone(&self.clock);
        let success_operation = operation_id.to_owned();

        let saga_result = crate::authbus_saga::consume_kv_v2_with_authbus_saga(
            client,
            authbus,
            crate::BaoAuthorizedReadV1 {
                admission,
                authority: &self.authority,
                grant,
                request,
            },
            evidence,
            crate::authbus_saga::BaoAuthBusSagaHooks {
                reserved: move |reservation: &QuotaReservation| {
                    let owner = Arc::clone(&reserved_owner);
                    let clock = Arc::clone(&reserved_clock);
                    let operation_id = reserved_operation.clone();
                    let reservation = reservation.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_reserved(
                                &operation_id,
                                current.revision,
                                reservation.reservation_id.as_str().to_owned(),
                                reservation_evidence(b"hepta.bao.sqlite.reserved.v1", &reservation),
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                dispatch_fenced: move |reservation: &QuotaReservation| {
                    let owner = Arc::clone(&fenced_owner);
                    let clock = Arc::clone(&fenced_clock);
                    let operation_id = fenced_operation.clone();
                    let reservation = reservation.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_dispatch_fenced(
                                &operation_id,
                                current.revision,
                                reservation_evidence(
                                    b"hepta.bao.sqlite.dispatch-fenced.v1",
                                    &reservation,
                                ),
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                provider_terminal: move |error: BaoClientError, terminal: Digest32| {
                    let owner = Arc::clone(&provider_owner);
                    let clock = Arc::clone(&provider_clock);
                    let operation_id = provider_operation.clone();
                    async move {
                        let code =
                            provider_failure_code(error).ok_or(BaoAuthBusError::Evidence(
                                "nonterminal provider error classified terminal",
                            ))?;
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_provider_failed(
                                &operation_id,
                                current.revision,
                                code.to_owned(),
                                terminal.into_array(),
                                current.operation.amount,
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                prepare_delivery: move |receipt: &BaoSecretReceipt| {
                    let owner = Arc::clone(&preparation_owner);
                    let clock = Arc::clone(&preparation_clock);
                    let operation_id = preparation_operation.clone();
                    let receipt = receipt.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        let digest = receipt
                            .evidence_digest()
                            .map_err(|_| BaoAuthBusError::Evidence("receipt encoding failed"))?;
                        owner
                            .prepare_consumption_delivery(
                                &operation_id,
                                current.revision,
                                receipt,
                                digest,
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                consumer: move |secret: &[u8], _receipt: &BaoSecretReceipt| {
                    self.ensure_revocation_fresh().map_err(|_| ())?;
                    callback(operation_id, semantic_sha256, secret)
                },
                consumer_succeeded: move |_receipt: &BaoSecretReceipt| {
                    let owner = Arc::clone(&success_owner);
                    let clock = Arc::clone(&success_clock);
                    let operation_id = success_operation.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_succeeded(
                                &operation_id,
                                current.revision,
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
            },
        )
        .await;

        match saga_result {
            Ok(receipt) => {
                let current = owner
                    .consumption_result(operation_id)
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                owner
                    .settle_consumption_terminal(
                        operation_id,
                        current.revision,
                        self.product_now()?,
                    )
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                Ok(receipt)
            }
            Err(error @ BaoAuthBusError::Provider(_)) => {
                let current = owner
                    .consumption_result(operation_id)
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                if current.operation.state == BaoConsumptionStateV1::ProviderFailed {
                    let terminal = owner
                        .settle_consumption_terminal(
                            operation_id,
                            current.revision,
                            self.product_now()?,
                        )
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                    Err(BaoProductHostError::TerminalFailure(Box::new(
                        terminal.operation,
                    )))
                } else {
                    Err(BaoProductHostError::AuthBus(error))
                }
            }
            Err(error @ BaoAuthBusError::Indeterminate { .. }) => {
                self.mark_sqlite_indeterminate(owner, operation_id, &error)
                    .await?;
                Err(BaoProductHostError::AuthBus(error))
            }
            Err(error) => {
                if let Some(terminal) = self
                    .close_unreserved_sqlite_failure(authbus, owner, operation_id, &error)
                    .await?
                {
                    Err(BaoProductHostError::TerminalFailure(Box::new(terminal)))
                } else {
                    Err(BaoProductHostError::AuthBus(error))
                }
            }
        }
    }
}
