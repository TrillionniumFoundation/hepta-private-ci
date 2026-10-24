//! Private, append-only qualification artifacts. This is not a production
//! TaskFlow, credential store, inference owner, or recovery implementation.

use anyhow::Result;
use anyhow::anyhow;
use codex_api::EncodedRequestBodyObserver;
use codex_api::EncodedRequestTerminal;
use codex_hepta_agent_loop::Error as LoopError;
use codex_hepta_agent_loop::ModelRequest;
use codex_hepta_agent_loop::ResponsesContinuation;
use codex_hepta_agent_loop::ResponsesContinuationOwner;
use codex_hepta_agent_loop::TurnBinding;
use codex_hepta_agent_loop::response_items_evidence;
use codex_hepta_types::Digest32;
use futures::future::BoxFuture;
use serde_json::Value;
use serde_json::json;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;

#[derive(Debug)]
pub(crate) struct Evidence {
    directory: PathBuf,
}

impl Evidence {
    pub(crate) fn create(directory: &Path) -> Result<Arc<Self>> {
        if !directory.is_absolute() {
            return Err(anyhow!("qualification evidence directory must be absolute"));
        }
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        // A new directory is mandatory. Resuming or rerunning does not create
        // another physical provider attempt under this qualification identity.
        builder
            .create(directory)
            .map_err(|_| anyhow!("qualification evidence directory must be new"))?;
        let directory = directory.canonicalize()?;
        #[cfg(unix)]
        if let Some(parent) = directory.parent() {
            File::open(parent)?.sync_all()?;
        }
        Ok(Arc::new(Self { directory }))
    }

    pub(crate) fn directory(&self) -> &Path {
        &self.directory
    }

    pub(crate) fn record(&self, name: &str, value: &Value) -> Result<Digest32> {
        self.record_bytes(name, &serde_json::to_vec(value)?)
    }

    pub(crate) fn record_bytes(&self, name: &str, bytes: &[u8]) -> Result<Digest32> {
        if name.contains('/') || name.contains('\\') || name.starts_with('.') {
            return Err(anyhow!("invalid qualification artifact name"));
        }
        let path = self.directory.join(name);
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&path) {
            Ok(mut file) => {
                file.write_all(bytes)?;
                file.sync_all()?;
                #[cfg(unix)]
                File::open(&self.directory)?.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if std::fs::read(&path)? != bytes {
                    return Err(anyhow!(
                        "qualification artifact conflicts with original evidence"
                    ));
                }
                // A previous attempt may have written matching bytes before
                // an fsync error. Exact bytes alone are not a durable ACK.
                OpenOptions::new()
                    .read(true)
                    .write(true)
                    .open(&path)?
                    .sync_all()?;
                #[cfg(unix)]
                File::open(&self.directory)?.sync_all()?;
            }
            Err(error) => return Err(error.into()),
        }
        Ok(Digest32::of_bytes(bytes))
    }
}

#[derive(Debug)]
pub(crate) struct ExactBodyObserver {
    pub(crate) evidence: Arc<Evidence>,
    pub(crate) expected_body_digest: Digest32,
    observed_body: AtomicBool,
    terminal_recorded: AtomicBool,
    terminal_notify: Notify,
}

impl ExactBodyObserver {
    pub(crate) fn new(evidence: Arc<Evidence>, expected_body_digest: Digest32) -> Self {
        Self {
            evidence,
            expected_body_digest,
            observed_body: AtomicBool::new(false),
            terminal_recorded: AtomicBool::new(false),
            terminal_notify: Notify::new(),
        }
    }

    pub(crate) async fn terminal_recorded(&self) {
        loop {
            let notified = self.terminal_notify.notified();
            if self.terminal_recorded.load(Ordering::Acquire) {
                return;
            }
            notified.await;
        }
    }
}

impl EncodedRequestBodyObserver for ExactBodyObserver {
    fn observe_encoded_body<'a>(
        &'a self,
        body: &'a [u8],
    ) -> BoxFuture<'a, std::result::Result<(), String>> {
        Box::pin(async move {
            if Digest32::of_bytes(body) != self.expected_body_digest {
                return Err("qualification_exact_body_mismatch".into());
            }
            if self.observed_body.swap(true, Ordering::AcqRel) {
                return Err("qualification_body_already_observed".into());
            }
            self.evidence
                .record_bytes("encoded-request.json", body)
                .map_err(|_| "qualification_body_evidence_failed".to_string())?;
            Ok(())
        })
    }

    fn observe_terminal<'a>(
        &'a self,
        terminal: EncodedRequestTerminal,
    ) -> BoxFuture<'a, std::result::Result<(), String>> {
        Box::pin(async move {
            let terminal = match terminal {
                EncodedRequestTerminal::Completed { response_id } => {
                    json!({"kind":"completed", "response_id": response_id})
                }
                EncodedRequestTerminal::Rejected { reason_code } => {
                    json!({"kind":"rejected", "reason_code":reason_code})
                }
                EncodedRequestTerminal::Indeterminate { reason_code } => {
                    json!({"kind":"indeterminate", "reason_code":reason_code})
                }
                EncodedRequestTerminal::Abandoned { reason_code } => {
                    json!({"kind":"abandoned", "reason_code":reason_code})
                }
            };
            self.evidence
                .record("encoded-terminal.json", &terminal)
                .map_err(|_| "qualification_terminal_evidence_failed".to_string())?;
            self.terminal_recorded.store(true, Ordering::Release);
            self.terminal_notify.notify_waiters();
            Ok(())
        })
    }
}

pub(crate) struct ContinuationEvidence {
    pub(crate) evidence: Arc<Evidence>,
    pub(crate) binding: TurnBinding,
    pub(crate) request: ModelRequest,
    pub(crate) retained: Arc<Mutex<Option<Value>>>,
}

impl ResponsesContinuationOwner for ContinuationEvidence {
    async fn retain(
        &mut self,
        binding: &TurnBinding,
        request: &ModelRequest,
        continuation: ResponsesContinuation,
    ) -> codex_hepta_agent_loop::Result<Digest32> {
        if binding != &self.binding || request != &self.request {
            return Err(LoopError::Contract("qualification continuation identity"));
        }
        let items = response_items_evidence(&continuation.items)?;
        let value = json!({
            "schema":"hepta-native-qualification-continuation:v1",
            "run_id":binding.run_id.as_str(), "turn_id":binding.turn_id.as_str(),
            "request_id":request.request_id.as_str(), "admission_digest":binding.admission_digest.to_string(),
            "context_digest":request.context_digest.to_string(),
            "provider_response_id":continuation.provider_response_id,
            "server_model":continuation.server_model,
            "items":items, "usage":continuation.usage,
            "provider_rollout_budget_units":continuation.provider_rollout_budget_units,
            "end_turn":continuation.end_turn,
        });
        // Actual usage and every provider item are retained even when a later
        // reservation or expected-output check rejects this qualification.
        let receipt = self
            .evidence
            .record("provider-continuation.json", &value)
            .map_err(|_| {
                LoopError::Owner("qualification continuation persistence failed".into())
            })?;
        *self
            .retained
            .lock()
            .map_err(|_| LoopError::Owner("qualification observation lock".into()))? = Some(value);
        Ok(receipt)
    }
}

#[cfg(test)]
#[path = "evidence_tests.rs"]
mod tests;
