//! final use host ingress implementation.

use super::*;

impl BaoFinalUseHost {
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
        let started = Instant::now();
        let result = async {
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
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::InvalidInput))?;
            let semantic_sha256 = Digest32::of_bytes(&semantics).into_array();
            let operation_id = admission.operation_id.as_str();
            let _execution = registry
                .lock()
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
            #[cfg(all(test, unix))]
            crate::saga_crash::cut("claim.before");
            let existing = registry
                .lock()
                .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                .claim_consumption(operation)
                .map_err(BaoProductHostError::Store)?;
            #[cfg(all(test, unix))]
            crate::saga_crash::cut("claim.after");
            if let Some(existing) = existing {
                return match existing.state.recovery_action() {
                    BaoConsumptionRecoveryActionV1::ReturnHistoricalSuccess => {
                        existing.receipt.ok_or(BaoProductHostError::Store(
                            LeaseRegistryErrorV1::CorruptState,
                        ))
                    }
                    BaoConsumptionRecoveryActionV1::ReturnHistoricalFailure => {
                        Err(BaoProductHostError::TerminalFailure(Box::new(existing)))
                    }
                    _ => Err(BaoProductHostError::OutcomePending(Box::new(existing))),
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
                crate::authbus_saga::BaoAuthBusSagaHooks {
                    reserved: |reservation: &QuotaReservation| {
                        let result = match registry.lock() {
                            Ok(mut owner) => owner
                                .mark_consumption_reserved(
                                    operation_id,
                                    reservation.reservation_id.as_str().to_owned(),
                                )
                                .map_err(|_| {
                                    BaoAuthBusError::Evidence("durable reservation commit failed")
                                }),
                            Err(_) => Err(BaoAuthBusError::Evidence("durable owner unavailable")),
                        };
                        std::future::ready(result)
                    },
                    dispatch_fenced: |reservation: &QuotaReservation| {
                        let result = match registry.lock() {
                            Ok(mut owner) => owner
                                .mark_consumption_dispatch_fenced(
                                    operation_id,
                                    reservation.reservation_id.as_str(),
                                )
                                .map_err(|_| {
                                    BaoAuthBusError::Evidence(
                                        "durable dispatch fence commit failed",
                                    )
                                }),
                            Err(_) => Err(BaoAuthBusError::Evidence("durable owner unavailable")),
                        };
                        std::future::ready(result)
                    },
                    provider_terminal: |error: BaoClientError, terminal: Digest32| {
                        let result = provider_failure_code(error)
                            .ok_or(BaoAuthBusError::Evidence(
                                "nonterminal provider error classified terminal",
                            ))
                            .and_then(|code| match registry.lock() {
                                Ok(mut owner) => owner
                                    .record_provider_failure(
                                        operation_id,
                                        code,
                                        terminal.into_array(),
                                        admission.amount,
                                    )
                                    .map_err(|_| {
                                        BaoAuthBusError::Evidence(
                                            "durable provider terminal commit failed",
                                        )
                                    }),
                                Err(_) => {
                                    Err(BaoAuthBusError::Evidence("durable owner unavailable"))
                                }
                            });
                        std::future::ready(result)
                    },
                    prepare_delivery: |receipt: &BaoSecretReceipt| {
                        let result = match registry.lock() {
                            Ok(mut owner) => owner
                                .enter_consumption(operation_id, receipt.clone())
                                .map_err(|_| {
                                    BaoAuthBusError::Evidence("durable delivery preparation failed")
                                }),
                            Err(_) => Err(BaoAuthBusError::Evidence("durable owner unavailable")),
                        };
                        std::future::ready(result)
                    },
                    consumer: |secret: &[u8], _receipt: &BaoSecretReceipt| {
                        self.ensure_revocation_fresh().map_err(|_| ())?;
                        callback(operation_id, semantic_sha256, secret)
                    },
                    consumer_succeeded: |_receipt: &BaoSecretReceipt| {
                        let result = match registry.lock() {
                            Ok(mut owner) => {
                                owner.observe_consumption(operation_id, true).map_err(|_| {
                                    BaoAuthBusError::Evidence(
                                        "durable consumer observation commit failed",
                                    )
                                })
                            }
                            Err(_) => Err(BaoAuthBusError::Evidence("durable owner unavailable")),
                        };
                        std::future::ready(result)
                    },
                },
            )
            .await;
            match result {
                Ok(_) => {
                    #[cfg(all(test, unix))]
                    crate::saga_crash::cut("local_terminal.before");
                    let result = registry
                        .lock()
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .settle_consumption(operation_id)
                        .map_err(BaoProductHostError::Store);
                    #[cfg(all(test, unix))]
                    crate::saga_crash::cut("local_terminal.after");
                    result
                }
                Err(error @ BaoAuthBusError::Provider(_)) => {
                    let current = registry
                        .lock()
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .consumption_result(operation_id)
                        .map_err(BaoProductHostError::Store)?;
                    if current.state == BaoConsumptionStateV1::ProviderFailed {
                        let row = registry
                            .lock()
                            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                            .settle_consumption_failure(operation_id)
                            .map_err(BaoProductHostError::Store)?;
                        Err(BaoProductHostError::TerminalFailure(Box::new(row)))
                    } else if let Some(terminal) = self
                        .close_unreserved_failure_if_proved(authbus, registry, operation_id, &error)
                        .await?
                    {
                        Err(BaoProductHostError::TerminalFailure(Box::new(terminal)))
                    } else {
                        Err(BaoProductHostError::AuthBus(error))
                    }
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
                        Err(BaoProductHostError::TerminalFailure(Box::new(terminal)))
                    } else {
                        Err(BaoProductHostError::AuthBus(error))
                    }
                }
            }
        }
        .await;
        self.record_forward_metric(started, &result);
        result
    }

    pub(super) async fn close_unreserved_failure_if_proved(
        &self,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        operation_id: &str,
        error: &BaoAuthBusError,
    ) -> Result<Option<BaoConsumptionOperationV1>, BaoProductHostError> {
        let operation = StableId::new(operation_id.to_owned())
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState))?;
        let row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        if row.state != BaoConsumptionStateV1::Claimed {
            return Ok(None);
        }
        if authbus
            .seal_unreserved_operation(&operation, Digest32::from_array(row.effect_sha256))
            .await
            .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
            .is_some()
        {
            return Ok(None);
        }
        let evidence = Digest32::of_bytes(
            format!("hepta.bao.pre-reservation.v1:{operation_id}:{error:?}").as_bytes(),
        );
        let terminal = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .record_consumption_abort(operation_id, false, "no_reservation", evidence.into_array())
            .map_err(BaoProductHostError::Store)?;
        Ok(Some(terminal))
    }
}
