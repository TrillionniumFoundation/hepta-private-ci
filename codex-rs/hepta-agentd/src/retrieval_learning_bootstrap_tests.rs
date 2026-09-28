use std::fs;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger as ledger;
use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

use super::*;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

struct Fixture {
    _temp: tempfile::TempDir,
    identity: AgentdIdentity,
    path: PathBuf,
    descriptor: Value,
    now: u64,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let fleet_path = root.join("fleet");
        let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
        let registry = FleetRegistry::initialize(fleet_root.clone()).unwrap();
        let workspace = root.join("workspace");
        fs::create_dir(&workspace).unwrap();
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let manifest = AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(&workspace, &fleet_root).unwrap(),
            ResourceBudget::local_default(),
        ).unwrap();
        let record = registry.register(manifest).unwrap();
        let identity = AgentdIdentity {
            agent_id,
            layout: record.layout.clone(),
            spawn_generation: 1,
            fleet_root: fleet_path,
            workspace,
            resources: record.manifest.resources,
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: record.layout.app_server_socket().to_path_buf(),
        };
        let mut paths = Vec::new();
        for name in ["ledger", "witness"] {
            let directory = root.join(name);
            fs::create_dir(&directory).unwrap();
            fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
            paths.push(directory.join("state"));
        }
        let create = |path: &Path| OpenOptions::new().create_new(true).read(true).write(true).mode(0o600).open(path).unwrap();
        drop(DurableLedger::create(create(&paths[0]), digest("binding"), 64).unwrap());
        drop(LedgerWitnessStore::create(create(&paths[1]), digest("binding")).unwrap());
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        let root_key = SigningKey::from_bytes(&[99; 32]);
        let signer_key = SigningKey::from_bytes(&[7; 32]);
        let signer = ledger::TrustedLearningSignerV1 {
            principal: ledger::AuthenticatedPrincipalV1 {
                principal_id: id("generator"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: Digest32::of_bytes(&signer_key.verifying_key().to_bytes()),
                scope_digest: digest("scope"),
                authority_epoch: 7,
                authenticated_at: now - 20,
                expires_at: now + 3600,
            },
            controller_id: id("generator-owner"),
            verifying_key: signer_key.verifying_key().to_bytes(),
            roles: vec![ledger::LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        };
        let mut signed = ledger::SignedLearningTrustDistributionV1 {
            distribution: ledger::LearningTrustDistributionV1 {
                distribution_id: id("trust-distribution"),
                generation: 1,
                effective_at: now - 10,
                trust: ledger::LearningEvidenceTrustV1 {
                    scope_digest: digest("scope"), objective_digest: digest("objective"),
                    authority_epoch: 7, signers: vec![signer],
                },
            },
            root_id: id("root"), issued_at: now - 20, expires_at: now + 3600, signature: [0; 64],
        };
        signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
        let descriptor = json!({
            "schema": "hepta.agentd.retrieval-learning-bootstrap.v1",
            "owner_id": identity.agent_id.as_str(), "body_generation": 1,
            "ledger_path": paths[0], "witness_path": paths[1],
            "ledger_binding": digest("binding").to_string(), "maximum_records": 64,
            "minimum_acknowledged_sequence": 0,
            "minimum_acknowledged_chain_digest": Digest32::ZERO.to_string(),
            "trust": {
                "root_id": "root", "root_public_key_hex": hex(&root_key.verifying_key().to_bytes()),
                "scope_digest": digest("scope").to_string(), "objective_digest": digest("objective").to_string(),
                "authority_epoch": 7, "root_valid_from_unix_s": now - 30,
                "root_expires_unix_s": now + 7200, "root_revoked_at_unix_s": null,
                "distribution_id": "trust-distribution", "generation": 1,
                "effective_at_unix_s": now - 10, "issued_at_unix_s": now - 20,
                "expires_at_unix_s": now + 3600, "signature_hex": hex(&signed.signature),
                "signers": [{"principal_id": "generator", "controller_id": "generator-owner",
                    "credential_chain_digest": digest("credential").to_string(),
                    "public_key_hex": hex(&signer_key.verifying_key().to_bytes()),
                    "authenticated_at_unix_s": now - 20, "expires_at_unix_s": now + 3600,
                    "revoked_at_unix_s": null, "roles": ["generator"]}]
            }
        });
        Self { _temp: temp, identity, path: root.join("bootstrap.json"), descriptor, now }
    }

    fn write(&self, descriptor: &Value) -> Digest32 {
        let bytes = serde_json::to_vec(descriptor).unwrap();
        fs::write(&self.path, &bytes).unwrap();
        fs::set_permissions(&self.path, fs::Permissions::from_mode(0o600)).unwrap();
        Digest32::of_bytes(&bytes)
    }
}

