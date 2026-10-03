//! Provider terminal facts retained by the original credential-owning relay.
//! These are not Generator, Evaluator, Selector or Observer qualifications.

use std::fs::File;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

use super::super::Peer;
use super::super::store;
use super::ModelRelayPolicy;
use super::http;

const PURPOSE: &str = "Provide candidate or assessment text for this self-iteration role.";
const MAX_EVENT_BYTES: usize = 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootModelAssessmentBindingV1 {
    pub request_id: String,
    pub role: String,
    pub envelope_digest: String,
    pub candidate_digest: Option<String>,
    pub deadline_ms: u64,
    pub maximum_response_bytes: u32,
}

impl RootModelAssessmentBindingV1 {
    fn parse(text: &str, now: u64) -> anyhow::Result<Option<Self>> {
        if !text.starts_with(PURPOSE) {
            return Ok(None);
        }
        let (_, rest) = text
            .split_once("\nBinding: ")
            .context("native assessment binding missing")?;
        let (binding, _) = rest
            .split_once("\nInput:\n")
            .context("native assessment input missing")?;
        anyhow::ensure!(
            binding.len() <= 1024,
            "native assessment binding byte bound"
        );
        let (
            domain,
            request_id,
            role,
            envelope_digest,
            candidate_digest,
            deadline_ms,
            maximum_response_bytes,
        ): (String, String, String, String, Option<String>, u64, u32) =
            serde_json::from_str(binding)?;
        anyhow::ensure!(
            domain == "hepta.self-iteration.model-assessment.v1"
                && matches!(
                    role.as_str(),
                    "Generator" | "Evaluator" | "Selector" | "Observer"
                )
                && !envelope_digest.parse::<Digest32>()?.is_zero()
                && deadline_ms > now
                && deadline_ms <= now.saturating_add(3_600_000)
                && (1..=65_536).contains(&maximum_response_bytes),
            "native assessment purpose, policy or budget invalid"
        );
        StableId::new(request_id.clone())?;
        if let Some(digest) = &candidate_digest {
            anyhow::ensure!(
                !digest.parse::<Digest32>()?.is_zero(),
                "candidate digest absent"
            );
        } else {
            anyhow::ensure!(role == "Generator", "assessment candidate binding absent");
        }
        Ok(Some(Self {
            request_id,
            role,
            envelope_digest,
            candidate_digest,
            deadline_ms,
            maximum_response_bytes,
        }))
    }
}

/// A write-once, Root-custodied observation of a real successful Responses
/// stream. Its native journal digest must still be checked by the original
/// native owner; this receipt does not manufacture that digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootModelTerminalReceiptV1 {
    pub schema: String,
    pub binding: RootModelAssessmentBindingV1,
    pub subject: String,
    pub pid: u32,
    pub start_ticks: u64,
    pub cgroup: String,
    pub executable_sha256: String,
    pub request_sha256: [u8; 32],
    pub scope_sha256: [u8; 32],
    pub payload_sha256: [u8; 32],
    pub model: String,
    pub admitted_at_ms: u64,
    pub completed_at_ms: u64,
    pub response_id: String,
    pub stream_sha256: [u8; 32],
    pub model_output_sha256: [u8; 32],
    pub model_output_bytes: usize,
}

pub(super) struct Observation {
    directory: PathBuf,
    identity: String,
    fact: RootModelTerminalReceiptV1,
    stream: Sha256,
    pending: Vec<u8>,
    completed: Option<(String, String)>,
}

