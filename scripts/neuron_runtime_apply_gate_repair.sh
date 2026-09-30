#!/usr/bin/env bash
set -euo pipefail

branch="codex/neuron-runtime-five-phase-closure-v2"
workflow=".github/workflows/neuron-runtime-gate-fix-once.yml"
script="scripts/neuron_runtime_apply_gate_repair.sh"

if [[ -n "${GITHUB_SHA:-}" ]]; then
  test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"
fi
test -z "$(git status --porcelain --untracked-files=all)"

python3 - <<'PY'
from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    file = Path(path)
    value = file.read_text()
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    file.write_text(value.replace(old, new))


def append_once(path: str, marker: str, value: str) -> None:
    file = Path(path)
    current = file.read_text()
    if marker not in current:
        file.write_text(current.rstrip() + "\n\n" + value.strip() + "\n")


# Preserve the already-reviewed MSRV and macOS portability repair in the final
# immutable source candidate. This migration is the last writer; qualification
# workflows that remain after it are read-only.
replace(
    "codex-rs/hepta-infer-core/Cargo.toml",
    "[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }\nserde = { workspace = true, features = [\"derive\"] }\nserde_json = { workspace = true }\n",
    "[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }\nfs2 = \"0.4.3\"\nserde = { workspace = true, features = [\"derive\"] }\nserde_json = { workspace = true }\n",
)
replace(
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "use std::path::Path;\nuse std::path::PathBuf;\n",
    "use std::path::Path;\nuse std::path::PathBuf;\n\nuse fs2::FileExt;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "        file.try_lock().map_err(|_| Error::WriterUnavailable)?;\n",
    "        file.try_lock_exclusive()\n            .map_err(|_| Error::WriterUnavailable)?;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "use std::fs::OpenOptions;\nuse std::fs::TryLockError;\n",
    "use std::fs::OpenOptions;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "use std::str::FromStr;\n\nuse codex_hepta_types::AuthorityPosture;\n",
    "use std::str::FromStr;\n\nuse fs2::FileExt;\n\nuse codex_hepta_types::AuthorityPosture;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "        match file.try_lock() {\n            Ok(()) => Ok(Self(file)),\n            Err(TryLockError::WouldBlock) => Err(NeuronFeatureStoreError::Busy),\n            Err(TryLockError::Error(error)) => Err(error.into()),\n        }\n",
    "        match file.try_lock_exclusive() {\n            Ok(()) => Ok(Self(file)),\n            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {\n                Err(NeuronFeatureStoreError::Busy)\n            }\n            Err(error) => Err(error.into()),\n        }\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "        let _ = self.0.unlock();\n",
    "        let _ = FileExt::unlock(&self.0);\n",
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        ServerNotification::AgentMessageDelta(delta)
            if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
        {
            if delta.delta.len() > MAX_OUTPUT_BYTES.saturating_sub(output.output.len()) {
                return Err("output byte limit exceeded".to_string());
            }
            output.output.push_str(&delta.delta);
        }
        ServerNotification::ThreadTokenUsageUpdated(usage)
''',
    '''        ServerNotification::AgentMessageDelta(delta)
            if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
        {
            if delta.delta.len() > MAX_OUTPUT_BYTES.saturating_sub(output.output.len()) {
                return Err("output byte limit exceeded".to_string());
            }
            output.output.push_str(&delta.delta);
        }
        ServerNotification::ItemCompleted(completed)
            if completed.thread_id == output.thread_id
                && completed.turn_id == output.turn_id =>
        {
            if let ThreadItem::AgentMessage { text, .. } = &completed.item
                && output.output.is_empty()
            {
                if text.len() > MAX_OUTPUT_BYTES {
                    return Err("output byte limit exceeded".to_string());
                }
                output.output.push_str(text);
            }
        }
        ServerNotification::ThreadTokenUsageUpdated(usage)
''',
)

# Materialize the daemon-owned V2 product boundary in ordinary Rust source.
Path("codex-rs/hepta-agentd/src/neuron_runtime_v2_product.rs").write_text(r'''/// Host-owned builder for the exact V2 Neuron tick bound to a canonical
/// intelligence request. Request bytes cannot install or replace this provider.
pub trait AgentdNeuronTickProviderV2: Send + Sync {
    fn build_tick(
        &self,
        identity: &crate::AgentdIdentity,
        record: &codex_hepta_learning_ledger::RunStartRecordV1,
        invocation: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, crate::AgentdError>;
}

/// One explicitly supplied active generation plus sealed historical
/// generations. Constructing this value does not start service; Agentd owns
/// recovery and activation when its normal daemon lifecycle starts.
pub struct AgentdNeuronRuntimeV2Config {
    active: AgentdNeuronHandleV2,
    retained: Vec<AgentdNeuronHandleV2>,
    control_state_path: PathBuf,
    tick_provider: Arc<dyn AgentdNeuronTickProviderV2>,
}

impl AgentdNeuronRuntimeV2Config {
    pub fn new(
        active: AgentdNeuronHandleV2,
        control_state_path: PathBuf,
        tick_provider: Arc<dyn AgentdNeuronTickProviderV2>,
    ) -> Result<Self, crate::AgentdError> {
        if !control_state_path.is_absolute() || control_state_path.file_name().is_none() {
            return Err(crate::AgentdError::Invalid(
                "Neuron V2 control-state path must be an absolute file path".to_string(),
            ));
        }
        Ok(Self {
            active,
            retained: Vec::new(),
            control_state_path,
            tick_provider,
        })
    }

    #[must_use]
    pub fn with_retained_generation(mut self, retained: AgentdNeuronHandleV2) -> Self {
        self.retained.push(retained);
        self
    }

    pub(crate) fn start(self) -> Result<Arc<AgentdNeuronRuntimeV2Host>, crate::AgentdError> {
        let controller = AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            self.active,
            self.retained,
            self.control_state_path,
        )
        .map_err(|error| neuron_product_error("recover controller", error))?;
        controller
            .start()
            .map_err(|error| neuron_product_error("start controller", error))?;
        Ok(Arc::new(AgentdNeuronRuntimeV2Host {
            controller,
            tick_provider: self.tick_provider,
            lifecycle: Mutex::new(()),
            stopped: AtomicBool::new(false),
        }))
    }
}

/// The sole process owner for V2 execution and lifecycle transitions. Request
/// handlers receive only prepared invocations; they cannot mutate generations.
pub struct AgentdNeuronRuntimeV2Host {
    controller: AgentdNeuronGenerationControllerV2,
    tick_provider: Arc<dyn AgentdNeuronTickProviderV2>,
    lifecycle: Mutex<()>,
    stopped: AtomicBool,
}

impl AgentdNeuronRuntimeV2Host {
    pub(crate) fn prepare(
        &self,
        identity: &crate::AgentdIdentity,
        record: &codex_hepta_learning_ledger::RunStartRecordV1,
        invocation: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<AgentdNeuronInvocationV2, crate::AgentdError> {
        if self.stopped.load(Ordering::Acquire) {
            return Err(crate::AgentdError::Protocol(
                "Neuron V2 runtime is stopped".to_string(),
            ));
        }
        let input = self.tick_provider.build_tick(identity, record, invocation)?;
        let snapshot = &invocation.request.snapshot;
        let mut body = b"hepta.agentd.intelligence-body.v1\0".to_vec();
        body.extend_from_slice(snapshot.digest().as_array());
        body.extend_from_slice(&snapshot.body_generation().get().to_be_bytes());
        let runtime_body_digest = Digest32::of_bytes(&body);
        self.controller
            .prepare(
                invocation.request.run_id.clone(),
                runtime_body_digest,
                input,
            )
            .map_err(|error| neuron_product_error("prepare invocation", error))
    }

    pub(crate) fn begin_quiesce(&self) -> Result<(), crate::AgentdError> {
        let _lifecycle = self.lifecycle.lock().map_err(|_| {
            crate::AgentdError::Protocol("Neuron V2 lifecycle lock poisoned".to_string())
        })?;
        match self
            .controller
            .state()
            .map_err(|error| neuron_product_error("read controller state", error))?
        {
            AgentdNeuronLifecycleStateV2::Serving => self
                .controller
                .begin_quiesce()
                .map_err(|error| neuron_product_error("begin quiesce", error)),
            AgentdNeuronLifecycleStateV2::Quiescing
            | AgentdNeuronLifecycleStateV2::Sealed
            | AgentdNeuronLifecycleStateV2::Stopped => Ok(()),
            state => Err(crate::AgentdError::Protocol(format!(
                "Neuron V2 cannot quiesce from {state:?}"
            ))),
        }
    }

    pub(crate) fn shutdown(&self) -> Result<(), crate::AgentdError> {
        if self.stopped.load(Ordering::Acquire) {
            return Ok(());
        }
        let _lifecycle = self.lifecycle.lock().map_err(|_| {
            crate::AgentdError::Protocol("Neuron V2 lifecycle lock poisoned".to_string())
        })?;
        if self.stopped.load(Ordering::Acquire) {
            return Ok(());
        }
        self.controller
            .shutdown()
            .map_err(|error| neuron_product_error("shutdown controller", error))?;
        self.stopped.store(true, Ordering::Release);
        Ok(())
    }
}

impl Drop for AgentdNeuronRuntimeV2Host {
    fn drop(&mut self) {
        if !self.stopped.load(Ordering::Acquire) {
            let _ = self.controller.shutdown();
        }
    }
}

fn neuron_product_error(
    operation: &str,
    error: AgentdNeuronControlErrorV2,
) -> crate::AgentdError {
    crate::AgentdError::Protocol(format!(
        "Neuron V2 {operation} failed [{}]: {error}",
        error.stable_code()
    ))
}
''')

replace(
    "codex-rs/hepta-agentd/src/neuron_runtime_v2.rs",
    'include!("neuron_runtime_v2_modules.rs");\n#[path = "neuron_runtime_v2_decision_cell.rs"]\n',
    'include!("neuron_runtime_v2_modules.rs");\ninclude!("neuron_runtime_v2_product.rs");\n#[path = "neuron_runtime_v2_decision_cell.rs"]\n',
)

replace(
    "codex-rs/hepta-agentd/src/config.rs",
    '''    intelligence_invocation_provider:
        Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
}''',
    '''    intelligence_invocation_provider:
        Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
    neuron_runtime_v2: Option<crate::neuron_runtime_v2::AgentdNeuronRuntimeV2Config>,
}''',
)
replace(
    "codex-rs/hepta-agentd/src/config.rs",
    '''            intelligence_product_runner: None,
            intelligence_invocation_provider: None,
        })''',
    '''            intelligence_product_runner: None,
            intelligence_invocation_provider: None,
            neuron_runtime_v2: None,
        })''',
)
replace(
    "codex-rs/hepta-agentd/src/config.rs",
    '''    pub(crate) fn intelligence_invocation_provider(
        &self,
    ) -> Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>> {
        self.intelligence_invocation_provider.clone()
    }

    pub fn identity(&self) -> &AgentdIdentity {''',
    '''    pub(crate) fn intelligence_invocation_provider(
        &self,
    ) -> Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>> {
        self.intelligence_invocation_provider.clone()
    }

    /// Attach the single daemon-owned V2 Neuron runtime. The ordinary process
    /// environment path never manufactures model, storage or tick authority.
    pub fn with_neuron_runtime_v2(
        mut self,
        runtime: crate::neuron_runtime_v2::AgentdNeuronRuntimeV2Config,
    ) -> Result<Self, AgentdError> {
        if self.neuron_runtime_v2.is_some() {
            return Err(AgentdError::Invalid(
                "Neuron V2 runtime already configured".to_string(),
            ));
        }
        self.neuron_runtime_v2 = Some(runtime);
        Ok(self)
    }

    pub(crate) fn take_neuron_runtime_v2(
        &mut self,
    ) -> Option<crate::neuron_runtime_v2::AgentdNeuronRuntimeV2Config> {
        self.neuron_runtime_v2.take()
    }

    pub fn identity(&self) -> &AgentdIdentity {''',
)

replace(
    "codex-rs/hepta-agentd/src/state.rs",
    '''    pub(crate) intelligence_invocation:
        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
    pub(crate) cognitive_ranker:''',
    '''    pub(crate) intelligence_invocation:
        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
    pub(crate) neuron_runtime_v2:
        std::sync::OnceLock<Arc<crate::neuron_runtime_v2::AgentdNeuronRuntimeV2Host>>,
    pub(crate) cognitive_ranker:''',
)
replace(
    "codex-rs/hepta-agentd/src/state.rs",
    '''            intelligence_product: std::sync::OnceLock::new(),
            intelligence_invocation: std::sync::OnceLock::new(),
            evidence:''',
    '''            intelligence_product: std::sync::OnceLock::new(),
            intelligence_invocation: std::sync::OnceLock::new(),
            neuron_runtime_v2: std::sync::OnceLock::new(),
            evidence:''',
)
replace(
    "codex-rs/hepta-agentd/src/state.rs",
    '''        let invocation = provider.build(&self.identity, record)?;
        invocation.validate(&self.identity, record)?;

        // Freeze only the small immutable composition while holding the run''',
    '''        let invocation = provider.build(&self.identity, record)?;
        invocation.validate(&self.identity, record)?;
        let durable_neuron_v2 = self
            .neuron_runtime_v2
            .get()
            .map(|host| host.prepare(&self.identity, record, &invocation))
            .transpose()?;

        // Freeze only the small immutable composition while holding the run''',
)
replace(
    "codex-rs/hepta-agentd/src/state.rs",
    '''        let outcome = runner
            .prepare_for_composition(&composition, invocation.request, invocation.inputs)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "canonical intelligence preparation failed: {error}"
                ))
            })?;''',
    '''        let outcome = match durable_neuron_v2 {
            Some(neuron) => {
                runner
                    .prepare_for_composition_with_durable_neuron_v2(
                        &composition,
                        invocation.request,
                        invocation.inputs,
                        neuron,
                    )
                    .await
            }
            None => {
                runner
                    .prepare_for_composition(
                        &composition,
                        invocation.request,
                        invocation.inputs,
                    )
                    .await
            }
        }
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "canonical intelligence preparation failed: {error}"
            ))
        })?;''',
)

replace(
    "codex-rs/hepta-agentd/src/runtime.rs",
    '''    let intelligence_product = config.intelligence_product_runner();
    let intelligence_invocation = config.intelligence_invocation_provider();
    let (identity, registry, writer_lock) = config.into_parts();''',
    '''    let intelligence_product = config.intelligence_product_runner();
    let intelligence_invocation = config.intelligence_invocation_provider();
    let neuron_runtime_v2 = config.take_neuron_runtime_v2();
    if neuron_runtime_v2.is_some()
        && (intelligence_product.is_none() || intelligence_invocation.is_none())
    {
        return Err(AgentdError::Invalid(
            "Neuron V2 requires the canonical intelligence runner and invocation provider"
                .to_string(),
        ));
    }
    let neuron_runtime_v2 = neuron_runtime_v2
        .map(crate::neuron_runtime_v2::AgentdNeuronRuntimeV2Config::start)
        .transpose()?;
    let (identity, registry, writer_lock) = config.into_parts();''',
)
replace(
    "codex-rs/hepta-agentd/src/runtime.rs",
    '''    if let Some(provider) = intelligence_invocation {
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
    }
    if let Some(current) = retrieval_context {''',
    '''    if let Some(provider) = intelligence_invocation {
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
    }
    if let Some(host) = neuron_runtime_v2.as_ref() {
        state
            .neuron_runtime_v2
            .set(Arc::clone(host))
            .map_err(|_| AgentdError::Invalid("Neuron V2 host already attached".to_string()))?;
    }
    if let Some(current) = retrieval_context {''',
)
replace(
    "codex-rs/hepta-agentd/src/runtime.rs",
    '''    if let Err(error) = startup {
        tasks.shutdown().await;
        return Err(error);
    }
    tasks
        .run_until(async move {
            shutdown_signal().await?;
            // Keep control and owner reconciliation alive throughout drain.
            drain_runtime(state).await
        })
        .await
}''',
    '''    if let Err(error) = startup {
        tasks.shutdown().await;
        if let Some(host) = neuron_runtime_v2.as_ref()
            && let Err(shutdown_error) = host.shutdown()
        {
            return Err(AgentdError::Protocol(format!(
                "Agentd startup failed: {error}; Neuron V2 shutdown also failed: {shutdown_error}"
            )));
        }
        return Err(error);
    }
    let runtime_result = tasks
        .run_until(async move {
            shutdown_signal().await?;
            // Keep control and owner reconciliation alive throughout drain.
            drain_runtime(state).await
        })
        .await;
    let neuron_shutdown = neuron_runtime_v2
        .as_ref()
        .map(|host| host.shutdown())
        .transpose();
    match (runtime_result, neuron_shutdown) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) => Err(error),
        (Ok(()), Err(error)) => Err(error),
        (Err(runtime_error), Err(neuron_error)) => Err(AgentdError::Protocol(format!(
            "Agentd runtime failed: {runtime_error}; Neuron V2 shutdown also failed: {neuron_error}"
        ))),
    }
}''',
)
replace(
    "codex-rs/hepta-agentd/src/runtime.rs",
    '''async fn drain_runtime(state: Arc<AgentdState>) -> Result<(), AgentdError> {
    state.mark_draining()?;''',
    '''async fn drain_runtime(state: Arc<AgentdState>) -> Result<(), AgentdError> {
    if let Some(host) = state.neuron_runtime_v2.get() {
        host.begin_quiesce()?;
    }
    state.mark_draining()?;''',
)

replace(
    "codex-rs/hepta-agentd/src/lib.rs",
    '''pub use neuron_runtime_v2::AgentdNeuronOwnerV2;
pub use neuron_runtime_v2::AgentdNeuronRecoveryReportV2;''',
    '''pub use neuron_runtime_v2::AgentdNeuronOwnerV2;
pub use neuron_runtime_v2::AgentdNeuronRecoveryReportV2;
pub use neuron_runtime_v2::AgentdNeuronRuntimeV2Config;
pub use neuron_runtime_v2::AgentdNeuronRuntimeV2Host;
pub use neuron_runtime_v2::AgentdNeuronTickProviderV2;''',
)

# Collapse the legacy documentation/map fork into one generated fact chain.
Path("docs/modules/neuron.runtime/IMPLEMENTATION_MAP.json").write_text('''{
  "schemaVersion": 1,
  "status": "compatibility-pointer",
  "sourceOfTruth": "MODULE_SPEC.json",
  "canonicalGeneratedMap": "IMPLEMENTATION_MAP.generated.json",
  "note": "This file intentionally contains no implementation facts. Generate the canonical map from MODULE_SPEC.json."
}
''')
append_once(
    "docs/modules/neuron.runtime/TECHNICAL.md",
    "## Canonical Agentd V2 product ownership",
    '''## Canonical Agentd V2 product ownership

The ordinary Agentd source path owns V2 through `AgentdNeuronRuntimeV2Config`.
`runtime::run` recovers and starts exactly one controller, attaches the resulting
host to `AgentdState`, routes canonical intelligence through a prepared V2
invocation, begins quiesce before daemon drain, and seals/stops the controller
before process exit. Request input cannot select the runtime, generation,
control-state path, or tick provider. Compatibility mode is explicit absence of
the V2 config; a configured V2 runtime never silently falls back to V1.

`MODULE_SPEC.json` is the sole handwritten module specification and
`IMPLEMENTATION_MAP.generated.json` is its generated implementation projection.
The legacy `IMPLEMENTATION_MAP.json` is only a compatibility pointer and carries
no independent readiness or source facts.''',
)
append_once(
    "docs/modules/neuron.runtime/V2_DEVELOPMENT.md",
    "## Daemon product-path closure",
    '''## Daemon product-path closure

V2 is installed only by the embedding that constructs `AgentdConfig`. Startup
fails closed unless the canonical product runner and host-owned invocation
provider are also present. The daemon, not a request handler, performs control
state recovery, lifecycle activation, quiesce, seal and shutdown. All
qualification after this migration runs against immutable source and has
read-only repository permissions.''',
)

legacy_patch = Path(".github/neuron-agentd-integration.patch")
if legacy_patch.exists():
    legacy_patch.unlink()

# Every surviving neuron qualification workflow is read-only. The migration
# workflow itself is removed after successful checks below.
for path in sorted(Path(".github/workflows").glob("*neuron*.yml")):
    if path.as_posix() == workflow:
        continue
    value = path.read_text()
    if "contents: write" in value:
        path.write_text(value.replace("contents: write", "contents: read"))

for path in sorted(Path(".github/workflows").glob("*neuron*.yml")):
    if path.as_posix() != workflow and "contents: write" in path.read_text():
        raise SystemExit(f"mutable neuron qualification workflow remains: {path}")

# The source assertions prove that the V2 path cannot silently regress to a
# component-only implementation.
checks = {
    "codex-rs/hepta-agentd/src/config.rs": (
        "with_neuron_runtime_v2",
        "take_neuron_runtime_v2",
    ),
    "codex-rs/hepta-agentd/src/runtime.rs": (
        "AgentdNeuronRuntimeV2Config::start",
        "host.begin_quiesce()?",
        "host.shutdown()",
    ),
    "codex-rs/hepta-agentd/src/state.rs": (
        "prepare_for_composition_with_durable_neuron_v2",
        "neuron_runtime_v2",
    ),
}
for path, needles in checks.items():
    value = Path(path).read_text()
    for needle in needles:
        if needle not in value:
            raise SystemExit(f"{path}: missing product-path closure marker {needle}")
PY

rustup toolchain install stable --profile minimal --component rustfmt
rustup toolchain install 1.88.0 --profile minimal
(
  cd codex-rs
  cargo +stable fmt --all
  cargo +stable check -p codex-hepta-agentd -p codex-hepta-infer-core -p codex-hepta-infer-worker-host
  cargo +1.88.0 check -p codex-hepta-agentd -p codex-hepta-infer-core -p codex-hepta-infer-worker-host
  cargo +stable test -p codex-hepta-agentd neuron_runtime_v2 --lib -- --nocapture
  cargo +stable test -p codex-hepta-infer-worker-host native_app_server -- --nocapture
)
python3 -m unittest discover -v -s scripts/neuron -p 'test_*.py'
git diff --check

rm -f "$workflow" "$script"

python3 - <<'PY'
import subprocess
from pathlib import Path

lines = subprocess.check_output(
    ["git", "status", "--porcelain=v1", "--untracked-files=all"], text=True
).splitlines()
paths = {line[3:] for line in lines if len(line) >= 4}
allowed_exact = {
    ".github/neuron-agentd-integration.patch",
    ".github/workflows/neuron-runtime-gate-fix-once.yml",
    "codex-rs/Cargo.lock",
    "codex-rs/hepta-agentd/src/config.rs",
    "codex-rs/hepta-agentd/src/lib.rs",
    "codex-rs/hepta-agentd/src/neuron_runtime_v2.rs",
    "codex-rs/hepta-agentd/src/neuron_runtime_v2_product.rs",
    "codex-rs/hepta-agentd/src/runtime.rs",
    "codex-rs/hepta-agentd/src/state.rs",
    "codex-rs/hepta-infer-core/Cargo.toml",
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "docs/modules/neuron.runtime/IMPLEMENTATION_MAP.json",
    "docs/modules/neuron.runtime/TECHNICAL.md",
    "docs/modules/neuron.runtime/V2_DEVELOPMENT.md",
    "scripts/neuron_runtime_apply_gate_repair.sh",
}
allowed_prefixes = (".github/workflows/neuron",)
unexpected = sorted(
    path for path in paths
    if path not in allowed_exact and not path.startswith(allowed_prefixes)
)
if unexpected:
    raise SystemExit(f"unexpected migration changes: {unexpected}")
required = {
    ".github/neuron-agentd-integration.patch",
    ".github/workflows/neuron-runtime-gate-fix-once.yml",
    "codex-rs/hepta-agentd/src/config.rs",
    "codex-rs/hepta-agentd/src/neuron_runtime_v2_product.rs",
    "codex-rs/hepta-agentd/src/runtime.rs",
    "codex-rs/hepta-agentd/src/state.rs",
    "docs/modules/neuron.runtime/IMPLEMENTATION_MAP.json",
    "scripts/neuron_runtime_apply_gate_repair.sh",
}
missing = sorted(required - paths)
if missing:
    raise SystemExit(f"expected migration changes absent: {missing}")
for path in Path(".github/workflows").glob("*neuron*.yml"):
    if "contents: write" in path.read_text():
        raise SystemExit(f"mutable qualification workflow remains after migration: {path}")
print("bounded V2 product-path migration:")
for path in sorted(paths):
    print(path)
PY

test -z "$(git diff --check)"
git config user.name hepta-qualification
git config user.email qualification@invalid
git add -A
git commit -m "feat(neuron): own V2 runtime in agentd lifecycle"
git push origin "HEAD:${branch}"
