use std::path::Path;
use std::process::Command;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::Sha256Digest;

use crate::runtime::NativeError;
use crate::runtime::OperationRecord;
use crate::runtime::OperationStatus;
use crate::runtime::PlatformAction;
use crate::runtime::PlatformActionKind;
use crate::runtime::PlatformEffectPort;
use crate::runtime::PlatformObservation;
use crate::runtime::PlatformRequest;

pub struct SecurePlatformAdapter {
    authority: Option<FinalUseAuthority>,
}

impl SecurePlatformAdapter {
    pub fn new(authority: Option<FinalUseAuthority>) -> Self {
        Self { authority }
    }

    pub fn authority_configured(&self) -> bool {
        self.authority.is_some()
    }

    fn expected_binding(request: &PlatformRequest) -> Result<FinalUseBinding, NativeError> {
        let payload = request.action.payload_digest()?;
        let payload_sha256 = digest_bytes(&payload)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.ui.native.platform-request.v1",
            &request.session,
            &request.operation_id,
            request.displayed_revision,
            &request.action,
        ))
        .map_err(|error| NativeError::Platform(format!("encode final-use request: {error}")))?;
        let scope_bytes = serde_json::to_vec(&(
            request.action.kind().as_str(),
            request.action.resource_label(),
        ))
        .map_err(|error| NativeError::Platform(format!("encode final-use scope: {error}")))?;
        Ok(FinalUseBinding {
            subject_id: request.operation_id.clone(),
            destination_id: format!("ui.native/{}", request.action.kind()),
            request_sha256: digest_array(&request_bytes),
            scope_sha256: digest_array(&scope_bytes),
            payload_sha256,
        })
    }

    fn invoke(&mut self, action: &PlatformAction) -> Result<PlatformObservation, NativeError> {
        match action {
            PlatformAction::OpenPath { path } => open_path(path, false),
            PlatformAction::RevealPath { path } => open_path(path, true),
            PlatformAction::CopyText { text } => {
                let mut clipboard = arboard::Clipboard::new()
                    .map_err(|error| NativeError::Platform(format!("open clipboard: {error}")))?;
                clipboard
                    .set_text(text.clone())
                    .map_err(|error| NativeError::Platform(format!("write clipboard: {error}")))?;
                terminal_success("clipboard write accepted")
            }
            PlatformAction::Notify { title, body } => {
                notify_rust::Notification::new()
                    .summary(title)
                    .body(body)
                    .show()
                    .map_err(|error| {
                        NativeError::Platform(format!("desktop notification rejected: {error}"))
                    })?;
                terminal_success("desktop notification accepted")
            }
        }
    }
}

impl PlatformEffectPort for SecurePlatformAdapter {
    fn dispatch(&mut self, request: &PlatformRequest) -> Result<PlatformObservation, NativeError> {
        request.action.validate()?;
        let expected = Self::expected_binding(request)?;
        let Some(authority) = self.authority.clone() else {
            return PlatformObservation::terminal(
                OperationStatus::Rejected,
                Sha256Digest::for_bytes(b"final-use authority unavailable"),
                Some("final-use authority is not configured".to_string()),
            );
        };
        let token = match authority.claim(&request.grant, &expected) {
            Ok(token) => token,
            Err(error) => {
                return PlatformObservation::terminal(
                    OperationStatus::Rejected,
                    Sha256Digest::for_bytes(format!("authority:{error}").as_bytes()),
                    Some(format!("final-use grant rejected: {error}")),
                );
            }
        };
        authority
            .with_verified_use(token, &expected, || self.invoke(&request.action))
            .map_err(|error| {
                NativeError::Platform(format!("final-use authority changed before effect: {error}"))
            })?
    }

    fn reconcile(
        &mut self,
        record: &OperationRecord,
    ) -> Result<PlatformObservation, NativeError> {
        match record.action {
            PlatformActionKind::CopyText => {
                let mut clipboard = arboard::Clipboard::new()
                    .map_err(|error| NativeError::Platform(format!("open clipboard: {error}")))?;
                match clipboard.get_text() {
                    Ok(text) => {
                        let digest = Sha256Digest::for_bytes(
                            &serde_json::to_vec(&PlatformAction::CopyText { text }).map_err(
                                |error| {
                                    NativeError::Platform(format!(
                                        "encode clipboard reconciliation payload: {error}"
                                    ))
                                },
                            )?,
                        );
                        if digest == record.payload_digest {
                            PlatformObservation::terminal(
                                OperationStatus::Succeeded,
                                Sha256Digest::for_bytes(b"clipboard currently matches payload"),
                                Some(
                                    "current clipboard contents independently match the pending payload"
                                        .to_string(),
                                ),
                            )
                        } else {
                            Ok(PlatformObservation::indeterminate(
                                "clipboard no longer proves whether the prior write occurred",
                            ))
                        }
                    }
                    Err(error) => Ok(PlatformObservation::indeterminate(format!(
                        "clipboard cannot be observed for reconciliation: {error}"
                    ))),
                }
            }
            PlatformActionKind::OpenPath
            | PlatformActionKind::RevealPath
            | PlatformActionKind::Notify => Ok(PlatformObservation::indeterminate(
                "the operating system exposes no process-independent terminal receipt for this effect",
            )),
        }
    }
}

