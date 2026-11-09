//! Read the original provider's completed records through its held directory.
//! OS termination is the bound runner's durable observation, not a second
//! waitpid performed here. Learning source/currentness checks follow separately.

use std::io;
use std::path::PathBuf;

use codex_hepta_automation::JOINT_TEXT_MAX_COMMAND_BYTES;
use codex_hepta_automation::JOINT_TEXT_MAX_PACKET_BYTES;
use codex_hepta_automation::JOINT_TEXT_MAX_REQUEST_BYTES;
use codex_hepta_automation::JOINT_TEXT_MAX_TERMINAL_BYTES;
use codex_hepta_automation::JointTextFileDigestV1;
use codex_hepta_automation::JointTextInputRefV1;
use codex_hepta_automation::JointTextJobIdentityV1;
use codex_hepta_automation::JointTextJobOutputsV1;
use codex_hepta_automation::JointTextJobStateV1;
use codex_hepta_automation::JointTextProcessIdentityV1;
use codex_hepta_automation::JointTextProfileV1;
use codex_hepta_automation::JointTextRootIdentityV1;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::JointTextInputCustodyV1;
use super::files;

const COST_SCOPE: &str = "runner claim through terminal observation; excludes dispatch, owner custody, earlier attempts and publication";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Terminal {
    schema_version: u32,
    profile: JointTextProfileV1,
    identity: JointTextJobIdentityV1,
    input: JointTextInputRefV1,
    root: JointTextRootIdentityV1,
    process: Option<JointTextProcessIdentityV1>,
    state: JointTextJobStateV1,
    returncode: Option<i32>,
    termination_confirmed: bool,
    reason: String,
    claim_sha256: Option<Sha256Digest>,
    outputs: Option<JointTextJobOutputsV1>,
    wall_nanoseconds: u64,
    child_cpu_nanoseconds: Option<u64>,
    cost_scope: String,
    physical_energy_joules: Option<()>,
    full_history_cost: Option<()>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Claim {
    schema_version: u32,
    profile: JointTextProfileV1,
    identity: JointTextJobIdentityV1,
    root: JointTextRootIdentityV1,
    runner: JointTextProcessIdentityV1,
    boot_id: Sha256Digest,
    clock: String,
    started_nanoseconds: u64,
    deadline_nanoseconds: u64,
    budget_milliseconds: u64,
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct JointTextRecordedSourceV1 {
    pub(crate) path: String,
    pub(crate) bytes: u64,
    pub(crate) sha256: Sha256Digest,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct JointTextRecordedPythonV1 {
    pub(crate) path: PathBuf,
    pub(crate) resolved_path: PathBuf,
    pub(crate) bytes: u64,
    pub(crate) sha256: Sha256Digest,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct JointTextReservationV1 {
    schema_version: u32,
    profile: JointTextProfileV1,
    identity: JointTextJobIdentityV1,
    input: JointTextInputRefV1,
    root: JointTextRootIdentityV1,
    nonce: Sha256Digest,
    pub(crate) sources: Vec<JointTextRecordedSourceV1>,
    pub(crate) absent_sources: Vec<String>,
    pub(crate) python: JointTextRecordedPythonV1,
}

pub(crate) struct JointTextCompletedOutputV1 {
    pub(crate) started: Vec<u8>,
    pub(crate) candidate: Vec<u8>,
    pub(crate) observation: Vec<u8>,
    pub(crate) completed: Vec<u8>,
    pub(crate) terminal_digest: Sha256Digest,
    pub(crate) runner_wall_nanoseconds: u64,
    pub(crate) runner_child_cpu_nanoseconds: Option<u64>,
    pub(crate) reservation: JointTextReservationV1,
}

impl JointTextInputCustodyV1 {
    pub(crate) fn read_completed(
        &self,
        identity: &JointTextJobIdentityV1,
        input: &JointTextInputRefV1,
        root: &JointTextRootIdentityV1,
        maximum_training_milliseconds: u64,
        maximum_artifact_bytes: u64,
    ) -> io::Result<JointTextCompletedOutputV1> {
        identity.validate().map_err(io::Error::other)?;
        root.validate().map_err(io::Error::other)?;
        let descriptor = input.encode().map_err(io::Error::other)?;
        if Sha256Digest::for_bytes(&descriptor) != identity.payload_sha256
            || maximum_training_milliseconds == 0
            || maximum_artifact_bytes == 0
        {
            return files::invalid("Joint completion input or original budget mismatch");
        }
        self.read(input)?;
        self.verify_root()?;
        let jobs = self.root.open("jobs")?;
        let job_key = Sha256Digest::for_bytes(identity.key.as_str().as_bytes());
        let job = jobs.open(job_key.as_str())?;
        let descriptor_file = job.read("descriptor.json", JOINT_TEXT_MAX_COMMAND_BYTES)?;
        let reservation_file = job.read("reservation.json", JOINT_TEXT_MAX_REQUEST_BYTES)?;
        let terminal_file = job.read("terminal.json", JOINT_TEXT_MAX_TERMINAL_BYTES)?;
        let claim_file = job.read("claim.json", JOINT_TEXT_MAX_REQUEST_BYTES)?;
        let worker_file = job.read("worker.json", JOINT_TEXT_MAX_REQUEST_BYTES)?;
        let terminal: Terminal =
            serde_json::from_slice(&terminal_file.bytes).map_err(io::Error::other)?;
        let claim: Claim = serde_json::from_slice(&claim_file.bytes).map_err(io::Error::other)?;
        let worker: JointTextProcessIdentityV1 =
            serde_json::from_slice(&worker_file.bytes).map_err(io::Error::other)?;
        let reservation: JointTextReservationV1 =
            serde_json::from_slice(&reservation_file.bytes).map_err(io::Error::other)?;
        if serde_json::to_vec(&reservation).map_err(io::Error::other)? != reservation_file.bytes
            || reservation.schema_version != 1
            || reservation.identity != *identity
            || reservation.input != *input
            || reservation.root != *root
        {
            return files::invalid("Joint original reservation does not bind this input and job");
        }
        Sha256Digest::parse(reservation.nonce.as_str()).map_err(io::Error::other)?;
        let budget = maximum_training_milliseconds.min(300_000);
        let deadline = claim
            .started_nanoseconds
            .checked_add(budget * 1_000_000)
            .ok_or_else(|| io::Error::other("Joint original deadline overflow"))?;
        if descriptor_file.bytes != descriptor
            || serde_json::to_vec(&terminal).map_err(io::Error::other)? != terminal_file.bytes
            || serde_json::to_vec(&claim).map_err(io::Error::other)? != claim_file.bytes
            || serde_json::to_vec(&worker).map_err(io::Error::other)? != worker_file.bytes
            || terminal.schema_version != 1
            || terminal.identity != *identity
            || terminal.input != *input
            || terminal.root != *root
            || terminal.state != JointTextJobStateV1::Succeeded
            || terminal.process.as_ref() != Some(&worker)
            || terminal.returncode != Some(0)
            || worker.host_id != claim.runner.host_id
            || !terminal.termination_confirmed
            || terminal.reason != "worker_exit_zero_and_outputs_closed"
            || terminal.claim_sha256.as_ref() != Some(&Sha256Digest::for_bytes(&claim_file.bytes))
            || terminal.cost_scope != COST_SCOPE
            || terminal.physical_energy_joules.is_some()
            || terminal.full_history_cost.is_some()
            || terminal.wall_nanoseconds > budget * 1_000_000
            || claim.schema_version != 1
            || claim.identity != *identity
            || claim.root != *root
            || claim.clock != "CLOCK_BOOTTIME"
            || claim.budget_milliseconds != budget
            || claim.deadline_nanoseconds != deadline
        {
            return files::invalid(
                "Joint original terminal, process or single deadline binding mismatch",
            );
        }
        for process in [&worker, &claim.runner] {
            if process.process_id == 0 {
                return files::invalid("Joint recorded process identity is missing");
            }
            Sha256Digest::parse(process.host_id.as_str()).map_err(io::Error::other)?;
            Sha256Digest::parse(process.incarnation.as_str()).map_err(io::Error::other)?;
        }
        Sha256Digest::parse(claim.boot_id.as_str()).map_err(io::Error::other)?;
        let outputs = terminal.outputs.as_ref().ok_or_else(|| {
            io::Error::other("Joint successful terminal lacks the output closure")
        })?;
        if outputs.input != *input {
            return files::invalid("Joint completed output descriptor mismatch");
        }
        let directory = job.open(identity.output_id.as_str())?;
        let packet_cap =
            usize::try_from(maximum_artifact_bytes.min(JOINT_TEXT_MAX_PACKET_BYTES as u64))
                .map_err(io::Error::other)?;
        let names = [
            "started.json",
            "candidate.heptapk",
            "observation.json",
            "completed.json",
        ];
        directory.exact_files(&names)?;
        let mut observed = Vec::new();
        for (name, expected, maximum) in [
            (
                "started.json",
                &outputs.started,
                JOINT_TEXT_MAX_REQUEST_BYTES,
            ),
            ("candidate.heptapk", &outputs.candidate, packet_cap),
            (
                "observation.json",
                &outputs.observation,
                JOINT_TEXT_MAX_REQUEST_BYTES,
            ),
            (
                "completed.json",
                &outputs.completed,
                JOINT_TEXT_MAX_REQUEST_BYTES,
            ),
        ] {
            let file = directory.read(name, maximum)?;
            verify_output(&file.bytes, expected)?;
            observed.push((name, file));
        }
        // Fixed inventory establishes the actual absence of failed.json.
        directory.exact_files(&names)?;
        for (name, file) in &observed {
            file.verify(&directory, name)?;
        }
        for (name, file) in [
            ("descriptor.json", &descriptor_file),
            ("terminal.json", &terminal_file),
            ("claim.json", &claim_file),
            ("worker.json", &worker_file),
            ("reservation.json", &reservation_file),
        ] {
            file.verify(&job, name)?;
        }
        job.verify_child(identity.output_id.as_str(), &directory)?;
        jobs.verify_child(job_key.as_str(), &job)?;
        self.root.verify_child("jobs", &jobs)?;
        self.read(input)?;
        self.verify_root()?;
        let mut bytes = observed.into_iter().map(|(_, file)| file.bytes);
        Ok(JointTextCompletedOutputV1 {
            started: bytes
                .next()
                .ok_or_else(|| io::Error::other("missing started output"))?,
            candidate: bytes
                .next()
                .ok_or_else(|| io::Error::other("missing candidate output"))?,
            observation: bytes
                .next()
                .ok_or_else(|| io::Error::other("missing observation output"))?,
            completed: bytes
                .next()
                .ok_or_else(|| io::Error::other("missing completed output"))?,
            terminal_digest: Sha256Digest::for_bytes(&terminal_file.bytes),
            runner_wall_nanoseconds: terminal.wall_nanoseconds,
            runner_child_cpu_nanoseconds: terminal.child_cpu_nanoseconds,
            reservation,
        })
    }
}

fn verify_output(bytes: &[u8], expected: &JointTextFileDigestV1) -> io::Result<()> {
    if bytes.len() as u64 != expected.bytes || Sha256Digest::for_bytes(bytes) != expected.sha256 {
        return files::invalid("Joint actual output differs from the original completed record");
    }
    Ok(())
}

#[cfg(test)]
#[path = "automation_joint_text_completion_tests.rs"]
mod tests;
