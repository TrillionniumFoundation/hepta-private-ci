//! Actual Artifact and independent Selection precede the Root CURRENT route.
//! These phases own no placeholder CURRENT and cannot prepare or publish one.

use std::time::Duration;

use super::*;

#[path = "cell_q24_publication_successor.rs"]
mod successor;
pub(crate) use successor::OriginalSuccessorPublication;
#[path = "cell_q24_publication_successor_current.rs"]
mod successor_current;
pub(crate) use successor_current::require_successor_admission;

/// A qualified adoption with actual original owners. Completed RetainParent,
/// DeferCandidate and NoUpdate use the separate read-only Artifact phase.
pub struct OriginalCellQ24ArtifactPublicationDriverV1 {
    original: OriginalDecision,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
}

/// The original acknowledged immutable Artifact, still without CURRENT.
pub struct OriginalCellQ24PublishedArtifactForRootV1 {
    original: OriginalDecision,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    publication: ArtifactPublicationReceiptV1,
}

/// The actual independently signed selection was checked and loaded by the
/// original Artifact owner. Root independently reads its own registered files.
pub struct OriginalCellQ24SelectedArtifactForRootV1 {
    original: OriginalDecision,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    selected: AgentdSelectedGenerationV1,
}

/// Same original owners plus one live purpose-bound CURRENT client.
pub struct OriginalCellQ24RootPublicationDriverV1 {
    driver: OriginalCellQ24PublicationDriverV1,
    selected: AgentdSelectedGenerationV1,
}

impl OriginalCellQ24ArtifactPublicationDriverV1 {
    pub async fn for_qualified_adoption(
        owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
        snapshot: LearningIterationSnapshotV1,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
    ) -> Result<Self, Error> {
        let decision = Decision::new(snapshot)?;
        decision.require_root_publication()?;
        if !decision.adopts() {
            return Err(Error::Binding(
                "retained result does not enroll Root candidate publication",
            ));
        }
        owners.validate_recovery(&decision.snapshot).await?;
        let manifest = owners
            .original_publication_manifest(&decision.snapshot)
            .await?;
        let original: OriginalDecision = OriginalDecision {
            owners,
            decision,
            manifest: Some(manifest),
        };
        original.require_current().await?;
        Ok(Self {
            original,
            authorities,
        })
    }

    pub fn artifact_operation_id(&self) -> &StableId {
        &self.original.decision.artifact_operation
    }

    pub fn candidate_manifest(&self) -> Option<&CellBackendManifestV2> {
        self.original.manifest.as_ref()
    }

    /// Use the real exclusive Artifact transaction. An uncertain result consumes
    /// this phase; there is no retry loop or replacement operation/signature.
    pub async fn publish_candidate(
        self,
        mut request: LearningArtifactPublishRequestV1,
    ) -> Result<OriginalCellQ24PublishedArtifactForRootV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        original.decision.require_new_work()?;
        validation::artifact_request(
            &original.decision,
            original
                .manifest
                .as_ref()
                .ok_or(Error::Binding("original B manifest missing"))?,
            &request,
        )?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                self.original.decision.require_new_work()?;
                request.now = self.authorities.now()?;
                let receipt = {
                    let mut locked = self
                        .authorities
                        .artifacts
                        .lock()
                        .map_err(|_| Error::CommitUncertain)?;
                    let artifacts: &mut LearningArtifactOwnerService = &mut locked;
                    artifacts.publish(request)?
                };
                Ok(OriginalCellQ24PublishedArtifactForRootV1 {
                    original: self.original,
                    authorities: self.authorities,
                    publication: receipt,
                })
            })
            .await
    }

    /// Read the actual already acknowledged operation after lost delivery.
    /// Missing/partial state is an error, never another call to publish.
    pub async fn recover_published(
        self,
    ) -> Result<OriginalCellQ24PublishedArtifactForRootV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                let receipt = {
                    let locked = self
                        .authorities
                        .artifacts
                        .lock()
                        .map_err(|_| Error::CommitUncertain)?;
                    let artifacts: &LearningArtifactOwnerService = &locked;
                    artifacts
                        .read_original_publication(&self.original.decision.artifact_operation)?
                };
                Ok(OriginalCellQ24PublishedArtifactForRootV1 {
                    original: self.original,
                    authorities: self.authorities,
                    publication: receipt,
                })
            })
            .await
    }
}

use codex_hepta_learning_artifacts::LearningArtifactOwnerService;

impl OriginalCellQ24PublishedArtifactForRootV1 {
    pub fn publication(&self) -> &ArtifactPublicationReceiptV1 {
        &self.publication
    }

    /// Accept the existing separately authorized Artifact Selector's signature.
    /// This method does not obtain a key or mint a selection.
    pub async fn accept_selection(
        self,
        input: OriginalCellQ24SelectionInputsV1,
    ) -> Result<OriginalCellQ24SelectedArtifactForRootV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                let selected = self.original.load_selected(
                    &self.authorities,
                    input,
                    Some(&self.publication),
                )?;
                if self.original.manifest.as_ref() != Some(selected.manifest()) {
                    return Err(Error::Binding(
                        "actual independent selection differs from B",
                    ));
                }
                Ok(OriginalCellQ24SelectedArtifactForRootV1 {
                    original: self.original,
                    authorities: self.authorities,
                    selected,
                })
            })
            .await
    }
}

