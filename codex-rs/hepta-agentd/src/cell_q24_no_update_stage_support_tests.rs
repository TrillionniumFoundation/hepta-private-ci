//! Test-only adapter with actual Material clients and no Root effect gate.
//! Future-stage channels are absent because these cases exercise only the
//! Material/Training readback edges. No helper can install or construct a Root gate.

use std::time::Duration;
use std::time::Instant;

use super::super::Error;
use super::super::Origin;
use super::super::OriginalCellQ24NoUpdateStageOwnersV1;
use super::Continuation;
use crate::OriginalCellQ24MaterialCommandClientV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;

fn material_only(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    experience: OriginalCellQ24MaterialCommandClientV1,
    dataset: OriginalCellQ24MaterialCommandClientV1,
    origin: Origin,
) -> Result<OriginalCellQ24NoUpdateStageOwnersV1, Error> {
    let (initial_binding, _) =
        OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)
            .map_err(|_| Error::WrongScope)?;
    Ok(OriginalCellQ24NoUpdateStageOwnersV1 {
        material,
        initial_binding,
        origin,
        end: Instant::now() + Duration::from_secs(300),
        continuation: tokio::sync::Mutex::new(Continuation {
            experience,
            dataset,
            trainer_initial: None,
            trainer: None,
            version_initial: None,
            version: None,
            selector_initial: None,
            selector: None,
            next_use_initial: None,
            next_use: None,
            readiness_initial: None,
            readiness: None,
            records: Vec::with_capacity(5),
            original_dataset: None,
            original_training: None,
            original_selection: None,
        }),
        root: None,
    })
}

pub(crate) fn fresh_material_only(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    experience: OriginalCellQ24MaterialCommandClientV1,
    dataset: OriginalCellQ24MaterialCommandClientV1,
) -> Result<OriginalCellQ24NoUpdateStageOwnersV1, Error> {
    material_only(material, experience, dataset, Origin::Fresh)
}

pub(crate) fn recovered_material_only(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    experience: OriginalCellQ24MaterialCommandClientV1,
    dataset: OriginalCellQ24MaterialCommandClientV1,
) -> Result<OriginalCellQ24NoUpdateStageOwnersV1, Error> {
    material_only(material, experience, dataset, Origin::Recovered)
}

pub(crate) fn recovered_candidate_clients(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    experience: OriginalCellQ24MaterialCommandClientV1,
    dataset: OriginalCellQ24MaterialCommandClientV1,
    trainer: crate::OriginalCellQ24TrainingCommandClientV1,
) -> Result<OriginalCellQ24NoUpdateStageOwnersV1, Error> {
    let mut owners = material_only(material, experience, dataset, Origin::Recovered)?;
    owners.continuation.get_mut().trainer = Some(trainer);
    Ok(owners)
}
