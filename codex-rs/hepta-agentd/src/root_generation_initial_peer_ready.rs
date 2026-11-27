//! Private ordinary startup handshake. The same socket and pinned Root are
//! consumed on uncertainty; readiness is not an execution or completion grant.

use super::InitialBootstrap;
use super::OriginalPublicationStream;
use super::RootGenerationInitialClient;
use super::uncertain;
use crate::AgentdError;
use crate::RootGenerationPublicationConnectionV1;
use crate::authority_host_service::generation_initial::ready;

impl RootGenerationInitialClient {
    pub(crate) fn from_original_ready_stream(
        mut stream: OriginalPublicationStream,
        bootstrap: &InitialBootstrap,
        connection: RootGenerationPublicationConnectionV1,
    ) -> Result<Self, AgentdError> {
        connection.require_original_publication_session()?;
        let binding = ready::bootstrap_binding(bootstrap)?;
        let response = stream
            .exchange(&ready::request(&binding)?)
            .map_err(readiness_exchange_error)?;
        let acknowledged = ready::require_response(&response, &binding)?;
        connection.require_original_publication_session()?;
        let client: RootGenerationInitialClient =
            Self::from_original_initial_stream(stream, bootstrap, connection)?;
        if client.profile.binding != acknowledged {
            return Err(uncertain());
        }
        client.connection.require_original_publication_session()?;
        Ok(client)
    }
}

fn readiness_exchange_error(error: std::io::Error) -> std::io::Error {
    std::io::Error::new(
        error.kind(),
        format!("original Initial readiness frame exchange: {error}"),
    )
}