fn create_fact(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let parent = path.parent().context("terminal fact has no parent")?;
    store::protected_directory(parent)?;
    let temporary = parent.join(format!(".model-fact-{}", uuid::Uuid::new_v4()));
    let mut file = File::options()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&temporary)?;
    let result = (|| -> anyhow::Result<()> {
        file.write_all(bytes)?;
        file.sync_all()?;
        // Publish complete durable bytes without replacing any old intent or
        // terminal. Protected readers reject the temporary two-link state.
        std::fs::hard_link(&temporary, path)?;
        std::fs::remove_file(&temporary)?;
        File::open(parent)?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        // Only this call's unpublished temporary is removable. A published
        // outcome remains reserved even if directory fsync failed.
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

impl Observation {
    pub(super) fn reserve(
        policy: &ModelRelayPolicy,
        request: &http::Request,
        peer: &Peer,
        binding: &FinalUseBinding,
        now: u64,
    ) -> anyhow::Result<Option<Self>> {
        let Some(directory) = &policy.terminal_receipt_directory else {
            return Ok(None);
        };
        let object = http::body_object(&request.body, &request.headers)?;
        let mut observed = None;
        for item in object
            .get("input")
            .and_then(Value::as_array)
            .context("native input absent")?
        {
            if item.get("role").and_then(Value::as_str) != Some("user") {
                continue;
            }
            for content in item
                .get("content")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let Some(text) = content.get("text").and_then(Value::as_str) else {
                    continue;
                };
                if let Some(value) = RootModelAssessmentBindingV1::parse(text, now)? {
                    anyhow::ensure!(observed.is_none(), "ambiguous native assessment bindings");
                    observed = Some(value);
                }
            }
        }
        let Some(native) = observed else {
            return Ok(None);
        };
        let identity = Digest32::of_bytes(&serde_json::to_vec(&(
            "hepta.root-model-terminal.identity.v1",
            &peer.subject,
            &native.request_id,
        ))?)
        .to_string();
        let fact = RootModelTerminalReceiptV1 {
            schema: "hepta.root-model-terminal.v1".to_string(),
            binding: native,
            subject: peer.subject.clone(),
            pid: peer.pid,
            start_ticks: peer.start_ticks,
            cgroup: peer.cgroup.clone(),
            executable_sha256: peer.executable_sha256.clone(),
            request_sha256: binding.request_sha256,
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
            model: request.model.clone(),
            admitted_at_ms: now,
            completed_at_ms: 0,
            response_id: String::new(),
            stream_sha256: [0; 32],
            model_output_sha256: [0; 32],
            model_output_bytes: 0,
        };
        // Preserve the original dispatch intent before polling provider I/O.
        // Existing, partial or terminal intent never authorizes redispatch.
        create_fact(
            &directory.join(format!("{identity}.intent.json")),
            &serde_json::to_vec(&fact)?,
        )?;
        Ok(Some(Self {
            directory: directory.clone(),
            identity,
            fact,
            stream: Sha256::new(),
            pending: Vec::new(),
            completed: None,
        }))
    }

    pub(super) fn observe(&mut self, bytes: &[u8]) -> anyhow::Result<()> {
        self.stream.update(bytes);
        for part in bytes.split_inclusive(|byte| *byte == b'\n') {
            anyhow::ensure!(
                self.pending.len() + part.len() <= MAX_EVENT_BYTES,
                "provider event byte bound"
            );
            self.pending.extend_from_slice(part);
            if self.pending.ends_with(b"\n\n") || self.pending.ends_with(b"\r\n\r\n") {
                self.event()?;
                self.pending.clear();
            }
        }
        Ok(())
    }

    fn event(&mut self) -> anyhow::Result<()> {
        let text = std::str::from_utf8(&self.pending)?;
        let data = text
            .lines()
            .filter_map(|line| line.strip_prefix("data:").map(str::trim_start))
            .collect::<Vec<_>>()
            .join("\n");
        if data.is_empty() || data == "[DONE]" {
            return Ok(());
        }
        let value: Value = serde_json::from_str(&data)?;
        match value.get("type").and_then(Value::as_str) {
            Some("response.failed" | "response.incomplete" | "error") => {
                anyhow::bail!("provider did not complete")
            }
            Some("response.completed") => {
                anyhow::ensure!(self.completed.is_none(), "duplicate provider terminal");
                let response = value
                    .get("response")
                    .context("provider terminal body absent")?;
                anyhow::ensure!(
                    response.get("status").and_then(Value::as_str) == Some("completed"),
                    "provider terminal status incomplete"
                );
                let id = response
                    .get("id")
                    .and_then(Value::as_str)
                    .context("provider terminal ID absent")?;
                anyhow::ensure!(
                    !id.is_empty() && id.len() <= 1024,
                    "provider terminal ID bound"
                );
                let mut output = String::new();
                for item in response
                    .get("output")
                    .and_then(Value::as_array)
                    .context("provider terminal output absent")?
                {
                    match item.get("type").and_then(Value::as_str) {
                        Some("reasoning") => {}
                        Some("message") => {
                            anyhow::ensure!(
                                item.get("role").and_then(Value::as_str) == Some("assistant"),
                                "provider terminal role changed"
                            );
                            for content in item
                                .get("content")
                                .and_then(Value::as_array)
                                .context("provider message content absent")?
                            {
                                anyhow::ensure!(
                                    content.get("type").and_then(Value::as_str)
                                        == Some("output_text"),
                                    "provider output is not assessment text"
                                );
                                output.push_str(
                                    content
                                        .get("text")
                                        .and_then(Value::as_str)
                                        .context("provider output text absent")?,
                                );
                                anyhow::ensure!(
                                    output.len()
                                        <= self.fact.binding.maximum_response_bytes as usize,
                                    "provider assessment byte bound"
                                );
                            }
                        }
                        _ => anyhow::bail!(
                            "provider tool or unknown output cannot qualify assessment"
                        ),
                    }
                }
                anyhow::ensure!(!output.is_empty(), "provider assessment is empty");
                self.completed = Some((id.to_owned(), output));
            }
            _ => {}
        }
        Ok(())
    }

    pub(super) fn finish(mut self, now: u64) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.pending.is_empty()
                && now >= self.fact.admitted_at_ms
                && now < self.fact.binding.deadline_ms,
            "provider terminal or preserved budget incomplete"
        );
        let (id, output) = self
            .completed
            .take()
            .context("provider completed receipt absent")?;
        self.fact.completed_at_ms = now;
        self.fact.response_id = id;
        self.fact.stream_sha256 = self.stream.finalize().into();
        self.fact.model_output_sha256 = Sha256::digest(output.as_bytes()).into();
        self.fact.model_output_bytes = output.len();
        create_fact(
            &self
                .directory
                .join(format!("{}.terminal.json", self.identity)),
            &serde_json::to_vec(&self.fact)?,
        )
    }
}

#[cfg(test)]
#[path = "local_model_relay_witness_tests.rs"]
mod tests;
