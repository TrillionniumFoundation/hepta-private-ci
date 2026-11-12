//! Actual protected Root state and original Material handlers. The held Trainer
//! socket is an explicit same-process zero-frame probe, never a canned result.
//! This tests consumption-time refusal, not an ordinary A/B/C qualification.

use crate::AgentdError;
use crate::OriginalCellEvaluationPanelRegistrationV1 as Panel;
use crate::OriginalCellEvaluationPanelTaskV1 as Task;
use crate::OriginalCellQ24MaterialEvidenceRoleV1 as Role;
use crate::cell_q24_material_receipt_owner::MaterialCommandFixture;
use crate::learning_iteration_evidence_client as stages;
use crate::learning_iteration_evidence_client::original_bootstrap_test_ports;
use crate::learning_iteration_evidence_client::original_material_bootstrap_test_ports as material_ports;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use super::support::ResidentRootFixture;

#[derive(Clone, Copy, Debug)]
enum Pairing {
    FreshRegistrationRecoveredChannels,
    RecoveredRegistrationFreshChannels,
    FreshRegistrationFreshChannels,
    RecoveredRegistrationRecoveredChannels,
}

#[derive(Clone, Copy, Debug)]
enum Branch {
    NoUpdate,
    Candidate,
}

struct ProtectedRecord {
    file: File,
    bytes: Vec<u8>,
}

impl ProtectedRecord {
    fn read(fixture: &ResidentRootFixture) -> anyhow::Result<Self> {
        let name = Digest32::of_bytes(fixture.profile.owner_id().as_bytes());
        let mut file = File::open(
            fixture
                .config
                .state_dir
                .join(format!("frontier-v1-{name}.json")),
        )?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        Ok(Self { file, bytes })
    }

    fn replacements_since(&self, previous: &Self) -> anyhow::Result<u64> {
        let current = self.file.metadata()?;
        let old = previous.file.metadata()?;
        // Holding the old inode prevents recycling. Every successful original
        // CAS replaces this file; the initial record is vacant and no other
        // writer runs during the synchronous consuming factory call.
        Ok(u64::from(
            (current.dev(), current.ino()) != (old.dev(), old.ino()),
        ))
    }
}

