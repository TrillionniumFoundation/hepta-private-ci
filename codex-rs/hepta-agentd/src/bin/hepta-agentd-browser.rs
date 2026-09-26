//! Persistent Agentd-owned product service for `browser.servo`.
//!
//! Calls use bounded newline-delimited JSON on inherited stdin/stdout. The
//! process retains the private Browser child, durable authority and live
//! revocation feed across calls; it exposes no Browser TCP or UDS listener.

use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

#[path = "../browser_revocation_feed.rs"]
mod browser_revocation_feed;
#[path = "../browser_servo_admission_frame.rs"]
mod browser_servo_admission_frame;
#[path = "../browser_servo_admission_transport.rs"]
mod browser_servo_admission_transport;
#[path = "../browser_servo_product.rs"]
mod browser_servo_product;
#[path = "../browser_servo_product_host.rs"]
mod browser_servo_product_host;

use browser_servo_product::BrowserServoError;
use browser_servo_product_host::{
    PersistentBrowserProduct, ProductCall, ProductHostConfig,
};

const MAX_CONFIG_BYTES: u64 = 1_048_576;
const MAX_REQUEST_BYTES: usize = 1_048_576;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let config_path = arguments
        .next()
        .ok_or("usage: hepta-agentd-browser PRODUCT_CONFIG.json")?;
    if arguments.next().is_some() {
        return Err(
            "usage: hepta-agentd-browser PRODUCT_CONFIG.json".into(),
        );
    }
    let config: ProductHostConfig = serde_json::from_slice(
        &bounded_private_file(
            PathBuf::from(config_path).as_path(),
            MAX_CONFIG_BYTES,
        )?,
    )?;
    let mut product = PersistentBrowserProduct::from_config(config)?;
    let mut input = BufReader::new(std::io::stdin().lock());
    let mut output = std::io::BufWriter::new(std::io::stdout().lock());
    let mut next_request_id = 1_u64;

    loop {
        let Some(bytes) = read_bounded_line(&mut input)? else {
            output.flush()?;
            return Ok(());
        };
        let call: ProductCall = match serde_json::from_slice(&bytes) {
            Ok(call) => call,
            Err(error) => {
                respond(
                    &mut output,
                    json!({
                        "requestId": Value::Null,
                        "ok": false,
                        "error": bounded(format!(
                            "invalid Browser call JSON: {error}"
                        )),
                    }),
                )?;
                continue;
            }
        };
        let request_id = match call.request_id.as_deref() {
            Some(value) => {
                stable_id(value)?;
                value.to_owned()
            }
            None => {
                let value = format!("browser.host.{next_request_id}");
                next_request_id = next_request_id
                    .checked_add(1)
                    .ok_or("Browser host request id exhausted")?;
                value
            }
        };
        match product.call(call) {
            Ok(result) => respond(
                &mut output,
                json!({
                    "requestId": request_id,
                    "ok": true,
                    "result": result,
                }),
            )?,
            Err(error) => respond(
                &mut output,
                json!({
                    "requestId": request_id,
                    "ok": false,
                    "error": bounded(error.to_string()),
                    "indeterminate": matches!(
                        error,
                        BrowserServoError::Indeterminate(_)
                    ),
                }),
            )?,
        }
    }
}

fn read_bounded_line(
    input: &mut impl BufRead,
) -> Result<Option<Vec<u8>>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    loop {
        let available = input.fill_buf()?;
        if available.is_empty() {
            if bytes.is_empty() {
                return Ok(None);
            }
            return Err(
                "Browser call channel ended with a partial frame".into(),
            );
        }
        if let Some(position) = available
            .iter()
            .position(|byte| *byte == b'\n')
        {
            let consumed = position + 1;
            if bytes.len() + consumed > MAX_REQUEST_BYTES + 1 {
                return Err(
                    "Browser call exceeds the bounded line protocol".into(),
                );
            }
            bytes.extend_from_slice(&available[..consumed]);
            input.consume(consumed);
            break;
        }
        if bytes.len() + available.len() > MAX_REQUEST_BYTES {
            return Err(
                "Browser call exceeds the bounded line protocol".into(),
            );
        }
        let consumed = available.len();
        bytes.extend_from_slice(available);
        input.consume(consumed);
    }
    bytes.pop();
    if bytes.is_empty() {
        return Err("Browser call line is empty".into());
    }
    Ok(Some(bytes))
}

fn respond(
    output: &mut impl Write,
    value: Value,
) -> Result<(), Box<dyn std::error::Error>> {
    serde_json::to_writer(&mut *output, &value)?;
    output.write_all(b"\n")?;
    output.flush()?;
    Ok(())
}

fn bounded_private_file(
    path: &Path,
    maximum: u64,
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
    {
        return Err(format!(
            "{} must be a non-empty regular non-symlink file",
            path.display()
        )
        .into());
    }
    if metadata.len() > maximum {
        return Err(format!(
            "{} exceeds {maximum} bytes",
            path.display()
        )
        .into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(format!(
                "{} permissions are too broad",
                path.display()
            )
            .into());
        }
    }
    Ok(fs::read(path)?)
}

fn stable_id(value: &str) -> Result<(), Box<dyn std::error::Error>> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| {
                byte.is_ascii_alphanumeric()
                    || b"._:-".contains(&byte)
            })
    {
        return Err(
            "Browser request_id must be a bounded stable identifier".into(),
        );
    }
    Ok(())
}

fn bounded(value: impl AsRef<str>) -> String {
    value.as_ref().chars().take(512).collect()
}
