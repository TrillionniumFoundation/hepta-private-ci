//! Previously observed records, with a reproducible public-input recipe.
//! The Audit witness is created now from old observed bytes, not backdated trust.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_intelligence_eval::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde_json::Value;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

pub(super) const BASELINE: &str = "fixed_dev_tuned";
pub(super) const CANDIDATE: &str = "risk_aware_recursive";
const TRAINING: &str = "terminal_entropic_ndu";
pub(super) fn id(s: &str) -> Result<StableId> {
    Ok(StableId::new(s)?)
}
pub(super) fn digest(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
fn string<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().context("string field")
}
fn pin(v: &Value, key: &str) -> Result<Digest32> {
    Ok(string(v, key)?.parse()?)
}
fn array<'a>(v: &'a Value, key: &str) -> Result<&'a Vec<Value>> {
    v[key].as_array().context("array field")
}
fn number(v: &Value, key: &str) -> Result<u64> {
    v[key].as_u64().context("integer field")
}
fn read_pinned(root: &Path, relative: &str, pins: &Value) -> Result<Vec<u8>> {
    ensure!(
        Path::new(relative)
            .components()
            .all(|c| matches!(c, Component::Normal(_)))
    );
    let path = root.join(relative);
    let metadata = std::fs::symlink_metadata(&path)?;
    ensure!(
        metadata.is_file()
            && !metadata.file_type().is_symlink()
            && metadata.len() <= 64 * 1024 * 1024
    );
    ensure!(path.canonicalize()?.starts_with(root.canonicalize()?));
    let raw = std::fs::read(path)?;
    ensure!(
        Digest32::of_bytes(&raw) == pin(pins, relative)?,
        "source file changed: {relative}"
    );
    Ok(raw)
}

pub(super) struct Fixture {
    raw: Value,
    pub protocol: Value,
    pub data: PairedDataV1,
    pub protocol_digest: Digest32,
    pub metric: Digest32,
    pub audit: Digest32,
    pub reward: Digest32,
    pub input_recipe_digest: Digest32,
}

impl Fixture {
    pub fn load(path: &Path, expected: Digest32, expected_rows: Digest32) -> Result<Self> {
        ensure!(std::fs::metadata(path)?.len() <= 8 * 1024 * 1024);
        let bytes = std::fs::read(path)?;
        ensure!(
            Digest32::of_bytes(&bytes) == expected,
            "independent fixture pin"
        );
        let raw: Value = serde_json::from_slice(&bytes)?;
        ensure!(
            pin(&raw, "expected_rows_sha256")? == expected_rows
                && pin(&raw["source_pins"], "rows.jsonl")? == expected_rows
        );
        ensure!(
            raw["schema"] == "hepta.ndu-v6.paired-owner-fixture.v1"
                && raw["authority"] == "deny_all"
        );
        ensure!(string(&raw, "source_usage")?.contains("posthoc engineering only"));
        ensure!(
            string(&raw, "observation_witness")?
                .contains("not a separately signed original observation")
        );
        ensure!(raw["family_alpha_ppm"] == 50_000 && raw["simultaneous_comparisons"] == 64);
        let protocol: Value = serde_json::from_str(string(&raw, "protocol_json")?)?;
        let protocol_digest = digest(string(&raw, "protocol_json")?);
        let metric = digest(string(&raw, "metric_json")?);
        ensure!(metric == pin(&protocol, "metric_sha256")?);
        ensure!(serde_json::from_str::<Value>(string(&raw, "metric_json")?)? == protocol["metric"]);
        let audit = pin(&raw["source_pins"], "audit-observer.pt")?;
        let reward = pin(&raw["source_pins"], "reward-observer.pt")?;
        ensure!(audit != reward);
        let input_recipe_digest = digest(string(&raw, "input_recipe_json")?);
        let budget = number(&raw["selection"], "budget")?;
        ensure!(raw["selection"]["training"] == TRAINING && raw["selection"]["split"] == "future");
        ensure!(
            raw["selection"]["baseline"] == BASELINE && raw["selection"]["candidate"] == CANDIDATE
        );
        ensure!(
            Some(budget)
                == array(&protocol, "budgets")?
                    .iter()
                    .filter_map(Value::as_u64)
                    .max()
        );
        let mut cases = Vec::new();
        for case in array(&raw, "cases")? {
            let sources = array(case, "source_ids")?;
            ensure!(sources.len() == 2);
            let source = |v: &Value| -> Result<Digest32> {
                let parts: Vec<_> = v.as_str().context("source ID")?.split(':').collect();
                ensure!(parts.len() == 4 && parts[0] == "mnist" && parts[1] == "test");
                parts[2].parse::<u64>()?;
                Ok(parts[3].parse()?)
            };
            let units = [source(&sources[0])?, source(&sources[1])?];
            let context = digest(&format!(
                "hepta.v6.public-recipe-case.v1:{input_recipe_digest}:{}:{}:{}:{}:{}",
                string(case, "case_id")?,
                number(case, "index")?,
                string(case, "corruption")?,
                units[0],
                units[1]
            ));
            cases.push(PairedSourceCaseV1 {
                case_id: id(string(case, "case_id")?)?,
                original_source_units: units,
                public_context_digest: context,
            });
        }
        let mut versions = Vec::new();
        for version in array(&raw, "versions")? {
            let seed = number(version, "seed")?;
            let model = pin(version, "snapshot_file_sha256")?;
            let forecast = pin(version, "forecast_file_sha256")?;
            let policy = |name| {
                digest(&format!(
                    "hepta.v6.frozen-policy.v1:{protocol_digest}:{seed}:{TRAINING}:{name}:{forecast}"
                ))
            };
            versions.push(PairedVersionV1 {
                seed,
                candidate_artifact: model,
                baseline_artifact: model,
                candidate_policy: policy(CANDIDATE),
                baseline_policy: policy(BASELINE),
            });
        }
        ensure!(budget <= i32::MAX as u64);
        let manifest = PairedManifestV1 {
            cases,
            versions,
            modeled_budget: FixedQ32::from_raw((budget as i64) << 32),
        };
        manifest.digests()?;
        let mut fixture = Self {
            raw,
            protocol,
            data: PairedDataV1 {
                manifest,
                observations: vec![],
            },
            protocol_digest,
            metric,
            audit,
            reward,
            input_recipe_digest,
        };
        fixture.verify_sources()?;
        fixture.data.observations = fixture.observations()?;
        fixture.data.canonical_digest()?;
        Ok(fixture)
    }

