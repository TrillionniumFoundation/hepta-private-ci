//! Original evaluated entry and sealed initial-only entry into one physical owner.
use super::*;
use crate::smollm_cognitive_host::InitialReadPermitV1;

impl NeuralCognitiveInferencePortV1 for SmolLmNeuralReadPortV1 {
    fn execute(
        &self,
        request: &NeuralCognitiveRequestV1,
        parameters: &[u8],
        execution: &codex_hepta_agentd::NeuralCognitiveExecutionV1,
    ) -> Result<NeuralCognitiveObservationV1, String> {
        let pin = self
            .pin
            .as_ref()
            .ok_or("initial-only model cannot enter the evaluated neural route")?;
        execution.check()?;
        if self.admission_closed.load(Ordering::SeqCst) {
            return Err(
                "neural session has unresolved physical execution; unload required".to_owned(),
            );
        }
        if request.owner_id != self.context.owner_id
            || request.body_generation != self.context.body_generation
            || &request.pin != pin
            || Digest32::of_bytes(parameters) != pin.payload_digest
            || request.query_digest != Digest32::of_bytes(request.query.as_bytes())
            || request.query.is_empty()
            || request.query.len() > 2048
            || request.action_ids.is_empty()
            || request.action_ids.len() > 128
        {
            return Err("neural owner request differs from its pinned parameters".to_owned());
        }
        let action_bytes = serde_json::to_vec(
            &request
                .action_ids
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>(),
        )
        .map_err(|error| error.to_string())?;
        let payload = Digest32::of_parts(&[
            b"hepta.smollm-read-request.v1\0",
            request.owner_id.as_str().as_bytes(),
            &request.body_generation.to_be_bytes(),
            pin.payload_digest.as_array(),
            pin.execution_profile_digest.as_array(),
            request.query_digest.as_array(),
            &action_bytes,
        ]);
        let (scores_q32, execution_receipt_digest) = self.execute_physical(
            &request.query,
            &request.action_ids,
            payload,
            pin.compatibility_digest(),
            execution,
        )?;
        // Verify the original completed load/forward journal before publishing
        // this historical observation. A failed join never refunds its nonce.
        let verified = self
            .with_measurements(|load, forward| {
                super::settled::verify(
                    &self.context,
                    request,
                    payload,
                    execution_receipt_digest,
                    load,
                    forward,
                )
            })
            .and_then(std::convert::identity)
            .and_then(|()| execution.check());
        if let Err(error) = verified {
            self.admission_closed.store(true, Ordering::SeqCst);
            return Err(error);
        }
        Ok(NeuralCognitiveObservationV1 {
            request: request.clone(),
            scores_q32,
            execution_receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl SmolLmNeuralReadPortV1 {
    pub(crate) fn execute_initial(
        &self,
        permit: InitialReadPermitV1<'_>,
        query: &str,
        action_ids: &[StableId],
        execution: &codex_hepta_agentd::NeuralCognitiveExecutionV1,
    ) -> Result<(Option<Vec<i64>>, Digest32), String> {
        let selection = permit.consume_for(self)?;
        execution.check()?;
        if query.is_empty() || query.len() > 2048 || action_ids.is_empty() || action_ids.len() > 128
        {
            return Err("initial query exceeds its original registered bounds".to_owned());
        }
        if self.pin.is_some() {
            return Err("evaluated port cannot consume an initial-only permit".to_owned());
        }
        let actions = serde_json::to_vec(
            &action_ids
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>(),
        )
        .map_err(|error| error.to_string())?;
        let payload = Digest32::of_parts(&[
            b"hepta.smollm.selected-initial-read-request.v1\0",
            self.context.owner_id.as_str().as_bytes(),
            &self.context.body_generation.to_be_bytes(),
            selection.as_array(),
            self.physical.payload_digest.as_array(),
            self.physical.execution_profile_digest.as_array(),
            Digest32::of_bytes(query.as_bytes()).as_array(),
            &actions,
        ]);
        self.execute_physical(query, action_ids, payload, self.scope, execution)
    }
}
