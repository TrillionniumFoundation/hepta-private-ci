//! Reconstruct only the exact retained, signed input, never a replacement input.
//! Journal hashes detect corruption; AuthBus authenticates the original body;
//! the objective owner separately checks the deterministic admission projection.
use super::*;

pub(super) fn retained_body(
    record: &RunStartRecordV1,
    identity: &AgentdIdentity,
) -> Result<AuthBusObjectiveBody, AgentdError> {
    let bytes = &record.authentication.signed_body_bytes;
    if bytes.is_empty() || bytes.len() > PRODUCT_BODY_JSON_BYTES {
        return Err(invalid(
            "durable objective lacks bounded original signed input",
        ));
    }
    if Digest32::of_bytes(bytes) != record.authentication.signed_body_digest {
        return Err(invalid("durable objective signed input digest changed"));
    }
    let body: AuthBusObjectiveBody = serde_json::from_slice(bytes)?;
    if objective_payload(identity, &body, record.snapshot.generation)? != *bytes {
        return Err(invalid("durable objective input is not canonical"));
    }
    let snapshot = &record.snapshot;
    if body.run_id != snapshot.run_id.as_str()
        || body.authority_epoch != snapshot.authority_epoch
        || parse_digest(&body.runtime_body_digest, "runtime body")? != record.runtime_body_digest
        || parse_digest(&body.preference_state_digest, "preference state")?
            != snapshot.preference_state_digest
        || parse_digest(&body.model_tuple_digest, "model tuple")? != snapshot.model_tuple_digest
        || parse_digest(&body.prompt_registry_digest, "prompt registry")?
            != snapshot.prompt_registry_digest
        || parse_digest(&body.artifact_set_digest, "artifact set")? != snapshot.artifact_set_digest
    {
        return Err(invalid(
            "durable objective projection differs from signed input",
        ));
    }
    Ok(body)
}

impl ObjectiveRuntimeHost {
    /// Validate every derived value against the selected owner profile at the
    /// ORIGINAL admission time. Reopening does not extend a relative deadline.
    pub(crate) fn revalidate_projection(
        &self,
        record: &RunStartRecordV1,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        let body = retained_body(record, identity)?;
        if record.admission.profile_digest != self.profile_digest {
            return Err(invalid("durable objective owner profile changed"));
        }
        let source = decode_source_envelope_json_v1(body.source_envelope_json.as_bytes())
            .map_err(|error| invalid(&format!("retained objective source: {error}")))?;
        let context = ObjectiveAdmissionContextV1 {
            revision: Revision::new(body.objective_revision)
                .map_err(|error| invalid(&format!("retained objective revision: {error}")))?,
            now_unix_micros: record.admission.observed_at_unix_micros,
            selected_profile_digest: self.profile_digest,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: record.authentication.issuer_id.clone(),
                source_digest: source.structured_intent.provenance.source_digest,
            },
        };
        let outcome =
            codex_hepta_objective::admit_and_compile_objective_v1(&source, &self.profile, &context)
                .map_err(|error| invalid(&format!("retained objective admission: {error}")))?;
        let receipt = &outcome.receipt;
        let admission = codex_hepta_learning_ledger::RunStartAdmissionBindingV1 {
            profile_id: receipt.profile_id.clone(),
            profile_revision: receipt.profile_revision.get(),
            profile_digest: receipt.profile_digest,
            supplied_source_digest: receipt.supplied_source_digest,
            intent_digest: receipt.intent_digest,
            admitted_source_digest: receipt.admitted_source_digest,
            observed_at_unix_micros: receipt.observed_at_unix_micros,
            deadline_unix_micros: receipt
                .deadline_unix_micros
                .ok_or_else(|| invalid("retained objective deadline missing"))?,
            authority: receipt.authority,
        };
        if admission != record.admission {
            return Err(invalid(
                "durable objective admission differs from original input",
            ));
        }
        let compiled = outcome
            .compile_result
            .map_err(|_| invalid("retained objective now conflicts"))?;
        let disposition = match compiled.disposition {
            codex_hepta_objective::CompileDisposition::Compiled => {
                RunStartObjectiveDispositionV1::Compiled
            }
            codex_hepta_objective::CompileDisposition::ExplicitAbstain => {
                RunStartObjectiveDispositionV1::ExplicitAbstain
            }
        };
        let protocol = codex_hepta_objective::encode_objective_function_v1(
            &compiled,
            &source,
            &self.profile,
            receipt,
        )
        .map_err(|error| invalid(&format!("retained objective protocol: {error}")))?;
        if disposition != record.disposition
            || compiled.objective.hard_constraint_digest != record.snapshot.hard_constraint_digest
            || compiled.objective.semantic_digest != record.snapshot.objective_digest
            || codex_hepta_objective::canonical_native_objective_semantic_bytes_v1(
                &compiled.objective,
            ) != record.objective_semantic_bytes
            || protocol.protocol_digest() != record.objective_function_v1_digest
            || protocol.canonical_bytes() != record.objective_function_v1_bytes
        {
            return Err(invalid(
                "durable objective compiled projection was substituted",
            ));
        }
        Ok(())
    }
}