    pub fn verify_sources(&self) -> Result<()> {
        let root = PathBuf::from(string(&self.raw, "source_root")?);
        ensure!(root.is_absolute());
        let pins = &self.raw["source_pins"];
        let status: Value = serde_json::from_slice(&read_pinned(&root, "status.json", pins)?)?;
        ensure!(
            status["state"] == "completed",
            "do not release unfinished results"
        );
        let summary: Value = serde_json::from_slice(&read_pinned(&root, "summary.json", pins)?)?;
        ensure!(summary == serde_json::from_str::<Value>(string(&self.raw, "summary_json")?)?);
        ensure!(status["summary_sha256"] == digest(string(&self.raw, "summary_json")?).to_string());
        ensure!(
            summary["protocol_sha256"] == self.protocol_digest.to_string()
                && summary["rows"] == status["rows"]
        );
        ensure!(
            serde_json::from_slice::<Value>(&read_pinned(&root, "protocol.json", pins)?)?
                == self.protocol
        );
        ensure!(self.protocol["hard_output_modalities"] == serde_json::json!(["text", "image"]));
        ensure!(summary["observer_binding"]["audit_artifact_sha256"] == self.audit.to_string());
        ensure!(summary["observer_binding"]["reward_artifact_sha256"] == self.reward.to_string());
        for relative in pins.as_object().context("source pins")?.keys() {
            read_pinned(&root, relative, pins)?;
        }
        let recipe: Value = serde_json::from_str(string(&self.raw, "input_recipe_json")?)?;
        ensure!(recipe["source_commit"] == self.protocol["source"]["git_commit"]);
        ensure!(recipe["source_bundle_sha256"] == self.protocol["source"]["bundle_sha256"]);
        ensure!(
            recipe["dataset_manifest"] == self.protocol["dataset_manifest"]
                && recipe["runtime_environment"] == summary["environment"]
        );
        ensure!(
            recipe["source_split"] == "test"
                && recipe["batch_size"] == 1
                && recipe["pair_offset"] == "case.index"
        );
        ensure!(
            recipe["observation_rng_seed"] == "424242 + case.index"
                && recipe["generation_noise_seed"] == "training_seed * 10000 + case.index"
        );
        ensure!(
            recipe["entrypoint"]
                == "run.case_batch(corpus, 'future', case.index, case.corruption).observation"
        );
        let recipe_sources = array(&self.raw, "recipe_sources")?;
        ensure!(recipe_sources.len() == 2);
        for (source, name) in recipe_sources.iter().zip(["data.py", "run.py"]) {
            let path = format!("experiments/multimodal_output_portfolio/v6/{name}");
            ensure!(
                source["path"] == path
                    && source["sha256"] == self.protocol["source"]["files"][&path]
            );
            ensure!(
                digest(string(source, "text")?) == pin(source, "sha256")?
                    && recipe["generator_sources"][&path] == source["sha256"]
            );
        }
        let cache = PathBuf::from(string(&self.raw, "cache_root")?);
        ensure!(
            cache.is_absolute()
                && self.raw["cache_pins"]
                    .as_object()
                    .context("cache pins")?
                    .len()
                    == 4
        );
        for file in array(&self.protocol["dataset_manifest"], "source_files")? {
            let name = string(file, "name")?;
            ensure!(self.raw["cache_pins"][name] == file["sha256"]);
            read_pinned(&cache, name, &self.raw["cache_pins"])?;
        }
        let mut cases = array(&self.protocol["cases"], "future")?.clone();
        cases.sort_by(|a, b| a["case_id"].as_str().cmp(&b["case_id"].as_str()));
        ensure!(self.raw["cases"] == Value::Array(cases));
        let seed_set: BTreeSet<_> = self.data.manifest.versions.iter().map(|v| v.seed).collect();
        ensure!(
            seed_set
                == array(&self.protocol, "seeds")?
                    .iter()
                    .map(|v| v.as_u64().context("seed"))
                    .collect::<Result<BTreeSet<_>>>()?
        );
        for v in array(&self.raw, "versions")? {
            let seed = number(v, "seed")?;
            let label = format!("seed-{seed}-{TRAINING}");
            for (field, suffix) in [
                ("snapshot_file_sha256", ".pt"),
                ("forecast_file_sha256", "-forecast.pt"),
            ] {
                ensure!(
                    v[field] == pins[format!("{label}{suffix}")]
                        && v[field] == summary["checkpoint_files"][&label][field]
                );
            }
        }
        let records = array(&self.raw, "records")?;
        let wanted = records
            .iter()
            .map(|r| Ok((string(r, "source_row_sha256")?.to_owned(), r)))
            .collect::<Result<BTreeMap<_, _>>>()?;
        ensure!(wanted.len() == records.len());
        let mut expected = BTreeSet::new();
        for seed in array(&self.protocol, "seeds")? {
            for training in array(&self.protocol, "trainings")? {
                for budget in array(&self.protocol, "budgets")? {
                    for policy in array(&self.protocol, "policies")? {
                        for (split, cases) in self.protocol["cases"].as_object().context("cases")? {
                            for case in cases.as_array().context("case list")? {
                                expected.insert(format!(
                                    "{seed}|{training}|{budget}|{policy}|{split}|{}",
                                    case["case_id"]
                                ));
                            }
                        }
                    }
                }
            }
        }
        ensure!(expected.len() as u64 == number(&status, "rows")?);
        let bytes = read_pinned(&root, "rows.jsonl", pins)?;
        let text = std::str::from_utf8(&bytes)?;
        let mut seen = BTreeSet::new();
        let mut found = BTreeSet::new();
        for line in text.lines() {
            let mut row: Value = serde_json::from_str(line)?;
            let key = format!(
                "{}|{}|{}|{}|{}|{}",
                row["seed"],
                row["training"],
                row["budget"],
                row["policy"],
                string(&row, "split")?,
                row["case_id"]
            );
            ensure!(
                expected.contains(&key) && seen.insert(key),
                "foreign or duplicated source execution"
            );
            if let Some(record) = wanted.get(&digest(line).to_string()) {
                ensure!(found.insert(string(record, "source_row_sha256")?.to_owned()));
                let receipt = row
                    .as_object_mut()
                    .context("row")?
                    .remove("receipt_sha256")
                    .context("receipt")?;
                ensure!(receipt == record["row_receipt_sha256"]);
                ensure!(row == serde_json::from_str::<Value>(string(record, "row_payload_json")?)?);
            }
        }
        ensure!(
            seen == expected && found.len() == records.len(),
            "incomplete actual census"
        );
        Ok(())
    }

