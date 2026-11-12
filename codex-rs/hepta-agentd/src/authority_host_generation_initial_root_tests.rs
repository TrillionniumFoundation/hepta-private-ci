//! Actual UID0 / UID60001 initial CURRENT publication through the separate
//! original purpose. Model, selection and role keys are explicit component
//! fixtures. No learning decision, ordinary task completion, benefit, separate
//! business controller or OS restart is asserted.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityPublicBootstrapV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::PreparedHostAuthoritySession;
use crate::RootGenerationJournalInputsV1;
use crate::RootPublicationFinalUseConsumerV1;

#[path = "authority_host_generation_initial_artifacts_tests.rs"]
mod artifacts;
#[path = "authority_host_generation_initial_child_tests.rs"]
mod child;
#[path = "authority_host_generation_initial_data_tests.rs"]
mod data;
#[path = "authority_host_generation_initial_fd_tests.rs"]
mod descriptors;
#[path = "authority_host_generation_initial_fixture_tests.rs"]
mod fixture;
#[path = "authority_host_generation_initial_material_tests.rs"]
mod material;
#[path = "authority_host_generation_publication_root_support_tests.rs"]
mod support;
use descriptors::receive_target_files;
use descriptors::send_target_files;

const CHILD_TEST: &str =
    "neuron_generation_current::initial_root_tests::child::original_initial_dedicated_uid_child";
const RECORDS: u64 = 128;
const TIMEOUT: Duration = Duration::from_millis(500);
const LIFETIME: Duration = Duration::from_secs(15);

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
enum Phase {
    Publish,
    ReserveExisting,
    Recover,
    RetiredSession,
    Corrupt,
    Restored,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
enum ArtifactAccess {
    OriginalWriter,
    OriginalReadView,
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Plan {
    phase: Phase,
    lose_ack: bool,
    artifact_access: ArtifactAccess,
    model_directory: PathBuf,
    artifacts: artifacts::Transfer,
    target: data::ObserverData,
}

fn now_ms() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}

fn control(socket: &UnixDatagram, expected: &[u8]) -> anyhow::Result<()> {
    socket.set_read_timeout(Some(LIFETIME))?;
    let mut bytes = [0; 256];
    let size = socket.recv(&mut bytes)?;
    assert_eq!(&bytes[..size], expected);
    Ok(())
}

fn send_data(socket: &UnixDatagram, value: &impl serde::Serialize) -> anyhow::Result<()> {
    let bytes = serde_json::to_vec(value)?;
    anyhow::ensure!(
        !bytes.is_empty() && bytes.len() <= 32768,
        "bounded component control"
    );
    assert_eq!(socket.send(&bytes)?, bytes.len());
    Ok(())
}

fn data<T: serde::de::DeserializeOwned>(socket: &UnixDatagram) -> anyhow::Result<T> {
    socket.set_read_timeout(Some(LIFETIME))?;
    let mut bytes = vec![0; 32769];
    let size = socket.recv(&mut bytes)?;
    anyhow::ensure!(size > 0 && size <= 32768, "bounded component control");
    Ok(serde_json::from_slice(&bytes[..size])?)
}

fn observer_config(
    generation: CellGenerationConfigV2,
) -> anyhow::Result<CellGenerationObserverConfigV1> {
    let binding = CellGenerationOwnerBindingV1::new(&generation, RECORDS)?;
    Ok(CellGenerationObserverConfigV1 {
        witness_scope: JournalScope {
            scope_digest: Digest32::from_array(binding.digest()?),
            objective_digest: Digest32::from_array(generation.task_digest),
        },
        witness_generation: Generation::new(generation.initial.generation)?,
        generation,
        journal_records: RECORDS,
        witness_records: 256,
    })
}

fn private_file(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
}

fn owned_mode(path: &Path, uid: u32, gid: u32, mode: u32) -> anyhow::Result<()> {
    let name = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
    // SAFETY: only this test's newly created path, never a deployment directory.
    anyhow::ensure!(
        unsafe { libc::chown(name.as_ptr(), uid, gid) } == 0,
        "{}",
        io::Error::last_os_error()
    );
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    Ok(())
}

#[test]
fn initial_feature_preflight_rejects_inexecutable_target_before_current() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (model, bundle, definition) = material::model(root.path())?;
    let source = material::source("component-agent")?;
    let config =
        material::configuration(&model, &bundle, &definition, &source, /*generation*/ 1)?;
    crate::circuit_feature_initial_root::require_feature(
        &config,
        &bundle,
        &model,
        &definition,
        &source,
    )?;
    let check = |definition: &CellDefinitionV1, source: &crate::CircuitTaskSourceInputV1| {
        let config =
            material::configuration(&model, &bundle, definition, source, /*generation*/ 1)?;
        // The complete task and manifest hashes are recomputed. Rejection
        // comes from the actual worker/encoder, not a stale outer digest.
        Ok::<bool, anyhow::Error>(
            crate::circuit_feature_initial_root::require_feature(
                &config, &bundle, &model, definition, source,
            )
            .is_err(),
        )
    };
    let mut weights = definition.clone();
    weights.runtime.weights_digest = Digest32::of_bytes(b"different-actual-weights");
    assert!(check(&weights, &source)?);
    let mut runtime = definition.clone();
    runtime.runtime.runtime_digest = Digest32::of_bytes(b"unsupported-runtime");
    assert!(check(&runtime, &source)?);
    let mut width = source.clone();
    width.observation = b"HQ24I001".to_vec();
    width.observation.extend_from_slice(&3_u16.to_le_bytes());
    for value in [1_i64 << 24, 0, 0] {
        width.observation.extend_from_slice(&value.to_le_bytes());
    }
    assert!(check(&definition, &width)?);
    let mut device = config;
    device.manifest.device_digest = [99; 32];
    device.initial.manifest_digest = device.manifest.digest()?;
    assert!(
        crate::circuit_feature_initial_root::require_feature(
            &device,
            &bundle,
            &model,
            &definition,
            &source,
        )
        .is_err()
    );
    Ok(())
}

