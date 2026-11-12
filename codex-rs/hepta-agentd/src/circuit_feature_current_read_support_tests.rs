//! New slot-state mechanisms over actual sealed Published owners. These
//! probes do not manufacture Source/Cell observations or issue signatures.
//! The complete physical read path remains covered by the ordinary Published
//! transport tests and the unchanged 500 ms Observer evidence test.

use codex_hepta_neuron::AnchorWitnessStore;

use crate::AgentdError;
use crate::PublishedCircuitCellOwnerV1;
use crate::circuit_feature_current::current_read::OriginalPublishedReadCurrent;
use crate::circuit_feature_current::current_read::OriginalPublishedReadPurpose;

pub(crate) struct PendingFinalCurrent<'a, W: AnchorWitnessStore> {
    cell: &'a PublishedCircuitCellOwnerV1<W>,
    current: OriginalPublishedReadCurrent<'a, W>,
}

impl<W: AnchorWitnessStore> PendingFinalCurrent<'_, W> {
    /// Only the original last slot remains. Its error is returned unchanged.
    pub(crate) fn finish(mut self) -> Result<(), AgentdError> {
        self.current.require(self.cell)?;
        self.current.finish()
    }
}

fn before_last<W: AnchorWitnessStore>(
    cell: &PublishedCircuitCellOwnerV1<W>,
    purpose: OriginalPublishedReadPurpose,
) -> Result<PendingFinalCurrent<'_, W>, AgentdError> {
    let mut current = OriginalPublishedReadCurrent::for_original_read(cell);
    for _ in 0..4 {
        current.require(cell)?;
    }
    let slots = match &purpose {
        OriginalPublishedReadPurpose::Selection => 10,
        OriginalPublishedReadPurpose::NextUse => 15,
    };
    current.select_purpose(purpose)?;
    for _ in 4..slots - 1 {
        current.require(cell)?;
    }
    Ok(PendingFinalCurrent { cell, current })
}

pub(crate) fn pending_final_reads<W: AnchorWitnessStore>(
    cell: &PublishedCircuitCellOwnerV1<W>,
) -> Result<[PendingFinalCurrent<'_, W>; 2], AgentdError> {
    Ok([
        before_last(cell, OriginalPublishedReadPurpose::Selection)?,
        before_last(cell, OriginalPublishedReadPurpose::NextUse)?,
    ])
}

pub(crate) fn reject_wrong_original_and_reuse<W: AnchorWitnessStore>(
    cell: &PublishedCircuitCellOwnerV1<W>,
    other: &PublishedCircuitCellOwnerV1<W>,
) -> anyhow::Result<()> {
    let mut wrong = OriginalPublishedReadCurrent::for_original_read(cell);
    wrong.require(cell)?;
    let error = wrong
        .require(other)
        .expect_err("another actual Cell must fail");
    anyhow::ensure!(
        error
            .to_string()
            .contains("same original published Cell and Task read")
    );
    anyhow::ensure!(
        wrong.require(cell).is_err(),
        "wrong original permanently poisoned call"
    );
    anyhow::ensure!(wrong.finish().is_err(), "wrong original cannot finish");

    let mut early = OriginalPublishedReadCurrent::for_original_read(cell);
    early.require(cell)?;
    anyhow::ensure!(
        early
            .select_purpose(OriginalPublishedReadPurpose::Selection)
            .is_err(),
        "purpose cannot precede the original first four slots"
    );
    anyhow::ensure!(early.require(cell).is_err());
    anyhow::ensure!(early.finish().is_err());

    let unfinished = before_last(cell, OriginalPublishedReadPurpose::Selection)?;
    anyhow::ensure!(
        unfinished.current.finish().is_err(),
        "the last physical CURRENT cannot be omitted"
    );

    let mut repeated = OriginalPublishedReadCurrent::for_original_read(cell);
    for _ in 0..4 {
        repeated.require(cell)?;
    }
    repeated.select_purpose(OriginalPublishedReadPurpose::Selection)?;
    anyhow::ensure!(
        repeated
            .select_purpose(OriginalPublishedReadPurpose::NextUse)
            .is_err(),
        "a purpose cannot extend or renew this call"
    );
    anyhow::ensure!(repeated.require(cell).is_err());
    anyhow::ensure!(repeated.finish().is_err());

    // This is the existing Clone view of the exact same journal and Task
    // allocations, not an independently opened owner or copied publication.
    let same = cell.clone();
    for (purpose, again) in [
        (
            OriginalPublishedReadPurpose::Selection,
            OriginalPublishedReadPurpose::Selection,
        ),
        (
            OriginalPublishedReadPurpose::NextUse,
            OriginalPublishedReadPurpose::NextUse,
        ),
    ] {
        let mut complete = before_last(cell, purpose)?;
        complete.current.require(&same)?;
        anyhow::ensure!(
            complete.current.require(cell).is_err(),
            "even an extra slot after completion must poison the call"
        );
        anyhow::ensure!(
            complete.current.finish().is_err(),
            "a refused extra slot cannot leave completed evidence usable"
        );
        let mut original = before_last(cell, again)?;
        original.current.require(&same)?;
        original.current.finish()?;
    }
    Ok(())
}