    fn observations(&self) -> Result<Vec<PairedObservationV1>> {
        let root = PathBuf::from(string(&self.raw, "source_root")?);
        let mut observations = Vec::new();
        let records = array(&self.raw, "records")?;
        ensure!(
            records.len() == self.data.manifest.cases.len() * self.data.manifest.versions.len() * 2
        );
        for (i, record) in records.iter().enumerate() {
            let case_index = i / (2 * self.data.manifest.versions.len());
            let case = &self.data.manifest.cases[case_index];
            let declared_case = &self.raw["cases"][case_index];
            let version = &self.data.manifest.versions[(i / 2) % self.data.manifest.versions.len()];
            let candidate = i % 2 == 1;
            let row: Value = serde_json::from_str(string(record, "row_payload_json")?)?;
            let execution = digest(string(record, "row_payload_json")?);
            ensure!(execution == pin(record, "row_receipt_sha256")?);
            ensure!(row["case_id"] == case.case_id.as_str() && row["seed"] == version.seed);
            ensure!(
                row["training"] == TRAINING
                    && row["split"] == "future"
                    && row["budget"] == self.raw["selection"]["budget"]
            );
            ensure!(row["policy"] == if candidate { CANDIDATE } else { BASELINE });
            ensure!(
                row["source_ids"] == declared_case["source_ids"]
                    && row["corruption"] == declared_case["corruption"]
            );
            ensure!(pin(&row, "snapshot_file_sha256")? == version.candidate_artifact);
            ensure!(
                row["forecast_file_sha256"]
                    == self.raw["versions"][(i / 2) % self.data.manifest.versions.len()]["forecast_file_sha256"]
            );
            ensure!(
                pin(&row, "observer_sha256")? == self.audit
                    && pin(&row, "reward_observer_sha256")? == self.reward
            );
            if candidate {
                let previous: Value =
                    serde_json::from_str(string(&records[i - 1], "row_payload_json")?)?;
                for name in ["snapshot_sha256", "forecast_sha256", "initial_content_plan"] {
                    ensure!(row[name] == previous[name]);
                }
            }
            let mut outputs = [Digest32::ZERO; 2];
            for (slot, modality) in ["text", "image"].iter().enumerate() {
                let path = string(&row["output_paths"], modality)?;
                let bytes = read_pinned(&root, path, &self.raw["source_pins"])?;
                outputs[slot] = Digest32::of_bytes(&bytes);
                ensure!(outputs[slot] == pin(&row["output_hashes"], modality)?);
                let contract = &row["joint_output_contract"]["slots"][slot];
                ensure!(
                    contract["modality"] == *modality
                        && contract["status"] == "complete"
                        && contract["output_sha256"] == outputs[slot].to_string()
                );
                if *modality == "image" {
                    ensure!(
                        bytes.len() >= 26
                            && &bytes[..8] == b"\x89PNG\r\n\x1a\n"
                            && &bytes[12..26] == b"IHDR\0\0\0\x38\0\0\0\x1c\x08\0"
                    );
                } else {
                    ensure!(bytes.len() <= 4096);
                    std::str::from_utf8(&bytes)?;
                }
            }
            ensure!(row["joint_output_contract"]["required_mask"] == 3);
            let metrics = &row["metrics"];
            let mut loss = 0.0;
            for (field, weight) in self.protocol["metric"]["weights"]
                .as_object()
                .context("weights")?
            {
                let value = metrics[field].as_f64().context("observed metric")?;
                ensure!(value.is_finite() && (0.0..=1.0).contains(&value));
                loss += value * weight.as_f64().context("weight")?;
            }
            let observed_loss = metrics["joint_loss"].as_f64().context("loss")?;
            ensure!((0.0..=1.0).contains(&observed_loss) && (loss - observed_loss).abs() < 1e-12);
            ensure!(
                (1.0 - 2.0 * loss - metrics["utility"].as_f64().context("utility")?).abs() < 1e-12
            );
            let loss_raw = (observed_loss * 4294967296.0).round_ties_even() as i64;
            ensure!(record["loss_q32"].as_i64() == Some(loss_raw));
            let factual = metrics["caption_valid"] == true
                && [
                    "text_fact",
                    "image_fact",
                    "relation",
                    "crossmodal_disagreement",
                ]
                .iter()
                .all(|k| metrics[*k].as_f64() == Some(0.0));
            // This is a new witness over the old, already-scored combined row.
            let observed = digest(&format!(
                "hepta.v6.posthoc-audit-witness.v1:{execution}:{}",
                self.audit
            ));
            observations.push(PairedObservationV1 {
                case_id: case.case_id.clone(),
                seed: version.seed,
                arm: if candidate {
                    PairedArmV1::Candidate
                } else {
                    PairedArmV1::Baseline
                },
                public_context_digest: case.public_context_digest,
                model_artifact: version.candidate_artifact,
                policy_digest: if candidate {
                    version.candidate_policy
                } else {
                    version.baseline_policy
                },
                modeled_budget: self.data.manifest.modeled_budget,
                actual_execution_receipt: execution,
                actual_observation_receipt: observed,
                observer_artifact: self.audit,
                metric_digest: self.metric,
                completed_modalities: 3,
                output_digests: outputs,
                joint_loss: FixedQ32::from_raw(loss_raw),
                joint_factual_success: factual,
            });
        }
        Ok(observations)
    }
}
