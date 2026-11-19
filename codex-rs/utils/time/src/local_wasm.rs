//! JavaScript's local-zone lookup covers the persisted timestamp range.

use super::LocalTimeError;
use crate::Timestamp;

pub(super) fn offset(value: Timestamp) -> Result<i32, LocalTimeError> {
    let milliseconds = wasm_bindgen::JsValue::from_f64(value.timestamp_millis() as f64);
    let minutes = js_sys::Date::new(&milliseconds).get_timezone_offset();
    (minutes as i32)
        .checked_mul(60)
        .and_then(i32::checked_neg)
        .filter(|seconds| (-86_399..=86_399).contains(seconds))
        .ok_or(LocalTimeError::InvalidOffset)
}
