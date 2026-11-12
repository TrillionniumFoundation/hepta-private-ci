//! Real protected CURRENT and original Root/UID60001 FinalUse publication.
//! Learning receipts, Q24 matrices and role keys are explicit component fixtures.
//! This is a live service reopen, not an OS cold restart, ordinary A/B/C run,
//! trained-model benefit or independent business consumer acceptance.

use super::*;
use anyhow::Context;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
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
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityLearningBootstrapV1;
use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityPublicBootstrapV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::PreparedHostAuthoritySession;
use crate::RootGenerationJournalInputsV1;
use crate::RootGenerationPublicationEnrollmentV1;
use crate::RootGenerationPublicationModeV1;
use crate::RootPublicationFinalUseConsumerV1;
use crate::learning_retained_task_operation_id_v1;

#[path = "authority_host_generation_publication_root_artifacts_tests.rs"]
mod artifacts;
#[path = "authority_host_generation_publication_root_child_tests.rs"]
mod child;
#[path = "authority_host_generation_publication_root_fixture_tests.rs"]
mod fixture;
#[path = "authority_host_publication_root_snapshot_tests.rs"]
mod snapshot;
#[path = "authority_host_generation_publication_root_support_tests.rs"]
mod support;

const CHILD_TEST: &str = "neuron_generation_current::publication_root_tests::child::original_publication_dedicated_uid_child";
const RECORDS: u64 = 128;
const COMPONENT_OBSERVED: u64 = 20;
const TIMEOUT: Duration = Duration::from_millis(500);
const LIFETIME: Duration = Duration::from_secs(10);

#[derive(Clone, Copy, Debug)]
enum Phase {
    Publish,
    Recover,
    RetiredSession,
    StalePrepare,
    Revoked,
    RefusedReopen,
}

fn now_ms() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn control(socket: &UnixDatagram, expected: &[u8]) -> anyhow::Result<()> {
    socket.set_read_timeout(Some(LIFETIME))?;
    let mut bytes = [0; 256];
    let size = socket.recv(&mut bytes).with_context(|| {
        format!(
            "publication component control awaiting {}",
            String::from_utf8_lossy(expected)
        )
    })?;
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
    let size = socket
        .recv(&mut bytes)
        .context("publication child awaiting original intent data")?;
    anyhow::ensure!(size > 0 && size <= 32768, "bounded component control");
    Ok(serde_json::from_slice(&bytes[..size])?)
}

/// Synthetic stage metadata is replayed through the actual registered Root
/// checkpoint. It is never passed off as signed original A/B role evidence.
fn record_component_decision(
    initial: LearningIterationSnapshotV1,
) -> anyhow::Result<LearningIterationCoordinatorV1> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(initial)?;
    let request = &coordinator.snapshot().request;
    let mut candidate = request.selected_bundle.clone();
    candidate.artifact_id = StableId::new("component-rejected-candidate")?;
    candidate.generation = candidate.generation.next()?;
    candidate.rollback_predecessor = Some(request.selected_bundle.digest()?);
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle: request.selected_bundle.digest()?,
        dataset: digest("component-dataset"),
        update_rule: digest("component-update-rule"),
        evaluation_profile: request.evaluation_profile,
    });
    let observations = [
        LearningIterationObservationV1::Experience {
            episode_digest: digest("component-episode"),
            completed_task_receipt: request.completed_task_receipt,
        },
        LearningIterationObservationV1::Dataset {
            snapshot_digest: digest("component-dataset"),
            episode_digest: digest("component-episode"),
            withdrawal_frontier: digest("component-withdrawals"),
            rows: 1,
            bytes: 64,
        },
        LearningIterationObservationV1::Training {
            candidate: Box::new(candidate.clone()),
            steps: 1,
            milliseconds: 1,
            artifact_bytes: 64,
        },
        LearningIterationObservationV1::Evaluation {
            candidate_bundle: candidate.digest()?,
            evaluation_profile: request.evaluation_profile,
            disposition: LearningEvaluationDispositionV1::NoUpdate,
        },
    ];
    for observation in observations {
        let before = coordinator.snapshot();
        let receipt = LearningIterationReceiptV1 {
            operation_id: before.request.operation_id.clone(),
            predecessor: before.head_digest,
            actor_id: before.owners.owner(observation.stage()).clone(),
            evidence_digest: digest("synthetic-component-role-evidence"),
            observed_unix_seconds: COMPONENT_OBSERVED,
            observation,
        };
        coordinator.record(receipt, COMPONENT_OBSERVED)?;
    }
    Ok(coordinator)
}

#[test]
#[ignore = "actual UID0, two original protected bind domains and dedicated non-Root child"]
fn root_broker_late_enrolls_publishes_and_recovers_original_current() -> anyhow::Result<()> {
    // SAFETY: only observe this test process's actual credentials.
    assert_eq!(unsafe { (libc::getuid(), libc::geteuid()) }, (0, 0));
    // Each real terminal refusal owns an independent protected scope. The
    // successful reopen path precedes it; no rejected slot is reset for another
    // negative case or treated as eligible for a later positive recovery.
    for terminal in [Phase::StalePrepare, Phase::Revoked] {
        let mut fixture =
            fixture::Fixture::new(terminal).context("publication component fixture setup")?;
        let initial_current = fixture.current.original_broker_head()?;
        fixture
            .run_phase(Phase::Publish)
            .context("publication component Publish phase")?;
        let published = fixture.current.original_broker_head()?;
        assert_eq!(published.current, fixture.intent.target);
        assert_eq!(published.prepared, None);
        assert_eq!(
            published.published.as_ref().map(|p| &p.intent),
            Some(&fixture.intent)
        );
        assert_ne!(published, initial_current);
        let mut protected = fixture.protected_snapshot()?;
        protected.require_ready();
        let claims_path = fixture.local.join("device/authority.claims");
        let claimed = std::fs::read(&claims_path)?;
        anyhow::ensure!(!claimed.is_empty(), "real original nonce append required");
        for phase in [Phase::Recover, Phase::RetiredSession, terminal] {
            fixture
                .run_phase(phase)
                .with_context(|| format!("publication component {phase:?} phase"))?;
            assert_eq!(fixture.current.original_broker_head()?, published);
            let after = fixture.protected_snapshot()?;
            after.require_later_phase(&protected, phase)?;
            assert_eq!(std::fs::read(&claims_path)?, claimed);
            protected = after;
        }
        protected.require_refused();
        fixture
            .run_phase(Phase::RefusedReopen)
            .context("publication component refused original Reopen phase")?;
        assert_eq!(fixture.current.original_broker_head()?, published);
        assert_eq!(fixture.protected_snapshot()?, protected);
        assert_eq!(std::fs::read(&claims_path)?, claimed);
        fixture.child.release()?;
        let output = fixture.child.finish()?;
        assert!(
            output.contains(&format!(
                "ROOT_PUBLICATION_ORIGINAL lifecycle=passed terminal={terminal:?}"
            )),
            "{output}"
        );
        println!("{output}");
    }
    Ok(())
}
