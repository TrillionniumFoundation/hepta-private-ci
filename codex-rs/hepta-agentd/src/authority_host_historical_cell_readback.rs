//! Read only an independently captured Cell cut. All descriptor acquisition,
//! primary reads and caller postchecks stay within the durable Cell refusal.

use super::*;

pub(crate) struct RootRetainedCellDataV1 {
    files: OriginalCellFiles,
    store: HostAuthorityFrontierStore<CellRecord>,
    owner: String,
    expected: CellRecord,
    refusal: RootDataRefusalV1,
}

pub(crate) struct OriginalRetainedCellReadV1<'a> {
    original: &'a RootRetainedCellDataV1,
}

impl RootRetainedCellDataV1 {
    pub(crate) fn open_captured(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
        open_original_files: impl FnOnce() -> io::Result<RootHistoricalCellInputsV1>,
    ) -> io::Result<Self> {
        original_root()?;
        let refusal = RootDataRefusalV1::open_existing(
            Arc::clone(&root),
            RootDataKind::CellSnapshot,
            target,
        )?;
        let owner = cell_owner(target)?;
        let (store, expected, files) = RootDataRefusalV1::inspect(&refusal, || {
            let store =
                HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?;
            let expected: CellRecord = store.load(&owner).map_err(io::Error::other)?;
            if expected.schema != 1
                || expected.purpose != CELL_PURPOSE
                || &expected.target != target
                || expected.publisher.uid == 0
                || expected.peer_gid == 0
                || expected.publisher_epoch == 0
                || !matches!(&expected.phase, CellPhase::Captured { .. })
            {
                return Err(io::Error::other(
                    "original captured Cell registration required",
                ));
            }
            let files = OriginalCellFiles::retain_original_cell(
                open_original_files()?,
                expected.publisher.uid,
                expected.peer_gid,
            )?;
            if expected.files != *files.file_pins()
                || expected.context != files.context_digest().to_string()
            {
                return Err(io::Error::other(
                    "original captured Cell descriptors differ",
                ));
            }
            let registered: HostAuthorityRegisteredIdentity =
                serde_json::from_str(&expected.registered_identity).map_err(io::Error::other)?;
            if serde_json::to_string(&registered).map_err(io::Error::other)?
                != expected.registered_identity
                || crate::neuron_generation_process_identity_digest_v1(&registered.identity()?)
                    .map_err(io::Error::other)?
                    .to_string()
                    != expected.identity
                || registered.agent_id.as_str() != target.scope().agent_id
            {
                return Err(io::Error::other("original Cell publisher identity differs"));
            }
            if store.load(&owner).map_err(io::Error::other)? != expected {
                return Err(io::Error::other("captured Cell changed while opening"));
            }
            Ok((store, expected, files))
        })?;
        Ok(Self {
            files,
            store,
            owner,
            expected,
            refusal,
        })
    }

    pub(crate) fn with_original_cell_data<T>(
        &self,
        action: impl FnOnce(&OriginalRetainedCellReadV1<'_>) -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        RootDataRefusalV1::inspect(&self.refusal, || {
            if self.store.load(&self.owner).map_err(io::Error::other)? != self.expected {
                return Err(io::Error::other("original captured Cell changed"));
            }
            let result = action(&OriginalRetainedCellReadV1 { original: self })?;
            if self.store.load(&self.owner).map_err(io::Error::other)? != self.expected {
                return Err(io::Error::other(
                    "original Cell changed after recipient context",
                ));
            }
            Ok(result)
        })
    }
}

impl OriginalRetainedCellReadV1<'_> {
    pub(in crate::authority_host_service::generation_initial::historical_source_pin) fn retained_cell_data_digest(
        &self,
    ) -> io::Result<Digest32> {
        Ok(Digest32::of_parts(&[
            b"hepta.root.original-historical-cell-data-cut.v1\0",
            &serde_json::to_vec(&self.original.expected).map_err(io::Error::other)?,
        ]))
    }

    pub(in crate::authority_host_service::generation_initial::historical_source_pin) fn original_cell_publisher_identity(
        &self,
    ) -> io::Result<crate::AgentdIdentity> {
        let registered: HostAuthorityRegisteredIdentity =
            serde_json::from_str(&self.original.expected.registered_identity)
                .map_err(io::Error::other)?;
        let identity = registered.identity()?;
        if serde_json::to_string(&registered).map_err(io::Error::other)?
            != self.original.expected.registered_identity
            || crate::neuron_generation_process_identity_digest_v1(&identity)
                .map_err(io::Error::other)?
                .to_string()
                != self.original.expected.identity
        {
            return Err(io::Error::other("original Cell identity changed"));
        }
        Ok(identity)
    }

    pub(in crate::authority_host_service::generation_initial::historical_source_pin) fn original_cell_peer_gid(
        &self,
    ) -> u32 {
        self.original.expected.peer_gid
    }

    pub(in crate::authority_host_service::generation_initial::historical_source_pin) fn read_original_cell_decision(
        &self,
        source_pin: &PinRecord,
        inputs: &RootHistoricalSourceInputsV1,
        publication: &crate::CircuitTaskSourcePublicationV1,
    ) -> io::Result<codex_hepta_neuron::CellDecisionReceiptV1> {
        original_root()?;
        let original = self.original;
        let record = &original.expected;
        let CellPhase::Captured {
            source_pin: retained_source,
            source_publication,
            sequence,
            checkpoint,
            decision,
        } = &record.phase
        else {
            return Err(io::Error::other("original Cell capture is incomplete"));
        };
        let digest = Digest32::of_parts(&[
            b"hepta.root.historical-source-pin.v1\0",
            &serde_json::to_vec(source_pin).map_err(io::Error::other)?,
        ]);
        if source_pin.fenced
            || *retained_source != digest.to_string()
            || *source_publication != publication.publication_digest().to_string()
            || source_pin.pin.initial_profile != record.initial_profile
            || source_pin.pin.identity != record.identity
            || source_pin.pin.writer != record.writer
            || source_pin.pin.publisher != record.publisher
            || source_pin.pin.publisher_epoch != record.publisher_epoch
            || source_pin.pin.target != record.target
        {
            return Err(io::Error::other(
                "original Cell and Source registrations differ",
            ));
        }
        let observed = original.files.read_original_cell_data(
            &inputs.definition,
            &inputs.source,
            publication,
            &record.target,
        )?;
        if observed.anchor.sequence != *sequence
            || observed.anchor.checkpoint_digest.to_string() != *checkpoint
            || original_decision_digest(&observed)?.to_string() != *decision
        {
            return Err(io::Error::other(
                "original physical Cell cut differs from Root",
            ));
        }
        Ok(observed.decision)
    }
}
