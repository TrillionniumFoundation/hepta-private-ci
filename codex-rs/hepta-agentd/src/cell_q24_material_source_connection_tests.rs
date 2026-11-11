//! Explicit fixture-only prebound transport; production constructors retain
//! their original independent-process checks.
use super::*;

pub(crate) fn retained_connection_fixture(
    transport: RootObservationStream,
    initial: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    baseline: Arc<LoadedCellQ24ModelV1>,
) -> OriginalCellQ24MaterialSourceConnectionV1 {
    OriginalCellQ24MaterialSourceConnectionV1 { transport, initial, scope, baseline }
}
