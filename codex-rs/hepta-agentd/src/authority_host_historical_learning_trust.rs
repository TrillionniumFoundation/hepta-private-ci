//! Current recipient trust held by the actual Root, separate from old A data.
//! Both metadata and already signed public payload are original Root0600 files.

use std::io;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::super::generation_publication::deployment::files::MetadataFile;
use crate::HostAuthorityService;
use crate::authority_host_service::generation_initial::original_root;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPayloadV1;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPinV1;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;
use crate::root_initial_learning_trust_data::LearningTrustRoleSelectionV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema: u8,
    purpose: String,
    mode: String,
    initial: String,
    target: CellGenerationOwnerBindingV1,
    learning_scope: String,
    signed_payload: PathBuf,
    freeze_evaluator: LearningTrustRoleSelectionV1,
}

pub(super) struct RootHistoricalLearningTrustV1 {
    metadata: MetadataFile,
    signed_file: MetadataFile,
    expected: Deployment,
    payload: HistoricalLearningTrustPayloadV1,
    initial: LearningIterationSnapshotV1,
    pub(super) pin: HistoricalLearningTrustPinV1,
}

impl RootHistoricalLearningTrustV1 {
    pub(super) fn open_original(
        service: &HostAuthorityService,
        path: &Path,
        initial: &LearningIterationSnapshotV1,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Self> {
        original_root()?;
        let (metadata, bytes) = MetadataFile::open_metadata(path)?;
        let expected: Deployment = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if expected.schema != 1
            || expected.purpose != "runtime.learning.historical-trust-deployment.v1"
            || expected.mode != "pinned_genesis_v1"
            || &expected.target != target
            || expected.initial != initial.head_digest.to_string()
            || expected.signed_payload == path
        {
            return Err(io::Error::other(
                "fixed original recipient trust deployment required",
            ));
        }
        let (signed_file, bytes) = MetadataFile::open_metadata(&expected.signed_payload)?;
        let signed: LearningTrustPayloadV1 =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        let payload = HistoricalLearningTrustPayloadV1 {
            signed,
            freeze_evaluator: expected.freeze_evaluator.clone(),
        };
        if serde_json::to_vec(&payload)
            .map_err(io::Error::other)?
            .len()
            > 12 * 1024
        {
            return Err(io::Error::other(
                "current recipient trust exceeds original lane bound",
            ));
        }
        let now = HostAuthorityService::original_learning_unix_seconds(service)?;
        let (activated, _) = payload.activate_for_recipient(initial, now)?;
        let pin = HistoricalLearningTrustPinV1 {
            initial: initial.head_digest.to_string(),
            target: Digest32::from_array(target.digest().map_err(io::Error::other)?).to_string(),
            mapping: metadata.digest().to_string(),
            payload: signed_file.digest().to_string(),
            root: activated.root_digest().to_string(),
            distribution: activated.distribution_digest().to_string(),
            trust: activated.verifier().trust_digest().to_string(),
            learning_scope: activated.verifier().scope_digest().to_string(),
            objective: activated.verifier().objective_digest().to_string(),
            freeze_evaluator: payload.freeze_evaluator_digest()?.to_string(),
        };
        if pin.learning_scope != expected.learning_scope {
            return Err(io::Error::other("current recipient Ledger scope differs"));
        }
        payload.require_activation_pin(initial, &activated, &pin)?;
        let held = Self {
            metadata,
            signed_file,
            expected,
            payload,
            initial: initial.clone(),
            pin,
        };
        held.revalidate(service, initial)?;
        Ok(held)
    }

    pub(super) fn revalidate(
        &self,
        service: &HostAuthorityService,
        initial: &LearningIterationSnapshotV1,
    ) -> io::Result<()> {
        original_root()?;
        self.metadata.require_metadata_unchanged()?;
        self.signed_file.require_metadata_unchanged()?;
        if initial != &self.initial
            || self.pin.mapping != self.metadata.digest().to_string()
            || self.pin.payload != self.signed_file.digest().to_string()
        {
            return Err(io::Error::other("original recipient trust custody changed"));
        }
        let now = HostAuthorityService::original_learning_unix_seconds(service)?;
        let (activated, _) = self.payload.activate_for_recipient(initial, now)?;
        self.payload
            .require_activation_pin(initial, &activated, &self.pin)?;
        self.metadata.require_metadata_unchanged()?;
        self.signed_file.require_metadata_unchanged()
    }

    pub(super) fn require_original_ledger(
        &self,
        ledger: &RootHistoricalLedgerReadDataV1,
    ) -> io::Result<()> {
        ledger.validate_data()?;
        if ledger.target != self.expected.target
            || ledger.trust.learning_scope != self.pin.learning_scope
            || ledger.trust.objective != self.pin.objective
        {
            return Err(io::Error::other(
                "current trust is not mapped to actual original task",
            ));
        }
        Ok(())
    }

    pub(super) fn read_original_payload(
        &self,
        service: &HostAuthorityService,
        initial: &LearningIterationSnapshotV1,
        ledger: &RootHistoricalLedgerReadDataV1,
    ) -> io::Result<HistoricalLearningTrustPayloadV1> {
        self.revalidate(service, initial)?;
        self.require_original_ledger(ledger)?;
        let payload = self.payload.clone();
        self.revalidate(service, initial)?;
        Ok(payload)
    }
}
