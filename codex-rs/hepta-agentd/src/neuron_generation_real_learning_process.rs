//! Explicit opt-in research process port. This is not the JointGenerator ABI.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde_json::{Value, json};

pub(super) fn now() -> anyhow::Result<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}

pub(super) fn monotonic() -> u64 {
    crate::neuron_generation_process_bootstrap::linux::boottime_micros().unwrap_or(0)
}

pub(super) fn digest(value: &Value) -> anyhow::Result<Digest32> {
    let result: Digest32 = value
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("expected digest string"))?
        .parse()?;
    anyhow::ensure!(!result.is_zero(), "zero research content digest");
    Ok(result)
}

pub(super) fn persist(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    File::open(
        path.parent()
            .ok_or_else(|| anyhow::anyhow!("missing evidence parent"))?,
    )?
    .sync_all()?;
    Ok(())
}

#[derive(Clone)]
pub(super) struct Driver {
    pub(super) operation: String,
    pub(super) output: PathBuf,
    pub(super) evidence: PathBuf,
    pub(super) deadline: u64,
    pub(super) frozen: String,
    pub(super) prepared: Value,
    pub(super) source_commit: String,
    pub(super) source_tree: String,
    python: PathBuf,
    python_digest: Digest32,
    script: PathBuf,
    script_digest: Digest32,
    config: PathBuf,
    config_digest: Digest32,
    calls: Arc<AtomicU64>,
}

