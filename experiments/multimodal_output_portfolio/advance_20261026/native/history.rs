//! Hash-chained, fsync'd public lifecycle state. No hidden target is serialized.
use crate::stream_io::Result;
use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use std::{
    collections::HashSet,
    fs::{File, OpenOptions},
    io::Write,
    path::Path,
};

pub struct History {
    file: File,
    pub events: usize,
    pub last: Digest32,
    pub native_sequence: u64,
    pub monotonic_micros: u64,
    pub modulator: Digest32,
    pub utility_q32: i64,
    pub requests: HashSet<String>,
    pub pending: Option<(String, String, usize)>,
    pub episode: Option<String>,
    pub prefix: Option<String>,
    pub late_label: Option<usize>,
    pub completed: bool,
    pub outcomes: usize,
    pub last_outcome: Option<String>,
}
impl History {
    pub fn open(path: &Path, resume: bool) -> Result<Self> {
        let bytes = if resume {
            std::fs::read(path)?
        } else {
            Vec::new()
        };
        if !bytes.is_empty() && bytes.last() != Some(&b'\n') {
            return Err("Incomplete controller event; reconcile explicitly".into());
        }
        let file = OpenOptions::new()
            .append(true)
            .create_new(!resume)
            .open(path)?;
        let mut h = Self {
            file,
            events: 0,
            last: Digest32::ZERO,
            native_sequence: 0,
            monotonic_micros: 0,
            modulator: Digest32::ZERO,
            utility_q32: 0,
            requests: HashSet::new(),
            pending: None,
            episode: None,
            prefix: None,
            late_label: None,
            completed: true,
            outcomes: 0,
            last_outcome: None,
        };
        for line in bytes.split(|b| *b == b'\n').filter(|s| !s.is_empty()) {
            let row: Value = serde_json::from_slice(line)?;
            let e = &row["event"];
            let d = h.digest(e)?;
            if row["previous"] != h.last.to_string()
                || row["sequence"].as_u64() != Some(h.events as u64 + 1)
                || row["digest"] != d.to_string()
            {
                return Err("Controller chain mismatch".into());
            }
            h.apply(e, d)?;
        }
        Ok(h)
    }
    fn digest(&self, event: &Value) -> Result<Digest32> {
        let mut bytes = b"hepta.advance.semantic-owner-event.v1".to_vec();
        bytes.extend_from_slice(self.last.as_array());
        bytes.extend(serde_json::to_vec(event)?);
        Ok(Digest32::of_bytes(&bytes))
    }
    pub fn append(&mut self, event: Value) -> Result<Digest32> {
        let d = self.digest(&event)?;
        writeln!(
            self.file,
            "{}",
            json!({"sequence":self.events+1,"previous":self.last.to_string(),"event":event,"digest":d.to_string()})
        )?;
        self.file.sync_all()?;
        self.apply(&event, d)?;
        Ok(d)
    }
    fn apply(&mut self, e: &Value, d: Digest32) -> Result<()> {
        self.native_sequence = e["native_sequence"]
            .as_u64()
            .ok_or("Missing native frontier")?;
        self.monotonic_micros = e["monotonic_micros"].as_u64().ok_or("Missing clock")?;
        self.modulator = e["modulator"]
            .as_str()
            .ok_or("Missing NDU identity")?
            .parse()?;
        self.utility_q32 = e["utility_q32"]
            .as_i64()
            .ok_or("Missing actual numeric context")?;
        match e["kind"].as_str().ok_or("Missing event kind")? {
            "bootstrap" => {}
            "decision" => {
                let r = e["request_id"]
                    .as_str()
                    .ok_or("Missing request")?
                    .to_string();
                if !self.requests.insert(r.clone()) {
                    return Err("Duplicate request".into());
                }
                if e["initial"] == true {
                    self.episode = Some(
                        e["episode_id"]
                            .as_str()
                            .ok_or("Missing episode")?
                            .to_string(),
                    );
                    self.prefix = Some(
                        e["prefix_digest"]
                            .as_str()
                            .ok_or("Missing prefix")?
                            .to_string(),
                    );
                    self.late_label = None;
                }
                self.pending = e["selected_action"]
                    .as_u64()
                    .map(|a| (r, d.to_string(), a as usize));
                self.completed = self.pending.is_none();
            }
            "outcome" => {
                self.pending = None;
                self.outcomes += 1;
                self.last_outcome = Some(d.to_string());
                self.late_label = e["external_audio_label"].as_u64().map(|x| x as usize);
                self.completed = e["completed"].as_bool().ok_or("Missing completion flag")?;
            }
            "cancel" => {
                self.pending = None;
                self.completed = true;
            }
            _ => return Err("Unknown public lifecycle event".into()),
        }
        self.events += 1;
        self.last = d;
        Ok(())
    }
}
