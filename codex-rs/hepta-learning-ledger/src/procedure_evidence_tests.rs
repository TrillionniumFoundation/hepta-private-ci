use super::*;
use std::collections::BTreeSet;
use std::future::Future;
use std::sync::OnceLock;

use pretty_assertions::assert_eq;

use crate::ProcedureArgumentV1;
use crate::ProcedureArtifactV1;
use crate::ProcedureCheckResultV1;
use crate::ProcedureCheckV1;
use crate::ProcedureEnvironmentV1;
use crate::ProcedureExecutionEvidenceV1;
use crate::ProcedureModelV1;
use crate::ProcedureStepDispositionV1;
use crate::ProcedureStepV1;
use crate::ProcedureTraceStepV1;

fn artifact(name: &str, bytes: &[u8]) -> ProcedureArtifactV1 {
    ProcedureArtifactV1 {
        id: id(name),
        content_digest: Digest32::of_bytes(bytes),
        byte_length: bytes.len() as u64,
    }
}

fn executable(name: &str) -> ProcedureArtifactV1 {
    static EXECUTABLE: OnceLock<(Digest32, u64)> = OnceLock::new();
    let (content_digest, byte_length) = *EXECUTABLE.get_or_init(|| {
        let file = File::open(std::env::current_exe().unwrap()).unwrap();
        let length = file.metadata().unwrap().len();
        (
            Digest32::of_reader(file, 256 * 1024 * 1024).unwrap(),
            length,
        )
    });
    ProcedureArtifactV1 {
        id: id(name),
        content_digest,
        byte_length,
    }
}

fn profile(evidence: &ProcedureExecutionEvidenceV1) -> ProcedureQualificationProfileV1 {
    ProcedureQualificationProfileV1 {
        profile_id: evidence.profile_id.clone(),
        contract_digest: evidence.contract_digest().unwrap(),
        unit_profile_digest: digest("checked-file-operation-binary-success"),
        successful_value: FixedQ32::ONE,
        maximum_evidence_age_seconds: 20,
    }
}

fn execute_files(fixture: &Fixture, writer: &mut LedgerWriter) -> ProcedureExecutionEvidenceV1 {
    let input = b" Pear \nAPPLE\npear\n banana \n\n";
    fs::write(fixture.root.join("input.txt"), input).unwrap();
    let input_artifact = artifact("input", input);
    assert!(input.is_ascii() && input.len() <= 4096);
    let mut evidence = ProcedureExecutionEvidenceV1 {
        procedure_id: id("action"), profile_id: id("ascii-normalize-sort-unique"),
        decision_record_id: id("decision-record"), episode_id: id("episode"),
        run_snapshot_digest: digest("run-snapshot"), observer_id: id("observer"),
        environment: ProcedureEnvironmentV1 {
            runtime: executable("native-runtime"), executable: executable("file-executor"),
            model: ProcedureModelV1::NoModel,
            context: vec![ProcedureArgumentV1 { name: id("target"), value: format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH) }],
        },
        checker: executable("independent-file-checker"),
        steps: vec![
            ProcedureStepV1 {
                id: id("normalize"), operation: id("trim-ascii-lowercase-remove-empty"), arguments: vec![],
                input_artifacts: vec![id("input")], output_artifacts: vec![id("normalized")],
            },
            ProcedureStepV1 {
                id: id("sort-unique"), operation: id("byte-sort-deduplicate-write-lf"), arguments: vec![],
                input_artifacts: vec![id("normalized")], output_artifacts: vec![id("result")],
            },
        ],
        preconditions: vec![ProcedureCheckV1 {
            id: id("bounded-ascii"), predicate: "input is ASCII and at most 4096 bytes".into(), arguments: vec![],
            observed_at: 30, result: ProcedureCheckResultV1::Satisfied, observations: vec![input_artifact.clone()],
        }],
        success_criteria: vec![ProcedureCheckV1 {
            id: id("exact-result"), predicate: "result contains precisely the sorted unique nonempty trimmed lowercase input lines, each ending in LF".into(),
            arguments: vec![], observed_at: 40, result: ProcedureCheckResultV1::Satisfied, observations: vec![],
        }],
        execution_started_at: 31, execution_finished_at: 35, observer_checked_at: 40,
        trace: vec![], final_outputs: vec![],
    };
    writer
        .install_procedure_profile(profile(&evidence))
        .unwrap();
    let mut request = decision();
    request.support_digest = evidence.contract_digest().unwrap();
    let signature = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    writer
        .append_decision(Digest32::ZERO, request, &signature, 30)
        .unwrap();

    // Execute actual file operations after the authenticated Decision. The
    // Observer below uses a separate algorithm and reopens every artifact.
    let raw = fs::read(fixture.root.join("input.txt")).unwrap();
    let mut normalized = Vec::new();
    for line in raw.split(|byte| *byte == b'\n') {
        let line = line.trim_ascii();
        if !line.is_empty() {
            normalized.extend(line.iter().map(u8::to_ascii_lowercase));
            normalized.push(b'\n');
        }
    }
    fs::write(fixture.root.join("normalized.txt"), &normalized).unwrap();
    let normalized = fs::read(fixture.root.join("normalized.txt")).unwrap();
    let normalized_artifact = artifact("normalized", &normalized);
    let mut lines: Vec<_> = normalized
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .collect();
    lines.sort_unstable();
    lines.dedup();
    let mut result = Vec::new();
    for line in lines {
        result.extend_from_slice(line);
        result.push(b'\n');
    }
    fs::write(fixture.root.join("result.txt"), &result).unwrap();
    let final_artifact = artifact(
        "result",
        &fs::read(fixture.root.join("result.txt")).unwrap(),
    );
    evidence.trace = vec![
        ProcedureTraceStepV1 {
            step_id: id("normalize"),
            sequence: 1,
            started_at: 31,
            finished_at: 32,
            disposition: ProcedureStepDispositionV1::Completed,
            inputs: vec![input_artifact],
            outputs: vec![normalized_artifact.clone()],
        },
        ProcedureTraceStepV1 {
            step_id: id("sort-unique"),
            sequence: 2,
            started_at: 34,
            finished_at: 35,
            disposition: ProcedureStepDispositionV1::Completed,
            inputs: vec![normalized_artifact.clone()],
            outputs: vec![final_artifact.clone()],
        },
    ];
    evidence.success_criteria[0].observations = vec![normalized_artifact, final_artifact.clone()];
    evidence.final_outputs = vec![final_artifact];
    evidence
}