impl Driver {
    pub(super) fn open() -> anyhow::Result<Self> {
        let variable = |name| std::env::var(name).map_err(anyhow::Error::from);
        let config = PathBuf::from(variable("HEPTA_REAL_MODEL_CONFIG")?);
        let config_digest: Digest32 = variable("HEPTA_REAL_MODEL_CONFIG_SHA256")?.parse()?;
        let script = PathBuf::from(variable("HEPTA_REAL_MODEL_DRIVER")?);
        let script_digest: Digest32 = variable("HEPTA_REAL_MODEL_DRIVER_SHA256")?.parse()?;
        let python = PathBuf::from(variable("HEPTA_REAL_MODEL_PYTHON")?);
        let python_digest: Digest32 = variable("HEPTA_REAL_MODEL_PYTHON_SHA256")?.parse()?;
        anyhow::ensure!(
            Digest32::of_bytes(&fs::read(&python)?) == python_digest,
            "Python binary pin"
        );
        let source_commit = variable("HEPTA_REAL_MODEL_SOURCE_COMMIT")?;
        let source_tree = variable("HEPTA_REAL_MODEL_SOURCE_TREE")?;
        anyhow::ensure!(
            [&source_commit, &source_tree]
                .iter()
                .all(|value| value.len() == 40
                    && value
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))),
            "canonical Git source identity"
        );
        anyhow::ensure!(
            Digest32::of_bytes(&fs::read(&script)?) == script_digest,
            "driver source pin"
        );
        anyhow::ensure!(
            Digest32::of_bytes(&fs::read(&config)?) == config_digest,
            "research config pin"
        );
        let value: Value = serde_json::from_slice(&fs::read(&config)?)?;
        let evidence = PathBuf::from(variable("HEPTA_REAL_MODEL_EVIDENCE")?);
        fs::create_dir(&evidence)?;
        let mut driver = Self {
            operation: value["operation"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("operation"))?
                .into(),
            output: PathBuf::from(
                value["output"]
                    .as_str()
                    .ok_or_else(|| anyhow::anyhow!("output"))?,
            ),
            evidence,
            deadline: now()?
                .checked_add(600)
                .ok_or_else(|| anyhow::anyhow!("deadline overflow"))?,
            frozen: String::new(),
            prepared: Value::Null,
            python,
            python_digest,
            source_commit,
            source_tree,
            script,
            script_digest,
            config,
            config_digest,
            calls: Arc::new(AtomicU64::new(0)),
        };
        let prepared = driver.run("prepare", json!({}), None)?;
        driver.frozen = prepared["result"]["frozen"]["sha256"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("frozen pin"))?
            .into();
        driver.prepared = prepared["result"].clone();
        Ok(driver)
    }

    pub(super) fn verify_evidence(&self, reference: &Value) -> anyhow::Result<Digest32> {
        let path = PathBuf::from(
            reference["path"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("evidence path"))?,
        );
        anyhow::ensure!(
            path.canonicalize()?
                .starts_with(self.output.canonicalize()?),
            "foreign process evidence"
        );
        let metadata = fs::symlink_metadata(&path)?;
        anyhow::ensure!(
            metadata.file_type().is_file() && metadata.len() <= 1_048_576,
            "bounded regular evidence"
        );
        let bytes = fs::read(&path)?;
        let expected = digest(&reference["sha256"])?;
        anyhow::ensure!(
            Digest32::of_bytes(&bytes) == expected,
            "changed owner evidence"
        );
        if let Some(length) = reference["bytes"].as_u64() {
            anyhow::ensure!(length == bytes.len() as u64, "evidence length changed");
        }
        Ok(expected)
    }

    pub(super) fn run(
        &self,
        action: &str,
        extra: Value,
        native_deadline: Option<u64>,
    ) -> anyhow::Result<Value> {
        anyhow::ensure!(
            Digest32::of_bytes(&fs::read(&self.script)?) == self.script_digest,
            "driver changed"
        );
        anyhow::ensure!(
            Digest32::of_bytes(&fs::read(&self.config)?) == self.config_digest,
            "config changed"
        );
        anyhow::ensure!(
            Digest32::of_bytes(&fs::read(&self.python)?) == self.python_digest,
            "Python binary changed"
        );
        let mut request = json!({"schema":"hepta.research.smollm.process.v1", "operation":self.operation,
            "action":action, "deadline_unix_seconds":self.deadline, "frozen_sha256":self.frozen});
        request
            .as_object_mut()
            .ok_or_else(|| anyhow::anyhow!("request object"))?
            .extend(
                extra
                    .as_object()
                    .ok_or_else(|| anyhow::anyhow!("extra object"))?
                    .clone(),
            );
        let raw = serde_json::to_vec(&request)?;
        anyhow::ensure!(
            raw.len() <= 16384 && now()? < self.deadline,
            "bounded live research request"
        );
        let wall_remaining = self.deadline - now()?;
        let remaining = if let Some(deadline) = native_deadline {
            let current = monotonic();
            anyhow::ensure!(
                current > 0 && current < deadline,
                "original generation deadline expired"
            );
            wall_remaining.min((deadline - current).div_ceil(1_000_000))
        } else {
            wall_remaining.min(120)
        };
        let index = self.calls.fetch_add(1, Ordering::SeqCst);
        let prefix = self.evidence.join(format!("process-{index:02}-{action}"));
        persist(&prefix.with_extension("request.json"), &raw)?;
        let stdout = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(prefix.with_extension("stdout"))?;
        let stderr = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(prefix.with_extension("stderr"))?;
        let mut child = Command::new("/usr/bin/timeout")
            .args(["--signal=TERM", "--kill-after=5s", &format!("{remaining}s")])
            .arg(&self.python)
            .arg(&self.script)
            .arg("--config")
            .arg(&self.config)
            .arg("--config-sha256")
            .arg(self.config_digest.to_string())
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("HF_HUB_OFFLINE", "1")
            .env("TRANSFORMERS_OFFLINE", "1")
            .stdin(Stdio::piped())
            .stdout(stdout)
            .stderr(stderr)
            .spawn()?;
        child
            .stdin
            .take()
            .ok_or_else(|| anyhow::anyhow!("missing driver stdin"))?
            .write_all(&raw)?;
        let status = child.wait()?;
        persist(
            &prefix.with_extension("exit.json"),
            &serde_json::to_vec(&json!({
                "pid":child.id(), "exit_code":status.code(), "absolute_unix_deadline":self.deadline,
                "original_native_deadline_micros":native_deadline, "completed_unix_seconds":now()?
            }))?,
        )?;
        anyhow::ensure!(status.success(), "real process {action} failed: {status}");
        let response = fs::read(prefix.with_extension("stdout"))?;
        anyhow::ensure!(response.len() <= 1_048_576, "bounded driver response");
        let result: Value = serde_json::from_slice(&response)?;
        anyhow::ensure!(
            result["schema"] == "hepta.research.smollm.process-result.v1"
                && result["operation"] == self.operation
                && result["action"] == action
                && digest(&result["request_sha256"])? == Digest32::of_bytes(&raw),
            "process response binding"
        );
        self.verify_evidence(&result["evidence"])?;
        Ok(result)
    }
}

