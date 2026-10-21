//! Research composition of the existing durable ledger and native tabular fit.
use super::*;
use codex_hepta_learning_ledger as ledger;
use serde_json::Value;
use serde_json::json;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::process::Child;
use std::process::ChildStdin;
use std::process::ChildStdout;
use std::process::Command;
use std::process::Stdio;

pub(super) fn micros() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_micros()
        .try_into()
        .unwrap()
}
pub(super) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|x| format!("{x:02x}")).collect()
}
fn unhex(value: &str) -> Vec<u8> {
    assert!(value.len().is_multiple_of(2));
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|x| u8::from_str_radix(std::str::from_utf8(x).unwrap(), 16).unwrap())
        .collect()
}
pub(super) fn save(path: &std::path::Path, value: &Value) {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    serde_json::to_writer(&mut file, value).unwrap();
    file.write_all(b"\n").unwrap();
    file.sync_all().unwrap();
    File::open(path.parent().unwrap())
        .unwrap()
        .sync_all()
        .unwrap();
}

pub(super) struct Role {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    pub key: [u8; 32],
    pub pid: u32,
    pub name: String,
}
impl Role {
    pub fn start(script: &std::path::Path, root: &std::path::Path, name: &str) -> Self {
        let python =
            std::env::var("HEPTA_LEARNING_STUDY_PYTHON").unwrap_or_else(|_| "python3".into());
        let mut child = Command::new(python)
            .arg(script)
            .arg(name)
            .arg(root.join(name))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let input = child.stdin.take().unwrap();
        let output = BufReader::new(child.stdout.take().unwrap());
        let mut result = Self {
            child,
            input,
            output,
            key: [0; 32],
            pid: 0,
            name: name.into(),
        };
        let hello = result.call(json!({"command":"hello"}));
        result.key = unhex(hello["public_key"].as_str().unwrap())
            .try_into()
            .unwrap();
        result.pid = hello["pid"].as_u64().unwrap().try_into().unwrap();
        result
    }
    pub fn call(&mut self, value: Value) -> Value {
        serde_json::to_writer(&mut self.input, &value).unwrap();
        self.input.write_all(b"\n").unwrap();
        self.input.flush().unwrap();
        let mut line = String::new();
        assert!(
            std::io::Read::take(&mut self.output, 8 * 1024 * 1024 + 1)
                .read_line(&mut line)
                .unwrap()
                > 0,
            "role process exited"
        );
        assert!(line.len() <= 8 * 1024 * 1024);
        serde_json::from_str::<Value>(&line).unwrap()["result"].clone()
    }
    pub fn sign(&mut self, bytes: &[u8]) -> [u8; 64] {
        unhex(
            self.call(json!({"command":"sign", "payload":hex(bytes)}))["signature"]
                .as_str()
                .unwrap(),
        )
        .try_into()
        .unwrap()
    }
    pub fn close(mut self) -> Value {
        let receipt = self.call(json!({"command":"close"}));
        assert!(self.child.wait().unwrap().success());
        receipt
    }
}

impl Drop for Role {
    fn drop(&mut self) {
        // Failed native assertions must still reap their measurement children.
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
    }
}

