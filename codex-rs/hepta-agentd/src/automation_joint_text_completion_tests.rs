//! Synthetic file observations only. No process is launched and no fixture is
//! a model, authentic execution receipt, current owner or Training permission.

use std::fs;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_automation::JointTextInputManifestV1;
use pretty_assertions::assert_eq;

use super::*;

struct Fixture {
    _root: tempfile::TempDir,
    custody: JointTextInputCustodyV1,
    root_identity: JointTextRootIdentityV1,
    input: JointTextInputRefV1,
    identity: JointTextJobIdentityV1,
    job: files::Directory,
    terminal: Terminal,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().expect("private file fixture");
        let path = root.path().canonicalize().expect("physical fixture");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).expect("fixture mode");
        let metadata = fs::metadata(&path).expect("fixture identity");
        let root_identity = JointTextRootIdentityV1 {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
        };
        let directory = files::Directory::open_root(&path, &root_identity).expect("fixture root");
        directory
            .write_new("layout.json", super::super::ROOT_LAYOUT)
            .expect("fixture layout");
        let custody =
            JointTextInputCustodyV1::open_existing(&path, &root_identity).expect("custody");
        let input = JointTextInputRefV1::from_manifest(JointTextInputManifestV1 {
            schema_version: 1,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            request_sha256: Sha256Digest::for_bytes(b"request"),
            request_bytes: 7,
            request_binding_digest: Sha256Digest::for_bytes(b"binding"),
            predecessor_sha256: Sha256Digest::for_bytes(b"packet"),
            predecessor_bytes: 6,
            worker_execution_source_digest: Sha256Digest::for_bytes(b"original worker"),
        })
        .expect("input fixture");
        custody
            .stage_bound(&input, b"request", b"packet")
            .expect("fixture stage");
        let descriptor = input.encode().expect("descriptor");
        let identity = JointTextJobIdentityV1::for_taskflow(
            "fixture-provider",
            "fixture-run",
            "fixture-step",
            Sha256Digest::for_bytes(&descriptor),
        )
        .expect("job data");
        let (jobs, _) = custody.root.create("jobs").expect("jobs");
        let key = Sha256Digest::for_bytes(identity.key.as_str().as_bytes());
        let (job, _) = jobs.create(key.as_str()).expect("job");
        job.write_new("descriptor.json", &descriptor)
            .expect("original descriptor");
        let process = JointTextProcessIdentityV1 {
            host_id: Sha256Digest::for_bytes(b"fixture host"),
            process_id: 101,
            incarnation: Sha256Digest::for_bytes(b"fixture incarnation"),
        };
        let claim = Claim {
            schema_version: 1,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            identity: identity.clone(),
            root: root_identity.clone(),
            runner: process.clone(),
            boot_id: Sha256Digest::for_bytes(b"fixture boot"),
            clock: "CLOCK_BOOTTIME".to_string(),
            started_nanoseconds: 1_000_000,
            deadline_nanoseconds: 2_001_000_000,
            budget_milliseconds: 2_000,
        };
        let claim_bytes = serde_json::to_vec(&claim).expect("claim");
        job.write_new("claim.json", &claim_bytes)
            .expect("original claim");
        job.write_new(
            "worker.json",
            &serde_json::to_vec(&process).expect("worker"),
        )
        .expect("worker file");
        let reservation = JointTextReservationV1 {
            schema_version: 1,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            identity: identity.clone(),
            input: input.clone(),
            root: root_identity.clone(),
            nonce: Sha256Digest::for_bytes(b"fixture nonce"),
            sources: Vec::new(),
            absent_sources: Vec::new(),
            python: JointTextRecordedPythonV1 {
                path: PathBuf::from("/fixture/not-executed"),
                resolved_path: PathBuf::from("/fixture/not-executed"),
                bytes: 1,
                sha256: Sha256Digest::for_bytes(b"x"),
            },
        };
        // Source origin is separately rejected/accepted by the signed source
        // verifier. This fixture isolates held-directory completion behavior.
        job.write_new(
            "reservation.json",
            &serde_json::to_vec(&reservation).expect("reservation"),
        )
        .expect("reservation file");
        let (output, _) = job.create(identity.output_id.as_str()).expect("outputs");
        let file_digest = |name: &str| {
            output
                .write_new(name, name.as_bytes())
                .expect("fixture output");
            JointTextFileDigestV1 {
                sha256: Sha256Digest::for_bytes(name.as_bytes()),
                bytes: name.len() as u64,
            }
        };
        let outputs = JointTextJobOutputsV1 {
            input: input.clone(),
            started: file_digest("started.json"),
            candidate: file_digest("candidate.heptapk"),
            observation: file_digest("observation.json"),
            completed: file_digest("completed.json"),
        };
        let terminal = Terminal {
            schema_version: 1,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            identity: identity.clone(),
            input: input.clone(),
            root: root_identity.clone(),
            process: Some(process),
            state: JointTextJobStateV1::Succeeded,
            returncode: Some(0),
            termination_confirmed: true,
            reason: "worker_exit_zero_and_outputs_closed".to_string(),
            claim_sha256: Some(Sha256Digest::for_bytes(&claim_bytes)),
            outputs: Some(outputs),
            wall_nanoseconds: 1_000_000,
            child_cpu_nanoseconds: None,
            cost_scope: COST_SCOPE.to_string(),
            physical_energy_joules: None,
            full_history_cost: None,
        };
        job.write_new(
            "terminal.json",
            &serde_json::to_vec(&terminal).expect("terminal"),
        )
        .expect("terminal file");
        Self {
            _root: root,
            custody,
            root_identity,
            input,
            identity,
            job,
            terminal,
        }
    }

    fn read(&self) -> io::Result<JointTextCompletedOutputV1> {
        self.custody.read_completed(
            &self.identity,
            &self.input,
            &self.root_identity,
            2_000,
            JOINT_TEXT_MAX_PACKET_BYTES as u64,
        )
    }

    fn job_path(&self) -> PathBuf {
        self.custody
            .root_path
            .join("jobs")
            .join(Sha256Digest::for_bytes(self.identity.key.as_str().as_bytes()).as_str())
    }

    fn rewrite_test_terminal(&self) {
        fs::write(
            self.job_path().join("terminal.json"),
            serde_json::to_vec(&self.terminal).expect("changed fixture"),
        )
        .expect("test-only terminal mutation");
    }
}