fn panel() -> anyhow::Result<Panel> {
    Ok(Panel::new(
        Task {
            plan_id: StableId::new("resident-origin-primary")?,
            task_digest: Digest32::of_bytes(b"resident-origin-primary-task"),
            cohort_rule_digest: Digest32::of_bytes(b"resident-origin-primary-rule"),
        },
        vec![Task {
            plan_id: StableId::new("resident-origin-retention")?,
            task_digest: Digest32::of_bytes(b"resident-origin-retention-task"),
            cohort_rule_digest: Digest32::of_bytes(b"resident-origin-retention-rule"),
        }],
    )?)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_consuming_origins_match_before_cas_issuance_and_dispatch()
-> anyhow::Result<()> {
    let protocol = panel()?;
    let material = Box::pin(
        MaterialCommandFixture::candidate_pages_for_evaluation_profile(
            protocol.evaluation_profile(),
        ),
    )
    .await?;
    for branch in [Branch::NoUpdate, Branch::Candidate] {
        for pairing in [
            Pairing::FreshRegistrationRecoveredChannels,
            Pairing::RecoveredRegistrationFreshChannels,
            Pairing::FreshRegistrationFreshChannels,
            Pairing::RecoveredRegistrationRecoveredChannels,
        ] {
            let mut fixture = ResidentRootFixture::new(
                material.config.initial.clone(),
                material.config.scope.clone(),
                &material.config.verifier,
            )?;
            if matches!(
                pairing,
                Pairing::RecoveredRegistrationFreshChannels
                    | Pairing::RecoveredRegistrationRecoveredChannels
            ) {
                fixture.recover()?;
            }
            let registration = fixture.registration.take().expect("original registration");
            let original = Arc::clone(&registration.owner);
            let issuer_before = original
                .authority
                .issuer
                .fixture_original_issuance_sequence()?;
            let checkpoint_before = ProtectedRecord::read(&fixture)?;
            let prior = original.checkpoint.read()?;
            assert!(prior.snapshot.is_none());
            assert!(!prior.dispatch_pending);
            let material_before = material.bytes()?;
            let (experience, e_peer) = material_ports::commands(&material, Role::Experience)?;
            let (dataset, d_peer) = material_ports::commands(&material, Role::Dataset)?;
            let common = match pairing {
                Pairing::FreshRegistrationRecoveredChannels
                | Pairing::RecoveredRegistrationRecoveredChannels => {
                    stages::recovered_material_only(material.config.clone(), experience, dataset)?
                }
                Pairing::RecoveredRegistrationFreshChannels
                | Pairing::FreshRegistrationFreshChannels => {
                    stages::fresh_material_only(material.config.clone(), experience, dataset)?
                }
            };
            let trainer_frames = Arc::new(AtomicU64::new(0));
            let mut trainer_peer = None;
            let result = match branch {
                Branch::NoUpdate => registration.into_runtime(
                    common,
                    material.config.verifier.clone(),
                    /*capacity*/ 1,
                ),
                Branch::Candidate => {
                    let (candidate, mut peer) = match pairing {
                        Pairing::FreshRegistrationRecoveredChannels
                        | Pairing::RecoveredRegistrationRecoveredChannels => {
                            original_bootstrap_test_ports::recovered_candidate_channel(
                                material.config.clone(),
                                /*expected*/ None,
                                Duration::from_secs(300),
                            )?
                        }
                        Pairing::RecoveredRegistrationFreshChannels
                        | Pairing::FreshRegistrationFreshChannels => {
                            original_bootstrap_test_ports::fresh_candidate_channel(
                                material.config.clone(),
                                Duration::from_secs(300),
                            )?
                        }
                    };
                    let frames = Arc::clone(&trainer_frames);
                    trainer_peer = Some(std::thread::spawn(move || {
                        peer.exchange(|_| {
                            frames.fetch_add(1, Ordering::SeqCst);
                            Err(HostIssuerTransportError::InvalidRequest)
                        })
                    }));
                    let candidate = stages::fixture_from_original_clients(
                        common,
                        protocol.clone(),
                        material.training_baseline(),
                        candidate,
                        Instant::now() + Duration::from_secs(300),
                    )?;
                    registration.into_candidate_runtime(
                        candidate,
                        material.config.verifier.clone(),
                        /*capacity*/ 1,
                    )
                }
            };
            let observed = result.map(|(handle, runtime)| {
                let readonly = handle.readonly;
                drop(handle);
                drop(runtime);
                readonly
            });
            if let Some(peer) = trainer_peer {
                assert!(
                    !peer
                        .join()
                        .map_err(|_| anyhow::anyhow!("original Trainer probe panicked"))??
                );
            }
            let checkpoint_after = ProtectedRecord::read(&fixture)?;
            let after = original.checkpoint.read()?;
            let issued = original
                .authority
                .issuer
                .fixture_original_issuance_sequence()?
                .checked_sub(issuer_before)
                .ok_or_else(|| anyhow::anyhow!("original issuance counter regressed"))?;
            let effects = (
                checkpoint_after.replacements_since(&checkpoint_before)?,
                issued,
                u64::from(after.snapshot.is_some()),
                u64::from(after.dispatch_pending),
                material_ports::finish(e_peer)?,
                material_ports::finish(d_peer)?,
                trainer_frames.load(Ordering::SeqCst),
            );
            assert_eq!(effects, (0, 0, 0, 0, 0, 0, 0), "{branch:?} / {pairing:?}");
            assert_eq!(checkpoint_after.bytes, checkpoint_before.bytes);
            assert_eq!(material.bytes()?, material_before);
            match pairing {
                Pairing::FreshRegistrationRecoveredChannels
                | Pairing::RecoveredRegistrationFreshChannels => {
                    assert!(matches!(observed, Err(AgentdError::Invalid(message))
                        if message == "resident registration and original role origins differ"));
                }
                Pairing::FreshRegistrationFreshChannels => assert!(!observed?),
                Pairing::RecoveredRegistrationRecoveredChannels => assert!(observed?),
            }
        }
    }
    Ok(())
}
