//! Receive the already sealed original B purpose under the same actual
//! five-lane session. Connect observes only its binding; it never executes B.

use std::io::Read;
use std::io::Seek;
use std::time::Duration;
use std::time::Instant;

use super::*;
use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::RootIndependentBEvaluationHandoffV1;

impl OriginalRootIndependentBEvaluationClientV1 {
    pub(crate) async fn connect_until(
        mut handoff: RootIndependentBEvaluationHandoffV1,
        connection: OriginalRootBEvaluationConnectionV1,
        timeout: Duration,
        end: Instant,
    ) -> Result<Arc<Self>, AgentdError> {
        // SAFETY: both calls only observe the actual process credentials.
        if unsafe { libc::getuid() } == 0
            || unsafe { libc::geteuid() } == 0
            || timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || remaining(end)? > Duration::from_secs(300)
        {
            return Err(refused("original non-Root bounded B consumer required"));
        }
        connection.require_original()?;
        let length = handoff.bootstrap.metadata()?.len();
        if length == 0 || length > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
            return Err(refused("bounded original B bootstrap required"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&handoff.bootstrap, length)?;
        handoff.bootstrap.rewind()?;
        let mut bytes = Vec::with_capacity(length as usize);
        handoff
            .bootstrap
            .by_ref()
            .take(length + 1)
            .read_to_end(&mut bytes)?;
        crate::authority_host_bootstrap_seal::validate_sealed(&handoff.bootstrap, length)?;
        let bootstrap: Bootstrap = serde_json::from_slice(&bytes)?;
        let (original, identity) = connection.original_launch_binding();
        let socket = original
            .sockets
            .observation
            .parent()
            .ok_or_else(|| refused("original B socket parent missing"))?
            .join(SOCKET);
        if length as usize != bytes.len()
            || serde_json::to_vec(&bootstrap)? != bytes
            || bootstrap.purpose != PURPOSE
            || bootstrap.root != original.root
            || bootstrap.consumer != original.consumer
            || bootstrap.identity.identity()? != *identity
            || bootstrap.root.pid != handoff.root_pid
            || bootstrap.root.uid != 0
            || bootstrap.writer != original.writer_proof.sha256()?.as_str()
            || bootstrap.socket != socket
        {
            return Err(refused(
                "B route differs from the actual original Root session",
            ));
        }
        super::candidate_data::require_original_data_file(&handoff.candidate_data, &bootstrap)?;
        let initial = digest(&bootstrap.initial)?;
        digest(&bootstrap.scope)?;
        digest(&bootstrap.writer)?;
        if digest(&bootstrap.binding)?
            != Digest32::of_parts(&[
                b"hepta.root.independent-b.custodian.v1\0",
                initial.as_array(),
            ])
        {
            return Err(refused("original B custodian binding differs"));
        }
        let paths = &original.sockets;
        // SAFETY: getegid only reads the actual current credential.
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
        connection.require_original()?;
        let stream = tokio::time::timeout(
            timeout.min(remaining(end)?),
            tokio::net::UnixStream::connect(&socket),
        )
        .await
        .map_err(|_| refused("original B connect timed out"))??;
        remaining(end)?;
        let stream = OriginalPublicationStream::from_stream_until(
            stream.into_std()?,
            handoff.root_pidfd,
            AgentdRootAuthorityPeer {
                pid: bootstrap.root.pid,
                boot_id: bootstrap.root.boot_id.clone(),
                process_start_ticks: bootstrap.root.process_start_ticks,
            },
            timeout,
            end,
        )?;
        // Bootstrap performs no execution/signing request. Stage methods below
        // are synchronous and stay in the aggregate's original blocking lane.
        tokio::task::spawn_blocking(move || {
            connection.require_original()?;
            let client = Self {
                bootstrap,
                connection,
                lane: Mutex::new(Lane {
                    stream,
                    sequence: 1,
                }),
                candidate_data: Mutex::new(handoff.candidate_data),
                refused: AtomicBool::new(false),
            };
            let observation = client
                .exchange(Command::Observe)
                .map_err(|error| AgentdError::Io(std::io::Error::other(error)))?;
            match observation {
                Observation::Bound { initial } if initial == client.bootstrap.initial => {}
                Observation::Bound { .. } | Observation::Completed(_) => {
                    return Err(refused("original B observe response differs"));
                }
            }
            client.connection.require_original()?;
            remaining(end)?;
            Ok(Arc::new(client))
        })
        .await
        .map_err(|_| refused("original B connect worker lost"))?
    }
}

fn remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|remaining| !remaining.is_zero())
        .ok_or_else(|| refused("original B session expired"))
}

fn refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
