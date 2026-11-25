//! Test-only synthetic metadata/content with real Registry/issuer/FD/socket owners.
//! This does not construct a genuine Core human turn or a fresh writer receipt.
use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;

pub(super) const FAILURE: &[u8] = b"synthetic failure";
pub(super) const CORRECTION: &[u8] = b"synthetic correction";

pub(super) enum PeerInput {
    Open,
    Closed,
}

pub(super) struct ReadWatch {
    file: File,
    failure: i32,
    correction: i32,
}

impl ReadWatch {
    pub(super) fn new(directory: &Path) -> Self {
        use std::os::unix::ffi::OsStrExt;
        // SAFETY: creates an owned nonblocking watcher for these two private
        // synthetic files only; watches content-access events, not metadata.
        let fd = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
        assert!(fd >= 0, "{}", io::Error::last_os_error());
        let file = unsafe { File::from_raw_fd(fd) };
        let watch = |name| {
            let path = std::ffi::CString::new(directory.join(name).as_os_str().as_bytes()).unwrap();
            let id = unsafe {
                libc::inotify_add_watch(file.as_raw_fd(), path.as_ptr(), libc::IN_ACCESS)
            };
            assert!(id >= 0, "{}", io::Error::last_os_error());
            id
        };
        let failure = watch("failure");
        let correction = watch("correction");
        Self {
            file,
            failure,
            correction,
        }
    }

    pub(super) fn content_accesses(&mut self) -> (bool, bool) {
        let mut result = (false, false);
        let mut total = 0;
        let end = Instant::now() + Duration::from_secs(1);
        loop {
            assert!(Instant::now() < end);
            let mut bytes = [0; 4096];
            let length = match self.file.read(&mut bytes) {
                Ok(length) => length,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => return result,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => panic!("synthetic access observation failed: {error}"),
            };
            assert!(length > 0);
            total += length;
            assert!(total <= 65_536);
            let mut offset = 0;
            while offset < length {
                assert!(offset + 16 <= length);
                let id = i32::from_ne_bytes(bytes[offset..offset + 4].try_into().unwrap());
                let mask = u32::from_ne_bytes(bytes[offset + 4..offset + 8].try_into().unwrap());
                let extra = u32::from_ne_bytes(bytes[offset + 12..offset + 16].try_into().unwrap())
                    as usize;
                assert_eq!(mask & libc::IN_Q_OVERFLOW, 0);
                if mask & libc::IN_ACCESS != 0 {
                    result.0 |= id == self.failure;
                    result.1 |= id == self.correction;
                }
                offset += 16 + extra;
                assert!(offset <= length);
            }
        }
    }
}

pub(super) struct TrainingFixture {
    pub(super) original: Fixture,
    pub(super) identity: AgentdIdentity,
    pub(super) human: crate::authority_host_service::SyntheticOriginalHuman,
    pub(super) ingress: AuthBusTextIngress,
    pub(super) manifest: PairedTrainingMaterialManifestV1,
}

pub(super) fn pidfd() -> OwnedFd {
    // SAFETY: opens only this test process; a successful fd is uniquely owned.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(fd >= 0, "{}", io::Error::last_os_error());
    unsafe { OwnedFd::from_raw_fd(fd as i32) }
}

impl TrainingFixture {
    pub(super) fn new() -> Self {
        let (mut original, identity, human, ingress) = super::super::live::original();
        let manifest = PairedTrainingMaterialManifestV1 {
            failure_sha256: Digest32::of_bytes(FAILURE),
            failure_bytes: FAILURE.len() as u64,
            correction_sha256: Digest32::of_bytes(CORRECTION),
            correction_bytes: CORRECTION.len() as u64,
        };
        original.registration.preparation.frozen_materials = manifest.commitment().unwrap();
        original.registration.request.materials = manifest.commitment().unwrap();
        original.registration.enrollment_revision = 2;
        original.registration.effect_revision = 2;
        let (enrollment, effect, _) = original.registration.bindings(&original.writer).unwrap();
        for (id, binding) in [
            (original.registration.enrollment_id().unwrap(), enrollment),
            (original.registration.effect_id(), effect),
        ] {
            let current = original.registry.read_lease(&id).unwrap().unwrap().lease;
            original
                .registry
                .put_lease(
                    AuthorityLease {
                        revision: 2,
                        binding,
                        ..current
                    },
                    /*expected_revision*/ 1,
                )
                .unwrap();
        }
        for (name, bytes) in [("failure", FAILURE), ("correction", CORRECTION)] {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(original.directory.path().join(name))
                .unwrap();
            file.write_all(bytes).unwrap();
            file.sync_all().unwrap();
        }
        Self {
            original,
            identity,
            human,
            ingress,
            manifest,
        }
    }

