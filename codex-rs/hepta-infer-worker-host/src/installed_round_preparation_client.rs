//! One bounded exchange with the original Root route. Unknown work retains the
//! reservation; only a protected whole output can complete preparation.
use super::*;
use crate::initial_cpu_anchor::InstalledCpuSourceV1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;

pub(crate) async fn prepare(
    source: &InstalledCpuSourceV1,
    round: &AgentdSelfIterationRoundV1,
) -> Result<RoundPreparationResultV1, AgentdError> {
    let pin: Digest32 = source.digest.parse().map_err(protocol)?;
    let route = Route::read(&source.path, pin).map_err(protocol)?;
    let round_bytes = round.canonical_bytes()?;
    let request = encode_round_preparation_request_v1(
        &RoundPreparationRequestV1::from_round_bytes(&round_bytes).map_err(protocol)?,
    ).map_err(protocol)?;
    let exchange = async {
        validate_issuer_socket(&route.socket, /*issuer_uid*/ 0).map_err(protocol)?;
        let mut stream = UnixStream::connect(&route.socket).await?;
        let bytes = exchange_connected_bytes(
            &mut stream, &route, &request, MAX_ROUND_PREPARATION_RESPONSE_BYTES_V1,
        ).await?;
        Route::read(&source.path, pin).map_err(protocol)?;
        let response = decode_round_preparation_response_v1(&bytes).map_err(protocol)?;
        if response.round_payload_digest != Digest32::of_bytes(&round_bytes).to_string() {
            return Err(protocol("Root preparation changed the whole original reservation"));
        }
        Ok(response.result)
    };
    tokio::time::timeout(Duration::from_millis(route.maximum_request_duration_ms), exchange)
        .await
        .map_err(|_| protocol("original preparation outcome remains unknown"))?
}
