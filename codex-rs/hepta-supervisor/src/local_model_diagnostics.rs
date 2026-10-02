//! Fixed diagnostics for the bounded issuer exchange. Caller-controlled text,
//! error displays and authority material never enter the diagnostic message.

use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy)]
#[repr(u8)]
pub(super) enum Stage {
    PeerCapture,
    ReadLength,
    RequestBound,
    ReadBody,
    Decode,
    ResourceObservation,
    TrustLoad,
    TrustMutation,
    GrantHead,
    GrantBinding,
    PeerRecheck,
    Encode,
    WriteLength,
    WriteBody,
    Flush,
}

pub(super) struct Progress(AtomicU8);

impl Progress {
    pub(super) fn new() -> Self {
        Self(AtomicU8::new(Stage::PeerCapture as u8))
    }

    pub(super) fn enter(&self, stage: Stage) {
        self.0.store(stage as u8, Ordering::Relaxed);
    }

    pub(super) fn diagnostic(
        &self,
        outcome: Result<anyhow::Result<()>, tokio::time::error::Elapsed>,
    ) -> Option<String> {
        let category = match outcome {
            Ok(Ok(())) => return None,
            Ok(Err(error)) => category(&error),
            Err(_) => "timeout",
        };
        let stage = match self.0.load(Ordering::Relaxed) {
            x if x == Stage::PeerCapture as u8 => "peer-capture",
            x if x == Stage::ReadLength as u8 => "request-length-read",
            x if x == Stage::RequestBound as u8 => "request-bound",
            x if x == Stage::ReadBody as u8 => "request-body-read",
            x if x == Stage::Decode as u8 => "request-decode",
            x if x == Stage::ResourceObservation as u8 => "resource-observation",
            x if x == Stage::TrustLoad as u8 => "trust-load",
            x if x == Stage::TrustMutation as u8 => "trust-mutation",
            x if x == Stage::GrantHead as u8 => "grant-head",
            x if x == Stage::GrantBinding as u8 => "grant-binding",
            x if x == Stage::PeerRecheck as u8 => "peer-recheck",
            x if x == Stage::Encode as u8 => "response-encode",
            x if x == Stage::WriteLength as u8 => "response-length-write",
            x if x == Stage::WriteBody as u8 => "response-body-write",
            x if x == Stage::Flush as u8 => "response-flush",
            _ => "exchange",
        };
        Some(format!(
            "ordinary model issuer rejection stage={stage} category={category}"
        ))
    }
}

fn category(error: &anyhow::Error) -> &'static str {
    for cause in error.chain() {
        if let Some(io) = cause.downcast_ref::<std::io::Error>() {
            return match io.kind() {
                std::io::ErrorKind::PermissionDenied => "permission-denied",
                std::io::ErrorKind::NotFound => "not-found",
                std::io::ErrorKind::UnexpectedEof => "unexpected-eof",
                std::io::ErrorKind::TimedOut => "io-timeout",
                std::io::ErrorKind::ConnectionReset => "connection-reset",
                std::io::ErrorKind::BrokenPipe => "broken-pipe",
                std::io::ErrorKind::WouldBlock => "would-block",
                std::io::ErrorKind::InvalidData => "invalid-data",
                _ => "io",
            };
        }
        if let Some(json) = cause.downcast_ref::<serde_json::Error>() {
            return match json.classify() {
                serde_json::error::Category::Io => "json-io",
                serde_json::error::Category::Syntax => "json-syntax",
                serde_json::error::Category::Data => "json-data",
                serde_json::error::Category::Eof => "json-eof",
            };
        }
    }
    "policy-or-state"
}

#[cfg(test)]
#[path = "local_model_diagnostics_tests.rs"]
mod tests;
