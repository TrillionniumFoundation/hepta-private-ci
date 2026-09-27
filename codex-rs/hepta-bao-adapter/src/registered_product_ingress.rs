//! Registered forward execution. Recovery exclusion spans all await points.
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
        let BaoApprovedReadV1 {
            admission,
            grant,
            approval,
            request,
        } = read;
        let _execution = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_execution(admission.operation_id.as_str())
            .map_err(BaoProductHostError::Store)?;
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
            "hepta.bao.durable-product.v1",
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
        let mut semantic_sha256 = Digest32::of_bytes(&semantics).into_array();
        let operation_id = admission.operation_id.as_str();
        let historical = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id);
        match historical {
            Ok(row) if row.semantic_sha256 != semantic_sha256 => {
                let mut compatible = semantics.clone();
                // The only compatibility change is the terminal domain byte.
                let prefix = b"[\"hepta.bao.durable-product.v1\"";
                if compatible.starts_with(prefix) {
                    compatible[prefix.len() - 2] = b'2';
                }
                if Digest32::of_bytes(&compatible).into_array() == row.semantic_sha256 {
                    semantic_sha256 = row.semantic_sha256;
                }
            }
            Ok(_) | Err(LeaseRegistryErrorV1::OperationNotFound) => {}
            Err(error) => return Err(BaoProductHostError::Store(error)),
        }
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
            crate::authbus_saga::BaoSagaCallbacks {
            reserved: |reservation| {
                registry
                    .lock()
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .mark_consumption_reserved(
                        operation_id,
                        reservation.reservation_id.as_str().to_owned(),
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable reservation commit failed"))
            },
            dispatch_fenced: |reservation| {
                registry
                    .lock()
                    .map_err(|_| BaoAuthBusError::Evidence("durable owner unavailable"))?
                    .mark_consumption_dispatch_fenced(
                        operation_id,
                        reservation.reservation_id.as_str(),
                    )
                    .map_err(|_| BaoAuthBusError::Evidence("durable dispatch fence commit failed"))
            },
            provider_terminal: |error, terminal| {
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
            prepare_delivery: |receipt| {
                registry
                    .lock()
                    .map_err(|_| ())?
                    .enter_consumption(operation_id, receipt.clone())
                    .map_err(|_| ())
            },
            consumer: |secret, _receipt| {
                self.ensure_revocation_fresh().map_err(|_| ())?;
                // Revalidate the durable owner after provider I/O and before entry.
                registry.lock().map_err(|_| ())?
                    .consumption_result(operation_id).map_err(|_| ())?;
                let result = callback(operation_id, semantic_sha256, secret);
                #[cfg(all(test, unix))]
                crate::saga_crash::cut("consumer_ack.before");
                registry
                    .lock()
                    .map_err(|_| ())?
                    .observe_consumption(operation_id, result.is_ok())
                    .map_err(|_| ())?;
                #[cfg(all(test, unix))]
                crate::saga_crash::cut("consumer_ack.after");
                result
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
            },
            Err(error @ BaoAuthBusError::Provider(_)) => {
                let current = registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .consumption_result(operation_id)
                    .map_err(BaoProductHostError::Store)?;
                if current.state != BaoConsumptionStateV1::ProviderFailed {
                    return match self
                        .close_unreserved_failure_if_proved(
                            authbus, registry, operation_id, evidence,
                        )
                        .await?
                    {
                        Some(row) => Err(BaoProductHostError::TerminalFailure(row)),
                        None => Err(BaoProductHostError::AuthBus(error)),
                    };
                }
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
                    .close_unreserved_failure_if_proved(authbus, registry, operation_id, evidence)
                    .await?
                {
                    Err(BaoProductHostError::TerminalFailure(terminal))
                } else {
                    Err(BaoProductHostError::AuthBus(error))
                }
            }
        }
    }

    async fn close_unreserved_failure_if_proved<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        operation_id: &str,
        evidence: &mut E,
    ) -> Result<Option<BaoConsumptionOperationV1>, BaoProductHostError> {
        let row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        if row.state != BaoConsumptionStateV1::Claimed {
            return Ok(None);
        }
        let operation = StableId::new(operation_id.to_owned())
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState))?;
        let time = authbus
            .observe_trusted_time_attestation(
                &evidence.trusted_time().map_err(BaoProductHostError::AuthBus)?,
            )
            .await
            .map_err(|error| BaoProductHostError::AuthBus(error.into()))?;
        if authbus
            .seal_unreserved_operation(
                &operation, Digest32::from_array(row.effect_sha256), time,
            )
            .await
            .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
            .is_some()
        {
            return Ok(None);
        }
        let terminal = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .record_consumption_abort(
                operation_id, false, "no_reservation",
                abort_evidence(&row, "no_reservation", None),
            )
            .map_err(BaoProductHostError::Store)?;
        Ok(Some(terminal))
    }

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