fn procedure_outcome(evidence: &ProcedureExecutionEvidenceV1) -> AuthenticatedOutcomeV1 {
    let mut request = outcome(
        "procedure-observed",
        "procedure-outcome",
        None,
        FixedQ32::ONE.raw(),
    );
    request.support_digest = evidence.canonical_digest().unwrap();
    request.unit_profile_digest = profile(evidence).unit_profile_digest;
    request
}

fn independent_observer_sign(
    fixture: &Fixture,
    writer: &LedgerWriter,
    evidence: &ProcedureExecutionEvidenceV1,
    request: &AuthenticatedOutcomeV1,
) -> Result<SignedLearningEvidenceV1, String> {
    let input = fs::read_to_string(fixture.root.join("input.txt")).map_err(|e| e.to_string())?;
    if !input.is_ascii() || input.len() > 4096 {
        return Err("precondition failed".into());
    }
    let lines: Vec<String> = input
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(str::to_lowercase)
        .collect();
    let expected_normalized = lines
        .iter()
        .map(|line| format!("{line}\n"))
        .collect::<String>();
    let expected_result = lines
        .into_iter()
        .collect::<BTreeSet<_>>()
        .iter()
        .map(|line| format!("{line}\n"))
        .collect::<String>();
    let normalized =
        fs::read_to_string(fixture.root.join("normalized.txt")).map_err(|e| e.to_string())?;
    let result = fs::read_to_string(fixture.root.join("result.txt")).map_err(|e| e.to_string())?;
    if normalized != expected_normalized
        || result != expected_result
        || evidence.trace[0].inputs != vec![artifact("input", input.as_bytes())]
        || evidence.trace[0].outputs != vec![artifact("normalized", normalized.as_bytes())]
        || evidence.trace[1].outputs != vec![artifact("result", result.as_bytes())]
        || evidence.preconditions[0].observations != vec![artifact("input", input.as_bytes())]
        || evidence.success_criteria[0].observations
            != vec![
                artifact("normalized", normalized.as_bytes()),
                artifact("result", result.as_bytes()),
            ]
        || writer
            .procedure_profiles
            .get(&evidence.profile_id)
            .map(|profile| profile.contract_digest)
            != Some(evidence.contract_digest().map_err(|e| e.to_string())?)
        || request.support_digest != evidence.canonical_digest().map_err(|e| e.to_string())?
        || request.value != Some(FixedQ32::ONE)
    {
        return Err("independent file observation mismatch".into());
    }
    evidence
        .validate_successful_execution()
        .map_err(|e| e.to_string())?;
    // Test-only key held by the independent Observer role/controller. This is
    // mechanism qualification, not proof of organizational independence.
    Ok(sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(request),
    ))
}