fn open_path(path: &Path, reveal: bool) -> Result<PlatformObservation, NativeError> {
    if !path.is_absolute() || !path.exists() {
        return PlatformObservation::terminal(
            OperationStatus::Failed,
            Sha256Digest::for_bytes(b"path missing or not absolute"),
            Some("path must exist and be absolute at adapter entry".to_string()),
        );
    }

    #[cfg(target_os = "macos")]
    let status = {
        let mut command = Command::new("/usr/bin/open");
        if reveal {
            command.arg("-R");
        }
        command.arg(path).status()
    };

    #[cfg(target_os = "linux")]
    let status = {
        let target = if reveal {
            path.parent().unwrap_or(path)
        } else {
            path
        };
        Command::new("xdg-open").arg(target).status()
    };

    #[cfg(target_os = "windows")]
    let status = {
        let mut command = Command::new("explorer.exe");
        if reveal {
            command.arg(format!("/select,{}", path.display()));
        } else {
            command.arg(path);
        }
        command.status()
    };

    #[cfg(not(any(target_os = "macos", target_os = "linux", target_os = "windows")))]
    let status: std::io::Result<std::process::ExitStatus> =
        Err(std::io::Error::new(std::io::ErrorKind::Unsupported, "unsupported OS"));

    match status {
        Ok(status) if status.success() => terminal_success(if reveal {
            "reveal handler exited successfully"
        } else {
            "open handler exited successfully"
        }),
        Ok(status) => PlatformObservation::terminal(
            OperationStatus::Failed,
            Sha256Digest::for_bytes(format!("platform exit:{status}").as_bytes()),
            Some(format!("platform handler failed: {status}")),
        ),
        Err(error) => PlatformObservation::terminal(
            OperationStatus::Failed,
            Sha256Digest::for_bytes(format!("platform spawn:{error}").as_bytes()),
            Some(format!("platform handler could not start: {error}")),
        ),
    }
}

fn terminal_success(detail: &str) -> Result<PlatformObservation, NativeError> {
    PlatformObservation::terminal(
        OperationStatus::Succeeded,
        Sha256Digest::for_bytes(detail.as_bytes()),
        Some(detail.to_string()),
    )
}

fn digest_array(bytes: &[u8]) -> [u8; 32] {
    use sha2::Digest;
    use sha2::Sha256;
    Sha256::digest(bytes).into()
}

fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], NativeError> {
    let raw = digest.as_str().as_bytes();
    let mut out = [0_u8; 32];
    for (index, pair) in raw.chunks_exact(2).enumerate() {
        let high = hex_value(pair[0]).ok_or_else(|| {
            NativeError::Platform("payload digest contains non-hex data".to_string())
        })?;
        let low = hex_value(pair[1]).ok_or_else(|| {
            NativeError::Platform("payload digest contains non-hex data".to_string())
        })?;
        out[index] = (high << 4) | low;
    }
    Ok(out)
}

fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        _ => None,
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use crate::runtime::SessionFence;

    fn unsigned_grant() -> SignedFinalUseGrant {
        SignedFinalUseGrant {
            grant: FinalUseGrant {
                schema_version: 1,
                signer_id: "issuer.1".to_string(),
                authority_epoch: 1,
                grant_id: "grant.1".to_string(),
                nonce: [1_u8; 32],
                binding: FinalUseBinding {
                    subject_id: "operation.1".to_string(),
                    destination_id: "ui.native/copy_text".to_string(),
                    request_sha256: [1_u8; 32],
                    scope_sha256: [2_u8; 32],
                    payload_sha256: [3_u8; 32],
                },
                not_before_unix_ms: 1,
                expires_at_unix_ms: 2,
            },
            signature: Vec::new(),
        }
    }

    #[test]
    fn missing_authority_rejects_before_platform_effect() -> Result<(), NativeError> {
        let mut adapter = SecurePlatformAdapter::new(None);
        let request = PlatformRequest {
            session: SessionFence {
                session_id: "session.1".to_string(),
                generation: 1,
            },
            operation_id: "operation.1".to_string(),
            displayed_revision: 1,
            action: PlatformAction::CopyText {
                text: "must-not-reach-clipboard".to_string(),
            },
            grant: unsigned_grant(),
        };
        let observation = adapter.dispatch(&request)?;
        assert_eq!(observation.status, OperationStatus::Rejected);
        assert!(observation.outcome_digest.is_some());
        Ok(())
    }
}
