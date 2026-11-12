//! Connect only a sealed complete-task offer from the original Root and the
//! independent connection captured by the original five-lane receiver.

use std::io::Read;
use std::io::Seek;
use std::time::Duration;
use std::time::Instant;

use super::*;
use crate::AgentdRootAuthorityPeer;
use crate::RootHistoricalTaskReadHandoffV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadBootstrapV1;
use crate::root_historical_task_read_protocol::SOCKET;

impl RootHistoricalTaskReadHandoffV1 {
    pub(crate) async fn connect_original(
        mut self,
        connection: RootHistoricalTaskReadConnectionV1,
        timeout: Duration,
        launch_end: Instant,
    ) -> Result<Arc<RootHistoricalTaskReadClientV1>, AgentdError> {
        connection.require_original_session()?;
        let end = connection.original_end().min(launch_end);
        remaining(end)?;
        if timeout.is_zero() || timeout > Duration::from_millis(500) {
            return Err(invalid("historical read timeout exceeds original bound"));
        }
        let size = self.bootstrap.metadata()?.len();
        if size == 0 || size > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
            return Err(invalid("historical read bootstrap exceeds original bound"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, size)?;
        self.bootstrap.rewind()?;
        let mut bytes = Vec::with_capacity(size as usize);
        self.bootstrap
            .by_ref()
            .take(size + 1)
            .read_to_end(&mut bytes)?;
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, size)?;
        if bytes.len() as u64 != size {
            return Err(invalid("historical read sealed bootstrap changed"));
        }
        let bundle: HistoricalTaskReadBootstrapV1 = serde_json::from_slice(&bytes)?;
        let (original, identity) = connection.original_binding();
        let socket = original
            .sockets
            .observation
            .parent()
            .ok_or_else(|| invalid("original Root socket parent missing"))?
            .join(SOCKET);
        if bundle.schema != 1
            || bundle.purpose != PURPOSE
            || bundle.root != original.root
            || bundle.consumer != original.consumer
            || bundle.root.pid != self.root_pid
            || bundle.root.uid != 0
            || bundle.identity.identity()? != *identity
            || original.registered_identity.identity()? != *identity
            || bundle.socket != socket
        {
            return Err(invalid(
                "historical route differs from the original Root session",
            ));
        }
        let initial = bundle.profile.require_original_context(
            identity,
            original.writer_proof.sha256()?.as_str(),
            &bundle.initial,
        )?;
        let paths = &original.sockets;
        // SAFETY: getegid only reads the current kernel credential.
        crate::authority_host_runtime::validate_lane_paths(
            &[
                &paths.observation,
                &paths.issuer,
                &paths.checkpoint,
                &paths.device_frontier,
                &paths.notes_frontier,
                &socket,
            ],
            unsafe { libc::getegid() },
        )?;
        connection.require_original_session()?;
        let stream = tokio::time::timeout(
            timeout.min(remaining(end)?),
            tokio::net::UnixStream::connect(&socket),
        )
        .await
        .map_err(|_| invalid("original historical Root connection timed out"))??;
        let stream = OriginalPublicationStream::from_stream_until(
            stream.into_std()?,
            self.root_pidfd,
            AgentdRootAuthorityPeer {
                pid: bundle.root.pid,
                boot_id: bundle.root.boot_id,
                process_start_ticks: bundle.root.process_start_ticks,
            },
            timeout,
            end,
        )?;
        connection.require_original_session()?;
        remaining(end)?;
        Ok(Arc::new(
            RootHistoricalTaskReadClientV1::from_original_stream(
                stream,
                connection,
                bundle.profile.binding,
                initial,
            )?,
        ))
    }
}

fn remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero() && *value <= Duration::from_secs(300))
        .ok_or_else(|| invalid("original historical read deadline expired"))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
