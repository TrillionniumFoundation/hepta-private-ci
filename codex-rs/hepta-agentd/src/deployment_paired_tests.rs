//! Synthetic enrollment and purpose metadata with actual temporary owners.
//! No human token, production Root enrollment or material-use grant is made.
use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[path = "deployment_paired_enrollment_tests.rs"]
mod enrollment;
#[path = "deployment_paired_live_tests.rs"]
mod live;
#[path = "deployment_paired_material_tests.rs"]
mod materials;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    clock: Arc<Clock>,
    registry: Arc<AuthorityLeaseRegistry>,
    issuer: Arc<DeploymentFinalUseIssuer>,
    writer: HostAuthorityWriterRegistration,
    registration: HostAuthorityPairedRegistration,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum PairRecords {
    Existing,
    PendingEnrollment,
}

impl Fixture {
    fn new() -> Self {
        Self::with_records(PairRecords::Existing)
    }

    fn with_records(records: PairRecords) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(10_000)));
        let registry = Arc::new(
            AuthorityLeaseRegistry::open_state_dir_with_clock(
                &directory.path().join("leases"),
                "synthetic-paired-owner".into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
                clock.clone(),
            )
            .unwrap(),
        );
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let writer = HostAuthorityWriterRegistration {
            registered_agent_id: agent.clone(),
            spawn_generation: 7,
            owner_epoch: 4,
            local_lease_id: "synthetic-paired-local-writer".into(),
            local_lease_generation: 9,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "synthetic-paired-writer".into(),
                authority_epoch: 1,
                revision: 1,
                issued_at_unix_ms: 10_000,
                expires_at_unix_ms: 20_000,
                binding: AuthorityLeaseBinding {
                    principal_id: agent.as_str().into(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "synthetic-cognitive-owner".into(),
                    scope_sha256: [4; 32],
                    payload_sha256: [5; 32],
                },
            },
        };
        let preparation = crate::PairedPreparationRegistration {
            study: Digest32::of_bytes(b"synthetic study"),
            enrollment: Digest32::of_bytes(b"synthetic enrollment"),
            frozen_materials: Digest32::of_bytes(b"synthetic material commitment"),
            principal_id: "synthetic-person".into(),
            policy_generation: Generation::new(1).unwrap(),
        };
        let registration = HostAuthorityPairedRegistration {
            request: crate::PairedPreparationRequest {
                original: crate::PairedTurnRequest {
                    turn_id: "synthetic-turn".into(),
                    delivery_id: Digest32::of_bytes(b"synthetic delivery"),
                    study: preparation.study,
                    expected_principal: preparation.principal_id.clone(),
                    usage: crate::PairedLearningDataUse::TrainOnFailureAndCorrection {
                        failure: Digest32::of_bytes(b"synthetic failure"),
                        correction: Digest32::of_bytes(b"synthetic correction"),
                    },
                },
                operation: Digest32::of_bytes(b"synthetic operation"),
                materials: preparation.frozen_materials,
            },
            preparation,
            original_route: crate::text_session::AgentdTextSessionConfig {
                control_socket: "/synthetic/agentd.sock".into(),
                agent_id: agent,
                spawn_generation: 7,
                thread_id: "synthetic-thread".into(),
                app_server_session_id: "synthetic-session".into(),
                codex_home: "/synthetic/home".into(),
            },
            permission_revision: 1,
            human_expires_at_ms: 17_000,
            enrollment_revision: 1,
            effect_revision: 1,
            effect_lifetime_ms: 5_000,
        };
        let (enrollment, effect, policy) = registration.bindings(&writer).unwrap();
        for (index, record) in [
            writer.authority_lease.clone(),
            AuthorityLease {
                lease_id: "synthetic-paired-issuer".into(),
                binding: AuthorityLeaseBinding {
                    operation_class: "synthetic-root-issuer".into(),
                    ..writer.authority_lease.binding.clone()
                },
                ..writer.authority_lease.clone()
            },
            AuthorityLease {
                lease_id: registration.enrollment_id().unwrap(),
                binding: enrollment,
                expires_at_unix_ms: 18_000,
                ..writer.authority_lease.clone()
            },
            AuthorityLease {
                lease_id: registration.effect_id(),
                binding: effect,
                expires_at_unix_ms: 15_000,
                ..writer.authority_lease.clone()
            },
        ]
        .into_iter()
        .enumerate()
        {
            if records == PairRecords::PendingEnrollment && index >= 2 {
                continue;
            }
            registry.put_lease(record, /*expected_revision*/ 0).unwrap();
        }
        let mut issuer = DeploymentFinalUseIssuer::create(
            &directory.path().join("issuer"),
            "synthetic-paired-issuer".into(),
            vec![policy],
            clock.clone(),
        )
        .unwrap();
        // Ordinary fixture state only. Production must receive the original
        // protected factory, registry and writer; this bypass is test-local.
        issuer.lease = Some(
            ProtectedLease::new(registry.verifier(), "synthetic-paired-issuer".into(), 1).unwrap(),
        );
        issuer
            .register_writer_authorization(&writer, &registry.verifier())
            .unwrap();
        Self {
            directory,
            clock,
            registry,
            issuer: Arc::new(issuer),
            writer,
            registration,
        }
    }

    fn open(
        &self,
        registration: HostAuthorityPairedRegistration,
    ) -> io::Result<RegisteredRootPaired> {
        RegisteredRootPaired::open(
            self.issuer.clone(),
            self.registry.clone(),
            self.writer.clone(),
            registration,
        )
    }

    fn reopen(self) -> Self {
        let Self {
            directory,
            clock,
            registry,
            issuer,
            writer,
            registration,
        } = self;
        let frontier = registry.frontier().unwrap();
        drop(issuer);
        drop(registry);
        let registry = Arc::new(
            AuthorityLeaseRegistry::open_state_dir_with_clock(
                &directory.path().join("leases"),
                "synthetic-paired-owner".into(),
                frontier,
                clock.clone(),
            )
            .unwrap(),
        );
        let mut issuer =
            DeploymentFinalUseIssuer::open(&directory.path().join("issuer"), clock.clone())
                .unwrap();
        issuer.lease = Some(
            ProtectedLease::new(registry.verifier(), "synthetic-paired-issuer".into(), 1).unwrap(),
        );
        Self {
            directory,
            clock,
            registry,
            issuer: Arc::new(issuer),
            writer,
            registration,
        }
    }
}

