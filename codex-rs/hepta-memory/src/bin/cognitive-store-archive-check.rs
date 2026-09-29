//! Read-only maintenance adapter to the existing cognitive owner's cold-image oracle.

use std::error::Error;
use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveRecoveryError;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::RecoveredCognitiveReadOnly;
use serde_json::json;

fn main() -> ExitCode {
    match inspect() {
        Ok(code) => code,
        Err(error) => {
            eprintln!("cognitive archive owner inspection failed: {error}");
            ExitCode::FAILURE
        }
    }
}

fn inspect() -> Result<ExitCode, Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    if args.next().as_deref() != Some(std::ffi::OsStr::new("--image")) {
        return Err(
            "usage: cognitive-store-archive-check --image ABSOLUTE_PATH < current-anchor.json"
                .into(),
        );
    }
    let path = PathBuf::from(args.next().ok_or("missing cold image path")?);
    if args.next().is_some() || !path.is_absolute() {
        return Err("one absolute cold image path is required".into());
    }
    let mut bytes = Vec::new();
    std::io::stdin().lock().take(8193).read_to_end(&mut bytes)?;
    if bytes.len() > 8192 {
        return Err("current anchor exceeds byte budget".into());
    }
    let anchor: CognitiveRecoveryAnchor = serde_json::from_slice(&bytes)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    match runtime.block_on(RecoveredCognitiveReadOnly::open_archive_image(
        &path,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
    )) {
        Ok(image) => {
            println!(
                "{}",
                json!({"schema": "hepta.cognitive.archive-owner-check.v1",
                       "anchor": image.anchor(), "exact_cut_verified": true,
                       "write_authority": false})
            );
            Ok(ExitCode::SUCCESS)
        }
        Err(CognitiveRecoveryError::AccessDenied(_)) => {
            println!(
                "{}",
                json!({"schema": "hepta.cognitive.archive-owner-check.v1",
                       "disposition": "access_denied", "write_authority": false})
            );
            Ok(ExitCode::from(2))
        }
        Err(error) => Err(error.into()),
    }
}
