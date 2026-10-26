//! Development-only recovery composition; no V7 acceptance profile is installed.
#[path = "../../../trained-cell-v5/actual-review-driver/src/census.rs"]
pub mod census;
pub mod handoff_dump;
mod handoff_pair;
pub mod owner;
pub mod parity;
#[path = "../../../trained-cell-v5/actual-review-driver/src/payload.rs"]
pub mod payload;
pub mod positive;
mod positive_owner;
#[path = "../../../trained-cell-v5/actual-review-driver/src/report.rs"]
pub mod report;
#[path = "../../../trained-cell-v5/actual-review-driver/src/serve.rs"]
pub mod serve;
mod serve_handoff;
mod terminal_review;
use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_neuron::TrainedCellErrorV5;
use codex_hepta_neuron::TrainedCellInputBindingV5;
use codex_hepta_neuron::trained_cell_compatibility_digest_v5;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use owner::id;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.to_string().into())
    }
}