    pub(super) fn owner(&self) -> RegisteredRootPaired {
        self.owner_with_files(
            File::open(self.original.directory.path().join("failure")).unwrap(),
            File::open(self.original.directory.path().join("correction")).unwrap(),
        )
    }

    pub(super) fn owner_with_files(&self, failure: File, correction: File) -> RegisteredRootPaired {
        let mut owner = self
            .original
            .open(self.original.registration.clone())
            .unwrap();
        // Test-local original custody only. Production's Root installer and
        // independent actual physical-login enrollment are not bypassed there.
        owner.training_materials = Some(
            FixedTrainingMaterials::capture(
                &self.original.registration,
                self.manifest.clone(),
                failure,
                correction,
                unsafe { libc::geteuid() },
            )
            .unwrap(),
        );
        owner
    }

    pub(super) fn reopen(self) -> Self {
        Self {
            original: self.original.reopen(),
            ..self
        }
    }

    pub(super) fn request_bytes(&self) -> Vec<u8> {
        #[derive(Serialize)]
        struct SyntheticPayload<'a> {
            schema: &'static str,
            identity: serde_json::Value,
            original_route: &'a crate::text_session::AgentdTextSessionConfig,
            permission_revision: u64,
            expires_at_ms: u64,
            statement_sha256: String,
        }
        let r = &self.original.registration;
        let p = &r.preparation;
        let purpose = r.request.original.usage.consent_text(p.study);
        let payload = serde_json::to_string(&SyntheticPayload {
            schema: "hepta.paired-learning.native-preparation.v1",
            identity: serde_json::json!({"study":p.study.to_string(), "enrollment":p.enrollment.to_string(),
                "materials":p.frozen_materials.to_string(), "principal":p.principal_id,
                "policy_generation":p.policy_generation.get(), "operation":r.request.operation.to_string(),
                "delivery":r.request.original.delivery_id.to_string(), "turn":r.request.original.turn_id,
                "purpose_statement":purpose}),
            original_route: &r.original_route, permission_revision: r.permission_revision,
            expires_at_ms: r.human_expires_at_ms, statement_sha256: Digest32::of_bytes(purpose.as_bytes()).to_string(),
        }).unwrap();
        let occurrence = format!(
            "paired.original-delivery.v1.{}",
            r.request.original.delivery_id
        );
        let scope = Digest32::from_array(r.bindings(&self.original.writer).unwrap().0.scope_sha256);
        let operation = OperationIntentV1::new(
            StableId::new(&occurrence).unwrap(),
            StableId::new(self.identity.agent_id.as_str()).unwrap(),
            StableId::new(crate::paired_preparation::DESTINATION).unwrap(),
            Digest32::of_bytes(payload.as_bytes()),
            scope,
            p.policy_generation,
            None,
        )
        .unwrap();
        let proof = self
            .original
            .issuer
            .retained_writer_authorization(&self.original.writer)
            .unwrap()
            .sha256()
            .unwrap();
        let payload_digest = operation.payload_digest().to_string();
        let semantic = operation.semantic_digest().to_string();
        let mut bytes = Vec::new();
        for part in [
            b"hepta:production-outbox-operation:v2".as_slice(),
            proof.as_str().as_bytes(),
            self.original.writer.local_lease_id.as_bytes(),
            occurrence.as_bytes(),
            b"hepta.paired-learning.prepare.v1".as_slice(),
            payload_digest.as_bytes(),
            semantic.as_bytes(),
        ] {
            bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
            bytes.extend_from_slice(part);
        }
        bytes.push(0);
        serde_json::to_vec(&serde_json::json!({"schema":"hepta.paired-training-read.v1", "ingress":self.ingress,
            "payload_json":payload, "binding":FinalUseBinding {
                subject_id:self.identity.agent_id.as_str().into(), destination_id:crate::paired_preparation::DESTINATION.into(),
                request_sha256:Digest32::of_bytes(&bytes).into_array(), scope_sha256:scope.into_array(),
                payload_sha256:operation.payload_digest().into_array(),
            }})).unwrap()
    }

    pub(super) fn channel(&self, raw: &[u8]) -> (HostAuthorityPeerChannel, UnixStream) {
        let (server, mut client) = UnixStream::pair().unwrap();
        client
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let server = HostAuthorityPeerChannel::from_stream(
            server,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: unsafe { libc::geteuid() },
                    pid: std::process::id(),
                },
                timeout: Duration::from_secs(1),
                lifetime: Duration::from_secs(2),
                request_bound: 65_536,
                response_bound: 65_536,
            },
            pidfd(),
        )
        .unwrap();
        client.write_all(&(raw.len() as u32).to_be_bytes()).unwrap();
        client.write_all(raw).unwrap();
        (server, client)
    }

    pub(super) fn serve(
        &self,
        owner: &RegisteredRootPaired,
        server: &mut HostAuthorityPeerChannel,
    ) -> Result<bool, HostIssuerTransportError> {
        server.exchange_with_original_response(|raw, response| {
            let request =
                crate::paired_preparation::material_protocol::PairedTrainingReadRequest::decode(
                    raw,
                )
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            let held = self
                .human
                .lifetime(response.current().deadline())
                .map_err(|_| HostIssuerTransportError::Unavailable)?;
            owner
                .read_fixed_training_once(&self.identity, &request, &held, response)
                .map_err(|_| HostIssuerTransportError::Unavailable)
        })
    }

    pub(super) fn exchange(
        &self,
        owner: &RegisteredRootPaired,
        raw: &[u8],
        input: PeerInput,
    ) -> (Result<bool, HostIssuerTransportError>, Vec<u8>) {
        let (mut server, mut client) = self.channel(raw);
        if matches!(input, PeerInput::Closed) {
            client.shutdown(std::net::Shutdown::Write).unwrap();
        }
        let result = self.serve(owner, &mut server);
        drop(server);
        let mut received = Vec::new();
        client.read_to_end(&mut received).unwrap();
        (result, received)
    }

    pub(super) fn blocked_channel(
        &self,
        raw: &[u8],
    ) -> (HostAuthorityPeerChannel, UnixStream, usize) {
        let (mut server, mut client) = UnixStream::pair().unwrap();
        client
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let size: libc::c_int = 4096;
        // SAFETY: a bounded socket option on this owned test endpoint only.
        assert_eq!(
            unsafe {
                libc::setsockopt(
                    server.as_raw_fd(),
                    libc::SOL_SOCKET,
                    libc::SO_SNDBUF,
                    (&size as *const libc::c_int).cast(),
                    std::mem::size_of_val(&size) as libc::socklen_t,
                )
            },
            0
        );
        server.set_nonblocking(true).unwrap();
        let mut buffered = 0;
        loop {
            match server.write(&[0x5a; 4096]) {
                Ok(count) => {
                    assert!(count > 0);
                    buffered += count;
                    assert!(buffered <= 262_144);
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(error) => panic!("unexpected synthetic buffer fill: {error}"),
            }
        }
        let server = HostAuthorityPeerChannel::from_stream(
            server,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: unsafe { libc::geteuid() },
                    pid: std::process::id(),
                },
                timeout: Duration::from_secs(1),
                lifetime: Duration::from_secs(2),
                request_bound: 65_536,
                response_bound: 65_536,
            },
            pidfd(),
        )
        .unwrap();
        client.write_all(&(raw.len() as u32).to_be_bytes()).unwrap();
        client.write_all(raw).unwrap();
        (server, client, buffered)
    }

    pub(super) fn wait_for_read_commit(&self) {
        let end = Instant::now() + Duration::from_millis(500);
        loop {
            let state = self.original.issuer.store.load(STATE_OWNER).unwrap();
            let value = serde_json::to_value(&state).unwrap();
            if value["paired_material_entries_v1"][self
                .original
                .registration
                .request
                .original
                .delivery_id
                .to_string()]["state"]["state"]
                == "read_committed"
            {
                return;
            }
            assert!(
                Instant::now() < end,
                "original read did not reach its actual durable commit"
            );
            std::thread::sleep(Duration::from_millis(1));
        }
    }
}
