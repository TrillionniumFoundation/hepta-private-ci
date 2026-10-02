//! Authenticated withdrawal publication before the first artifact CURRENT.
//!
//! Snapshot bytes precede the signed acknowledgement record. An orphan snapshot
//! grants no frontier change; an acknowledged record must recover its exact bytes.
use super::*;
use crate::DatasetWithdrawalSnapshotReceiptV1;
use crate::read_dataset_withdrawal_snapshot;
use crate::write_dataset_withdrawal_snapshot_beneath;

const MAGIC: &str = "HEPTA-ARTIFACT-WITHDRAWAL-BOOTSTRAP-V1";

#[derive(Clone, Debug)]
pub struct LearningArtifactWithdrawalBootstrapRequestV1 {
    pub operation_id: StableId,
    pub registry_id: StableId,
    pub binding: Digest32,
    pub expected_withdrawal_head: Digest32,
    pub next_withdrawal_registry: DatasetWithdrawalRegistry,
    pub signer_id: StableId,
    pub signing_key_digest: Digest32,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: [u8; 64],
}

impl LearningArtifactWithdrawalBootstrapRequestV1 {
    /// The deployment's trusted head signer authorizes this domain separately
    /// from CURRENT. No registry head or artifact selection is manufactured.
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.withdrawal-bootstrap.v1".to_vec();
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.registry_id);
        for digest in [
            self.binding,
            self.expected_withdrawal_head,
            self.next_withdrawal_registry
                .scope_digest()
                .unwrap_or(Digest32::ZERO),
            self.next_withdrawal_registry.head_digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.signer_id);
        bytes.extend_from_slice(self.signing_key_digest.as_array());
        for value in [self.authority_epoch, self.issued_at, self.expires_at] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactWithdrawalBootstrapReceiptV1 {
    pub operation_id: StableId,
    pub withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
    pub authorization_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl LearningArtifactOwnerHost {
    pub(crate) fn bootstrap_record_exists(&self, operation: &StableId) -> bool {
        self.bootstrap_record_path(operation).exists()
    }

    fn bootstrap_record_path(&self, operation: &StableId) -> PathBuf {
        self.root.join("withdrawal-bootstrap").join(format!(
            "{}.receipt",
            Digest32::of_bytes(operation.as_str().as_bytes())
        ))
    }

    fn verify_bootstrap_authorization(
        &self,
        request: &LearningArtifactWithdrawalBootstrapRequestV1,
        now: u64,
        require_current: bool,
    ) -> Result<(), ArtifactOwnerHostError> {
        if request.registry_id != self.verifier.trust.registry_id
            || request.binding.is_zero()
            || request.next_withdrawal_registry.scope_digest()
                != Some(self.verifier.trust.withdrawal_scope_digest)
            || (require_current
                && request.authority_epoch < self.verifier.trust.minimum_authority_epoch)
            || request.issued_at > now
            || request.issued_at > request.expires_at
            || require_current && now > request.expires_at
        {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let signer = self
            .verifier
            .head_signers
            .get(&request.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        verify_signer_context(
            signer,
            request.signing_key_digest,
            request.authority_epoch,
            request.issued_at,
            now,
            require_current,
        )?;
        verify_signature(
            &signer.verifying_key,
            &request.signing_bytes(),
            &request.signature,
        )
    }

    pub(crate) fn publish_bootstrap_withdrawal(
        &self,
        request: &LearningArtifactWithdrawalBootstrapRequestV1,
        predecessor: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<ArtifactWithdrawalBootstrapReceiptV1, ArtifactOwnerHostError> {
        let _gate = self
            .publication_gate
            .lock()
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        if !self.recovery_required_operations()?.is_empty()
            || !self.state_recovery_operations()?.is_empty()
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        self.require_current_writer(now)?;
        self.verify_bootstrap_authorization(request, now, true)?;
        if self.recover_publication(&request.operation_id)?.is_some()
            || self
                .recover_state_publication(&request.operation_id)?
                .is_some()
        {
            return Err(ArtifactOwnerHostError::IdentityConflict);
        }
        let bytes = crate::durable_snapshots::encode_withdrawal_snapshot(
            &request.next_withdrawal_registry,
            request.binding,
        )?;
        let withdrawal_receipt = DatasetWithdrawalSnapshotReceiptV1 {
            binding: request.binding,
            scope_digest: self.verifier.trust.withdrawal_scope_digest,
            head_digest: request.next_withdrawal_registry.head_digest(),
            file_digest: Digest32::of_bytes(&bytes),
            records: request.next_withdrawal_registry.snapshot().records().len(),
            encoded_bytes: bytes.len(),
        };
        let encoded = encode(request, withdrawal_receipt);
        let record_path = self.bootstrap_record_path(&request.operation_id);
        if record_path.exists() {
            if read_small_record(&record_path, MAX_SMALL_RECORD_BYTES)? != encoded {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
            self.read_bootstrap_record(&record_path)?;
            recovery::synchronize_artifact_path(&record_path)?;
            return Ok(receipt(request, withdrawal_receipt));
        }
        if self.discover_current_head(now)?.is_some() {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        if predecessor.head_digest() != request.expected_withdrawal_head {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let previous = predecessor.snapshot();
        let next = request.next_withdrawal_registry.snapshot();
        if next.records().len() < previous.records().len()
            || &next.records()[..previous.records().len()] != previous.records()
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        if fs::read_dir(self.root.join("withdrawal-bootstrap"))?
            .take(MAX_HEAD_RECORDS)
            .count()
            >= MAX_HEAD_RECORDS
        {
            return Err(ArtifactOwnerHostError::Capacity);
        }
        capacity::reserve(self, "withdrawals", MAX_HEAD_RECORDS * 3, 1)?;
        let relative = withdrawal_path(withdrawal_receipt);
        match write_dataset_withdrawal_snapshot_beneath(
            &self.root,
            &relative,
            &request.next_withdrawal_registry,
            request.binding,
        ) {
            Ok(actual) if actual == withdrawal_receipt => {}
            Ok(_) => return Err(ArtifactOwnerHostError::CheckpointMismatch),
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                read_dataset_withdrawal_snapshot(
                    File::open(self.root.join(&relative))?,
                    withdrawal_receipt,
                )?;
            }
            Err(error) => return Err(error.into()),
        }
        recovery::synchronize_artifact_path(&self.root.join(relative))?;
        write_create_only_or_exact(&record_path, &encoded)?;
        Ok(receipt(request, withdrawal_receipt))
    }

    fn read_bootstrap_record(
        &self,
        path: &Path,
    ) -> Result<
        (
            LearningArtifactWithdrawalBootstrapRequestV1,
            ArtifactWithdrawalBootstrapReceiptV1,
        ),
        ArtifactOwnerHostError,
    > {
        let bytes = read_small_record(path, MAX_SMALL_RECORD_BYTES)?;
        let text =
            std::str::from_utf8(&bytes).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
        let fields: Vec<_> = text.lines().collect();
        if fields.len() != 16 || fields[0] != MAGIC {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let snapshot_receipt = DatasetWithdrawalSnapshotReceiptV1 {
            binding: parse_digest(fields[3])?,
            scope_digest: parse_digest(fields[5])?,
            head_digest: parse_digest(fields[6])?,
            file_digest: parse_digest(fields[7])?,
            records: parse_usize(fields[8])?,
            encoded_bytes: parse_usize(fields[9])?,
        };
        let request = LearningArtifactWithdrawalBootstrapRequestV1 {
            operation_id: StableId::new(fields[1])
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
            registry_id: StableId::new(fields[2])
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
            binding: snapshot_receipt.binding,
            expected_withdrawal_head: parse_digest(fields[4])?,
            next_withdrawal_registry: read_dataset_withdrawal_snapshot(
                File::open(self.root.join(withdrawal_path(snapshot_receipt)))?,
                snapshot_receipt,
            )?,
            signer_id: StableId::new(fields[10])
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
            signing_key_digest: parse_digest(fields[11])?,
            authority_epoch: parse_u64(fields[12])?,
            issued_at: parse_u64(fields[13])?,
            expires_at: parse_u64(fields[14])?,
            signature: decode_signature(fields[15])?,
        };
        if self.bootstrap_record_path(&request.operation_id) != path
            || encode(&request, snapshot_receipt) != bytes
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        self.verify_bootstrap_authorization(&request, request.issued_at, false)?;
        let snapshot = request.next_withdrawal_registry.snapshot();
        let genesis = DatasetWithdrawalRegistry::new_scoped(
            request
                .next_withdrawal_registry
                .scope()
                .cloned()
                .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?,
        )
        .head_digest();
        if request.expected_withdrawal_head != genesis
            && request.expected_withdrawal_head != snapshot.head_digest
            && !snapshot
                .records()
                .iter()
                .any(|record| record.chain_digest == request.expected_withdrawal_head)
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let receipt = receipt(&request, snapshot_receipt);
        Ok((request, receipt))
    }

    pub(crate) fn recover_bootstrap_withdrawals(
        &self,
        supplied: DatasetWithdrawalRegistry,
        binding: Digest32,
    ) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
        let mut frontier = supplied;
        for (index, entry) in fs::read_dir(self.root.join("withdrawal-bootstrap"))?.enumerate() {
            if index >= MAX_HEAD_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            let entry = entry?;
            let (request, _) = self.read_bootstrap_record(&entry.path())?;
            if request.binding != binding {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            let current = frontier.snapshot();
            let next = request.next_withdrawal_registry.snapshot();
            let common = current.records().len().min(next.records().len());
            if current.records()[..common] != next.records()[..common] {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            if next.records().len() > current.records().len() {
                frontier = request.next_withdrawal_registry;
            }
        }
        Ok(frontier)
    }
}

fn withdrawal_path(receipt: DatasetWithdrawalSnapshotReceiptV1) -> PathBuf {
    PathBuf::from("withdrawals").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ))
}
fn receipt(
    request: &LearningArtifactWithdrawalBootstrapRequestV1,
    withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
) -> ArtifactWithdrawalBootstrapReceiptV1 {
    let mut bytes = request.signing_bytes();
    bytes.extend_from_slice(&request.signature);
    ArtifactWithdrawalBootstrapReceiptV1 {
        operation_id: request.operation_id.clone(),
        withdrawal_receipt,
        authorization_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    }
}
fn encode(
    request: &LearningArtifactWithdrawalBootstrapRequestV1,
    receipt: DatasetWithdrawalSnapshotReceiptV1,
) -> Vec<u8> {
    format!(
        "{MAGIC}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n",
        request.operation_id,
        request.registry_id,
        request.binding,
        request.expected_withdrawal_head,
        receipt.scope_digest,
        receipt.head_digest,
        receipt.file_digest,
        receipt.records,
        receipt.encoded_bytes,
        request.signer_id,
        request.signing_key_digest,
        request.authority_epoch,
        request.issued_at,
        request.expires_at,
        encode_hex(&request.signature)
    )
    .into_bytes()
}
