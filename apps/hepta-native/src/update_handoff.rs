//! Local update-process handoff; this is not release or effect authority.
use crate::error::ShellError;
use crate::model::SessionIncarnation;
use crate::model::sha256_hex;
use crate::model::validate_digest;
use serde::Deserialize;
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UpdateHandoff {
    nonce: String,
    arguments_digest: String,
}

impl UpdateHandoff {
    pub(crate) fn issue(arguments: &[String]) -> Result<Self, ShellError> {
        let mut random = [0; 32];
        getrandom::fill(&mut random)
            .map_err(|e| ShellError::Update(format!("update handoff entropy: {e}")))?;
        Self::from_invocation(sha256_hex(random), arguments)
    }
    pub fn from_invocation(nonce: String, arguments: &[String]) -> Result<Self, ShellError> {
        validate_digest(&nonce, "update handoff nonce")?;
        if arguments.len() > 128
            || arguments.iter().map(String::len).sum::<usize>() > 64 * 1024
            || arguments.iter().any(|a| {
                a == "--check-connection"
                    || a == "--self-test"
                    || a.starts_with("--qualification-")
                    || a == "--update-handoff"
            })
        {
            return Err(ShellError::Update(
                "update restart requires bounded ordinary product arguments".into(),
            ));
        }
        for required in ["--endpoint-manifest", "--trusted-keys", "--state-dir"] {
            if !arguments.iter().any(|a| a == required) {
                return Err(ShellError::Update(format!(
                    "update restart lacks {required}"
                )));
            }
        }
        let arguments_digest = sha256_hex(serde_json::to_vec(&(
            "hepta.native-restart-arguments.v1",
            arguments,
        ))?);
        Ok(Self {
            nonce,
            arguments_digest,
        })
    }
    pub fn nonce(&self) -> &str {
        &self.nonce
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UpdateReadiness {
    pub process_id: u32,
    pub session: SessionIncarnation,
    pub view_digest: String,
    pub view_revision: u64,
    pub binary_digest: String,
}

/// A candidate may outlive its helper only after the helper has observed the
/// durable, process-bound GUI readiness record and acknowledged it over stdin.
/// A dead or stalled helper before that boundary leaves recovery to a new owner.
pub fn watch_helper_lifetime() -> Result<(), ShellError> {
    let (sender, receiver) = std::sync::mpsc::sync_channel(1);
    std::thread::Builder::new()
        .name("native-update-ack-reader".into())
        .spawn(move || {
            use std::io::Read as _;
            let mut ack = [0; 1];
            let ready = std::io::stdin().read_exact(&mut ack).is_ok() && ack == *b"C";
            let _ = sender.send(ready);
        })?;
    std::thread::Builder::new()
        .name("native-update-startup-watch".into())
        .spawn(move || {
            if receiver.recv_timeout(std::time::Duration::from_secs(35)) != Ok(true) {
                eprintln!("hepta-native: update helper disappeared before startup acknowledgement");
                std::process::exit(1);
            }
        })?;
    Ok(())
}
