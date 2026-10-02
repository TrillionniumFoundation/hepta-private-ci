//! Rust-only portal selection. A selected name remains untrusted local input.
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

use zbus::zvariant::Value;

use crate::error::ShellError;
use crate::native_portal;
use crate::native_portal::PortalResponse;

use super::MAX_SELECTION_BYTES;

pub(super) fn choose_file() -> Result<Option<PathBuf>, ShellError> {
    futures_lite::future::block_on(async {
        let token = native_portal::request_token()?;
        let options = HashMap::from([
            ("handle_token", Value::from(token.as_str())),
            ("multiple", Value::from(false)),
            ("directory", Value::from(false)),
            ("modal", Value::from(true)),
        ]);
        match native_portal::request(
            "org.freedesktop.portal.FileChooser",
            "OpenFile",
            &("", "Select a Hepta input file", options),
            &token,
            Duration::from_secs(120),
        )
        .await?
        {
            PortalResponse::Cancelled => Ok(None),
            PortalResponse::Completed(mut results) => {
                let uris = results.remove("uris").ok_or_else(|| {
                    ShellError::Platform("portal selection is missing uris".into())
                })?;
                let uris: Vec<String> = uris.try_into().map_err(|_| {
                    ShellError::Platform("portal selection has invalid uris".into())
                })?;
                let [uri] = uris.as_slice() else {
                    return Err(ShellError::InvalidInput(
                        "portal must select exactly one file".into(),
                    ));
                };
                decode_selected_uri(uri).map(Some)
            }
        }
    })
}

fn decode_selected_uri(uri: &str) -> Result<PathBuf, ShellError> {
    let invalid = || ShellError::InvalidInput("portal returned an invalid local file URI".into());
    if uri.len() > MAX_SELECTION_BYTES || uri.contains(['?', '#']) {
        return Err(invalid());
    }
    let encoded = if let Some(rest) = uri.strip_prefix("file://") {
        if rest.starts_with('/') {
            rest
        } else {
            rest.strip_prefix("localhost")
                .filter(|path| path.starts_with('/'))
                .ok_or_else(invalid)?
        }
    } else {
        uri.strip_prefix("file:")
            .filter(|path| path.starts_with('/'))
            .ok_or_else(invalid)?
    };
    let mut decoded = Vec::with_capacity(encoded.len());
    let mut bytes = encoded.bytes();
    while let Some(byte) = bytes.next() {
        if byte == b'%' {
            let high = bytes
                .next()
                .and_then(|digit| char::from(digit).to_digit(16))
                .ok_or_else(invalid)?;
            let low = bytes
                .next()
                .and_then(|digit| char::from(digit).to_digit(16))
                .ok_or_else(invalid)?;
            decoded.push(((high << 4) | low) as u8);
        } else {
            decoded.push(byte);
        }
    }
    let path = String::from_utf8(decoded).map_err(|_| invalid())?;
    // Do not use a URL normalizer: resolving dot segments can change the
    // meaning of a filesystem path with symlink ancestors.
    super::validate_selection(&path)
}

#[cfg(test)]
#[path = "native_picker_linux_tests.rs"]
mod tests;
