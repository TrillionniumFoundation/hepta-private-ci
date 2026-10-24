//! Optional native UI lane of the SAME Root service and canonical issuer.
//! Registration is read from a Root-owned file; peer JSON can only hello,
//! sign exact bounded text, or look up its original signature identity.
use super::*;
use crate::AuthBusTextBody;
use crate::TextIssuerOperation;
use crate::text_session::AgentdTextSessionConfig;
use crate::text_session::TextOwnerReceipt;
use codex_hepta_contracts::AuthorityClock;
use std::os::unix::net::UnixListener;
use std::time::Duration;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityTextUiRegistration {
    pub schema_version: u32,
    pub socket_path: std::path::PathBuf,
    pub peer_uid: u32,
    pub peer_gid: u32,
    pub peer_pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
    /// An identity already authenticated by the trusted launcher. Never read
    /// from renderer JSON, a Console token, or socket connectivity alone.
    pub principal_id: String,
    pub session_id: String,
    pub permission_revision: u64,
    pub expires_at_ms: u64,
    pub route: AgentdTextSessionConfig,
    pub can_interrupt: bool,
    /// Explicit existing human-session permission, never inferred from text
    /// submission or a model provider login. Old registrations default to false.
    #[serde(default)]
    pub can_resolve_approvals: bool,
}

#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Hello {
        schema_version: u32,
    },
    Pending {
        schema_version: u32,
        after_sequence: u64,
        through_sequence: u64,
    },
    Sign {
        schema_version: u32,
        request_id: String,
        agent_id: codex_hepta_contracts::AgentId,
        spawn_generation: u64,
        thread_id: String,
        text: String,
    },
    Lookup {
        schema_version: u32,
        request_id: String,
        agent_id: codex_hepta_contracts::AgentId,
        spawn_generation: u64,
        thread_id: String,
        text: String,
    },
    Retire {
        schema_version: u32,
        request_id: String,
        agent_id: codex_hepta_contracts::AgentId,
        spawn_generation: u64,
        thread_id: String,
        text: String,
    },
    CloseUnsigned {
        schema_version: u32,
        request_id: String,
        agent_id: codex_hepta_contracts::AgentId,
        spawn_generation: u64,
        thread_id: String,
        text: String,
    },
}

impl HostAuthorityTextUiRegistration {
    fn namespace(&self) -> String {
        let bytes = format!(
            "hepta.ui.text.intent.v1\0{}\0{}\0{}",
            self.principal_id, self.route.agent_id, self.route.thread_id
        );
        format!(
            "text:{}",
            codex_hepta_types::Digest32::of_bytes(bytes.as_bytes())
        )
    }

    fn receipt(&self) -> TextOwnerReceipt {
        TextOwnerReceipt {
            schema_version: 1,
            protocol: "hepta.ui-chat-owner.v1".into(),
            principal_id: self.principal_id.clone(),
            session_id: self.session_id.clone(),
            permission_revision: self.permission_revision,
            expires_at_ms: self.expires_at_ms,
            route: self.route.clone(),
            can_interrupt: self.can_interrupt,
            can_resolve_approvals: self.can_resolve_approvals,
            intent_namespace: self.namespace(),
            next_intent_sequence: 1,
        }
    }

    pub(crate) fn validate(&self, service: &HostAuthorityService) -> io::Result<()> {
        if self.schema_version != 1
            || self.peer_uid == 0
            || self.peer_pid == 0
            || self.peer_pid > i32::MAX as u32
            || self.process_start_ticks == 0
            || !self.receipt().validate()
            || self.route.agent_id != service.identity.agent_id
            || self.route.spawn_generation != service.identity.spawn_generation
            || self.route.control_socket != service.identity.control_socket
            || self.route.codex_home != service.identity.home_root
        {
            return Err(io::Error::other(
                "text UI registration differs from original owner",
            ));
        }
        crate::DeploymentFinalUseIssuer::text_destination(&self.route.thread_id)?;
        let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", self.peer_pid))?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok());
        if boot.trim() != self.boot_id || start != Some(self.process_start_ticks) {
            return Err(io::Error::other(
                "text UI process lifetime identity mismatch",
            ));
        }
        let status = std::fs::read_to_string(format!("/proc/{}/status", self.peer_pid))?;
        let expected = self.peer_uid.to_string();
        let values = status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:"))
            .map(|line| line.split_whitespace().collect::<Vec<_>>())
            .unwrap_or_default();
        if values.len() != 4 || values.iter().any(|value| *value != expected) {
            return Err(io::Error::other("text UI exact UID mismatch"));
        }
        service.text_ui_owner(self).map_err(io::Error::other)?;
        Ok(())
    }
}

