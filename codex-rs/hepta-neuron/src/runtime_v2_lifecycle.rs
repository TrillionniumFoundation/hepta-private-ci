//! Operation lifecycle: preflight -> reservation -> dispatch fence -> local
//! result commit -> index completion -> external witness reconciliation.
use super::*;
use crate::NeuronOperationFailureV2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NeuronRecoveryDispositionV2 {
    PreserveUnexecuted,
    CloseUnexecuted,
}

include!("runtime_v2_lifecycle_status.rs");
include!("runtime_v2_lifecycle_query.rs");
include!("runtime_v2_lifecycle_facade.rs");
include!("runtime_v2_lifecycle_execute.rs");
include!("runtime_v2_lifecycle_recover.rs");
include!("runtime_v2_lifecycle_commit.rs");
include!("runtime_v2_lifecycle_test_modules.rs");