#[test]
#[ignore = "actual UID0, original protected bind domains and dedicated non-Root child"]
fn root_initial_publication_uses_original_consumer_and_readonly_recovery() -> anyhow::Result<()> {
    exercise_original_initial_artifacts(ArtifactAccess::OriginalWriter)
}

#[test]
#[ignore = "actual UID0, original protected bind domains and dedicated non-Root child"]
fn root_initial_readview_keeps_original_writer_locked_and_binds_live_session() -> anyhow::Result<()>
{
    exercise_original_initial_artifacts(ArtifactAccess::OriginalReadView)
}

fn exercise_original_initial_artifacts(artifact_access: ArtifactAccess) -> anyhow::Result<()> {
    // SAFETY: only observes the parent process's actual kernel credentials.
    assert_eq!(unsafe { (libc::getuid(), libc::geteuid()) }, (0, 0));
    for lose_ack in [false, true] {
        let mut fixture = fixture::Fixture::new(lose_ack, artifact_access)?;
        // CURRENT does not exist until the child passes complete Feature and
        // original Artifact/target validation and requests this purpose.
        assert!(fixture.head().is_err());
        fixture.run_phase(Phase::Publish)?;
        let published = fixture.head()?;
        assert_eq!(published.current, fixture.deployment.target);
        assert_eq!(published.prepared, None);
        assert_eq!(published.published, None);
        assert!(matches!(
            published.initial,
            Some(InitialState::Published(_))
        ));
        let protected = support::protected_files(&fixture.current_path)?;
        let claims_path = fixture.local.join("device/authority.claims");
        let claims = std::fs::read(&claims_path)?;
        assert!(!claims.is_empty());
        let original_target = std::fs::read(&fixture.target_journal)?;
        assert!(!original_target.is_empty());
        for phase in [
            Phase::ReserveExisting,
            Phase::Recover,
            Phase::RetiredSession,
        ] {
            fixture.run_phase(phase)?;
            assert_eq!(fixture.head()?, published);
            assert_eq!(support::protected_files(&fixture.current_path)?, protected);
            assert_eq!(std::fs::read(&claims_path)?, claims);
            assert_eq!(std::fs::read(&fixture.target_journal)?, original_target);
        }

        // All original workers and owners have stopped and joined. Corrupt
        // only this fixture's actual journal, keeping its inode and witness.
        let file = OpenOptions::new()
            .write(true)
            .open(&fixture.target_journal)?;
        file.set_len(0)?;
        file.sync_all()?;
        drop(file);
        fixture.run_phase(Phase::Corrupt)?;
        assert_eq!(fixture.head()?, published);
        assert_eq!(std::fs::read(&claims_path)?, claims);
        let mut file = OpenOptions::new()
            .write(true)
            .open(&fixture.target_journal)?;
        file.write_all(&original_target)?;
        file.sync_all()?;
        drop(file);
        // Restoring raw bytes cannot clear the original Root's durable fence.
        fixture.run_phase(Phase::Restored)?;
        assert_eq!(fixture.head()?, published);
        assert_eq!(std::fs::read(&claims_path)?, claims);
        fixture.child.release()?;
        let output = fixture.child.finish()?;
        assert!(
            output.contains("ROOT_INITIAL_ORIGINAL lifecycle=passed"),
            "{output}"
        );
        println!("{output}");
    }
    Ok(())
}
