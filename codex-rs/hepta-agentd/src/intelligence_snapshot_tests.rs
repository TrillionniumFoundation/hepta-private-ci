use super::*;

use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_intelligence::CapabilityBindingV2;
use codex_hepta_intelligence::CapabilityNecessityV2;
use codex_hepta_intelligence::CapabilityRequirementV2;
use codex_hepta_intelligence::CapabilitySnapshotRequestV2;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn snapshot() -> CapabilitySnapshotV2 {
    let pairs = [
        ("objective.validation", "objective.compiler"),
        ("utility.evaluation", "utility.ndu"),
    ];
    let requirements = pairs
        .iter()
        .map(|(capability, owner)| CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: CapabilityNecessityV2::Required,
        })
        .collect::<Vec<_>>();
    let bindings = requirements
        .iter()
        .map(|requirement| CapabilityBindingV2 {
            capability_id: requirement.capability_id.clone(),
            owner_id: requirement.owner_id.clone(),
            contract_digest: requirement.contract_digest,
            implementation_digest: digest(&format!(
                "implementation:{}",
                requirement.capability_id.as_str()
            )),
            generation: generation(4),
        })
        .collect();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 7,
        body_generation: generation(3),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocation-frontier"),
        requirements,
        bindings,
    })
    .expect("snapshot")
}

struct Fixture {
    _temp: tempfile::TempDir,
    identity: AgentdIdentity,
    trust_file: PathBuf,
    snapshot: CapabilitySnapshotV2,
    owners: Vec<(StableId, SigningKey)>,
    now_ms: u64,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("tempdir");
        let home = temp.path().join("home");
        fs::create_dir(&home).expect("home");
        #[cfg(unix)]
        fs::set_permissions(&home, fs::Permissions::from_mode(0o700)).expect("home mode");
        let home = home.canonicalize().expect("canonical home");

        let agent_id = AgentId::parse(AGENT_ID).expect("agent");
        let fleet_root_path = temp.path().join("fleet");
        fs::create_dir(&fleet_root_path).expect("fleet root");
        let fleet_root = HeptaFleetRoot::parse(fleet_root_path.clone()).expect("fleet root type");
        let layout = fleet_root.layout().agent(&agent_id);
        let identity = AgentdIdentity {
            agent_id,
            layout,
            spawn_generation: 5,
            fleet_root: fleet_root_path,
            workspace: temp.path().join("workspace"),
            resources: ResourceBudget::local_default(),
            home_root: home.clone(),
            run_root: temp.path().join("run"),
            control_socket: temp.path().join("control.sock"),
            app_server_socket: temp.path().join("app.sock"),
        };
        let trust_file = home.join("intelligence-capability-trust.json");
        let snapshot = snapshot();
        let owners = vec![
            (id("objective.compiler"), SigningKey::from_bytes(&[21; 32])),
            (id("utility.ndu"), SigningKey::from_bytes(&[22; 32])),
        ];
        let now_ms = 1_800_000_000_000;
        let fixture = Self {
            _temp: temp,
            identity,
            trust_file,
            snapshot,
            owners,
            now_ms,
        };
        fixture.write_trust(
            /*sequence*/ 11,
            /*authority_epoch*/ 7,
            digest("revocation-frontier"),
            /*revoked_owner*/ None,
            /*rotate_first_key*/ false,
        );
        fixture
    }

    fn write_trust(
        &self,
        sequence: u64,
        authority_epoch: u64,
        revocation_frontier: Digest32,
        revoked_owner: Option<&str>,
        rotate_first_key: bool,
    ) {
        let owners = self
            .owners
            .iter()
            .enumerate()
            .map(|(index, (owner, key))| {
                let replacement = SigningKey::from_bytes(&[91; 32]);
                let active_key = if rotate_first_key && index == 0 {
                    &replacement
                } else {
                    key
                };
                json!({
                    "owner_id": owner.as_str(),
                    "issuer_id": format!("issuer.{}", owner.as_str()),
                    "key_epoch": if rotate_first_key && index == 0 { 3 } else { 2 },
                    "public_key_hex": hex(&active_key.verifying_key().to_bytes()),
                    "revoked": revoked_owner == Some(owner.as_str()),
                    "current_sequence": sequence,
                })
            })
            .collect::<Vec<_>>();
        let value = json!({
            "schema_version": 1,
            "agent_id": self.identity.agent_id.as_str(),
            "authority_epoch": authority_epoch,
            "body_generation": 3,
            "configuration_digest": digest("configuration").to_string(),
            "revocation_frontier_digest": revocation_frontier.to_string(),
            "owners": owners,
        });
        fs::write(
            &self.trust_file,
            serde_json::to_vec(&value).expect("encode trust"),
        )
        .expect("write trust");
        #[cfg(unix)]
        fs::set_permissions(&self.trust_file, fs::Permissions::from_mode(0o600))
            .expect("trust mode");
    }

    fn attestations(&self) -> Vec<CapabilityOwnerAttestationV3> {
        self.owners
            .iter()
            .map(|(owner, key)| CapabilityOwnerAttestationV3 {
                owner_id: owner.clone(),
                message: signed_attestation(
                    &self.identity,
                    &self.snapshot,
                    owner,
                    key,
                    /*key_epoch*/ 2,
                    /*sequence*/ 11,
                    self.now_ms + 60_000,
                ),
            })
            .collect()
    }

    fn provider(&self) -> AuthenticatedCapabilitySnapshotProviderV3 {
        AuthenticatedCapabilitySnapshotProviderV3::new(
            self.identity.clone(),
            self.trust_file.clone(),
            self.snapshot.clone(),
            self.attestations(),
        )
        .expect("provider")
    }
}

