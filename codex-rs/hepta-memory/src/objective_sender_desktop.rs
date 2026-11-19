//! Versioned raw navigation data retained by the same original sender.
use super::*;

/// A Desktop callback reference is not a Core proof, grant, or replay token.
/// Readback must compare it to the exact signed source and retained operation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalDesktopThreadReference {
    pub profile: String,
    pub tool: String,
    pub app_server_session_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub call_id: String,
    pub callback_sha256: String,
}

impl OriginalDesktopThreadReference {
    pub fn validate_shape(&self) -> Result<(), ObjectiveSenderInputError> {
        if self.profile != "organ.desktop.thread-tool.v1"
            || !matches!(
                self.tool.as_str(),
                "hepta_notes_replace" | "hepta_calculator_evaluate"
            )
        {
            return Err(ObjectiveSenderInputError::Identity);
        }
        for (value, limit) in [
            (&self.app_server_session_id, 256),
            (&self.thread_id, 128),
            (&self.turn_id, 128),
            (&self.call_id, 128),
        ] {
            if value.is_empty() || value.len() > limit || value.contains('\0') {
                return Err(ObjectiveSenderInputError::Identity);
            }
        }
        if Digest32::from_str(&self.callback_sha256)
            .map_err(|_| ObjectiveSenderInputError::Identity)?
            .is_zero()
        {
            return Err(ObjectiveSenderInputError::Identity);
        }
        Ok(())
    }
}
