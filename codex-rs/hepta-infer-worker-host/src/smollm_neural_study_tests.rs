//! Actual parent training, prospective comparison, transport and ordinary use.
//! The four study roles are separate controlled keys, not product enrollment.
use super::*;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger as ledger;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::CommandExt;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

// Reuse the unchanged ordinary process codecs, including their closed fields.
// These modules exist only in this native test, and are explicit Bazel inputs.
#[path = "../../hepta-agentd/src/cognitive_process_evaluation.rs"]
mod cognitive_process_evaluation;
#[path = "../../hepta-agentd/src/cognitive_process_evidence.rs"]
mod cognitive_process_evidence;
#[path = "../../hepta-agentd/src/cognitive_process_materials.rs"]
mod cognitive_process_materials;
#[path = "../../hepta-agentd/src/cognitive_process_product_wire.rs"]
mod cognitive_process_product_wire;
#[path = "../../hepta-agentd/src/cognitive_process_wire.rs"]
mod cognitive_process_wire;
#[path = "smollm_study_diverse_tests.rs"]
mod diverse;
#[path = "smollm_study_evaluation_tests.rs"]
mod evaluation;
#[path = "smollm_study_install_tests.rs"]
mod install;
#[path = "smollm_study_ordinary_tests.rs"]
mod ordinary;
#[path = "smollm_study_roles_tests.rs"]
mod roles;

#[derive(Clone, Copy)]
enum StudyProfile {
    OriginalV1,
    BinaryAnswerV2,
    BinaryDiverse60V3,
}

impl StudyProfile {
    fn training_source_rows(self) -> usize {
        match self {
            Self::OriginalV1 | Self::BinaryAnswerV2 => 10,
            Self::BinaryDiverse60V3 => 60,
        }
    }

    fn training_ledger_binding(self) -> Digest32 {
        digest(match self {
            Self::OriginalV1 | Self::BinaryAnswerV2 => "controlled-neural-actual-training-ledger",
            Self::BinaryDiverse60V3 => "controlled-neural-diverse60-training-ledger-v3",
        })
    }
}

fn now() -> u64 {
    roles::micros()
}

fn pin(path: &Path) -> TestResult<Value> {
    Ok(json!({"path":path,"sha256":Digest32::of_bytes(&fs::read(path)?).to_string()}))
}

fn actual_test_executable() -> TestResult<Value> {
    let path = std::env::current_exe()?;
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(&path)?;
    let before = file.metadata()?;
    let image = fs::metadata("/proc/self/exe")?;
    let maximum = 512 * 1024 * 1024;
    if !path.is_absolute()
        || !before.is_file()
        || !(4..=maximum).contains(&before.len())
        || (before.dev(), before.ino()) != (image.dev(), image.ino())
    {
        return Err("bounded actual kernel-mapped test executable required".into());
    }
    let identity = |metadata: &fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
        )
    };
    let mut header = [0; 4];
    file.read_exact(&mut header)?;
    if header != *b"\x7fELF" {
        return Err("actual native test ELF required".into());
    }
    let mut hasher = Sha256::new();
    hasher.update(header);
    let mut bytes = 4_u64;
    let mut buffer = [0; 64 * 1024];
    loop {
        let count = match file.read(&mut buffer) {
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            result => result?,
        };
        if count == 0 {
            break;
        }
        bytes += count as u64;
        if bytes > maximum {
            return Err("actual test executable exceeded size bound".into());
        }
        hasher.update(&buffer[..count]);
    }
    if bytes != before.len()
        || identity(&before) != identity(&file.metadata()?)
        || identity(&before) != identity(&fs::symlink_metadata(&path)?)
        || identity(&before) != identity(&fs::metadata("/proc/self/exe")?)
    {
        return Err("actual test executable changed while hashing".into());
    }
    Ok(
        json!({"schema":"hepta-actual-test-executable-v1","pid":std::process::id(),
        "executable":{"path":path,"bytes":bytes,"sha256":format!("{:x}",hasher.finalize())}}),
    )
}