#[test]
fn paired_root_open_and_reopen_only_observe_original_records_and_counter() {
    let f = Fixture::new();
    let frontier = f.registry.frontier().unwrap();
    let state = serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let owner = f.open(f.registration.clone()).unwrap();
    let original = owner.observe().unwrap();
    assert_eq!(owner.observe().unwrap(), original);
    drop(owner);
    let f = f.reopen();
    assert_eq!(
        f.open(f.registration.clone()).unwrap().observe().unwrap(),
        original
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        state
    );
}

#[test]
fn paired_root_changed_purpose_material_route_or_principal_cannot_open_another_slot() {
    let f = Fixture::new();
    let before = f.registry.frontier().unwrap();
    for mutation in 0..5 {
        let mut registration = f.registration.clone();
        match mutation {
            0 => {
                registration.request.original.usage =
                    crate::PairedLearningDataUse::EvaluateOnlyAfterFreeze {
                        freeze: Digest32::of_bytes(b"synthetic freeze"),
                        task: Digest32::of_bytes(b"synthetic task"),
                    }
            }
            1 => {
                registration.preparation.frozen_materials = Digest32::of_bytes(b"other material");
                registration.request.materials = registration.preparation.frozen_materials;
            }
            2 => registration.original_route.app_server_session_id = "other-session".into(),
            3 => {
                registration.preparation.principal_id = "other-person".into();
                registration.request.original.expected_principal = "other-person".into();
            }
            4 => registration.preparation.enrollment = Digest32::of_bytes(b"changed enrollment"),
            _ => unreachable!(),
        }
        assert_eq!(registration.effect_id(), f.registration.effect_id());
        assert!(f.open(registration).is_err());
        assert_eq!(f.registry.frontier().unwrap(), before);
    }
}

#[test]
fn paired_root_independent_enrollment_revocation_survives_reopen_without_replacement() {
    let f = Fixture::new();
    let owner = f.open(f.registration.clone()).unwrap();
    let id = f.registration.enrollment_id().unwrap();
    let original = f.registry.read_lease(&id).unwrap().unwrap().lease;
    f.registry
        .revoke(&id, /*expected_revision*/ 1, [8; 32])
        .unwrap();
    let revoked = f.registry.frontier().unwrap();
    assert!(owner.observe().is_err());
    drop(owner);
    let f = f.reopen();
    assert!(f.open(f.registration.clone()).is_err());
    assert!(
        f.registry
            .put_lease(original, /*expected_revision*/ 0)
            .is_err()
    );
    assert_eq!(f.registry.frontier().unwrap(), revoked);
}