#[test]
fn reads_exact_outputs_and_keeps_unknown_cpu_cost_null() {
    let fixture = Fixture::new();
    let output = fixture.read().expect("fixed completed file closure");
    assert_eq!(output.candidate, b"candidate.heptapk");
    assert_eq!(output.started, b"started.json");
    assert_eq!(output.observation, b"observation.json");
    assert_eq!(output.completed, b"completed.json");
    assert_eq!(output.runner_wall_nanoseconds, 1_000_000);
    assert_eq!(output.runner_child_cpu_nanoseconds, None);
    assert_eq!(
        output.terminal_digest,
        Sha256Digest::for_bytes(&serde_json::to_vec(&fixture.terminal).expect("terminal"))
    );
}

#[test]
fn exit_zero_without_confirmed_process_and_nonzero_exit_are_refused() {
    let mut fixture = Fixture::new();
    fixture.terminal.returncode = Some(1);
    fixture.rewrite_test_terminal();
    assert!(fixture.read().is_err());
    fixture.terminal.returncode = Some(0);
    fixture.terminal.termination_confirmed = false;
    fixture.rewrite_test_terminal();
    assert!(fixture.read().is_err());
    fixture.terminal.termination_confirmed = true;
    fixture.terminal.process = None;
    fixture.rewrite_test_terminal();
    assert!(fixture.read().is_err());
}

#[test]
fn failed_marker_and_changed_output_never_become_completed_candidate() {
    let fixture = Fixture::new();
    let output = fixture
        .job
        .open(fixture.identity.output_id.as_str())
        .expect("output directory");
    output
        .write_new("failed.json", b"failure record")
        .expect("test contradiction");
    assert!(fixture.read().is_err());
    let path = fixture.job_path().join(fixture.identity.output_id.as_str());
    fs::remove_file(path.join("failed.json")).expect("remove test contradiction");
    fs::write(path.join("candidate.heptapk"), b"changed candidate").expect("test changed packet");
    assert!(fixture.read().is_err());
}