fn admit_observed_files(
    fixture: &Fixture,
    writer: &mut LedgerWriter,
    evidence: &ProcedureExecutionEvidenceV1,
) {
    let request = procedure_outcome(evidence);
    let signature = independent_observer_sign(fixture, writer, evidence, &request).unwrap();
    writer
        .append_outcome(
            writer.witness_frontier().unwrap().anchor.chain_digest,
            request,
            &signature,
            50,
        )
        .unwrap();
}

#[test]
fn real_file_execution_independent_observation_and_owner_proof_are_async_send() {
    fn require_send_sync<T: Send + Sync>(_: &T) {}
    fn require_send_future<F: Future + Send>(_: &F) {}
    let fixture = Fixture::new();
    let (mut writer, _) = current_writer(&fixture);
    let evidence = execute_files(&fixture, &mut writer);
    admit_observed_files(&fixture, &mut writer, &evidence);
    let token = writer
        .resolve_procedure_execution(&id("procedure-observed"), &evidence)
        .unwrap();
    require_send_sync(&writer);
    require_send_sync(&token);
    let future = async {
        token.ensure_current()?;
        std::future::ready(()).await;
        token.ensure_current()
    };
    require_send_future(&future);
    drop(future);
    std::thread::scope(|scope| scope.spawn(move || token.ensure_current()).join().unwrap())
        .unwrap();
    assert_eq!(
        fs::read_to_string(fixture.root.join("result.txt")).unwrap(),
        "apple\nbanana\npear\n"
    );
}

#[test]
fn changing_any_contract_or_execution_dimension_cannot_reuse_observer_evidence() {
    let fixture = Fixture::new();
    let (mut writer, _) = current_writer(&fixture);
    let evidence = execute_files(&fixture, &mut writer);
    admit_observed_files(&fixture, &mut writer, &evidence);
    let mut variants = vec![evidence.clone(); 14];
    variants[0].steps.swap(0, 1);
    variants[1].steps[0].arguments.push(ProcedureArgumentV1 {
        name: id("mode"),
        value: "different".into(),
    });
    variants[2].preconditions[0].predicate = "a different precondition".into();
    variants[3].preconditions[0].result = ProcedureCheckResultV1::Unknown;
    variants[4].environment.runtime.content_digest = digest("other-runtime");
    variants[5].environment.model =
        ProcedureModelV1::Artifact(artifact("model", b"unapproved-model"));
    variants[6].checker.content_digest = digest("other-checker");
    variants[7].success_criteria[0].predicate = "a different success criterion".into();
    variants[8].trace[0].inputs[0].content_digest = digest("substituted-input");
    variants[9].final_outputs[0].content_digest = digest("substituted-output");
    variants[10].observer_id = id("generator");
    variants[11].run_snapshot_digest = digest("other-run");
    variants[12].trace.pop();
    variants[13].trace[1].disposition = ProcedureStepDispositionV1::Skipped;
    for (index, changed) in variants.iter().enumerate() {
        assert!(
            writer
                .resolve_procedure_execution(&id("procedure-observed"), changed)
                .is_err(),
            "mutation {index}"
        );
    }
    writer
        .resolve_procedure_execution(&id("procedure-observed"), &evidence)
        .unwrap()
        .ensure_current()
        .unwrap();
}

#[test]
fn independent_observer_refuses_tampered_actual_output_before_signing() {
    let fixture = Fixture::new();
    let (mut writer, _) = current_writer(&fixture);
    let evidence = execute_files(&fixture, &mut writer);
    fs::write(fixture.root.join("result.txt"), b"incorrect\n").unwrap();
    assert!(
        independent_observer_sign(&fixture, &writer, &evidence, &procedure_outcome(&evidence))
            .is_err()
    );
    assert!(
        writer
            .resolve_procedure_execution(&id("procedure-observed"), &evidence)
            .is_err()
    );
    assert_eq!(writer.records().unwrap().len(), 1);
}