#[test]
fn paired_root_conflicting_effect_cas_never_rebinds_retained_owner() {
    let f = Fixture::new();
    let owner = f.open(f.registration.clone()).unwrap();
    let id = f.registration.effect_id();
    let mut changed = f.registry.read_lease(&id).unwrap().unwrap().lease;
    changed.revision = 2;
    changed.binding.payload_sha256 = [7; 32];
    f.registry
        .put_lease(changed.clone(), /*expected_revision*/ 1)
        .unwrap();
    let after = f.registry.frontier().unwrap();
    assert!(owner.observe().is_err());
    let mut registration = f.registration.clone();
    registration.effect_revision = 2;
    assert!(f.open(registration).is_err());
    assert_eq!(f.registry.read_lease(&id).unwrap().unwrap().lease, changed);
    assert_eq!(f.registry.frontier().unwrap(), after);
}

#[test]
fn paired_root_equal_foreign_registry_is_refused_without_mutation() {
    let f = Fixture::new();
    let foreign = Fixture::new();
    let before = f.registry.frontier().unwrap();
    let other_before = foreign.registry.frontier().unwrap();
    assert!(
        RegisteredRootPaired::open(
            f.issuer.clone(),
            foreign.registry.clone(),
            f.writer.clone(),
            f.registration.clone()
        )
        .is_err()
    );
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(foreign.registry.frontier().unwrap(), other_before);
}

#[test]
fn paired_root_missing_policy_or_expired_records_are_not_created_or_renewed() {
    let f = Fixture::new();
    let before = f.registry.frontier().unwrap();
    let mut missing = f.registration.clone();
    missing.request.original.delivery_id = Digest32::of_bytes(b"missing delivery");
    assert!(f.open(missing.clone()).is_err());
    assert!(
        f.registry
            .read_lease(&missing.effect_id())
            .unwrap()
            .is_none()
    );
    let owner = f.open(f.registration.clone()).unwrap();
    f.clock.0.store(15_000, Ordering::SeqCst);
    assert!(owner.observe().is_err());
    assert!(f.open(f.registration.clone()).is_err());
    assert_eq!(f.registry.frontier().unwrap(), before);
    let f = Fixture::new();
    let before = f.registry.frontier().unwrap();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut changed = state.clone();
    changed.policies.clear();
    f.issuer
        .store
        .compare_and_set(STATE_OWNER, &state, &changed)
        .unwrap();
    assert!(f.open(f.registration.clone()).is_err());
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(changed).unwrap()
    );
    assert_eq!(f.registry.frontier().unwrap(), before);
}

