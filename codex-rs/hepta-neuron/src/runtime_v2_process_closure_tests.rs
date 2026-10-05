//! Real subprocess exits against the actual V2 runtime, store, index and file
//! witness. The model is explicitly a deterministic durable fixture, not a
//! production-model accuracy or performance qualification.
use super::*;
use crate::FileNeuronWitnessStoreV2;
use crate::NeuronWitnessContextV2;
use std::fs::OpenOptions;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::process::ExitStatusExt;
use std::path::Path;
use std::process::Command;

struct FileModel {
    root: PathBuf,
}

impl FileModel {
    fn output(
        &self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        FakeDurableModel::new(Arc::new(AtomicUsize::new(0))).execute(request)
    }
}

impl NeuronModelPort for FileModel {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        // create_new makes a duplicate physical dispatch fail, not look like a
        // second valid execution. This fixture persists the exact request key.
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.root.join("physical-model-call"))
            .map_err(|_| NeuronModelError::Rejected)?;
        file.write_all(request.input_digest.to_string().as_bytes())
            .map_err(|_| NeuronModelError::Indeterminate)?;
        file.sync_all()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        #[cfg(unix)]
        std::fs::File::open(&self.root)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| NeuronModelError::Indeterminate)?;
        self.output(request)
    }
}

impl DurableNeuronModelPort for FileModel {
    fn reconcile(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        match fs::read_to_string(self.root.join("physical-model-call")) {
            Ok(value) if value == request.input_digest.to_string() => self
                .output(request)
                .map(Box::new)
                .map(NeuronModelResolutionV2::Observed),
            Ok(_) => Err(NeuronModelError::Indeterminate),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                Ok(NeuronModelResolutionV2::NotStarted)
            }
            Err(_) => Err(NeuronModelError::Indeterminate),
        }
    }
}

fn child_with_style(mode: &str, root: &Path, cut: &str, crash_style: &str) -> std::process::Output {
    let module = checked(module_path!().split_once("::").ok_or("test module path")).1;
    checked(
        Command::new(checked(std::env::current_exe()))
            .args([
                "--exact",
                &format!("{module}::runtime_v2_process_child"),
                "--ignored",
                "--nocapture",
            ])
            .env("HEPTA_NEURON_V2_CLOSURE_CHILD", mode)
            .env("HEPTA_NEURON_V2_CLOSURE_ROOT", root)
            .env("HEPTA_NEURON_V2_CLOSURE_CUT", cut)
            .env("HEPTA_NEURON_V2_CLOSURE_CRASH_STYLE", crash_style)
            .output(),
    )
}

fn child(mode: &str, root: &Path, cut: &str) -> std::process::Output {
    child_with_style(mode, root, cut, "exit")
}

fn assert_recovery_converges_once(fixture: &Fixture, cut: &str) {
    for _ in 0..2 {
        let resumed = child("resume", &fixture.0, "");
        assert!(
            resumed.status.success(),
            "cut={cut}: {} {}",
            String::from_utf8_lossy(&resumed.stdout),
            String::from_utf8_lossy(&resumed.stderr)
        );
    }
    assert_eq!(
        checked(fs::read_to_string(fixture.0.join("physical-model-call"))),
        checked(input(1, Digest32::ZERO).semantic_digest()).to_string()
    );
}

#[test]
fn real_process_recovery_preserves_one_physical_execution_at_each_durable_boundary() {
    for cut in [
        "after_reservation",
        "after_dispatch_fence",
        "after_model_observation",
        "after_store_commit",
        "after_index_completion",
        "after_witness_acknowledgement",
    ] {
        let fixture = Fixture::new();
        let output = child("crash", &fixture.0, cut);
        assert_eq!(
            output.status.code(),
            Some(73),
            "cut={cut}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_recovery_converges_once(&fixture, cut);
    }
}

#[cfg(unix)]
#[test]
fn sigkill_recovery_preserves_one_physical_execution_at_each_durable_boundary() {
    for cut in [
        "after_reservation",
        "after_dispatch_fence",
        "after_model_observation",
        "after_store_commit",
        "after_index_completion",
        "after_witness_acknowledgement",
    ] {
        let fixture = Fixture::new();
        let output = child_with_style("crash", &fixture.0, cut, "sigkill");
        assert_eq!(
            output.status.signal(),
            Some(9),
            "cut={cut}: code={:?} stdout={} stderr={}",
            output.status.code(),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert_recovery_converges_once(&fixture, cut);
    }
}

#[test]
#[ignore = "subprocess-only fixture; exercised by the parent crash/recovery test"]
fn runtime_v2_process_child() {
    let mode = checked(std::env::var("HEPTA_NEURON_V2_CLOSURE_CHILD"));
    let root = PathBuf::from(checked(std::env::var("HEPTA_NEURON_V2_CLOSURE_ROOT")));
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness_context = NeuronWitnessContextV2 {
        generation: native.generation,
        scope: scope(),
        key_epoch: 1,
        deletion_epoch: 1,
        max_records: 16,
    };
    let store = root.join("generation.hptngs02");
    let index = root.join("runtime-index.hptngi02");
    let witness_path = root.join("witness.hptnwv02");
    let mut runtime = if mode == "crash" {
        let witness = checked(FileNeuronWitnessStoreV2::create(
            &witness_path,
            witness_context,
        ));
        checked(NeuronRuntimeV2::bootstrap(
            &store,
            &index,
            native,
            scope(),
            config,
            body,
            store_context,
            index_context,
            witness,
        ))
    } else {
        let witness = checked(FileNeuronWitnessStoreV2::open_existing(
            &witness_path,
            witness_context,
        ));
        checked(NeuronRuntimeV2::recover(
            &store,
            &index,
            native,
            scope(),
            config,
            body,
            store_context,
            index_context,
            witness,
        ))
    };
    let mut model = FileModel { root: root.clone() };
    let receipt = checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    assert_eq!(checked(runtime.pending_witness_count()), 0);
    let identity_path = root.join("returned-operation-digest");
    if identity_path.exists() {
        assert_eq!(
            checked(fs::read_to_string(identity_path)),
            receipt.operation_digest.to_string()
        );
    } else {
        checked(fs::write(
            identity_path,
            receipt.operation_digest.to_string(),
        ));
    }
}