impl OriginalCellQ24SelectedArtifactForRootV1 {
    pub fn selected_manifest(&self) -> &CellBackendManifestV2 {
        self.selected.manifest()
    }

    pub fn selection_observation(&self) -> &crate::AgentdGenerationSelectionObservationV1 {
        self.selected.observation()
    }

    /// Call after the same trusted Root has acknowledged late enrollment from
    /// actual files/trust/selection. Neither pins nor this value enroll Root.
    pub async fn connect_current(
        self,
        handoff: crate::RootGenerationPublicationHandoffV1,
        connection: crate::RootGenerationPublicationConnectionV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<OriginalCellQ24RootPublicationDriverV1, Error> {
        OriginalDecision::require_current(&self.original).await?;
        let handoff: crate::RootGenerationPublicationHandoffV1 = handoff;
        let current: Arc<NeuronGenerationCurrentOwnerV1> =
            handoff.connect(connection, timeout, lifetime).await?;
        current.require_original_root_selection(
            &self.original.decision.snapshot,
            &self.original.decision.operation,
            self.selected.observation().digest(),
        )?;
        OriginalDecision::require_current(&self.original).await?;
        Ok(OriginalCellQ24RootPublicationDriverV1 {
            driver: OriginalCellQ24PublicationDriverV1 {
                original: self.original,
                current,
                authorities: self.authorities,
            },
            selected: self.selected,
        })
    }
}

impl OriginalCellQ24RootPublicationDriverV1 {
    pub async fn prepare_feature(
        self,
        predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        target: OriginalCellQ24FeatureTargetV1,
    ) -> Result<OriginalCellQ24PreparedPublicationV1, Error> {
        let original: &OriginalDecision = &self.driver.original;
        original.require_current().await?;
        original.decision.require_new_work()?;
        validation::feature_target(
            &original.decision,
            &target.target,
            &target.definition,
            &target.source,
            &target.model,
        )?;
        validation::predecessor(
            &original.decision,
            &predecessor,
            &target.previous,
            &target.source,
        )?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                self.driver.original.decision.require_new_work()?;
                let mut selected = self.selected;
                revalidate(&self.driver, &mut selected)?;
                current::prepare_selected(self.driver, selected, predecessor, target)
            })
            .await
    }

    pub async fn recover_feature(
        self,
        recovery: OriginalCellQ24FeatureRecoveryV1,
    ) -> Result<PublishedCircuitFeatureTaskV1, Error> {
        let original: &OriginalDecision = &self.driver.original;
        original.require_current().await?;
        validation::feature_target(
            &original.decision,
            &recovery.target,
            &recovery.definition,
            &recovery.source,
            &recovery.model,
        )?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                let mut selected = self.selected;
                revalidate(&self.driver, &mut selected)?;
                current::recover_selected(self.driver, selected, recovery)
            })
            .await
    }
}

fn revalidate(
    driver: &OriginalCellQ24PublicationDriverV1,
    selected: &mut AgentdSelectedGenerationV1,
) -> Result<(), Error> {
    let locked = driver
        .authorities
        .artifacts
        .lock()
        .map_err(|_| Error::CommitUncertain)?;
    let artifacts: &LearningArtifactOwnerService = &locked;
    selected.revalidate(artifacts, driver.authorities.now()?)?;
    if let Some(manifest) = &driver.original.manifest
        && manifest != selected.manifest()
    {
        return Err(Error::Binding("original selected B manifest changed"));
    }
    Ok(())
}

/// An original completed NoUpdate, RetainParent or DeferCandidate result.
/// It retains that exact protocol identity, has no Artifact publish method,
/// creates no new model and is not an evaluator-failure fallback.
pub struct OriginalCellQ24RetainedArtifactForRootV1 {
    original: OriginalDecision,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
}

impl OriginalCellQ24RetainedArtifactForRootV1 {
    pub async fn from_original_result(
        owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
        snapshot: LearningIterationSnapshotV1,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
    ) -> Result<Self, Error> {
        let decision = Decision::new(snapshot)?;
        decision.require_root_publication()?;
        if decision.adopts() {
            return Err(Error::Binding(
                "adopted model requires the actual Artifact publication phase",
            ));
        }
        owners.validate_recovery(&decision.snapshot).await?;
        let original: OriginalDecision = OriginalDecision {
            owners,
            decision,
            manifest: None,
        };
        original.require_current().await?;
        Ok(Self {
            original,
            authorities,
        })
    }

    pub fn retained_bundle(&self) -> &codex_hepta_learning_artifacts::CellCompatibilityBundleV1 {
        &self.original.decision.bundle
    }

    pub async fn accept_selection(
        self,
        input: OriginalCellQ24SelectionInputsV1,
    ) -> Result<OriginalCellQ24SelectedArtifactForRootV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        original.decision.require_root_publication()?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        owners
            .with_original_publication(snapshot, /*manifest*/ None, move || {
                let selected = self.original.load_selected(
                    &self.authorities,
                    input,
                    /*publication*/ None,
                )?;
                Ok(OriginalCellQ24SelectedArtifactForRootV1 {
                    original: self.original,
                    authorities: self.authorities,
                    selected,
                })
            })
            .await
    }
}

#[path = "cell_q24_publication_same_actor.rs"]
mod same_actor_phase;