impl HostAuthorityService {
    fn text_ui_owner(
        &self,
        registration: &HostAuthorityTextUiRegistration,
    ) -> Result<TextOwnerReceipt, HostIssuerTransportError> {
        self.issuer
            .text_route_available(&self.identity, &registration.route.thread_id)
            .map_err(unavailable)?;
        let bytes = self
            .writer
            .as_ref()
            .ok_or(HostIssuerTransportError::Unavailable)?
            .observe(
                &self.issuer,
                &self.clock,
                &self.identity,
                &ObservationRequest {
                    schema_version: 2,
                    operation: crate::HOST_AUTHORITY_OBSERVATION_V2.into(),
                },
            )?;
        let observed: crate::HostAuthorityObservationResponseV2 = decode(&bytes)?;
        if observed.observed_unix_ms >= registration.expires_at_ms
            || registration.expires_at_ms > observed.writer.authority_lease.expires_at_unix_ms
            || registration.permission_revision != observed.writer.authority_lease.revision
        {
            return Err(HostIssuerTransportError::Unavailable);
        }
        let mut receipt = registration.receipt();
        receipt.next_intent_sequence = self.issuer.next_text_intent().map_err(unavailable)?;
        Ok(receipt)
    }

    fn handle_text_ui(
        &self,
        registration: &HostAuthorityTextUiRegistration,
        bytes: &[u8],
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        let request: Request = decode(bytes)?;
        let owner = self.text_ui_owner(registration)?;
        let mode = if matches!(&request, Request::Lookup { .. }) {
            TextIssuerOperation::Lookup
        } else {
            TextIssuerOperation::Sign
        };
        let retiring = matches!(&request, Request::Retire { .. });
        let closing_unsigned = matches!(&request, Request::CloseUnsigned { .. });
        match request {
            Request::Hello { schema_version: 1 } => encode_bounded(&owner, 16 * 1024),
            Request::Hello { .. } => Err(HostIssuerTransportError::InvalidRequest),
            Request::Pending {
                schema_version,
                after_sequence,
                through_sequence,
            } => {
                if schema_version != 1 {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                let entry = self
                    .issuer
                    .retained_text_page(
                        &self.identity,
                        &owner.intent_namespace,
                        &owner.route.thread_id,
                        after_sequence,
                        through_sequence,
                    )
                    .map_err(unavailable)?;
                // Recheck the original writer lease after reading. Principal,
                // namespace, route and generation never come from peer JSON.
                self.text_ui_owner(registration)?;
                encode_bounded(
                    &serde_json::json!({
                        "schema_version": 1, "operation": "pending",
                        "through_sequence": through_sequence,
                        "entry": entry.map(|(request_id, envelope)| serde_json::json!({
                            "request_id": request_id, "envelope": envelope
                        }))
                    }),
                    32 * 1024,
                )
            }
            Request::Sign {
                schema_version,
                request_id,
                agent_id,
                spawn_generation,
                thread_id,
                text,
            }
            | Request::Lookup {
                schema_version,
                request_id,
                agent_id,
                spawn_generation,
                thread_id,
                text,
            }
            | Request::Retire {
                schema_version,
                request_id,
                agent_id,
                spawn_generation,
                thread_id,
                text,
            }
            | Request::CloseUnsigned {
                schema_version,
                request_id,
                agent_id,
                spawn_generation,
                thread_id,
                text,
            } => {
                if schema_version != 1
                    || agent_id != owner.route.agent_id
                    || spawn_generation != owner.route.spawn_generation
                    || thread_id != owner.route.thread_id
                    || text.trim().is_empty()
                    || text.len() > 8192
                    || !request_id
                        .strip_prefix(&format!("{}:", owner.intent_namespace))
                        .is_some_and(|suffix| {
                            !suffix.is_empty() && suffix.bytes().all(|byte| byte.is_ascii_digit())
                        })
                {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                let body = AuthBusTextBody {
                    spawn_generation,
                    thread_id,
                    text,
                };
                if retiring {
                    return self.retire_text_ui(registration, &request_id, body);
                }
                if closing_unsigned {
                    let outcome = self
                        .writer
                        .as_ref()
                        .ok_or(HostIssuerTransportError::Unavailable)?
                        .close_unsigned_text(
                            &self.issuer,
                            &self.identity,
                            &owner.intent_namespace,
                            &request_id,
                            body,
                        )
                        .map_err(unavailable)?;
                    self.text_ui_owner(registration)?;
                    return encode_bounded(
                        &serde_json::json!({
                            "schema_version": 1, "operation": "close_unsigned", "request_id": request_id, "outcome": outcome,
                        }),
                        32 * 1024,
                    );
                }
                let envelope = self
                    .writer
                    .as_ref()
                    .ok_or(HostIssuerTransportError::Unavailable)?
                    .text(&self.issuer, &self.identity, &request_id, body, mode)
                    .map_err(unavailable)?;
                self.text_ui_owner(registration)?;
                encode_bounded(
                    &serde_json::json!({"schema_version":1,"request_id":request_id,"envelope":envelope}),
                    32 * 1024,
                )
            }
        }
    }

    fn retire_text_ui(
        &self,
        registration: &HostAuthorityTextUiRegistration,
        request_id: &str,
        body: AuthBusTextBody,
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        // An ACK lost after the retirement CAS only reads its monotonic state;
        // no expired signature needs to be regenerated or sent anywhere.
        if !self
            .issuer
            .text_reference_retired(request_id)
            .map_err(unavailable)?
        {
            let writer = self
                .writer
                .as_ref()
                .ok_or(HostIssuerTransportError::Unavailable)?;
            let original = writer
                .text(
                    &self.issuer,
                    &self.identity,
                    request_id,
                    body,
                    TextIssuerOperation::Lookup,
                )
                .map_err(unavailable)?;
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(unavailable)?;
            let observed_root_ms = self.clock.now_unix_ms().map_err(unavailable)?;
            let verified = runtime.block_on(async {
                tokio::time::timeout(
                    Duration::from_secs(4),
                    crate::deployment_issuer::VerifiedTextRetirement::read_original(
                        registration.route.clone(),
                        original,
                        observed_root_ms,
                    ),
                )
                .await
                .map_err(unavailable)?
                .map_err(unavailable)
            });
            runtime.shutdown_timeout(Duration::from_millis(100));
            writer
                .retire_text(&self.issuer, &self.identity, request_id, verified?)
                .map_err(unavailable)?;
        }
        self.text_ui_owner(registration)?;
        encode_bounded(
            &serde_json::json!({"schema_version":1,"operation":"retired","request_id":request_id}),
            1024,
        )
    }

    /// Finite repeated connections from the one registered UI lifetime. Each
    /// exchange uses the existing peer channel/pidfd guard; no key enters UI.
    pub(crate) fn serve_text_ui(
        &self,
        registration: &HostAuthorityTextUiRegistration,
        ui_pidfd: &OwnedFd,
        daemon_pidfd: &OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> io::Result<()> {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        registration.validate(self)?;
        let path = &registration.socket_path;
        let parent = path
            .parent()
            .ok_or_else(|| io::Error::other("text socket parent"))?;
        let metadata = std::fs::symlink_metadata(parent)?;
        if !path.is_absolute()
            || !metadata.is_dir()
            || metadata.uid() != 0
            || metadata.gid() != registration.peer_gid
            || metadata.mode() & 0o7777 != 0o2710
        {
            return Err(io::Error::other(
                "text socket parent must be root:peer-gid mode02710",
            ));
        }
        for ancestor in parent.ancestors() {
            let entry = std::fs::symlink_metadata(ancestor)?;
            if !entry.is_dir() || entry.uid() != 0 || entry.mode() & 0o022 != 0 {
                return Err(io::Error::other("unsafe text socket ancestor"));
            }
        }
        let listener = UnixListener::bind(path)?;
        let _guard = SocketGuard {
            path: path.clone(),
            identity: std::fs::symlink_metadata(path)?,
        };
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))?;
        listener.set_nonblocking(true)?;
        let end = std::time::Instant::now() + lifetime;
        loop {
            if std::time::Instant::now() >= end {
                return Ok(());
            }
            crate::authority_host_runtime::owner_alive(daemon_pidfd, end)?;
            crate::authority_host_runtime::owner_alive(ui_pidfd, end)?;
            match listener.accept() {
                Ok((stream, _)) => {
                    let policy = HostAuthorityPeerPolicy {
                        peer: codex_hepta_contracts::HostIssuerPeer {
                            uid: registration.peer_uid,
                            pid: registration.peer_pid,
                        },
                        timeout,
                        lifetime: end.saturating_duration_since(std::time::Instant::now()),
                        request_bound: 32 * 1024,
                        response_bound: 32 * 1024,
                    };
                    // A wrong peer or malformed request never affects another
                    // lane and cannot extend the original bounded lifetime.
                    if let Ok(mut channel) =
                        HostAuthorityPeerChannel::from_stream(stream, policy, ui_pidfd.try_clone()?)
                    {
                        let _ = channel.exchange(|bytes| {
                            crate::authority_host_runtime::owner_alive(daemon_pidfd, end)
                                .map_err(unavailable)?;
                            let response = self.handle_text_ui(registration, bytes)?;
                            crate::authority_host_runtime::owner_alive(daemon_pidfd, end)
                                .map_err(unavailable)?;
                            Ok(response)
                        });
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(5))
                }
                Err(error) => return Err(error),
            }
        }
    }
}

struct SocketGuard {
    path: std::path::PathBuf,
    identity: std::fs::Metadata,
}
impl Drop for SocketGuard {
    fn drop(&mut self) {
        use std::os::unix::fs::MetadataExt;
        if std::fs::symlink_metadata(&self.path).is_ok_and(|value| {
            value.dev() == self.identity.dev() && value.ino() == self.identity.ino()
        }) {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}