fn save(path: &Path, value: &Value) -> TestResult<Value> {
    let bytes = serde_json::to_vec(value)?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    output.write_all(&bytes)?;
    output.sync_all()?;
    File::open(path.parent().ok_or("missing output parent")?)?.sync_all()?;
    pin(path)
}

fn read_pin(value: &Value) -> TestResult<Value> {
    let path = Path::new(value["path"].as_str().ok_or("pin path")?);
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    if !path.is_absolute()
        || !metadata.is_file()
        || !(1..=32 * 1024 * 1024).contains(&metadata.len())
    {
        return Err("bounded regular study input required".into());
    }
    let mut bytes = Vec::new();
    file.take(32 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len()
        || Digest32::of_bytes(&bytes).to_string() != value["sha256"]
    {
        return Err("study input changed".into());
    }
    Ok(serde_json::from_slice(&bytes)?)
}

struct OwnedHelper {
    child: std::process::Child,
    reaped: bool,
}
impl Drop for OwnedHelper {
    fn drop(&mut self) {
        if !self.reaped {
            let _ = rustix::process::kill_process_group(
                rustix::process::Pid::from_child(&self.child),
                rustix::process::Signal::KILL,
            );
            self.reaped = self.child.wait().is_ok();
        }
    }
}

fn helper(
    input: &NativeInput,
    script: &Path,
    request: &Value,
    root: &Path,
    seconds: u64,
) -> TestResult<()> {
    let source = script.canonicalize()?;
    let mut request = request.clone();
    request["host_parent_pid"] = json!(std::process::id());
    let config = save(&root.with_extension("input.json"), &request)?;
    let stdout = File::create(root.with_extension("stdout.log"))?;
    let stderr = File::create(root.with_extension("stderr.log"))?;
    let child = Command::new(&input.python)
        .args(["-I", "-B"])
        .arg(&source)
        .arg("--input")
        .arg(config["path"].as_str().ok_or("configuration path")?)
        .arg("--input-sha256")
        .arg(config["sha256"].as_str().ok_or("configuration hash")?)
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONUSERBASE")
        .env("PYTHONNOUSERSITE", "1")
        .stdin(Stdio::null())
        .stdout(stdout)
        .stderr(stderr)
        .process_group(/*pgroup*/ 0)
        .spawn()?;
    let mut owned = OwnedHelper {
        child,
        reaped: false,
    };
    let deadline = Instant::now() + Duration::from_secs(seconds);
    loop {
        if let Some(status) = owned.child.try_wait()? {
            owned.reaped = true;
            save(
                &root.with_extension("exit.json"),
                &json!({"input":config,"script":pin(&source)?,
                "success":status.success(),"exit_code":status.code(),"reaped":true,"guard_seconds":seconds}),
            )?;
            return if status.success() {
                Ok(())
            } else {
                Err(format!("actual study helper failed: {status}").into())
            };
        }
        if Instant::now() >= deadline {
            // This Child is still unreaped. Only its freshly owned group is signalled.
            let signal = rustix::process::kill_process_group(
                rustix::process::Pid::from_child(&owned.child),
                rustix::process::Signal::KILL,
            );
            let status = owned.child.wait();
            owned.reaped = status.is_ok();
            save(
                &root.with_extension("exit.json"),
                &json!({"input":config,"success":false,
                "failure":"campaign guard","reaped":status.is_ok(),"signal_error":signal.err().map(|e|e.to_string())}),
            )?;
            return Err("actual study helper exceeded its bounded campaign guard".into());
        }
        std::thread::sleep(Duration::from_millis(25));
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact real model, original observer and real two-node Cell binary"]
async fn real_trained_child_prospective_qualification_cell_install_next_ordinary_read()
-> TestResult<()> {
    run_study(StudyProfile::OriginalV1).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact real model, original observer and real two-node Cell binary"]
async fn real_binary_trained_child_prospective_qualification_cell_install_next_ordinary_read()
-> TestResult<()> {
    run_study(StudyProfile::BinaryAnswerV2).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact real model, original observer and real two-node Cell binary"]
async fn real_diverse_trained_child_prospective_qualification_cell_install_next_ordinary_read()
-> TestResult<()> {
    run_study(StudyProfile::BinaryDiverse60V3).await
}

async fn run_study(profile: StudyProfile) -> TestResult<()> {
    let (input, mut worker, parent_bytes) = input_and_worker("positive-parent")?;
    let root = input.output.join("n");
    fs::create_dir(&root)?;
    let executable = actual_test_executable()?;
    let executable_before = save(
        &root.join("actual-test-executable-before.json"),
        &executable,
    )?;
    let objective = digest(match profile {
        StudyProfile::OriginalV1 => {
            "hepta-real-neural-study-v1:original-ten-step-parent:future-two-windows:256-numeric-256-uppercase-each:final-holdout-512:ips-correctness:alpha-50000:superiority-0:observed-family-retention"
        }
        StudyProfile::BinaryAnswerV2 => {
            "hepta-real-neural-study-binary-v2:original-parent:ten-updates-ten-row-binary-CE:100-exposures-10-independent:exclude-067-consumed-prompt-identities:future-two-windows:256-numeric-256-uppercase-each:final-holdout-512:ips-correctness:alpha-50000:superiority-0:observed-family-retention"
        }
        StudyProfile::BinaryDiverse60V3 => diverse::OBJECTIVE,
    });
    let mut declaration = json!({"schema":"hepta-neural-study-v1-preregistered",
        "frozen_unix_micros":now(),"objective_digest":objective.to_string(),"parent_file_sha256":Digest32::of_bytes(&parent_bytes).to_string(),
        "model_training_steps":10,"future_windows":2,"tasks_per_window":512,"minimum_window_micros":1_000_000,
        "metric":"IPS binary correctness; original simultaneous cluster confidence", "alpha_ppm":50_000,
        "minimum_improvement_q32":0,"primary_window":"future-window-1","primary_holdout_rows":512,"first_window_use":"actual prospective observations and retention, excluded from primary OPE","task_rule":"each window has 256 fresh distinct adjacent integer pairs and 256 fresh uppercase tasks; each family balanced yes/no; no outcome-based resampling",
        "retention_rule":"for each of the two original training families, aggregate actual child correct count must be at least actual parent correct count across both future windows; observational gate, no population noninferiority claim",
        "training_provenance":"original 12-row offered population; exact first 10 consumed rows from unchanged ten-step schedule; one authenticated ground-truth target per consumed row, no synthetic counterfactual outcomes",
        "withdrawal_rule":"roundtrip the live scoped registry snapshot and reject any source dataset withdrawal; empty registry establishes only no active withdrawal obligation",
        "training_budget":{"wall_seconds":1800,"rss_bytes":16_u64*1024*1024*1024},
        "per_model_window_budget":{"wall_seconds":600,"rss_bytes":8_u64*1024*1024*1024},"maximum_drain_ns":100_000_000,
        "controlled_role_keys":true,"external_administrative_independence":false,"public_reward":false});
    if matches!(profile, StudyProfile::BinaryAnswerV2) {
        declaration["schema"] = json!("hepta-neural-study-binary-v2-preregistered");
        declaration["optimizer_steps"] = json!(10);
        declaration["actual_row_exposures"] = json!(100);
        declaration["independent_source_rows"] = json!(10);
        declaration["recipe"] = json!(
            "fixed-AdamW-0.002-zero-decay-ten-updates-mean-ten-row-last-prompt-original-yes-no-CE-no-EOS"
        );
        declaration["disclosed_adaptive_followup_to_known_NoGain"] = json!(true);
        declaration["previous_consumed_prompt_exclusion_sha256"] =
            json!("d2101f954f9b025d5fe0a87b73ae2d31f20eb6f989ed279a04ffe38d0932b06d");
        declaration["training_provenance"] = json!(
            "original first ten source rows and twenty authenticated ledger records; ten optimizer updates each use these same ten rows: 100 actual gradient exposures, ten independent examples"
        );
        declaration["task_rule"] = json!(
            "same original 100..9998 numeric range and uppercase word families; fresh random seed and new generation domain; exclude all 1024 previously consumed exact prompt hashes without using prior outputs or labels; each family balanced yes/no; no outcome-based resampling"
        );
    }
    if matches!(profile, StudyProfile::BinaryDiverse60V3) {
        diverse::declaration(&mut declaration)?;
    }
    let study = save(&root.join("study.json"), &declaration)?;
    let mut fixture = Fixture::with_study_objective(
        root.join("o"),
        &parent_bytes,
        Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2),
        objective,
    )?;
    let config = fixture.config("b")?;
    let identity = config.identity().clone();
    let actions = super::agentd_tests::seed_actions(&config, i64::try_from(fixture.now)?).await?;
    worker.action_completions = actions.clone();
    let worker_plan = worker.run_directory.join("session/worker-plan.json");
    let effects = root.join("parent-use");
    let initial =
        super::agentd_tests::ordinary_session(config, worker, &fixture, &effects, /*reads*/ 1)
            .await?;
    let baseline = fixture
        .service
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    let training_chain = PathBuf::from(
        std::env::var_os("HEPTA_NEURAL_STUDY_TRAINING_CHAIN")
            .ok_or("exact training source required")?,
    )
    .canonicalize()?;
    let script = PathBuf::from(
        std::env::var_os("HEPTA_NEURAL_STUDY_RUNNER").ok_or("explicit study runner required")?,
    )
    .canonicalize()?;
    let action_ids: [StableId; 2] = actions
        .keys()
        .cloned()
        .collect::<Vec<_>>()
        .try_into()
        .map_err(|_| "two actions required")?;
    let yes = actions
        .iter()
        .find(|(_, value)| value.as_str() == "yes")
        .ok_or("yes action")?
        .0
        .clone();
    let mut roles = roles::ControlledRoles::new(objective, action_ids.clone(), yes.clone());
    let plan_path = script
        .parent()
        .and_then(Path::parent)
        .ok_or("source root")?
        .join("codex-rs/hepta-learning-artifacts/profiles/smollm2-public-initial-v2.plan.json");
    let model_plan_pin = pin(&plan_path)?;
    let model_plan = read_pin(&model_plan_pin)?;
    let offered = model_plan["tasks"]
        .as_array()
        .ok_or("original model tasks")?
        .iter()
        .filter(|row| row["partition"] == "training")
        .cloned()
        .collect::<Vec<_>>();
    if offered.len() != 12 || model_plan["training_steps"] != 10 {
        return Err("unchanged original training population and schedule required".into());
    }
    let (offered, consumed) = match profile {
        StudyProfile::OriginalV1 | StudyProfile::BinaryAnswerV2 => {
            let consumed = offered[..10].to_vec();
            (offered, consumed)
        }
        StudyProfile::BinaryDiverse60V3 => {
            let rows = diverse::training_rows()?;
            (rows.clone(), rows)
        }
    };
    for row in &consumed {
        if Digest32::of_bytes(row["prompt"].as_str().ok_or("training prompt")?.as_bytes())
            .to_string()
            != row["prompt_sha256"]
            || Digest32::of_bytes(
                row["expected_output"]
                    .as_str()
                    .ok_or("training target")?
                    .as_bytes(),
            )
            .to_string()
                != row["target_output_sha256"]
            || !matches!(row["expected_output"].as_str(), Some("yes" | "no"))
        {
            return Err("actual training prompt and target bytes required".into());
        }
    }
    let (dataset, ledger) = roles.dataset(profile, &root.join("training-ledger"), &consumed);
    let training_data = save(
        &root.join("actual-training-data.json"),
        &json!({
        "schema":match profile { StudyProfile::OriginalV1 | StudyProfile::BinaryAnswerV2 => "hepta-neural-actual-training-data-v1", StudyProfile::BinaryDiverse60V3 => "hepta-neural-actual-training-data-diverse-v3" },"model_plan":model_plan_pin,
        "offered_training_rows":offered,"consumed_training_rows":consumed,"consumed_step_indices":(0..profile.training_source_rows()).collect::<Vec<_>>(),
        "source_dataset_digest":dataset.snapshot.dataset_digest.to_string(),
        "dataset_receipt":cognitive_process_evidence::DatasetSnapshotReceiptV3Raw::from(dataset.clone()),
        "ledger":pin(&root.join("training-ledger/ledger"))?,
        "row_encoding":match profile { StudyProfile::OriginalV1 | StudyProfile::BinaryAnswerV2 => "canonical original plan row; run_snapshot_digest binds each row", StudyProfile::BinaryDiverse60V3 => "canonical fixed diverse60 public row; run_snapshot_digest binds each row; original material plan unchanged" },
        "record_semantics":"one selected supervised target and authenticated correctness=1 per actual consumed row; no neural prediction claim",
        "frozen_unix_micros":now()}),
    )?;
    let training_output = root.join("trained");
    helper(
        &input,
        &script,
        &json!({"schema":match profile { StudyProfile::OriginalV1 => "hepta-neural-study-v1", StudyProfile::BinaryAnswerV2 => "hepta-neural-study-binary-v2", StudyProfile::BinaryDiverse60V3 => "hepta-neural-study-diverse-v3" },"operation":"train",
        "training_chain":training_chain,"runtime_chain":input.chain,"materials":input.materials,
        "parent":pin(&input.parent)?,"ordinary":pin(&effects.join("ordinary-session-result.json"))?,
        "study":study,"training_data":training_data,"output":training_output}),
        &root.join("train-launch"),
        /*seconds*/ 2_700,
    )?;
    let trained = read_pin(&pin(&training_output.join("training-result.json"))?)?;
    let child = read_pin(&trained["child"])?;
    if trained["training_data"] != training_data
        || trained["source_dataset_digest"] != dataset.snapshot.dataset_digest.to_string()
        || fixture
            .service
            .current_registry_view(initial_now_seconds()?)?
            .receipt()
            != baseline
    {
        return Err("training changed original CURRENT".into());
    }
    let qualified = evaluation::evaluate(
        profile,
        &input,
        &script,
        &training_chain,
        &root,
        &trained,
        &worker_plan,
        &study,
        &action_ids,
        &yes,
        &dataset,
        &ledger,
        &mut roles,
        fixture.service.withdrawal_registry(),
    )?;
    let config = super::agentd_tests::restart_stopped_config(&identity)?;
    let installed = install::install(
        profile,
        &input,
        &root,
        &mut fixture,
        &config,
        &trained,
        &child,
        &dataset,
        &ledger,
        &mut roles,
        actions.clone(),
        qualified,
    )?;
    let next =
        ordinary::read_child(config, installed, &input, actions, &root.join("next-use")).await?;
    let completed_executable = actual_test_executable()?;
    if completed_executable != executable {
        return Err("actual test executable changed during the positive loop".into());
    }
    let executable_after = save(
        &root.join("actual-test-executable-after.json"),
        &completed_executable,
    )?;
    save(
        &root.join("positive-loop-result.json"),
        &json!({"schema":match profile { StudyProfile::OriginalV1 => "hepta-real-neural-ordinary-loop-v1", StudyProfile::BinaryAnswerV2 => "hepta-real-neural-ordinary-loop-binary-v2", StudyProfile::BinaryDiverse60V3 => "hepta-real-neural-ordinary-loop-diverse-v3" },
        "parent":initial,"study":study,"training":trained,"child":child,"next":next,
        "actual_test_executable":{"before":executable_before,"after":executable_after},
        "installed_children":1,"ordinary_child_reads":1,"same_artifact_owner":true,
        "same_home_root":identity.home_root,"current_before":baseline.head_digest.to_string(),
        "current_after":fixture.service.current_registry_view(initial_now_seconds()?)?.receipt().head_digest.to_string(),
        "actual_model_training":true,"controlled_role_keys":true,"public_network_ready":false}),
    )?;
    Ok(())
}
