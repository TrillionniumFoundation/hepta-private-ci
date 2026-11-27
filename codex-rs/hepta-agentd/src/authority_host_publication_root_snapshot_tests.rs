//! Test DATA observations: business files remain exactly equal. Only the two
//! actual publication control records may take their specified durable steps.

use std::collections::BTreeMap;

use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

use super::*;
use crate::authority_host_service::generation_publication::PublicationProfile;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Envelope<T> {
    schema: u8,
    owner_id: String,
    frontier: T,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Primary {
    profile: PublicationProfile,
    fenced: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum RefusalPhase {
    Armed,
    Ready,
    Refused,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RefusalBinding {
    schema: u8,
    purpose: String,
    publication_purpose: String,
    learning_operation: String,
    initial: String,
    scope: String,
    previous: CellGenerationOwnerBindingV1,
    target: CellGenerationOwnerBindingV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Refusal {
    binding: RefusalBinding,
    attempt: u64,
    phase: RefusalPhase,
    original: Option<PublicationProfile>,
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct Snapshot {
    business: BTreeMap<PathBuf, support::ProtectedFile>,
    primary_file: support::ProtectedFile,
    primary: Envelope<Primary>,
    refusal_file: support::ProtectedFile,
    refusal: Envelope<Refusal>,
}

impl Snapshot {
    pub(super) fn observe(
        path: &Path,
        intent: &types::UpdateIntent,
        physical: &[PathBuf],
    ) -> anyhow::Result<Self> {
        let mut business = support::protected_files(path)?;
        for path in physical {
            anyhow::ensure!(
                business
                    .insert(path.clone(), support::protected_file(path)?)
                    .is_none(),
                "duplicate original physical path"
            );
        }
        let primary_owner = format!(
            "generation-publication/{}",
            Digest32::of_bytes(intent.operation_id.as_bytes())
        );
        let (primary_file, primary): (_, Envelope<Primary>) =
            take_record(&mut business, path, &primary_owner)?;
        let profile = &primary.frontier.profile;
        assert_eq!(profile.intent, *intent);
        assert_eq!(profile.digest()?, profile.binding);
        let refusal_owner = format!(
            "publication-refusal/{}",
            Digest32::of_bytes(profile.learning_operation.as_bytes())
        );
        let (refusal_file, refusal): (_, Envelope<Refusal>) =
            take_record(&mut business, path, &refusal_owner)?;
        assert_eq!(
            refusal.frontier.binding,
            RefusalBinding {
                schema: 1,
                purpose: "runtime.learning.publication-refusal.v1".into(),
                publication_purpose: profile.purpose.clone(),
                learning_operation: profile.learning_operation.clone(),
                initial: profile.initial.clone(),
                scope: profile.scope.clone(),
                previous: intent.previous.clone(),
                target: intent.target.clone(),
            }
        );
        assert_eq!(refusal.frontier.original.as_ref(), Some(profile));
        anyhow::ensure!(
            refusal.frontier.attempt > 0,
            "actual durable attempt required"
        );
        Ok(Self {
            business,
            primary_file,
            primary,
            refusal_file,
            refusal,
        })
    }

    pub(super) fn require_ready(&self) {
        assert_eq!(self.refusal.frontier.phase, RefusalPhase::Ready);
        assert!(!self.primary.frontier.fenced);
    }

    pub(super) fn require_refused(&self) {
        assert_eq!(self.refusal.frontier.phase, RefusalPhase::Refused);
        assert!(self.primary.frontier.fenced);
    }

    pub(super) fn require_transition(&self, before: &Self, phase: Phase) -> anyhow::Result<()> {
        if matches!(phase, Phase::RefusedReopen) {
            before.require_refused();
            self.require_refused();
            assert_eq!(
                self, before,
                "refused reopen changed original protected data"
            );
            return Ok(());
        }
        before.require_ready();
        self.require_progress(before, phase)?;
        let frames_after_barrier = match phase {
            Phase::Publish | Phase::StalePrepare | Phase::Revoked => 1,
            Phase::Recover | Phase::RetiredSession => 0,
            Phase::RefusedReopen => unreachable!("handled above"),
        };
        assert_eq!(
            self.refusal.frontier.attempt,
            before
                .refusal
                .frontier
                .attempt
                .checked_add(frames_after_barrier)
                .ok_or_else(|| anyhow::anyhow!("component attempt exhausted"))?
        );
        Ok(())
    }

    pub(super) fn require_progress(&self, before: &Self, phase: Phase) -> anyhow::Result<()> {
        assert_eq!(
            self.business, before.business,
            "business bytes and custody changed"
        );
        assert_eq!(
            self.primary.frontier.profile,
            before.primary.frontier.profile
        );
        let refused = matches!(phase, Phase::StalePrepare | Phase::Revoked);
        if refused {
            self.require_refused();
        } else {
            self.require_ready();
        }
        let mut expected_primary = before.primary.clone();
        expected_primary.frontier.fenced = refused;
        assert_eq!(self.primary, expected_primary);
        require_same_custody(&self.primary_file, &before.primary_file);
        if !refused {
            assert_eq!(self.primary_file, before.primary_file);
        }
        require_same_custody(&self.refusal_file, &before.refusal_file);
        anyhow::ensure!(
            self.refusal.frontier.attempt >= before.refusal.frontier.attempt,
            "durable refusal attempt regressed"
        );
        let mut expected_refusal = before.refusal.clone();
        expected_refusal.frontier.attempt = self.refusal.frontier.attempt;
        expected_refusal.frontier.phase = if refused {
            RefusalPhase::Refused
        } else {
            RefusalPhase::Ready
        };
        assert_eq!(self.refusal, expected_refusal);
        Ok(())
    }

    pub(super) fn require_later_phase(&self, before: &Self, phase: Phase) -> anyhow::Result<()> {
        self.require_progress(before, phase)?;
        anyhow::ensure!(
            self.refusal.frontier.attempt > before.refusal.frontier.attempt,
            "original Root enrollment and reads did not advance their durable attempt"
        );
        Ok(())
    }
}

fn take_record<T: serde::de::DeserializeOwned + Serialize>(
    files: &mut BTreeMap<PathBuf, support::ProtectedFile>,
    root: &Path,
    owner: &str,
) -> anyhow::Result<(support::ProtectedFile, Envelope<T>)> {
    let path = root.join(format!(
        "frontier-v1-{}.json",
        Digest32::of_bytes(owner.as_bytes())
    ));
    let file = files
        .remove(&path)
        .ok_or_else(|| anyhow::anyhow!("actual record absent: {}", path.display()))?;
    anyhow::ensure!(
        file.owner == 0 && file.links == 1 && file.mode & 0o7777 == 0o600,
        "original Root record custody differs"
    );
    let record: Envelope<T> = serde_json::from_slice(&file.bytes)?;
    assert_eq!((record.schema, record.owner_id.as_str()), (1, owner));
    assert_eq!(serde_json::to_vec(&record)?, file.bytes);
    Ok((file, record))
}

fn require_same_custody(actual: &support::ProtectedFile, before: &support::ProtectedFile) {
    assert_eq!(
        (
            actual.device,
            actual.owner,
            actual.group,
            actual.mode,
            actual.links
        ),
        (
            before.device,
            before.owner,
            before.group,
            before.mode,
            before.links
        )
    );
}