fn signed_attestation(
    identity: &AgentdIdentity,
    snapshot: &CapabilitySnapshotV2,
    owner: &StableId,
    key: &SigningKey,
    key_epoch: u64,
    sequence: u64,
    expires_at_ms: u64,
) -> SignedMessage {
    let subject = id(identity.agent_id.as_str());
    let claims = codex_hepta_authbus::SignedMessageClaims {
        issuer_id: id(&format!("issuer.{}", owner.as_str())),
        key_epoch: generation(key_epoch),
        message_id: id(&format!("snapshot.{}", owner.as_str())),
        subject_id: subject,
        scope_digest: capability_scope(identity, owner),
        payload_digest: snapshot.digest(),
        sequence,
        expires_at_ms,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    SignedMessage { claims, signature }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[test]
fn authenticated_provider_accepts_exact_current_owner_set() {
    let fixture = Fixture::new();
    let provider = fixture.provider();
    let current = provider
        .verify_at(fixture.now_ms)
        .expect("current authenticated snapshot");
    assert_eq!(current.digest(), fixture.snapshot.digest());
}

#[test]
fn owner_sequence_advancement_rejects_old_attestation_replay() {
    let fixture = Fixture::new();
    let provider = fixture.provider();
    provider
        .verify_at(fixture.now_ms)
        .expect("initial current snapshot");
    fixture.write_trust(
        /*sequence*/ 12,
        /*authority_epoch*/ 7,
        digest("revocation-frontier"),
        None,
        false,
    );
    assert!(provider.verify_at(fixture.now_ms + 1).is_err());
}

#[test]
fn key_rotation_and_revocation_reject_previous_owner_evidence() {
    let fixture = Fixture::new();
    let provider = fixture.provider();
    fixture.write_trust(
        /*sequence*/ 11,
        /*authority_epoch*/ 7,
        digest("revocation-frontier"),
        None,
        /*rotate_first_key*/ true,
    );
    assert!(provider.verify_at(fixture.now_ms).is_err());

    fixture.write_trust(
        /*sequence*/ 11,
        /*authority_epoch*/ 7,
        digest("revocation-frontier"),
        Some("utility.ndu"),
        false,
    );
    assert!(provider.verify_at(fixture.now_ms).is_err());
}

#[test]
fn authority_or_revocation_frontier_drift_rejects_frozen_snapshot() {
    let fixture = Fixture::new();
    let provider = fixture.provider();
    fixture.write_trust(
        /*sequence*/ 11,
        /*authority_epoch*/ 8,
        digest("revocation-frontier"),
        None,
        false,
    );
    assert!(provider.verify_at(fixture.now_ms).is_err());

    fixture.write_trust(
        /*sequence*/ 11,
        /*authority_epoch*/ 7,
        digest("new-revocation-frontier"),
        None,
        false,
    );
    assert!(provider.verify_at(fixture.now_ms).is_err());
}

#[test]
fn wrong_owner_signature_cannot_substitute_for_bound_owner() {
    let fixture = Fixture::new();
    let mut attestations = fixture.attestations();
    let wrong = signed_attestation(
        &fixture.identity,
        &fixture.snapshot,
        &fixture.owners[0].0,
        &fixture.owners[1].1,
        /*key_epoch*/ 2,
        /*sequence*/ 11,
        fixture.now_ms + 60_000,
    );
    attestations[0] = CapabilityOwnerAttestationV3 {
        owner_id: fixture.owners[0].0.clone(),
        message: wrong,
    };
    let provider = AuthenticatedCapabilitySnapshotProviderV3::new(
        fixture.identity.clone(),
        fixture.trust_file.clone(),
        fixture.snapshot.clone(),
        attestations,
    )
    .expect("provider construction is structural only");
    assert!(provider.verify_at(fixture.now_ms).is_err());
}
