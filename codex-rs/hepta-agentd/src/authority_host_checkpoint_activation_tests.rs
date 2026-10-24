//! Real original Root preparation/signing, actual child death and disk refusal.
//! These host tests do not claim a real second kernel boot.

use super::*;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;

fn candidate(f: &Fixture, id: &str) -> HostAuthorityWriterRegistration {
    let mut candidate = f.replacement.clone();
    candidate.authority_lease.lease_id = id.into();
    candidate.authority_lease.issued_at_unix_ms = f.clock.now_unix_ms().unwrap();
    candidate.authority_lease.expires_at_unix_ms =
        candidate.authority_lease.issued_at_unix_ms + 90_000;
    crate::HostCognitiveCheckpoint::prepare_activation_for_root(
        f.directory.clone(),
        &f.clock,
        &f.previous,
        &f.old.retired(),
        &f.successor.retained,
        &f.material,
        candidate,
    )
    .unwrap()
}

fn observation_id(candidate: &HostAuthorityWriterRegistration) -> String {
    format!(
        "checkpoint-activation-v1.{}",
        codex_hepta_contracts::Sha256Digest::for_bytes(&serde_json::to_vec(candidate).unwrap(),)
            .as_str()
    )
}
fn record_path(f: &Fixture, candidate: &HostAuthorityWriterRegistration) -> PathBuf {
    let digest = Sha256::digest(observation_id(candidate).as_bytes());
    f._temp
        .path()
        .join("checkpoint")
        .join(format!("observation-v1-{digest:x}.json"))
}
fn sign(
    f: &mut Fixture,
    candidate: &HostAuthorityWriterRegistration,
) -> HostSignedWriterAuthorizationV1 {
    f.retire_failed_authority();
    f.registry
        .put_lease(candidate.authority_lease.clone(), 0)
        .unwrap();
    f.issuer
        .replace_unactivated_writer_authorization(
            &f.failed_writer,
            &f.failed_proof,
            candidate,
            f.directory.clone(),
            &f.previous,
            &f.old.retired(),
            &f.failed.retired(),
            &f.successor.retained,
            &f.material,
        )
        .unwrap()
}
fn observe(f: &Fixture) -> Result<crate::RetiredCheckpointPublisher, AuthorityTrustError> {
    crate::HostCognitiveCheckpoint::observe_unactivated_publisher_for_root(
        f.directory.clone(),
        &f.issuer,
        &f.clock,
        &f.previous,
        &f.material,
    )
}
fn replace_bytes(path: &std::path::Path, bytes: &[u8]) {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(path)
        .unwrap();
    file.write_all(bytes).unwrap();
    file.sync_all().unwrap();
    std::fs::File::open(path.parent().unwrap())
        .unwrap()
        .sync_all()
        .unwrap();
}

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_activation_witness_durably_precedes_signature_and_reopens_actual_dead_peer() {
    let mut f = Fixture::new().await;
    let canonical = f.issuer.retained_writer_state_for_root().unwrap();
    let candidate = candidate(&f, "activation-witness-candidate");
    let saved = f
        .directory
        .open_observation(&observation_id(&candidate))
        .unwrap();
    saved.verify_durable().unwrap();
    let metadata = std::fs::metadata(record_path(&f, &candidate)).unwrap();
    assert_eq!(
        (metadata.uid(), metadata.mode() & 0o7777, metadata.nlink()),
        (0, 0o600, 1)
    );
    assert!(metadata.len() <= 16 * 1024);
    assert!(
        f.registry
            .read_lease(&candidate.authority_lease.lease_id)
            .unwrap()
            .is_none()
    );
    assert_eq!(
        f.issuer.retained_writer_state_for_root().unwrap(),
        canonical
    );
    assert!(
        observe(&f).is_err(),
        "unsigned saved candidate is not canonical retirement evidence"
    );
    let proof = sign(&mut f, &candidate);
    assert_eq!(proof.claims.authority_lease, candidate.authority_lease);
    assert!(
        observe(&f).is_err(),
        "a live actual publisher has not retired"
    );
    drop(saved);
    // Actual SIGKILL/wait occurs after the real canonical signature returned.
    // Reopening uses only the canonical candidate to locate the durable record.
    f.successor.stop();
    let retired = observe(&f).unwrap();
    assert_eq!(f.actual_head(), f.previous.head);
    let next_peer = Publisher::spawn();
    let mut next = candidate.clone();
    next.spawn_generation += 2;
    next.owner_epoch += 1;
    next.authority_lease.lease_id = "activation-witness-next".into();
    next.authority_lease.issued_at_unix_ms = f.clock.now_unix_ms().unwrap();
    next.authority_lease.expires_at_unix_ms = next.authority_lease.issued_at_unix_ms + 90_000;
    let next = crate::HostCognitiveCheckpoint::prepare_activation_for_root(
        f.directory.clone(),
        &f.clock,
        &f.previous,
        &f.old.retired(),
        &next_peer.retained,
        &f.material,
        next,
    )
    .unwrap();
    f.registry
        .revoke(&candidate.authority_lease.lease_id, 1, [29; 32])
        .unwrap();
    f.registry
        .put_lease(next.authority_lease.clone(), 0)
        .unwrap();
    let replacement = f
        .issuer
        .replace_unactivated_writer_authorization(
            &candidate,
            &proof,
            &next,
            f.directory.clone(),
            &f.previous,
            &f.old.retired(),
            &retired,
            &next_peer.retained,
            &f.material,
        )
        .unwrap();
    assert_eq!(
        replacement.claims.local_lease_generation,
        candidate.local_lease_generation
    );
    assert_eq!(replacement.claims.sequence, proof.claims.sequence + 1);
    assert_eq!(f.actual_head(), f.previous.head);
}

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_activation_witness_rejects_missing_corrupt_boot_peer_token_and_candidate() {
    let mut f = Fixture::new().await;
    let candidate = candidate(&f, "activation-witness-corruption");
    let proof = sign(&mut f, &candidate);
    f.successor.stop();
    let path = record_path(&f, &candidate);
    let original = std::fs::read(&path).unwrap();
    let moved = path.with_extension("withheld");
    std::fs::rename(&path, &moved).unwrap();
    assert!(
        observe(&f).is_err(),
        "a missing witness cannot be rebuilt from a PID"
    );
    std::fs::rename(&moved, &path).unwrap();
    replace_bytes(&path, b"{");
    assert!(observe(&f).is_err());
    replace_bytes(&path, &original);
    let outer: serde_json::Value = serde_json::from_slice(&original).unwrap();
    let payload: Vec<u8> = serde_json::from_value(outer["payload"].clone()).unwrap();
    let original_payload: serde_json::Value = serde_json::from_slice(&payload).unwrap();
    for field in [
        "root_boot",
        "peer_boot",
        "both_boots",
        "root_start",
        "peer_pid",
        "peer_start",
        "token",
        "candidate",
        "material",
    ] {
        let mut changed = original_payload.clone();
        match field {
            "root_boot" => {
                changed["root"]["boot_id"] = "00000000-0000-4000-8000-000000000099".into()
            }
            "peer_boot" => {
                changed["peer"]["boot_id"] = "00000000-0000-4000-8000-000000000099".into()
            }
            "both_boots" => {
                changed["root"]["boot_id"] = "00000000-0000-4000-8000-000000000099".into();
                changed["peer"]["boot_id"] = "00000000-0000-4000-8000-000000000099".into();
            }
            "root_start" => {
                changed["root"]["process_start_ticks"] =
                    (changed["root"]["process_start_ticks"].as_u64().unwrap() + 1).into()
            }
            "peer_pid" => {
                changed["peer"]["pid"] = (changed["peer"]["pid"].as_u64().unwrap() + 1).into()
            }
            "peer_start" => {
                changed["peer"]["process_start_ticks"] =
                    (changed["peer"]["process_start_ticks"].as_u64().unwrap() + 1).into()
            }
            "token" => {
                changed["previous_token"]["counter"] =
                    (changed["previous_token"]["counter"].as_u64().unwrap() + 1).into()
            }
            "candidate" => {
                changed["candidate"]["owner_epoch"] =
                    (changed["candidate"]["owner_epoch"].as_u64().unwrap() + 1).into()
            }
            "material" => changed["material_cut_sha256"] = "11".repeat(32).into(),
            _ => unreachable!(),
        }
        let mut altered = outer.clone();
        altered["payload"] = serde_json::to_value(serde_json::to_vec(&changed).unwrap()).unwrap();
        replace_bytes(&path, &serde_json::to_vec(&altered).unwrap());
        assert!(
            observe(&f).is_err(),
            "changed original activation field was accepted: {field}"
        );
        replace_bytes(&path, &original);
    }
    let mut wrong = f.previous.clone();
    wrong.token.counter += 1;
    assert!(
        crate::HostCognitiveCheckpoint::observe_unactivated_publisher_for_root(
            f.directory.clone(),
            &f.issuer,
            &f.clock,
            &wrong,
            &f.material,
        )
        .is_err()
    );
    assert!(observe(&f).is_ok());
    assert_eq!(f.actual_head(), f.previous.head);
    assert_eq!(
        f.issuer.retained_writer_authorization(&candidate).unwrap(),
        proof
    );
}

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_activation_witness_cannot_reinterpret_an_actually_installed_generation() {
    let mut f = Fixture::new().await;
    let candidate = candidate(&f, "activation-witness-installed");
    let proof = sign(&mut f, &candidate);
    let registration = checkpoint_registration(
        &f.issuer,
        &f.registry,
        &candidate,
        &proof,
        f.previous.head.publisher_epoch + 1,
        &f.successor,
    );
    let adopted = crate::HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
        f.directory.clone(),
        &f.previous,
        &f.old.retired(),
        registration.clone(),
        &f.successor.retained,
        f.clock.clone(),
        &f.material,
    )
    .unwrap();
    let installed = current(&adopted, registration.publisher_epoch);
    f.successor.stop();
    assert!(
        observe(&f).is_err(),
        "a real installed head cannot be reclassified as an unused proof"
    );
    assert_eq!(f.actual_head(), installed.head);
    let actual = crate::HostCognitiveCheckpoint::read_retired_head_for_root(
        f.directory.clone(),
        &registration,
        &f.successor.retired(),
        &f.material,
    )
    .unwrap();
    assert_eq!(actual, installed);
    assert_eq!(
        f.issuer.retained_writer_authorization(&candidate).unwrap(),
        proof
    );
}
