//! A typed one-result pipe protocol for the main-thread OS picker helper.
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;

const SCHEMA: &str = "hepta.native-file-picker.v1";

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PickerReply {
    schema: String,
    binary_digest: String,
    selection: Option<String>,
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
pub(in crate::ui) fn run() -> Result<(), ShellError> {
    use std::io::Write as _;
    let binary_digest = crate::update_storage::running_binary_digest()?;
    let selection = hepta_native_platform::picker::choose_file()
        .map_err(ShellError::Platform)?
        .map(|path| {
            let text = path.to_str().ok_or_else(|| {
                ShellError::InvalidInput("selected filename is not representable as UTF-8".into())
            })?;
            super::validate_selection(text)?;
            Ok::<_, ShellError>(text.to_owned())
        })
        .transpose()?;
    let reply = PickerReply {
        schema: SCHEMA.into(),
        binary_digest,
        selection,
    };
    serde_json::to_writer(std::io::stdout().lock(), &reply)?;
    std::io::stdout().flush()?;
    Ok(())
}

pub(super) fn parse_reply(
    bytes: &[u8],
    expected_digest: &str,
) -> Result<Option<PathBuf>, ShellError> {
    if bytes.len() > super::MAX_DIALOG_OUTPUT_BYTES {
        return Err(ShellError::InvalidInput(
            "picker response exceeds byte bound".into(),
        ));
    }
    let reply: PickerReply = serde_json::from_slice(bytes)?;
    if reply.schema != SCHEMA || reply.binary_digest != expected_digest {
        return Err(ShellError::Security(
            "picker helper identity mismatch".into(),
        ));
    }
    reply
        .selection
        .as_deref()
        .map(super::validate_selection)
        .transpose()
}
