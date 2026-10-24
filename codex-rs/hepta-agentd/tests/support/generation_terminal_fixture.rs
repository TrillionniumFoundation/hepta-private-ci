//! Explicit local fixture keys and old, raw-output-bound research observations.
//! Key/controller separation here tests the owner contract; it is not external
//! organizational independence, production authentication or fresh evaluation.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde_json::Value;

pub(super) fn id(value: &str) -> Result<StableId> {
    Ok(StableId::new(value)?)
}

pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Record {
    pub policy: String,
    pub row_payload_json: String,
    pub row_receipt_sha256: String,
    pub source_row_sha256: String,
    pub value_q32: i64,
    pub caption: String,
    pub png: Vec<u8>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Fixture {
    pub schema: String,
    pub scope: String,
    pub authority: String,
    pub source_usage: String,
    pub source_root: PathBuf,
    pub source_commit: String,
    pub source_bundle_sha256: String,
    pub source_pins: BTreeMap<String, String>,
    pub selection: Value,
    pub protocol_json: String,
    pub summary_json: String,
    pub state_json: String,
    pub state_sha256: String,
    pub objective_sha256: String,
    pub metric_sha256: String,
    pub metric_json: String,
    pub policy_ids: Vec<String>,
    pub selected_propensity_q32: u64,
    pub behavior: String,
    pub records: Vec<Record>,
}

impl Fixture {
    pub fn load(path: &Path, expected: Digest32) -> Result<Self> {
        let raw = std::fs::read(path)?;
        ensure!(
            raw.len() <= 1024 * 1024,
            "fixture exceeds the bounded import profile"
        );
        ensure!(
            Digest32::of_bytes(&raw) == expected,
            "independently supplied fixture pin differs"
        );
        let fixture: Self = serde_json::from_slice(&raw)?;
        ensure!(fixture.schema == "hepta.ndu-v6.local-terminal-owner-fixture.v2");
        ensure!(fixture.scope == "local_research_replay" && fixture.authority == "deny_all");
        ensure!(
            fixture.source_usage.contains("Previously observed")
                && fixture.source_usage.contains("engineering fixture")
                && fixture
                    .source_usage
                    .contains("not new scientific data or production certification")
        );
        ensure!(fixture.behavior.contains("not a randomized 1/7"));
        ensure!(
            fixture.source_commit.len() == 40
                && fixture.source_commit.bytes().all(|b| b.is_ascii_hexdigit())
        );
        ensure!(fixture.selected_propensity_q32 == 1_u64 << 32);
        ensure!(
            fixture
                .selection
                .as_object()
                .context("selection object")?
                .len()
                == 5
        );
        for key in ["seed", "training", "split", "case_id", "budget"] {
            ensure!(
                !fixture.selection[key].is_null(),
                "missing selected-state field"
            );
        }
        ensure!(digest(&fixture.state_json).to_string() == fixture.state_sha256);
        ensure!(digest(&fixture.metric_json).to_string() == fixture.metric_sha256);
        ensure!(
            digest(&format!(
                "{{\"metric\":{},\"requirements\":3}}",
                fixture.metric_json
            ))
            .to_string()
                == fixture.objective_sha256
        );
        ensure!(fixture.policy_ids.len() == 7 && fixture.records.len() == 7);
        let policies = fixture.policy_ids.iter().collect::<BTreeSet<_>>();
        ensure!(policies.len() == 7 && fixture.policy_ids.windows(2).all(|p| p[0] < p[1]));
        ensure!(
            fixture
                .records
                .iter()
                .map(|r| &r.policy)
                .collect::<BTreeSet<_>>()
                == policies
        );
        ensure!(
            fixture
                .records
                .iter()
                .map(|r| &r.row_receipt_sha256)
                .collect::<BTreeSet<_>>()
                .len()
                == 7
        );
        fixture.verify_sources()?;
        for record in &fixture.records {
            fixture.verify_record(record)?;
        }
        Ok(fixture)
    }

    pub fn verify_sources(&self) -> Result<()> {
        ensure!(self.source_root.is_absolute() && self.source_pins.len() == 21);
        // Do not open any outcome artifact of an unfinished run.
        let status_bytes = std::fs::read(self.source_root.join("status.json"))?;
        ensure!(
            Digest32::of_bytes(&status_bytes).to_string()
                == *self.source_pins.get("status.json").context("status pin")?
        );
        let status: Value = serde_json::from_slice(&status_bytes)?;
        ensure!(status["state"] == "completed");
        let expected_rows = status["rows"].as_u64().context("completed row count")?;
        ensure!(expected_rows >= 7);
        let root = self.source_root.canonicalize()?;
        for (relative, expected) in &self.source_pins {
            ensure!(
                Path::new(relative)
                    .components()
                    .all(|p| matches!(p, Component::Normal(_)))
            );
            let path = self.source_root.join(relative);
            let metadata = std::fs::symlink_metadata(&path)?;
            ensure!(metadata.is_file() && !metadata.file_type().is_symlink());
            ensure!(metadata.len() <= 64 * 1024 * 1024 && path.canonicalize()?.starts_with(&root));
            ensure!(
                Digest32::of_bytes(&std::fs::read(path)?).to_string() == *expected,
                "old source bytes changed: {relative}"
            );
        }
        let protocol: Value =
            serde_json::from_slice(&std::fs::read(self.source_root.join("protocol.json"))?)?;
        ensure!(protocol == serde_json::from_str::<Value>(&self.protocol_json)?);
        let canonical_protocol_digest = digest(&self.protocol_json).to_string();
        let summary: Value =
            serde_json::from_slice(&std::fs::read(self.source_root.join("summary.json"))?)?;
        ensure!(summary == serde_json::from_str::<Value>(&self.summary_json)?);
        ensure!(status["summary_sha256"] == digest(&self.summary_json).to_string());
        ensure!(
            summary["protocol_sha256"] == canonical_protocol_digest
                && summary["rows"].as_u64() == Some(expected_rows)
        );
        let state: Value = serde_json::from_str(&self.state_json)?;
        ensure!(state["source_protocol_sha256"] == canonical_protocol_digest);
        ensure!(
            protocol["source"]["git_commit"] == self.source_commit
                && protocol["source"]["bundle_sha256"] == self.source_bundle_sha256
                && protocol["metric_sha256"] == self.metric_sha256
        );
        // Membership is checked against the full independently pinned old log,
        // rather than accepting any caller-authored nonzero support digest.
        let source = std::fs::read_to_string(self.source_root.join("rows.jsonl"))?;
        let wanted = self
            .records
            .iter()
            .map(|r| (r.source_row_sha256.clone(), r))
            .collect::<BTreeMap<_, _>>();
        let mut found = BTreeSet::new();
        for line in source.lines() {
            if let Some(record) = wanted.get(&digest(line).to_string()) {
                let mut row: Value = serde_json::from_str(line)?;
                let receipt = row
                    .as_object_mut()
                    .context("source row object")?
                    .remove("receipt_sha256")
                    .context("source receipt")?;
                ensure!(receipt == record.row_receipt_sha256);
                ensure!(row == serde_json::from_str::<Value>(&record.row_payload_json)?);
                ensure!(
                    found.insert(record.policy.clone()),
                    "duplicate old source record"
                );
            }
        }
        ensure!(source.lines().count() as u64 == expected_rows && found.len() == 7);
        Ok(())
    }

    pub fn verify_record(&self, record: &Record) -> Result<()> {
        ensure!(digest(&record.row_payload_json).to_string() == record.row_receipt_sha256);
        let row: Value = serde_json::from_str(&record.row_payload_json)?;
        let state: Value = serde_json::from_str(&self.state_json)?;
        for (name, value) in self.selection.as_object().context("selection")? {
            ensure!(&row[name] == value, "row leaves the declared fixed state");
        }
        for name in [
            "snapshot_sha256",
            "forecast_sha256",
            "observer_sha256",
            "reward_observer_sha256",
            "source_ids",
            "corruption",
        ] {
            ensure!(row[name] == state[name], "heterogeneous state field {name}");
        }
        ensure!(row["policy"] == record.policy);
        ensure!(
            Digest32::of_bytes(&record.png).to_string()
                == row["output_hashes"]["image"]
                    .as_str()
                    .context("image hash")?
        );
        ensure!(
            digest(&record.caption).to_string()
                == row["output_hashes"]["text"]
                    .as_str()
                    .context("caption hash")?
        );
        ensure!(record.png.len() >= 26 && &record.png[..8] == b"\x89PNG\r\n\x1a\n");
        ensure!(&record.png[12..26] == b"IHDR\0\0\0\x38\0\0\0\x1c\x08\0");
        ensure!(record.caption.len() <= 4096);
        let metric: Value = serde_json::from_str(&self.metric_json)?;
        let weights = metric["weights"].as_object().context("metric weights")?;
        let mut joint = 0.0;
        for (name, weight) in weights {
            let observed = row["metrics"][name].as_f64().context("observed scalar")?;
            ensure!(observed.is_finite() && (0.0..=1.0).contains(&observed));
            joint += weight.as_f64().context("metric weight")? * observed;
        }
        let recorded = row["metrics"]["joint_loss"]
            .as_f64()
            .context("recorded loss")?;
        let utility = row["metrics"]["utility"]
            .as_f64()
            .context("recorded utility")?;
        ensure!((joint - recorded).abs() < 1e-12 && (1.0 - 2.0 * joint - utility).abs() < 1e-12);
        ensure!((-1.0..=1.0).contains(&utility));
        ensure!((utility * 4294967296.0).round_ties_even() as i64 == record.value_q32);
        Ok(())
    }
}

pub(super) struct LocalTrust {
    objective: Digest32,
    scope: Digest32,
    now: u64,
    keys: [SigningKey; 3],
    principals: [AuthenticatedPrincipalV1; 3],
}

const ROLES: [LearningEvidenceRoleV1; 3] = [
    LearningEvidenceRoleV1::Generator,
    LearningEvidenceRoleV1::Observer,
    LearningEvidenceRoleV1::Evaluator,
];

impl LocalTrust {
    pub fn new(objective: Digest32, scope: Digest32, now: u64) -> Result<Self> {
        let keys = [101, 102, 103].map(|seed| SigningKey::from_bytes(&[seed; 32]));
        let principal = |index: usize| -> Result<AuthenticatedPrincipalV1> {
            let name = format!("local-research-fixture-role-{index}");
            Ok(AuthenticatedPrincipalV1 {
                principal_id: id(&name)?,
                credential_chain_digest: digest(&format!("fixture-credential:{name}:{scope}")),
                signing_key_digest: Digest32::of_bytes(&keys[index].verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 1,
                authenticated_at: now,
                expires_at: now + 3600,
            })
        };
        let principals = [principal(0)?, principal(1)?, principal(2)?];
        Ok(Self {
            objective,
            scope,
            now,
            keys,
            principals,
        })
    }

    pub fn principal(&self, index: usize) -> AuthenticatedPrincipalV1 {
        self.principals[index].clone()
    }

    pub fn activated(&self) -> Result<ActivatedLearningTrustV1> {
        let root_key = SigningKey::from_bytes(&[104; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("local-research-fixture-root")?,
            scope_digest: self.scope,
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: self.now,
            expires_at: self.now + 3600,
            revoked_at: None,
        };
        let signers = (0..3)
            .map(|index| {
                Ok(TrustedLearningSignerV1 {
                    principal: self.principals[index].clone(),
                    controller_id: id(&format!("local-fixture-controller-{index}"))?,
                    verifying_key: self.keys[index].verifying_key().to_bytes(),
                    roles: vec![ROLES[index]],
                    revoked_at: None,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("local-research-fixture-distribution")?,
                generation: 1,
                effective_at: self.now,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: self.scope,
                    objective_digest: self.objective,
                    authority_epoch: 1,
                    signers,
                },
            },
            root_id: root.root_id.clone(),
            issued_at: self.now,
            expires_at: self.now + 3600,
            signature: [0; 64],
        };
        distribution.signature = root_key.sign(&distribution.signing_bytes()?).to_bytes();
        Ok(activate_learning_trust(
            &root,
            distribution,
            /*previous*/ None,
            self.now,
        )?)
    }

    pub fn sign(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        index: usize,
        payload: &[u8],
    ) -> Result<SignedLearningEvidenceV1> {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!(
                "fixture-evidence:{index}:{}",
                Digest32::of_bytes(payload)
            ))?,
            principal_id: self.principals[index].principal_id.clone(),
            role: ROLES[index],
            trust_digest: verifier.trust_digest(),
            scope_digest: self.scope,
            objective_digest: self.objective,
            authority_epoch: 1,
            issued_at: self.now,
            expires_at: self.now + 3600,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        Ok(evidence)
    }

    pub fn writer(&self, directory: &Path, binding: Digest32) -> Result<LedgerWriter> {
        let create = |name: &str| -> Result<File> {
            Ok(File::options()
                .read(true)
                .write(true)
                .create_new(true)
                .open(directory.join(name))?)
        };
        let ledger =
            DurableLedger::create(create("ledger.bin")?, binding, /*max_records*/ 64)?;
        let witness = LedgerWitnessStore::create(create("witness.bin")?, binding)?;
        let containing = File::open(directory)?;
        Ok(LedgerWriter::from_durable(
            ledger,
            witness,
            self.activated()?,
            &containing,
            &containing,
        )?)
    }
}