#[test]
fn ordinary_bootstrap_reopens_the_real_writer_and_keeps_preparation_idempotent() {
    let fixture = Fixture::new();
    let pin = fixture.write(&fixture.descriptor);
    let sink = load_retrieval_learning_bootstrap_v1(&fixture.path, pin, &fixture.identity).unwrap();
    let candidate = RetrievalCandidateIdentityV1 {
        record_id: id("memory:1"), record_revision: Revision::new(1).unwrap(), record_digest: digest("record"),
    };
    let mut observation = RetrievalAssignmentObservationV1 {
        cue_digest: digest("cue"), policy_digest: digest("policy"),
        source_completeness_digest: digest("complete"), candidate_union_digest: digest("union"),
        recall_packet_digest: digest("packet"), enumerated_candidates: vec![candidate.clone()],
        legal_candidates: vec![candidate.clone()], selected_candidates: vec![candidate],
        omitted_by_policy_limits: 0, completeness: RetrievalAssignmentCompletenessV1::Complete,
        assignment_propensity: ProbabilityQ32::ONE, observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    observation.observation_digest = observation.compute_observation_digest();
    let append = |sink: &CognitiveRetrievalLearningSink| sink.append_preparation(
        &fixture.identity.agent_id, 1, 77, &observation, &observation.selected_candidates,
        Some(digest("exact-context")), None, ProbabilityQ32::ONE,
    ).unwrap();
    let first = append(&sink);
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    drop(sink);
    let sink = load_at(&fixture.path, pin, &fixture.identity, fixture.now).unwrap();
    let replay = append(&sink);
    assert_eq!(replay.event_digest, first.event_digest);
    assert_eq!(replay.disposition, ledger::AppendDisposition::IdempotentReplay);
    drop(sink);
    let witness_path = Path::new(fixture.descriptor["witness_path"].as_str().unwrap());
    let witness = LedgerWitnessStore::recover(files::open(witness_path, &fixture.identity.home_root, 1_000_000, true).unwrap(), digest("binding")).unwrap();
    assert_eq!(witness.frontier().unwrap().anchor.sequence, 1);
}

#[test]
fn bootstrap_rejects_wrong_pin_identity_signature_stale_anchor_and_expired_trust() {
    let fixture = Fixture::new();
    let pin = fixture.write(&fixture.descriptor);
    assert!(load_at(&fixture.path, digest("wrong-pin"), &fixture.identity, fixture.now).is_err());
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now + 3601).is_err());
    let mutations = [
        ("body_generation", json!(2)), ("maximum_records", json!(true)),
        ("allow_unsigned", json!(true)),
    ];
    for (field, value) in mutations {
        let mut descriptor = fixture.descriptor.clone();
        descriptor[field] = value;
        let pin = fixture.write(&descriptor);
        assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    }
    let mut descriptor = fixture.descriptor.clone();
    descriptor["trust"]["signature_hex"] = json!("00".repeat(64));
    let pin = fixture.write(&descriptor);
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    let mut descriptor = fixture.descriptor.clone();
    descriptor["minimum_acknowledged_sequence"] = json!(1);
    descriptor["minimum_acknowledged_chain_digest"] = json!(digest("absent-record").to_string());
    let pin = fixture.write(&descriptor);
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    let pin = fixture.write(&fixture.descriptor);
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_ok());
}

#[test]
fn missing_or_aliased_owner_files_never_become_new_empty_stores() {
    let fixture = Fixture::new();
    let pin = fixture.write(&fixture.descriptor);
    let ledger_path = Path::new(fixture.descriptor["ledger_path"].as_str().unwrap());
    let alias = ledger_path.with_file_name("alias");
    fs::hard_link(ledger_path, &alias).unwrap();
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    fs::remove_file(&alias).unwrap();
    fs::set_permissions(ledger_path, fs::Permissions::from_mode(0o666)).unwrap();
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    fs::set_permissions(ledger_path, fs::Permissions::from_mode(0o600)).unwrap();
    fs::rename(ledger_path, &alias).unwrap();
    std::os::unix::fs::symlink(&alias, ledger_path).unwrap();
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    fs::remove_file(ledger_path).unwrap();
    assert!(load_at(&fixture.path, pin, &fixture.identity, fixture.now).is_err());
    assert!(!ledger_path.exists());
}