#[test]
fn original_deadline_and_reservation_cannot_be_rebound() {
    let fixture = Fixture::new();
    assert!(
        fixture
            .custody
            .read_completed(
                &fixture.identity,
                &fixture.input,
                &fixture.root_identity,
                2_001,
                JOINT_TEXT_MAX_PACKET_BYTES as u64,
            )
            .is_err()
    );
    let path = fixture.job_path().join("reservation.json");
    let mut reservation: JointTextReservationV1 =
        serde_json::from_slice(&fs::read(&path).expect("original reservation"))
            .expect("original shape");
    reservation.identity = JointTextJobIdentityV1::for_taskflow(
        "fixture-provider",
        "another-run",
        "fixture-step",
        fixture.identity.payload_sha256.clone(),
    )
    .expect("other logical job");
    fs::write(
        path,
        serde_json::to_vec(&reservation).expect("rebound fixture"),
    )
    .expect("test reservation change");
    assert!(fixture.read().is_err());
}

#[test]
fn additional_terminal_field_and_output_alias_are_refused() {
    let fixture = Fixture::new();
    let mut value = serde_json::to_value(&fixture.terminal).expect("test terminal object");
    value["new_authority"] = serde_json::json!(true);
    fs::write(
        fixture.job_path().join("terminal.json"),
        serde_json::to_vec(&value).expect("unknown field"),
    )
    .expect("test field addition");
    assert!(fixture.read().is_err());
    fixture.rewrite_test_terminal();
    let packet = fixture
        .job_path()
        .join(fixture.identity.output_id.as_str())
        .join("candidate.heptapk");
    fs::hard_link(packet, fixture.custody.root_path.join("external-alias"))
        .expect("test output alias");
    assert!(fixture.read().is_err());
}

#[test]
fn successful_marker_cannot_hide_an_exceeded_original_deadline() {
    let mut fixture = Fixture::new();
    fixture.terminal.wall_nanoseconds = 2_000_000_001;
    fixture.rewrite_test_terminal();
    assert!(fixture.read().is_err());
}

#[test]
fn packet_read_is_bounded_by_the_original_artifact_budget() {
    let fixture = Fixture::new();
    assert!(
        fixture
            .custody
            .read_completed(
                &fixture.identity,
                &fixture.input,
                &fixture.root_identity,
                2_000,
                1,
            )
            .is_err()
    );
    assert!(
        fixture
            .custody
            .read_completed(
                &fixture.identity,
                &fixture.input,
                &fixture.root_identity,
                2_000,
                0,
            )
            .is_err()
    );
}

#[test]
fn input_stays_bound_to_one_authorized_logical_job_across_reopen() {
    use crate::automation_joint_text_inputs::JointTextJobBindingV1;

    let fixture = Fixture::new();
    let binding = JointTextJobBindingV1 {
        schema_version: 1,
        provider_scope: "fixture-provider".to_string(),
        run_id: "fixture-run".to_string(),
        step_id: "fixture-step".to_string(),
        identity: fixture.identity.clone(),
        input: fixture.input.clone(),
    };
    fixture
        .custody
        .bind_job(&binding)
        .expect("original logical binding");
    fixture
        .custody
        .bind_job(&binding)
        .expect("same job is read back");
    let reopened =
        JointTextInputCustodyV1::open_existing(&fixture.custody.root_path, &fixture.root_identity)
            .expect("original root reopened");
    let actual = reopened
        .read_bound_job(&fixture.input)
        .expect("original durable binding");
    assert_eq!(actual.identity, binding.identity);
    let mut other = binding.clone();
    other.run_id = "another-run".to_string();
    other.identity = JointTextJobIdentityV1::for_taskflow(
        &other.provider_scope,
        &other.run_id,
        &other.step_id,
        other.identity.payload_sha256.clone(),
    )
    .expect("different logical job");
    assert!(reopened.bind_job(&other).is_err());
    assert_eq!(
        reopened
            .read_bound_job(&fixture.input)
            .expect("original preserved")
            .identity,
        binding.identity
    );
}