#[derive(Clone)]
pub(super) struct ProcessControl {
    pub(super) driver: Driver,
    pub(super) executions: Arc<AtomicUsize>,
    pub(super) manifest: CellBackendManifestV2,
    retained: Option<CellGenerationProposalV2>,
}

impl ProcessControl {
    pub(super) fn new(driver: Driver, manifest: CellBackendManifestV2) -> Self {
        Self {
            driver,
            executions: Arc::new(AtomicUsize::new(0)),
            manifest,
            retained: None,
        }
    }

    pub(super) fn model_request(&self, request: &CellGenerationRequestV2) -> anyhow::Result<Value> {
        Ok(
            json!({"inputs":serde_json::from_slice::<Value>(&request.input)?,
            "selected_adapter":self.driver.prepared["parent"]["adapter"],
            "native_request_digest":Digest32::from_array(request.digest()?).to_string()}),
        )
    }

    fn execute(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> anyhow::Result<CellGenerationProposalV2> {
        anyhow::ensure!(
            manifest == &self.manifest,
            "actual process manifest differs from admitted owner"
        );
        let started = Instant::now();
        self.executions.fetch_add(1, Ordering::SeqCst);
        let response = self.driver.run(
            "probe",
            self.model_request(request)?,
            Some(request.deadline_micros),
        )?;
        let output = &response["result"];
        anyhow::ensure!(
            digest(&output["selected_adapter"])?
                == digest(&self.driver.prepared["parent"]["adapter"])?
                && digest(&output["selected_file_sha256"])?
                    == digest(&self.driver.prepared["parent"]["file_sha256"])?
                && digest(&output["native_request_digest"])?
                    == Digest32::from_array(request.digest()?)
                && output["new_forward_calls"] == 1,
            "actual retained model result differs"
        );
        let identity = CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        };
        let mut cost = CellTaskCostV2::new(identity)?;
        cost.record(CellCostEntryV2 {
            event_id: Digest32::of_parts(&[
                b"hepta.research.actual-smollm-process.v1\0",
                &request.digest()?,
            ])
            .into_array(),
            identity,
            stage: CellCostStageV2::Inference,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(u64::try_from(started.elapsed().as_micros())?),
                ..CellCostMetricsV2::default()
            },
        })?;
        let proposal = CellGenerationProposalV2 {
            request_digest: request.digest()?,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: request.input.clone(),
            output_delta: serde_json::to_vec(output)?,
            disposition: CellGenerationDispositionV2::Stopped,
            cost,
        };
        self.retained = Some(proposal.clone());
        Ok(proposal)
    }
}

impl CellGenerationControlPortV2 for ProcessControl {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.execute(manifest, request).map_err(|error| {
            eprintln!("actual research model process refused: {error:#}");
            CellGenerationErrorV2::Unavailable
        })
    }
    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        let expected = request.digest()?;
        Ok(self
            .retained
            .as_ref()
            .filter(|value| value.request_digest == expected)
            .cloned())
    }
    fn cancel_generation(
        &mut self,
        _request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        // This synchronous test port is bounded by timeout's process-group
        // watchdog. It never treats an uncertain effect as permission to retry.
        Err(CellGenerationErrorV2::Unavailable)
    }
}
