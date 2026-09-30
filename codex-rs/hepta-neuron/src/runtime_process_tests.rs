//! Real child-process exits at durable transaction cuts. This proves process
//! reopen, not physical power-loss durability or independent model efficacy.
use super::*;
use crate::FileAnchorWitnessStore;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

struct CountedModel {
    inner: FakeModel,
    calls: PathBuf,
}
impl NeuronModelPort for CountedModel {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.calls)
            .map_err(|_| NeuronModelError::Unavailable)?;
        file.write_all(b"called\n")
            .map_err(|_| NeuronModelError::Unavailable)?;
        file.sync_all().map_err(|_| NeuronModelError::Unavailable)?;
        self.inner.execute(request)
    }
}

struct ExitWitness {
    inner: FileAnchorWitnessStore,
    cut: String,
}
impl AnchorWitnessStore for ExitWitness {
    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        self.inner.admit_new_anchor(expected)
    }
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.cut == "journal" {
            std::process::exit(73);
        }
        self.inner.compare_and_swap(expected, next)?;
        if self.cut == "witness" {
            std::process::exit(73);
        }
        Ok(())
    }
}

#[test]
fn durable_process_crash_matrix() {
    if let Some(root) = std::env::var_os("HEPTA_NEURON_CRASH_ROOT") {
        let fixture = Fixture(PathBuf::from(root));
        let cut = std::env::var("HEPTA_NEURON_CRASH_CUT").expect("cut");
        let native = native_config();
        let config = runtime_config(&native);
        let witness = checked(FileAnchorWitnessStore::open(
            fixture.named_file("witness"),
            scope(),
            native.generation,
            /*max_records*/ 16,
        ));
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(),
            fixture.operations(),
            native,
            scope(),
            /*max_records*/ 16,
            /*max_operations*/ 16,
            config,
            ExitWitness {
                inner: witness,
                cut: cut.clone(),
            },
        ));
        // Persist fixture directory entries as well as the stores' own headers.
        checked(checked(File::open(&fixture.0)).sync_all());
        if cut == "bootstrap" {
            std::process::exit(73);
        }
        if cut == "prepared" {
            runtime.operations.fail_next_append_after_sync();
        }
        let mut model = CountedModel {
            inner: FakeModel::new(),
            calls: fixture.0.join("calls"),
        };
        let result = runtime.tick(&mut model, input(1, Digest32::ZERO));
        if cut == "prepared" {
            assert!(matches!(
                result,
                Err(NeuronRuntimeError::Operation(
                    OperationStoreError::Indeterminate
                ))
            ));
        } else {
            checked(result);
        }
        // No destructors/unlocks execute. Kernel process teardown releases locks.
        std::process::exit(73);
    }
    for cut in ["bootstrap", "prepared", "journal", "witness", "complete"] {
        let fixture = Fixture::new();
        let mut child = checked(
            Command::new(checked(std::env::current_exe()))
                .arg("--exact")
                .arg("runtime::tests::process::durable_process_crash_matrix")
                .arg("--nocapture")
                .env("HEPTA_NEURON_CRASH_ROOT", &fixture.0)
                .env("HEPTA_NEURON_CRASH_CUT", cut)
                .stdout(Stdio::null())
                .stderr(Stdio::inherit())
                .spawn(),
        );
        let started = Instant::now();
        let status = loop {
            if let Some(status) = checked(child.try_wait()) {
                break status;
            }
            if started.elapsed() > Duration::from_secs(30) {
                let _ = child.kill();
                let _ = child.wait();
                panic!("child process did not reach {cut} cut");
            }
            std::thread::sleep(Duration::from_millis(10));
        };
        assert_eq!(status.code(), Some(73), "cut={cut}");
        let native = native_config();
        let config = runtime_config(&native);
        let before = {
            let operations = checked(FileNeuronOperationStore::open_existing(
                fixture.operations(),
                checked(config.semantic_digest()),
                scope(),
                native.generation,
                native.width,
                /*max_operations*/ 16,
            ));
            checked(operations.find_tick(&input(1, Digest32::ZERO).tick_id))
                .map(|value| value.output)
        };
        assert_eq!(before.is_some(), cut != "bootstrap");
        let witness = checked(FileAnchorWitnessStore::open(
            fixture.named_file("witness"),
            scope(),
            native.generation,
            /*max_records*/ 16,
        ));
        let mut runtime = checked(NeuronRuntime::recover(
            fixture.file(),
            fixture.operations(),
            native,
            scope(),
            /*max_records*/ 16,
            /*max_operations*/ 16,
            config,
            witness,
        ));
        let mut model = CountedModel {
            inner: FakeModel::new(),
            calls: fixture.0.join("calls"),
        };
        let output = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
        if let Some(before) = before {
            assert_eq!(output, before);
        }
        assert_eq!(
            checked(runtime.tick(&mut model, input(1, Digest32::ZERO))),
            output
        );
        assert_eq!(checked(fs::read(fixture.0.join("calls"))), b"called\n");
    }
}
