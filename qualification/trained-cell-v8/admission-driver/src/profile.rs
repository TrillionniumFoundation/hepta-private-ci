//! The expected profile digest is host configuration, never candidate input.
//! Installing a profile is an explicit research trust decision, not a file scan.

use crate::Result;
use crate::ensure;
use crate::report::array;
use crate::report::hash;
use crate::report::number;
use crate::report::read;
use crate::report::string;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeSet;
use std::path::Path;

pub const TASKS: [&str; 2] = ["agnews", "dbpedia"];
pub const HEADS: [&str; 2] = ["linear", "gated"];
pub const SEEDS: [u64; 3] = [7, 17, 29];
pub const BINDINGS: [&str; 4] = [
    "training_code_sha256",
    "runtime_sha256",
    "source_dataset_sha256",
    "run_seal_sha256",
];

pub struct Profile {
    digest: Digest32,
    value: Value,
}

impl Profile {
    pub fn load(path: &Path, expected: Digest32) -> Result<Self> {
        let bytes = read(path)?;
        ensure(
            !expected.is_zero() && Digest32::of_bytes(&bytes) == expected,
            "profile differs from the externally installed host pin",
        )?;
        let value: Value = serde_json::from_slice(&bytes)?;
        ensure(
            value["schema"] == "hepta.host-pinned-native-profile.v1"
                && value["scope"] == "local-research-only"
                && value["study_scope"] == "fresh-independent-confirmation"
                && value["thresholds"]
                    == json!({"task_upper_strict":-0.001,
                "retention_upper_inclusive":0.0,"total_cpu_ratio_inclusive":3.0})
                && value["family"] == json!({"tasks":TASKS,"heads":HEADS,"seeds":SEEDS,"steps":32}),
            "unsupported profile, transport or scientific policy",
        )?;
        ensure(
            (value["controller_schema"] == "hepta.cell-field-controller.v7"
                && value["candidate_format"] == "hepta.training-handoff-bundle.v7")
                || (value["controller_schema"] == "hepta.cell-field-controller.v8"
                    && value["candidate_format"] == "hepta.training-handoff-bundle.v8"),
            "controller and payload version pair is unsupported",
        )?;
        if value["controller_schema"] == "hepta.cell-field-controller.v8" {
            hash(&value, "parity_header_sha256")?;
        }
        for field in BINDINGS
            .into_iter()
            .chain(["protocol_sha256", "controller_contracts_sha256"])
        {
            hash(&value, field)?;
        }
        for field in ["evaluation_schema", "candidate_policy", "conversion_scope"] {
            let text = string(&value, field)?;
            ensure(
                !text.is_empty() && text.len() <= 128,
                "bounded profile identity required",
            )?;
        }
        Ok(Self {
            digest: expected,
            value,
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }
    pub fn value(&self) -> &Value {
        &self.value
    }
    pub fn version(&self) -> u8 {
        if self.value["controller_schema"] == "hepta.cell-field-controller.v8" {
            8
        } else {
            7
        }
    }

    pub fn verify_protocol(&self, bytes: &[u8], protocol: &Value) -> Result<()> {
        ensure(
            Digest32::of_bytes(bytes) == hash(&self.value, "protocol_sha256")?,
            "protocol differs from the host profile",
        )?;
        let e = &protocol["evaluation"];
        let baselines = array(e, "primary_future_baselines")?;
        let policies = array(e, "policies")?;
        let required = array(e, "required_completed_policies")?;
        let candidate = string(e, "candidate")?;
        let names = |rows: &[Value]| -> Result<BTreeSet<String>> {
            rows.iter()
                .map(|v| {
                    v.as_str()
                        .filter(|s| !s.is_empty() && s.len() <= 128)
                        .map(str::to_owned)
                        .ok_or_else(|| "bounded policy identity required".into())
                })
                .collect()
        };
        let b = names(baselines)?;
        let all = names(policies)?;
        let mut need = b.clone();
        need.insert(candidate.to_owned());
        ensure(
            e["tasks"] == json!(TASKS)
                && e["heads"] == json!(HEADS)
                && e["seeds"] == json!(SEEDS)
                && e["splits"] == json!(["current", "future", "old"])
                && e["required_completed_steps"] == 32
                && e["family_size"] == 12
                && number(e, "improvement_margin")? == 0.001
                && number(e, "retention_margin")? == 0.0
                && number(e, "max_cpu_ratio")? == 3.0
                && candidate == string(&self.value, "candidate_policy")?
                && baselines.len() == 2
                && b.len() == 2
                && need.len() == 3
                && (3..=16).contains(&policies.len())
                && all.len() == policies.len()
                && !all.contains("warmup_old")
                && required.len() == 3
                && names(required)? == need
                && need.is_subset(&all),
            "frozen family, comparisons or completion policy differs",
        )?;
        let review = &protocol["native_research_review"];
        ensure(
            review == &self.value["native_research_review"]
                && review["scope"] == "local-research-only"
                && review["authority_epoch"] == 1
                && review["signed_proposal_validity_seconds"] == 900
                && review["required_audits"]
                    == json!(["independent_replay", "independent_statistics"]),
            "research reviewer differs from the installed trust root",
        )?;
        let key =
            hepta_handoff_recovery_v7::positive::unhex(string(review, "ed25519_public_key_hex")?)?;
        let key: [u8; 32] = key
            .try_into()
            .map_err(|_| "32-byte public reviewer key required")?;
        ed25519_dalek::VerifyingKey::from_bytes(&key)?;
        codex_hepta_types::StableId::new(string(review, "reviewer_id")?)?;
        Ok(())
    }

    pub fn verify_bindings(&self, value: &Value) -> Result<()> {
        ensure(
            hash(value, "native_profile_sha256")? == self.digest,
            "evidence names another installed profile",
        )?;
        for field in BINDINGS {
            ensure(
                hash(value, field)? == hash(&self.value, field)?,
                "run, source or dataset differs from the installed profile",
            )?;
        }
        Ok(())
    }
}

pub fn family() -> BTreeSet<String> {
    TASKS
        .iter()
        .flat_map(|task| {
            HEADS.iter().flat_map(move |head| {
                SEEDS
                    .iter()
                    .map(move |seed| format!("{task}-{head}-seed{seed}"))
            })
        })
        .collect()
}
