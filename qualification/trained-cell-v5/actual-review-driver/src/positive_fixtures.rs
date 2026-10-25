//! Synthetic mechanics only. These inputs cannot pass the CLI's frozen-profile
//! report validator and are never scientific acceptance evidence.

use super::*;
use codex_hepta_neuron::TrainedCellHeadV5;
use codex_hepta_neuron::TrainedCellModeV5;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub struct Fixture {
    pub root: PathBuf,
    pub protocol: Value,
    pub inputs: Inputs,
    pub gate: Value,
    pub replay: PathBuf,
    pub statistics: PathBuf,
    pub conversion: PathBuf,
    pub parity: PathBuf,
    pub output: PathBuf,
    pub signing_key: SigningKey,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

pub fn must<T, E: std::fmt::Debug>(result: std::result::Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}
fn write(path: &Path, value: &Value) -> Result<Digest32> {
    let bytes = serde_json::to_vec_pretty(value)?;
    fs::write(path, &bytes)?;
    Ok(Digest32::of_bytes(&bytes))
}

impl Fixture {
    pub fn new() -> Result<Self> {
        static NEXT: AtomicU64 = AtomicU64::new(1);
        let root = std::env::temp_dir().join(format!(
            "hepta-v5-external-review-unit-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root)?;
        let parity = root.join("parity");
        fs::create_dir(&parity)?;
        let signing_key = SigningKey::from_bytes(&[201; 32]);
        let protocol = json!({"scope":"SYNTHETIC UNIT FIXTURE; not an allowed CLI protocol", "native_research_review":{
            "reviewer_id":"test-independent-reviewer","ed25519_public_key_hex":owner::hex(&signing_key.verifying_key().to_bytes()),
            "authority_epoch":1,"scope":"local-research-only","signed_proposal_validity_seconds":900,"required_audits":["independent_replay","independent_statistics"]}});
        let protocol_digest = Digest32::of_bytes(&serde_json::to_vec(&protocol)?);
        let report_digest = owner::digest("SYNTHETIC test report; no measured science");
        let mut payloads = Vec::new();
        let mut versions = Vec::new();
        let mut expected = Vec::new();
        for (index, name) in ["predecessor", "candidate"].iter().enumerate() {
            let generation = Generation::new(index as u64 + 1)?;
            let bias = (index + 1) as f64 * 0.125;
            let mut heads = Vec::new();
            let mut metadata = Vec::new();
            let mut cases = Vec::new();
            for task in report::TASKS {
                for mode in ["linear", "gated"] {
                    for seed in report::SEEDS {
                        let cell = format!("{task}-{mode}-seed{seed}");
                        let state = owner::digest(&format!("synthetic state {index}/{cell}"));
                        let feature = owner::digest("synthetic features");
                        heads.push(TrainedCellHeadV5::new(
                            owner::id(&cell)?,
                            state,
                            feature,
                            [[0.0; 4]; 8],
                            [bias; 4],
                            if mode == "linear" {
                                TrainedCellModeV5::Linear
                            } else {
                                TrainedCellModeV5::Gated {
                                    a: [0.0; 8],
                                    g: [0.0; 8],
                                }
                            },
                        )?);
                        metadata.push(json!({"cell_id":cell,"task":task,"head":mode,"seed":seed,"training_state_sha256":state.to_string(),"feature_identity_sha256":feature.to_string()}));
                        cases.push(json!({"cell_id":cell,"task":task,"rows":1,"offset_bytes":expected.len()}));
                        for number in [bias, bias, bias, bias, 0.25, 0.25, 0.25, 0.25] {
                            expected.extend_from_slice(&number.to_be_bytes());
                        }
                    }
                }
            }
            let bundle = TrainedCellBundleV5::new(
                owner::id(if index == 0 {
                    "all12-typed-warmup-v5"
                } else {
                    "all12-typed-candidate-v5"
                })?,
                generation,
                owner::digest("synthetic encoder"),
                vec![0.0; 384 * 8],
                heads,
            )?;
            let binding = bundle.input_binding();
            let bytes = bundle.encode();
            fs::write(parity.join(format!("{name}.bin")), &bytes)?;
            versions.push(json!({"name":name,"artifact_id":bundle.artifact_id().as_str(),"generation":generation.get(),"heads":metadata,"cases":cases,
                "payload_sha256":bundle.content_digest().to_string(),"source_bundle_sha256":owner::digest(&format!("synthetic {name} archive")).to_string(),
                "encoder_sha256":binding.encoder_digest.to_string(),"projection_sha256":binding.projection_digest.to_string(),"normalization_sha256":binding.normalization_digest.to_string()}));
            payloads.push(bytes);
        }
        let raw = vec![0_u8; 2 * 384 * 8];
        fs::write(parity.join("vectors.bin"), &raw)?;
        fs::write(parity.join("expected.bin"), &expected)?;
        let conversion = parity.join("manifest.json");
        let conversion_digest = write(
            &conversion,
            &json!({"schema":"hepta.trained-cell-parity-input.v5","scope":"synthetic-unit-fixture",
            "authority":"DENY_ALL","production_authority":false,"scientific_acceptance":false,"absolute_tolerance":1e-12,
            "protocol_sha256":protocol_digest.to_string(),"compatibility_sha256":trained_cell_compatibility_digest_v5().to_string(),
            "versions":versions,"tasks":[{"task":"agnews","rows":1,"offset_bytes":0},{"task":"dbpedia","rows":1,"offset_bytes":384*8}],
            "vectors_sha256":Digest32::of_bytes(&raw).to_string(),"expected_sha256":Digest32::of_bytes(&expected).to_string()}),
        )?;
        let replay = root.join("replay.json");
        let statistics = root.join("statistics.json");
        let mut audit_digests = Vec::new();
        for (path, kind) in [
            (&replay, "independent_replay"),
            (&statistics, "independent_statistics"),
        ] {
            audit_digests.push(write(path,&json!({"schema":"hepta.independent-research-audit.v1","kind":kind,"protocol_sha256":protocol_digest.to_string(),
                "report_sha256":report_digest.to_string(),"source_candidate_bundle_sha256":owner::digest("synthetic candidate archive").to_string(),
                "all_checks_passed":true,"findings":"SYNTHETIC unit fixture only; not a real audit","production_authority":false}))?);
        }
        let gate = json!({"independent_replay_sha256":audit_digests[0].to_string(),"independent_statistics_sha256":audit_digests[1].to_string(),
            "conversion_manifest_sha256":conversion_digest.to_string(),"source_candidate_bundle_sha256":owner::digest("synthetic candidate archive").to_string()});
        let comparison = |name: &str, threshold: f64| ScientificComparisonPolicyV1 {
            comparison_digest: owner::digest(name),
            maximum_upper_bound: threshold,
            minimum_observations: 3,
        };
        let policy = ScientificCandidatePolicyV1 {
            protocol_digest,
            candidate_definition_digest: owner::digest("synthetic candidate definition"),
            task: comparison("synthetic task", -0.001),
            retention: comparison("synthetic retention", 0.0),
            total_cost: comparison("synthetic cost", 3.0),
        };
        let measurement = |p: &ScientificComparisonPolicyV1, upper: f64, lower: f64| {
            ScientificMeasurementStatusV1::Measured(ScientificMeasurementV1 {
                comparison_digest: p.comparison_digest,
                evidence_digest: report_digest,
                observations: 3,
                lower_bound: lower,
                estimate: upper,
                upper_bound: upper,
            })
        };
        let measurements = [
            measurement(&policy.task, -0.01, -1.0),
            measurement(&policy.retention, -0.005, -1.0),
            measurement(&policy.total_cost, 1.0, 0.0),
        ];
        let inputs = Inputs {
            policy,
            measurements,
            aggregate: json!("SYNTHETIC passing fixture measurements"),
            report_digest,
            gate_digest: Digest32::of_bytes(&serde_json::to_vec(&gate)?),
            predecessor: payloads.remove(0),
            candidate: payloads.remove(0),
            code_digest: owner::digest("synthetic code"),
            runtime_digest: owner::digest("synthetic runtime"),
            dataset_digest: owner::digest("synthetic source dataset"),
            all_numeric_gates_pass: true,
        };
        Ok(Self {
            output: root.join("prepared"),
            root,
            protocol,
            inputs,
            gate,
            replay,
            statistics,
            conversion,
            parity,
            signing_key,
        })
    }
    pub fn paths(&self) -> [&Path; 4] {
        [
            &self.replay,
            &self.statistics,
            &self.conversion,
            &self.parity,
        ]
    }
    pub fn prepare(&self) -> Result<Value> {
        run(
            "prepare",
            &self.protocol,
            &self.inputs,
            &self.gate,
            self.paths(),
            &self.output,
            None,
        )
    }
    pub fn signature(&self, key: &SigningKey) -> Result<PathBuf> {
        let bytes = read(&self.output.join("proposal.json"))?;
        let value: Value = serde_json::from_slice(&bytes)?;
        let signature = key
            .sign(&unhex(string(&value, "review_signing_bytes_hex")?)?)
            .to_bytes();
        let path = self.root.join("signature.json");
        write(
            &path,
            &json!({"proposal_sha256":Digest32::of_bytes(&bytes).to_string(),"signature_hex":owner::hex(&signature)}),
        )?;
        Ok(path)
    }
}
