//! Original publication path shared by statically selected execution profiles.
//!
//! Static selection lets a finite Organ reuse admission without linking the
//! model/App Server execution branch. It does not select an effect owner or
//! change replay, generation, signature, publication or Notes operation checks.

use super::*;

/// An internal composition decision, never supplied in an IPC request.
trait ObjectiveExecutionProfile {
    fn execute<'a>(
        agentd: &'a AgentdState,
        record: &'a RunStartRecordV1,
    ) -> impl std::future::Future<Output = Result<&'static str, AgentdError>> + Send + 'a;
}

struct FullObjectiveExecution;
#[cfg(target_os = "linux")]
struct FiniteNotesExecution;

impl ObjectiveExecutionProfile for FullObjectiveExecution {
    async fn execute<'a>(
        agentd: &'a AgentdState,
        record: &'a RunStartRecordV1,
    ) -> Result<&'static str, AgentdError> {
        let disposition = match record.disposition {
            RunStartObjectiveDispositionV1::Compiled => {
                match agentd.start_canonical_intelligence(record).await? {
                    Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready { .. }) => {
                        "canonical_ready"
                    }
                    Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained) => {
                        "canonical_abstained"
                    }
                    Some(crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath) => {
                        "canonical_slow_path"
                    }
                    None => {
                        agentd.start_current_run_start_record(record)?;
                        agentd.execute_notes_objective(record).await?;
                        "compiled"
                    }
                }
            }
            RunStartObjectiveDispositionV1::ExplicitAbstain => "explicit_abstain",
        };
        Ok(disposition)
    }
}

#[cfg(target_os = "linux")]
impl ObjectiveExecutionProfile for FiniteNotesExecution {
    async fn execute<'a>(
        agentd: &'a AgentdState,
        record: &'a RunStartRecordV1,
    ) -> Result<&'static str, AgentdError> {
        match record.disposition {
            RunStartObjectiveDispositionV1::Compiled => {
                agentd.start_current_run_start_record(record)?;
                agentd.execute_notes_objective(record).await?;
                Ok("compiled")
            }
            RunStartObjectiveDispositionV1::ExplicitAbstain => Ok("explicit_abstain"),
        }
    }
}

impl ObjectiveRuntimeHost {
    pub(crate) async fn submit(
        &self,
        agentd: &AgentdState,
        request: AuthBusObjectiveIngress,
        current_generation: u64,
    ) -> Result<ObjectiveStartResult, AgentdError> {
        self.submit_for::<FullObjectiveExecution>(agentd, request, current_generation)
            .await
    }

    #[cfg(target_os = "linux")]
    pub(crate) async fn submit_notes(
        &self,
        agentd: &AgentdState,
        request: AuthBusObjectiveIngress,
        current_generation: u64,
    ) -> Result<ObjectiveStartResult, AgentdError> {
        if agentd.notes_objective.get().is_none()
            || agentd.production_operations.get().is_none()
            || agentd.intelligence_product.get().is_some()
            || agentd.intelligence_invocation.get().is_some()
        {
            return Err(invalid(
                "finite Notes execution requires its original dedicated owner",
            ));
        }
        self.submit_for::<FiniteNotesExecution>(agentd, request, current_generation)
            .await
    }

    async fn submit_for<P: ObjectiveExecutionProfile>(
        &self,
        agentd: &AgentdState,
        request: AuthBusObjectiveIngress,
        current_generation: u64,
    ) -> Result<ObjectiveStartResult, AgentdError> {
        authbus_ingress::require_objective_ready(agentd)?;
        let now_ms = authbus_ingress::now_ms()?;
        let payload = objective_payload(agentd.identity(), &request.body, current_generation)?;
        if request.expires_at_ms <= now_ms || request.expires_at_ms.saturating_sub(now_ms) > 300_000
        {
            return Err(invalid("objective expiry must be within five minutes"));
        }

        let authbus = authbus_ingress::attached(agentd)?;
        let trust = authbus.trust(agentd)?;
        let issuer = trust.issuer()?;
        let message = SignedMessage {
            claims: authbus_objective_claims(agentd.identity(), &request)?,
            signature: hex_bytes(&request.signature_hex)?,
        };
        let authenticated = message
            .authenticate(
                &issuer,
                objective_scope(agentd.identity()),
                Digest32::of_bytes(&payload),
                now_ms,
            )
            .map_err(|error| invalid(&format!("objective signature: {error}")))?;

        let source = decode_source_envelope_json_v1(request.body.source_envelope_json.as_bytes())
            .map_err(|error| invalid(&format!("objective source: {error}")))?;
        agentd
            .validate_notes_source(
                self.profile_digest,
                &request.body.run_id,
                source.structured_intent.provenance.source_digest,
            )
            .await?;
        let now_unix_micros = now_ms
            .checked_mul(1_000)
            .ok_or_else(|| invalid("objective host clock overflow"))?;
        let context = ObjectiveAdmissionContextV1 {
            revision: Revision::new(request.body.objective_revision)
                .map_err(|error| invalid(&format!("objective revision: {error}")))?,
            now_unix_micros,
            selected_profile_digest: self.profile_digest,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: issuer.issuer_id,
                source_digest: source.structured_intent.provenance.source_digest,
            },
        };