#[test]
fn signed_pending_censored_failed_or_wrong_unit_outcomes_do_not_qualify() {
    for disposition in 0..4 {
        let fixture = Fixture::new();
        let (mut writer, _) = current_writer(&fixture);
        let evidence = execute_files(&fixture, &mut writer);
        let mut request = procedure_outcome(&evidence);
        match disposition {
            0 => {
                request.observed_at = None;
                request.value = None;
                request.watermark.finalized_at = None;
                request.watermark.terminality = OutcomeTerminalityV1::Pending;
            }
            1 => {
                request.observed_at = None;
                request.value = None;
                request.watermark.terminality = OutcomeTerminalityV1::Censored;
                request.watermark.censoring_reason = Some(id("not-observed"));
            }
            2 => request.value = Some(FixedQ32::ZERO),
            3 => request.unit_profile_digest = digest("other-units"),
            _ => unreachable!(),
        }
        append_observed(&mut writer, request);
        assert!(
            writer
                .resolve_procedure_execution(&id("procedure-observed"), &evidence)
                .is_err(),
            "outcome {disposition}"
        );
    }
}

#[test]
fn procedure_current_use_rejects_profile_withdrawal_correction_and_unlearning() {
    let fixture = Fixture::new();
    let (mut writer, clock) = current_writer(&fixture);
    let evidence = execute_files(&fixture, &mut writer);
    admit_observed_files(&fixture, &mut writer, &evidence);
    let token = writer
        .resolve_procedure_execution(&id("procedure-observed"), &evidence)
        .unwrap();
    assert_eq!(token.valid_until_unix_seconds(), 60);
    clock.0.store(60, Ordering::SeqCst);
    token.ensure_current().unwrap();
    drop(token);
    assert!(writer.remove_procedure_profile(&evidence.profile_id));
    assert!(
        writer
            .resolve_procedure_execution(&id("procedure-observed"), &evidence)
            .is_err()
    );
    writer
        .install_procedure_profile(profile(&evidence))
        .unwrap();
    writer
        .resolve_procedure_execution(&id("procedure-observed"), &evidence)
        .unwrap();
    let mut corrected = procedure_outcome(&evidence);
    corrected.record_id = id("corrected-procedure");
    corrected.outcome_id = id("corrected-outcome");
    corrected.watermark.correction_predecessor = Some(id("procedure-outcome"));
    append_observed(&mut writer, corrected);
    assert!(
        writer
            .resolve_procedure_execution(&id("procedure-observed"), &evidence)
            .is_err()
    );
    writer
        .resolve_procedure_execution(&id("corrected-procedure"), &evidence)
        .unwrap();
    withdraw(&mut writer, "corrected-procedure");
    assert!(
        writer
            .resolve_procedure_execution(&id("corrected-procedure"), &evidence)
            .is_err()
    );
}

#[test]
fn procedure_age_limit_is_rechecked_on_the_same_borrowed_token() {
    let fixture = Fixture::new();
    let (mut writer, clock) = current_writer(&fixture);
    let evidence = execute_files(&fixture, &mut writer);
    admit_observed_files(&fixture, &mut writer, &evidence);
    let token = writer
        .resolve_procedure_execution(&id("procedure-observed"), &evidence)
        .unwrap();
    clock.0.store(61, Ordering::SeqCst);
    assert!(token.ensure_current().is_err());
}

#[test]
fn self_observation_and_unbounded_contracts_cannot_be_admitted() {
    let fixture = Fixture::new();
    let (mut writer, _) = current_writer(&fixture);
    let evidence = execute_files(&fixture, &mut writer);
    let mut next = trust();
    next.signers[0].roles.push(LearningEvidenceRoleV1::Observer);
    rotate(&mut writer, next);
    let mut request = procedure_outcome(&evidence);
    request.observer = principal("generator");
    let signature = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&request),
    );
    assert!(
        writer
            .append_outcome(
                writer.witness_frontier().unwrap().anchor.chain_digest,
                request,
                &signature,
                50
            )
            .is_err()
    );
    let mut oversized = evidence.clone();
    oversized.steps.resize(33, evidence.steps[0].clone());
    assert!(oversized.canonical_bytes().is_err());
    let mut oversized = evidence;
    oversized.success_criteria[0].predicate = "x".repeat(1025);
    assert!(oversized.canonical_bytes().is_err());
}
