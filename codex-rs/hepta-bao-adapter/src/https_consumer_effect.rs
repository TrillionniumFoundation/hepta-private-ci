use super::*;

impl BaoClient {
    /// Product composition for a quota-controlled Bao read. The adapter
    /// accepts only the bounded effect port; it cannot enroll issuers or mutate
    /// policy and quota configuration.
    pub async fn consume_kv_v2_with_authbus<
        E: BaoAuthBusEvidenceProvider,
        C: AsAuthBusEffectPort + ?Sized,
    >(
        &self,
        authbus: &C,
        admission: &BaoAuthBusAdmission,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        evidence: &mut E,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoSecretReceipt, BaoAuthBusError> {
        if admission.policy_revision == 0
            || admission.expected_quota_revision == 0
            || admission.amount == 0
            || admission.expires_at_ms == 0
        {
            return Err(BaoClientError::InvalidRequest.into());
        }
        let authbus = authbus.as_authbus_effect_port();
        let binding = self.binding(request)?;
        let principal = StableId::new(binding.subject_id.clone())
            .map_err(|_| BaoClientError::InvalidRequest)?;
        let action =
            StableId::new("action:bao-read").map_err(|_| BaoClientError::InvalidRequest)?;
        let scope = Digest32::from_array(binding.scope_sha256);
        let effect_digest = self.authbus_effect_digest(request, &admission.operation_id)?;

        let observed = evidence.trusted_time()?;
        let time = authbus.observe_trusted_time_attestation(&observed).await?;
        let decision = authbus
            .authorize(
                &principal,
                &action,
                scope,
                admission.policy_revision,
                time.clone(),
            )
            .await?;
        let reservation = authbus
            .reserve(
                &decision,
                ReservationRequest {
                    quota_key: admission.quota_key.clone(),
                    operation_id: admission.operation_id.clone(),
                    amount: admission.amount,
                    effect_digest,
                    expected_quota_revision: admission.expected_quota_revision,
                    expires_at_ms: admission.expires_at_ms,
                },
                time,
            )
            .await?;

        // Re-sample authenticated time immediately before the irreversible
        // boundary. Once this transition commits, timeout/transport uncertainty
        // can never refund quota without signed terminal evidence.
        let dispatch_time = authbus
            .observe_trusted_time_attestation(&evidence.trusted_time()?)
            .await?;
        let dispatched = authbus
            .mark_dispatch_attempted(
                &reservation.reservation_id,
                reservation.revision,
                effect_digest,
                dispatch_time,
            )
            .await?;

        let provider = self
            .consume_kv_v2(authority, grant, request, consumer)
            .await;
        match provider {
            Ok(receipt) => {
                let terminal = Digest32::of_bytes(
                    &serde_json::to_vec(&receipt)
                        .map_err(|_| BaoAuthBusError::Evidence("receipt encoding failed"))?,
                );
                settle_observed(
                    &authbus,
                    evidence,
                    &dispatched,
                    SettlementStatus::Completed,
                    admission.amount,
                    terminal,
                    Some(receipt),
                )
                .await?
                .ok_or(BaoAuthBusError::Evidence(
                    "successful settlement lost its receipt",
                ))
            }
            Err(error) if ambiguous_after_dispatch(&error) => {
                let time = authbus
                    .observe_trusted_time_attestation(&evidence.trusted_time()?)
                    .await;
                match time {
                    Ok(time) => {
                        let _ = authbus
                            .mark_indeterminate(
                                &dispatched.reservation_id,
                                dispatched.revision,
                                time,
                            )
                            .await;
                    }
                    Err(_) => {
                        // The durable DispatchAttempted row remains conservative;
                        // restart reconciliation promotes it to Indeterminate.
                    }
                }
                Err(BaoAuthBusError::Indeterminate {
                    reservation_id: dispatched.reservation_id,
                    provider_error: error,
                })
            }
            Err(error) => {
                let terminal =
                    Digest32::of_bytes(format!("hepta.bao.terminal.v3:{error:?}").as_bytes());
                match settle_observed(
                    &authbus,
                    evidence,
                    &dispatched,
                    SettlementStatus::Completed,
                    admission.amount,
                    terminal,
                    None,
                )
                .await
                {
                    Ok(None) => Err(BaoAuthBusError::Provider(error)),
                    Ok(Some(_)) => Err(BaoAuthBusError::Evidence(
                        "terminal provider failure unexpectedly produced a receipt",
                    )),
                    Err(pending) => Err(pending),
                }
            }
        }
    }
}


async fn settle_observed<E: BaoAuthBusEvidenceProvider>(
    authbus: &AuthBusEffectPort<'_>,
    evidence: &mut E,
    reservation: &QuotaReservation,
    status: SettlementStatus,
    observed_cost: u64,
    terminal_evidence_digest: Digest32,
    receipt: Option<BaoSecretReceipt>,
) -> Result<Option<BaoSecretReceipt>, BaoAuthBusError> {
    let time = match authbus
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await
    {
        Ok(time) => time,
        Err(error) => {
            return Err(BaoAuthBusError::SettlementPending {
                reservation_id: reservation.reservation_id.clone(),
                receipt,
                control_error: error.to_string(),
            });
        }
    };
    let signed = evidence.settlement_evidence(
        reservation,
        status,
        observed_cost,
        terminal_evidence_digest,
        time.wall_time_ms(),
    )?;
    if let Err(error) = authbus.settle(&signed, time).await {
        return Err(BaoAuthBusError::SettlementPending {
            reservation_id: reservation.reservation_id.clone(),
            receipt,
            control_error: error.to_string(),
        });
    }
    Ok(receipt)
}

fn ambiguous_after_dispatch(error: &BaoClientError) -> bool {
    matches!(
        error,
        BaoClientError::TransportUnavailable
            | BaoClientError::TimedOut
            | BaoClientError::ConsumerIndeterminate
            | BaoClientError::Authority(_)
            | BaoClientError::InvalidConfiguration
            | BaoClientError::InvalidRequest
    )
}

