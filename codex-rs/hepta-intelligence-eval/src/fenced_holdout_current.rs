//! Full physical CURRENT from the original locked final-holdout file.
//! Both complete reads and replay use the same grammar as recovery and CAS.
//! No replacement handle, minimum-anchor repair or external effect occurs.

use super::*;

pub(super) struct PhysicalCurrent {
    pub(super) bytes: Vec<u8>,
    pub(super) state: Option<FinalHoldoutCasRecordV1>,
    pub(super) history_digest: Digest32,
}

pub(super) fn read_physical(
    file: &mut AcquiredFile,
    binding: Digest32,
    minimum: Option<FinalHoldoutCasAnchorV1>,
) -> Result<PhysicalCurrent, LockedFileCasErrorV1> {
    let original_position = file.stream_position().map_err(io_error)?;
    let image = physical::read_stable_image(file);
    let restored = file
        .seek(SeekFrom::Start(original_position))
        .map_err(io_error)?;
    if restored != original_position {
        return Err(LockedFileCasErrorV1::Indeterminate);
    }
    let bytes = image?;
    let state = physical::replay_image(&bytes, binding, minimum)?;
    let history_digest = Digest32::of_parts(&[
        b"hepta.intelligence-eval.locked-holdout-current.v1\0",
        binding.as_array(),
        &bytes,
    ]);
    Ok(PhysicalCurrent {
        bytes,
        state,
        history_digest,
    })
}