#[test]
#[ignore = "explicit isolated Root service qualification on a registered temporary state parent"]
fn paired_actual_root_service_refuses_configured_policy_without_minting() {
    use codex_hepta_contracts::HostAuthorityClock;
    use codex_hepta_contracts::HostAuthorityFrontierStore;
    use codex_hepta_contracts::HostAuthorityPeerPolicy;
    use codex_hepta_contracts::HostIssuerPeer;
    use codex_hepta_contracts::HostIssuerTransportError;
    use codex_hepta_contracts::RootAuthorityDirectory;
    use std::io::Read;
    use std::io::Write;
    use std::net::Shutdown;
    use std::os::fd::FromRawFd;
    use std::os::fd::OwnedFd;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::UnixStream;
    use std::time::Duration;
    // This is a real Root test on explicitly selected temporary state only.
    // It is never counted among the ordinary nine controls when ignored.
    // SAFETY: geteuid reads the actual kernel credential.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap();
    let temporary = tempfile::Builder::new()
        .prefix("paired-root-denial-")
        .tempdir_in(parent)
        .unwrap();
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let directory = RootAuthorityDirectory::open(temporary.path()).unwrap();
    let clock = Arc::new(
        HostAuthorityClock::initialize(directory.clone(), "paired-root-clock".into()).unwrap(),
    );
    let frontier = Arc::new(
        HostAuthorityFrontierStore::initialize(
            directory,
            "paired-root-leases".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
        )
        .unwrap(),
    );
    let leases = temporary.path().join("leases");
    std::fs::create_dir(&leases).unwrap();
    std::fs::set_permissions(&leases, std::fs::Permissions::from_mode(0o700)).unwrap();
    let registry = Arc::new(
        AuthorityLeaseRegistry::open_state_dir_with_trust(
            &leases,
            "paired-root-leases".into(),
            clock.clone(),
            frontier,
        )
        .unwrap(),
    );
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let binding = FinalUseBinding {
        subject_id: agent.as_str().into(),
        destination_id: crate::paired_preparation::DESTINATION.into(),
        scope_sha256: [1; 32],
        request_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let now = clock.now_unix_ms().unwrap();
    registry
        .put_lease(
            AuthorityLease {
                schema_version: 1,
                lease_id: "paired-root-policy".into(),
                revision: 1,
                authority_epoch: 1,
                issued_at_unix_ms: now,
                expires_at_unix_ms: now + 60_000,
                binding: AuthorityLeaseBinding {
                    principal_id: binding.subject_id.clone(),
                    operation_class: "runtime.agentd.production_operation".into(),
                    destination_id: binding.destination_id.clone(),
                    scope_sha256: binding.scope_sha256,
                    payload_sha256: binding.payload_sha256,
                },
            },
            /*expected_revision*/ 0,
        )
        .unwrap();
    let issuer = Arc::new(
        DeploymentFinalUseIssuer::create_protected(
            &temporary.path().join("issuer"),
            "paired-root-policy".into(),
            vec![DeploymentGrantPolicy {
                subject_id: binding.subject_id.clone(),
                destination_id: binding.destination_id.clone(),
                scope_sha256: binding.scope_sha256,
                lifetime_ms: 1_000,
            }],
            clock.clone(),
            registry.verifier(),
            "paired-root-policy".into(),
            1,
        )
        .unwrap(),
    );
    // The original generic issuer lease really admits this exact binding.
    // Checking it does not issue a grant or reserve a nonce/sequence.
    issuer
        .lease
        .as_ref()
        .unwrap()
        .with_binding(&binding, |_, _| Ok(()))
        .unwrap();
    let fleet = temporary.path().join("fleet");
    let workspace = temporary.path().join("workspace");
    std::fs::create_dir(&fleet).unwrap();
    std::fs::create_dir(&workspace).unwrap();
    let identity = crate::HostAuthorityRegisteredIdentity {
        agent_id: agent,
        spawn_generation: 1,
        fleet_root: fleet,
        workspace,
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
    }
    .identity()
    .unwrap();
    let service =
        crate::HostAuthorityService::from_registered_owner(issuer.clone(), clock, identity)
            .unwrap()
            .retain_original_root_registry(registry.clone());
    let original = serde_json::to_value(issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let original_frontier = registry.frontier().unwrap();
    assert!(service.observe_registered_paired().is_err());
    let request = serde_json::to_vec(&serde_json::json!({
        "schema_version":1, "operation":"runtime.agentd.production_operation", "binding":binding,
    }))
    .unwrap();
    // Exercise the existing framed service and actual peer/pidfd checks. The
    // write-half EOF also bounds completion if the refusal regresses: the
    // generic issuer would return a response and then see the original EOF.
    let (server, mut client) = UnixStream::pair().unwrap();
    client
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    client
        .set_write_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    client
        .write_all(&(request.len() as u32).to_be_bytes())
        .unwrap();
    client.write_all(&request).unwrap();
    client.shutdown(Shutdown::Write).unwrap();
    let pid = std::process::id();
    // SAFETY: pidfd_open takes this live process PID, zero flags and no pointers.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(
        raw >= 0,
        "pidfd_open failed: {}",
        io::Error::last_os_error()
    );
    // SAFETY: a successful pidfd_open returns precisely one fresh owned descriptor.
    let owner = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    let result = service.serve(
        crate::HostAuthorityLane::Issuer,
        server,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid: 0, pid },
            timeout: Duration::from_secs(2),
            lifetime: Duration::from_secs(3),
            request_bound: 16 * 1024,
            response_bound: 64 * 1024,
        },
        owner,
    );
    assert_eq!(result, Err(HostIssuerTransportError::InvalidRequest));
    assert_eq!(client.read(&mut [0; 1]).unwrap(), 0);
    assert_eq!(
        serde_json::to_value(issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        original
    );
    assert_eq!(registry.frontier().unwrap(), original_frontier);
}