        let runtime_body_digest = parse_digest(&request.body.runtime_body_digest, "runtime body")?;
        let preference_state_digest =
            parse_digest(&request.body.preference_state_digest, "preference state")?;
        let model_tuple_digest = parse_digest(&request.body.model_tuple_digest, "model tuple")?;
        let prompt_registry_digest =
            parse_digest(&request.body.prompt_registry_digest, "prompt registry")?;
        let artifact_set_digest = parse_digest(&request.body.artifact_set_digest, "artifact set")?;
        let run_id = StableId::new(&request.body.run_id)
            .map_err(|error| invalid(&format!("objective run id: {error}")))?;
        let authentication = RunStartAuthenticationV1 {
            issuer_id: authenticated.claims().issuer_id.clone(),
            key_epoch: authenticated.claims().key_epoch.get(),
            message_id: authenticated.claims().message_id.clone(),
            sequence: authenticated.claims().sequence,
            expires_at_ms: authenticated.claims().expires_at_ms,
            scope_digest: authenticated.claims().scope_digest,
            signed_body_digest: authenticated.claims().payload_digest,
            signature: message.signature,
        };

        // Durable publication and replay-frontier mutation remain serialized,
        // but the guard is deliberately dropped before seven-owner execution.
        let (published, record) = {
            let mut state = self.state.lock().map_err(|_| {
                AgentdError::Protocol("objective runtime mutex is poisoned".to_string())
            })?;
            require_replay_admission(&state, &authentication, &run_id)?;

            let expected_run_start_head = state.journal.head_digest();
            let published = match compile_and_publish_objective_run_v1(
                &source,
                &self.profile,
                &context,
                ObjectiveRunBindingsV1 {
                    authentication,
                    run_id: run_id.clone(),
                    runtime_body_digest,
                    preference_state_digest,
                    model_tuple_digest,
                    prompt_registry_digest,
                    artifact_set_digest,
                    authority_epoch: request.body.authority_epoch,
                    generation: current_generation,
                    fence_digest: objective_fence(agentd.identity(), current_generation),
                    expected_run_start_head,
                },
                &mut state.journal,
            ) {
                Ok(published) => published,
                Err(ObjectiveRunError::Conflict {
                    conflict,
                    publication: _,
                }) => {
                    let record = state
                        .journal
                        .get_conflict(&run_id)
                        .map_err(store_error)?
                        .cloned()
                        .ok_or_else(|| {
                            invalid("durable objective conflict publication disappeared")
                        })?;
                    let key = (
                        record.authentication.issuer_id.to_string(),
                        record.authentication.key_epoch,
                    );
                    state
                        .highest_sequences
                        .entry(key)
                        .and_modify(|value| *value = (*value).max(record.authentication.sequence))
                        .or_insert(record.authentication.sequence);
                    return Ok(ObjectiveStartResult::Conflict {
                        run_id: request.body.run_id,
                        conflict_digest: conflict.conflict_digest.to_string(),
                    });
                }
                Err(error) => {
                    return Err(invalid(&format!("objective publication: {error}")));
                }
            };

            let record = state
                .journal
                .get(&run_id)
                .map_err(store_error)?
                .cloned()
                .ok_or_else(|| invalid("durable objective publication disappeared"))?;
            let key = (
                record.authentication.issuer_id.to_string(),
                record.authentication.key_epoch,
            );
            state
                .highest_sequences
                .entry(key)
                .and_modify(|value| *value = (*value).max(record.authentication.sequence))
                .or_insert(record.authentication.sequence);
            (published, record)
        };

        authbus_ingress::require_objective_ready(agentd)?;
        let current = authbus.trust(agentd)?;
        if !authentication_is_current(
            &record,
            &current,
            agentd.identity(),
            authbus_ingress::now_ms()?,
        )? {
            return Err(invalid(
                "objective trust changed after durable publication; retry after reconciliation",
            ));
        }

        let disposition = P::execute(agentd, &record).await?;

        Ok(ObjectiveStartResult::Admitted(ObjectiveRunAdmission {
            run_id: published.run_start.run_id.to_string(),
            objective_digest: published.run_start.objective_digest.to_string(),
            hard_constraint_digest: published.run_start.hard_constraint_digest.to_string(),
            publication_digest: published.publication.record_digest.to_string(),
            chain_digest: published.publication.chain_digest.to_string(),
            disposition: disposition.to_string(),
            idempotent: published.publication.disposition
                == RunStartAppendDisposition::IdempotentReplay,
        }))
    }
}
