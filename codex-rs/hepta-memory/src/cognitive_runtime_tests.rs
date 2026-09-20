use pretty_assertions::assert_eq;

use crate::CognitiveRuntime;
use crate::CognitiveStoreError;
use crate::CognitiveUnavailableReason;

#[test]
fn unavailable_runtime_exposes_only_a_stable_sanitized_code() {
    let runtime = CognitiveRuntime::from_open_result(Err(CognitiveStoreError::Unavailable(
        "/private/store/path: secret database detail".to_string(),
    )));
    assert_eq!(
        runtime.unavailable_reason(),
        Some(CognitiveUnavailableReason::StorageUnavailable)
    );
    assert_eq!(
        runtime
            .unavailable_reason()
            .map(super::cognitive_runtime::CognitiveUnavailableReason::code),
        Some("storage_unavailable")
    );
    assert_eq!(
        format!("{runtime:?}"),
        "CognitiveRuntime::Unavailable(StorageUnavailable)"
    );
}
