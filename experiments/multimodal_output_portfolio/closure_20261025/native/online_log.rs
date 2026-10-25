//! Durable controller history; incomplete cross-store commits fail closed.
use std::collections::HashSet;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::Path;

use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use crate::stream_io::Result;

pub struct History {
    file: File,
    pub events: usize,
    pub last: Digest32,
    pub native_sequence: u64,
    pub monotonic_micros: u64,
    pub modulator: Digest32,
    pub requests: HashSet<String>,
    pub pending: Option<(String, String, String)>,
    pub outcomes: usize,
}

impl History {
    pub fn open(path: &Path, resume: bool) -> Result<Self> {
        let bytes = if resume { std::fs::read(path)? } else { Vec::new() };
        if !bytes.is_empty() && bytes.last() != Some(&b'\n') {
            return Err("Incomplete controller history; reconciliation required".into());
        }
        let file = OpenOptions::new().append(true).create_new(!resume).open(path)?;
        let mut history = Self { file, events: 0, last: Digest32::ZERO,
            native_sequence: 0, monotonic_micros: 0, modulator: Digest32::ZERO, requests: HashSet::new(),
            pending: None, outcomes: 0 };
        for line in bytes.split(|b| *b == b'\n').filter(|s| !s.is_empty()) {
            let record: Value = serde_json::from_slice(line)?;
            let event = &record["event"];
            let digest = history.digest(event)?;
            if record["previous"] != history.last.to_string()
                || record["sequence"].as_u64() != Some(history.events as u64 + 1)
                || record["digest"] != digest.to_string()
            {
                return Err("Controller history digest or sequence mismatch".into());
            }
            history.apply(event, digest)?;
        }
        Ok(history)
    }

    fn digest(&self, event: &Value) -> Result<Digest32> {
        let mut bytes = b"hepta.closure.online-event.v1".to_vec();
        bytes.extend_from_slice(self.last.as_array());
        bytes.extend_from_slice(&serde_json::to_vec(event)?);
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn append(&mut self, event: Value) -> Result<Digest32> {
        let digest = self.digest(&event)?;
        let record = json!({"sequence": self.events + 1, "previous": self.last.to_string(),
            "event": event, "digest": digest.to_string()});
        writeln!(self.file, "{record}")?;
        self.file.sync_all()?;
        self.apply(&event, digest)?;
        Ok(digest)
    }

    fn apply(&mut self, event: &Value, digest: Digest32) -> Result<()> {
        self.native_sequence = event["native_sequence"].as_u64().ok_or("Missing native sequence")?;
        self.monotonic_micros = event["monotonic_micros"].as_u64().ok_or("Missing monotonic clock")?;
        self.modulator = event["modulator"].as_str().ok_or("Missing NDU binding")?.parse()?;
        match event["kind"].as_str().ok_or("Missing history event kind")? {
            "bootstrap" => {}
            "decision" => {
                let request = event["request_id"].as_str().ok_or("Missing request identity")?.to_string();
                if !self.requests.insert(request.clone()) { return Err("Duplicate committed request".into()); }
                self.pending = event["selected_action"].as_str().map(|action|
                    (request, digest.to_string(), action.to_string()));
            }
            "outcome" => { self.pending = None; self.outcomes += 1; }
            "cancel" => { self.pending = None; }
            _ => return Err("Unknown committed event kind".into()),
        }
        self.events += 1;
        self.last = digest;
        Ok(())
    }
}