pub(super) struct Roles {
    pub processes: Vec<Role>,
    pub principals: Vec<ledger::AuthenticatedPrincipalV1>,
    pub kinds: Vec<ledger::LearningEvidenceRoleV1>,
    pub trust: ledger::LearningEvidenceTrustV1,
    pub verifier: ledger::LearningEvidenceVerifierV1,
    pub from: u64,
    pub until: u64,
}
impl Roles {
    pub fn new(script: &std::path::Path, root: &std::path::Path) -> Self {
        let names = [
            "generator",
            "evaluator",
            "observer",
            "selector",
            "publisher",
            "trust-root",
            "future-custodian",
        ];
        let kinds = vec![
            ledger::LearningEvidenceRoleV1::Generator,
            ledger::LearningEvidenceRoleV1::Evaluator,
            ledger::LearningEvidenceRoleV1::Observer,
            ledger::LearningEvidenceRoleV1::Selector,
        ];
        let processes: Vec<_> = names
            .iter()
            .map(|name| Role::start(script, root, name))
            .collect();
        let from = micros();
        let until = from + 3_600_000_000;
        let principals: Vec<_> = (0..4)
            .map(|i| ledger::AuthenticatedPrincipalV1 {
                principal_id: id(names[i]),
                credential_chain_digest: hash(&format!(
                    "local-process-credential-{}",
                    processes[i].pid
                )),
                signing_key_digest: Digest32::of_bytes(&processes[i].key),
                scope_digest: hash("local-three-generation-scope"),
                authority_epoch: 1,
                authenticated_at: from,
                expires_at: until,
            })
            .collect();
        let trust = ledger::LearningEvidenceTrustV1 {
            scope_digest: hash("local-three-generation-scope"),
            objective_digest: hash("fresh-instance-arithmetic-instruction-retrieval"),
            authority_epoch: 1,
            signers: (0..4)
                .map(|i| ledger::TrustedLearningSignerV1 {
                    principal: principals[i].clone(),
                    controller_id: id(&format!("local-role-process-{}", processes[i].pid)),
                    verifying_key: processes[i].key,
                    roles: vec![kinds[i]],
                    revoked_at: None,
                })
                .collect(),
        };
        let verifier = ledger::LearningEvidenceVerifierV1::new(trust.clone()).unwrap();
        Self {
            processes,
            principals,
            kinds,
            trust,
            verifier,
            from,
            until,
        }
    }
    pub fn evidence(
        &mut self,
        index: usize,
        payload: &[u8],
        issued_at: u64,
    ) -> ledger::SignedLearningEvidenceV1 {
        let mut evidence = ledger::SignedLearningEvidenceV1 {
            evidence_id: id(&format!("{}-{issued_at}", self.processes[index].name)),
            principal_id: self.principals[index].principal_id.clone(),
            role: self.kinds[index],
            trust_digest: self.verifier.trust_digest(),
            scope_digest: self.trust.scope_digest,
            objective_digest: self.trust.objective_digest,
            authority_epoch: 1,
            issued_at,
            expires_at: self.until,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.processes[index].sign(&evidence.signing_bytes());
        evidence
    }
    pub fn writer(&mut self, root: &std::path::Path) -> ledger::LedgerWriter {
        std::fs::create_dir(root).unwrap();
        let root_key = self.processes[5].key;
        let root_trust = ledger::LearningTrustRootV1 {
            root_id: id("local-study-root"),
            scope_digest: self.trust.scope_digest,
            verifying_key: root_key,
            valid_from: self.from,
            expires_at: self.until,
            revoked_at: None,
        };
        let now = micros();
        let mut distribution = ledger::SignedLearningTrustDistributionV1 {
            distribution: ledger::LearningTrustDistributionV1 {
                distribution_id: id("local-study-distribution"),
                generation: 1,
                effective_at: now,
                trust: self.trust.clone(),
            },
            root_id: root_trust.root_id.clone(),
            issued_at: now,
            expires_at: self.until,
            signature: [0; 64],
        };
        distribution.signature = self.processes[5].sign(&distribution.signing_bytes().unwrap());
        let activated =
            ledger::activate_learning_trust(&root_trust, distribution, None, micros()).unwrap();
        let create = |name| {
            std::fs::OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(root.join(name))
                .unwrap()
        };
        let binding = hash("local-three-generation-ledger");
        let durable = ledger::DurableLedger::create(create("ledger"), binding, 4096).unwrap();
        let witness = ledger::LedgerWitnessStore::create(create("witness"), binding).unwrap();
        let directory = File::open(root).unwrap();
        ledger::LedgerWriter::from_durable(durable, witness, activated, &directory, &directory)
            .unwrap()
    }
}

pub(super) struct Fitted {
    pub artifact: codex_hepta_bellman_operator::TabularOperatorArtifactV1,
    pub dataset: ledger::DatasetSnapshotReceiptV3,
    pub snapshot: ledger::LedgerSnapshot,
    pub bytes: Vec<u8>,
    pub pin: TabularPayloadPinV1,
    pub temporal_training: Vec<codex_hepta_intelligence_eval::OutcomeTrainingSample>,
}

pub(super) fn fit(
    root: &std::path::Path,
    generation: u64,
    roles: &mut Roles,
    actions: &[(CognitiveContextItem, String)],
) -> Fitted {
    let observed =
        roles.processes[0].call(json!({"command":"training", "generation":generation.min(3)}));
    let mut writer = roles.writer(&root.join("training-owner"));
    let mut candidates: Vec<_> = actions
        .iter()
        .map(|(item, _)| cognitive_action_id(item).unwrap())
        .collect();
    candidates.push(id("abstain"));
    let mut samples = Vec::new();
    let mut temporal_training = Vec::new();
    let mut sensors = std::collections::BTreeSet::new();
    for (task_index, task) in observed["body"]["tasks"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let sensor = cognitive_sensor_id(task["query"].as_str().unwrap()).unwrap();
        sensors.insert(sensor.clone());
        for (action_index, (_, operation)) in actions.iter().enumerate() {
            let episode = format!("g{generation}-t{task_index}-a{action_index}");
            let support = Digest32::of_bytes(&serde_json::to_vec(task).unwrap());
            let decision = ledger::ProductionDecisionV2 {
                record_id: id(&format!("{episode}-decision")),
                episode_id: id(&episode),
                run_snapshot_digest: Digest32::of_bytes(sensor.as_str().as_bytes()),
                objective_digest: roles.trust.objective_digest,
                policy_digest: hash("complete-action-census"),
                candidate_ids: candidates.clone(),
                selected_candidate_id: candidates[action_index].clone(),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: ledger::CandidateSetCompletenessReceiptV1 {
                    set_id: id("complete-four-instruction-set"),
                    state_digest: support,
                    generator_id: id("generator"),
                    generator_code_digest: hash("custodian-arithmetic-v1"),
                    grammar_digest: hash("four-instructions"),
                    hard_filter_digest: hash("admitted-memory-only"),
                    truncation_digest: hash("no-truncation"),
                    candidates_digest: ledger::candidate_ids_digest_v2(&candidates),
                    candidate_count: candidates.len().try_into().unwrap(),
                    omitted_count_bound: 0,
                    canonical_order_digest: ledger::candidate_order_digest_v2(&candidates),
                    complete_for_generator: true,
                },
                support_digest: support,
            };
            let signed = roles.evidence(
                /*index*/ 0,
                &ledger::decision_signing_payload_v2(&decision).unwrap(),
                micros(),
            );
            let head = writer.witness_frontier().unwrap().anchor.chain_digest;
            let decision_receipt = writer
                .append_decision(head, decision, &signed, micros())
                .unwrap();
            let a = task["a"].as_i64().unwrap();
            let b = task["b"].as_i64().unwrap();
            let actual = match operation.as_str() {
                "add" => a + b,
                "multiply" => a * b,
                "xor" => a ^ b,
                "subtract" => a - b,
                _ => panic!("unknown action"),
            };
            let observed = roles.processes[2]
                .call(json!({"command":"observe", "task":task, "operation":operation}));
            assert_eq!(observed["body"]["actual"].as_i64().unwrap(), actual);
            let value = if observed["body"]["correct"].as_bool().unwrap() {
                FixedQ32::ONE
            } else {
                FixedQ32::ZERO
            };
            let at = micros();
            let outcome = ledger::AuthenticatedOutcomeV1 {
                record_id: id(&format!("{episode}-outcome")),
                outcome_id: id(&format!("{episode}-result")),
                episode_id: id(&episode),
                observer: roles.principals[2].clone(),
                observed_at: Some(at),
                value: Some(value),
                unit_profile_digest: hash("exact-answer-0-or-1"),
                support_digest: support,
                watermark: ledger::OutcomeWatermarkV1 {
                    latest_observable_at: at,
                    expected_delay_profile_digest: hash("synchronous-local-arithmetic"),
                    terminality: ledger::OutcomeTerminalityV1::Terminal,
                    censoring_reason: None,
                    correction_predecessor: None,
                    finalized_at: Some(at),
                },
            };
            let signed = roles.evidence(
                /*index*/ 2,
                &ledger::outcome_signing_payload_v2(&outcome),
                micros(),
            );
            let receipt = writer
                .append_outcome(decision_receipt.chain_digest, outcome, &signed, micros())
                .unwrap();
            temporal_training.push(codex_hepta_intelligence_eval::OutcomeTrainingSample {
                decision_id: id(&format!("{episode}-decision")),
                principal_lineage: id("generator-training"),
                episode_lineage: id(&episode),
                window_id: id(&format!("generation-{generation}-training")),
                action_id: super::temporal::action(task["query"].as_str().unwrap(), operation),
                outcome: value,
                observed_at: at,
                evidence_digest: receipt.event_digest,
            });
            samples.push(TabularOperatorSampleV1 {
                sample_id: id(&episode),
                sensor_id: sensor.clone(),
                action_id: candidates[action_index].clone(),
                target: value,
                evidence_digest: receipt.event_digest,
            });
        }
    }
    let plan = ledger::DatasetFreezePlanV2 {
        snapshot_id: id(&format!("dataset-{generation}")),
        objective_digest: roles.trust.objective_digest,
        inclusion_policy_digest: hash("all-current-authenticated-observations"),
    };
    let signed = roles.evidence(
        /*index*/ 1,
        &ledger::dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
        micros(),
    );
    let dataset = writer.freeze_dataset(plan, &signed, micros()).unwrap();
    let snapshot = writer.snapshot().unwrap();
    ledger::verify_dataset_snapshot_receipt_against_ledger_v3(&dataset, &snapshot, micros())
        .unwrap();
    // The complete dataset contains decisions AND outcomes. Training uses each
    // observed outcome once, paired with its authenticated action/sensor above;
    // decisions are provenance, not duplicated independent reward samples.
    let artifact = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id(&format!("learned-generation-{generation}")),
        producer_id: id("generator"),
        generation: Generation::new(generation + 1).unwrap(),
        objective_digest: roles.trust.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        sensor_core_digest: hash("exact-native-query-memory-revision"),
        training_profile_digest: hash("observed-full-action-census-mean-v1"),
        minimum_samples_per_cell: 8,
        sensor_ids: sensors.into_iter().collect(),
        action_ids: actions
            .iter()
            .map(|(item, _)| cognitive_action_id(item).unwrap())
            .collect(),
        samples,
    })
    .unwrap();
    writer
        .revalidate_dataset_snapshot(&dataset, micros())
        .unwrap();
    let bytes = encode_tabular_payload_v1(&artifact).unwrap();
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: artifact.artifact_digest,
        objective_digest: artifact.objective_digest,
        dataset_digest: artifact.dataset_digest,
        sensor_core_digest: artifact.sensor_core_digest,
        training_profile_digest: artifact.training_profile_digest,
        generation: artifact.generation,
    };
    save(
        &root.join("training.json"),
        &json!({"observations":observed, "dataset":dataset.snapshot.dataset_digest.to_string(),
        "ledger_head":snapshot.head_digest.to_string(), "payload_sha256":pin.payload_digest.to_string(),
        "native_fit":"fit_tabular_operator_strict_v2", "authenticated_owner":"LedgerWriter", "task_count":observed["body"]["tasks"].as_array().unwrap().len()}),
    );
    Fitted {
        artifact,
        dataset,
        snapshot,
        bytes,
        pin,
        temporal_training,
    }
}
