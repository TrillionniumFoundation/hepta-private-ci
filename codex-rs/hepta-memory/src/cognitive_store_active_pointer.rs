//! The original active-generation spelling, shared by ordinary and Root copy publication.

use super::COGNITIVE_ACTIVE_DB_POINTER;
use super::COGNITIVE_RECOVERED_DB_PREFIX;
use super::CognitiveStoreError;
use super::valid_recovered_database_filename;

pub(super) fn parse_active_pointer(value: &str) -> Result<&str, CognitiveStoreError> {
    if value.len() > 256 {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive active database pointer exceeds its bound".to_string(),
        ));
    }
    let value = value.trim();
    if !valid_recovered_database_filename(value) {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive active database pointer is invalid".to_string(),
        ));
    }
    Ok(value)
}

pub(super) fn active_pointer_temporary_name(
    file_name: &str,
) -> Result<String, CognitiveStoreError> {
    if !valid_recovered_database_filename(file_name) {
        return Err(CognitiveStoreError::Invalid(
            "recovered cognitive database has an invalid generation name".to_string(),
        ));
    }
    let generation = file_name
        .strip_prefix(COGNITIVE_RECOVERED_DB_PREFIX)
        .and_then(|value| value.strip_suffix(".sqlite3"))
        .expect("validated recovered database spelling");
    Ok(format!(
        "{COGNITIVE_ACTIVE_DB_POINTER}.tmp-{}-{}",
        std::process::id(),
        &generation[..16]
    ))
}
