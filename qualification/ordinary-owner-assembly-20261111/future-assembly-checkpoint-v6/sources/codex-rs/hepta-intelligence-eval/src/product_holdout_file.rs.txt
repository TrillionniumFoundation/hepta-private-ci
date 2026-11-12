//! Bounded file material owned by the original final-holdout provider.
//!
//! The host supplies an authorized regular file whose exact bytes were bound
//! into the frozen plan. The shared OS lock coordinates cooperating writers;
//! pathname admission, permissions, provenance and independent row collection
//! remain host responsibilities. Transfer the open file description exclusively:
//! do not retain writable duplicates or mutate the file outside this owner.
//! No decoded rows leave this type without the original runner's one-shot
//! post-consumption permit. This type does not issue roles or authenticate data.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

use codex_hepta_types::Digest32;

use super::FinalHoldoutProviderV1;
use super::OriginalFinalHoldoutReleasePermitV1;
use super::ProductFrozenEvaluationPlanV1;
use super::ProductProviderErrorV1;
use super::TemporalComparisonInputsV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutUseDispositionV1;

#[path = "product_holdout_file_codec.rs"]
mod codec;

pub use codec::encode_file_final_holdout_material_v1;

const MAX_MATERIAL_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FileFinalHoldoutErrorV1 {
    Binding,
    NotRegular,
    Busy,
    Capacity,
    Corrupt,
    Io(io::ErrorKind),
}

impl fmt::Display for FileFinalHoldoutErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for FileFinalHoldoutErrorV1 {}

type FileError = FileFinalHoldoutErrorV1;

struct HeldMaterialFile(File);

impl Drop for HeldMaterialFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

/// The supplied plan and material are data inputs, not credentials. There is no
/// receipt-only release, public permit constructor, File getter or rearm API.
pub struct LockedFileFinalHoldoutProviderV1 {
    material_file: HeldMaterialFile,
    expected_product: ProductFrozenEvaluationPlanV1,
    material_length: u64,
    release_attempted: bool,
}

impl LockedFileFinalHoldoutProviderV1 {
    pub fn open(file: File, expected: &ProductFrozenEvaluationPlanV1) -> Result<Self, FileError> {
        expected
            .validate_integrity()
            .map_err(|_| FileError::Binding)?;
        let metadata = File::metadata(&file).map_err(io_error)?;
        if !metadata.is_file() {
            return Err(FileError::NotRegular);
        }
        File::try_lock_shared(&file).map_err(|error| match error {
            TryLockError::WouldBlock => FileError::Busy,
            TryLockError::Error(error) => io_error(error),
        })?;
        let material_file = HeldMaterialFile(file);
        let material_length = File::metadata(&material_file.0).map_err(io_error)?.len();
        if material_length == 0 || material_length > MAX_MATERIAL_BYTES {
            return Err(FileError::Capacity);
        }
        let mut provider = Self {
            material_file,
            expected_product: expected.clone(),
            material_length,
            release_attempted: false,
        };
        provider.require_original_material()?;
        Ok(provider)
    }

    fn require_original_material(&mut self) -> Result<(), FileError> {
        let file: &mut File = &mut self.material_file.0;
        if File::metadata(file).map_err(io_error)?.len() != self.material_length {
            return Err(FileError::Corrupt);
        }
        Seek::seek(file, SeekFrom::Start(0)).map_err(io_error)?;
        let digest = Digest32::of_reader(&mut *file, MAX_MATERIAL_BYTES).map_err(io_error)?;
        if File::metadata(file).map_err(io_error)?.len() != self.material_length
            || digest != self.expected_product.frozen_plan.final_holdout_digest
        {
            return Err(FileError::Corrupt);
        }
        Ok(())
    }

    fn read_original_material(&mut self) -> Result<TemporalComparisonInputsV1, FileError> {
        let file: &mut File = &mut self.material_file.0;
        if File::metadata(file).map_err(io_error)?.len() != self.material_length {
            return Err(FileError::Corrupt);
        }
        Seek::seek(file, SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        Read::take(&mut *file, MAX_MATERIAL_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != self.material_length
            || File::metadata(file).map_err(io_error)?.len() != self.material_length
            || Digest32::of_bytes(&bytes)
                != self.expected_product.frozen_plan.final_holdout_digest
        {
            return Err(FileError::Corrupt);
        }
        codec::decode_original_material(&bytes, &self.expected_product.frozen_plan)
    }
}

impl FinalHoldoutProviderV1 for LockedFileFinalHoldoutProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        if self.release_attempted {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.require_original_material().map_err(provider_error)?;
        Ok(self.expected_product.frozen_plan.final_holdout_digest)
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        // A copied public receipt is not the original call's release permit.
        Err(ProductProviderErrorV1::Rejected)
    }

    fn release_original_consumption(
        &mut self,
        permit: OriginalFinalHoldoutReleasePermitV1<'_>,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        if std::mem::replace(&mut self.release_attempted, true) {
            return Err(ProductProviderErrorV1::Rejected);
        }
        let frozen = &self.expected_product.frozen_plan;
        if permit.plan != &self.expected_product
            || permit.receipt.disposition != HoldoutUseDispositionV1::Recorded
            || permit.receipt.use_receipt.disposition != HoldoutUseDispositionV1::Recorded
            || permit.receipt.sequence == 0
            || permit.receipt.record_digest.is_zero()
            || permit.receipt.head_digest.is_zero()
            || permit.receipt.authority.grants_any()
            || permit.receipt.use_receipt.authority.grants_any()
            || permit.receipt.use_receipt.plan_digest != frozen.plan_digest
            || permit.receipt.use_receipt.holdout_digest != frozen.final_holdout_digest
        {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.read_original_material().map_err(provider_error)
    }
}

fn io_error(error: io::Error) -> FileError {
    FileError::Io(error.kind())
}

fn provider_error(error: FileError) -> ProductProviderErrorV1 {
    match error {
        FileError::Busy | FileError::Io(_) => ProductProviderErrorV1::Unavailable,
        FileError::Binding | FileError::NotRegular | FileError::Capacity | FileError::Corrupt => {
            ProductProviderErrorV1::Rejected
        }
    }
}
