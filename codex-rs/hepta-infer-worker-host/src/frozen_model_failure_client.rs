//! Same authenticated Root route, fixed readonly observation, whole finite facts.
use super::*;
use codex_hepta_infer_core::SelfIterationModelFailureFactsV1;
use codex_hepta_infer_core::SelfIterationModelRequestV1;

impl CpuNeuronFrozenGeneratorClientV1 {
    pub async fn observe_model_failure_facts(
        &self,
        request: &SelfIterationModelRequestV1,
    ) -> Result<Option<SelfIterationModelFailureFactsV1>, AgentdError> {
        let wire = SelfIterationModelFailureObservationRequestV1::from_request(request)
            .map_err(protocol)?;
        let bytes =
            encode_self_iteration_model_failure_observation_request_v1(&wire).map_err(protocol)?;
        let route = Route::read(&self.route_path, self.route_digest).map_err(protocol)?;
        let exchange = async {
            validate_issuer_socket(&route.socket, 0).map_err(protocol)?;
            let mut stream = UnixStream::connect(&route.socket).await?;
            let response = exchange_connected_bytes(
                &mut stream,
                &route,
                &bytes,
                MAX_SELF_ITERATION_FAILURE_OBSERVATION_RESPONSE_BYTES_V1,
            )
            .await?;
            Route::read(&self.route_path, self.route_digest).map_err(protocol)?;
            match decode_self_iteration_model_failure_observation_response_v1(&response)
                .map_err(protocol)?
            {
                SelfIterationModelFailureObservationResponseV1::Facts(wire) => {
                    let facts = wire.facts().map_err(protocol)?;
                    if facts.request != *request {
                        return Err(AgentdError::Protocol(
                            "Root failure observation changed exact original request".into(),
                        ));
                    }
                    Ok(Some(facts))
                }
                SelfIterationModelFailureObservationResponseV1::Refused(refusal)
                    if matches!(
                        refusal.error,
                        FrozenGeneratorErrorCodeV1::Pending
                            | FrozenGeneratorErrorCodeV1::Unavailable
                    ) =>
                {
                    Ok(None)
                }
                SelfIterationModelFailureObservationResponseV1::Refused(refusal) => {
                    Err(AgentdError::Protocol(format!(
                        "Root readonly model failure refused: {:?}",
                        refusal.error
                    )))
                }
            }
        };
        tokio::time::timeout(
            Duration::from_millis(route.maximum_request_duration_ms),
            exchange,
        )
        .await
        .map_err(|_| AgentdError::Protocol("readonly model failure observation unknown".into()))?
    }
}
