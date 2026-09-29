//! Agentd ownership boundary for the unified V2 Neuron runtime.
//!
//! Product construction requires a durable inference-control port. The shared
//! handle exposes guarded invocation, reconciliation-only recovery, serialized
//! administrative queries and explicit generation lifecycle control. It never
//! exposes the mutable runtime or an execution bypass.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
#[cfg(unix)]
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::RwLock;
use std::sync::RwLockReadGuard;
use std::sync::RwLockWriteGuard;
use std::sync::TryLockError;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::DurableInferenceControlModelPort;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronOperationStatusV2;
use codex_hepta_neuron::NeuronRuntimeCapacityV2;
use codex_hepta_neuron::NeuronRuntimeCommitV2;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeIndexError;
use codex_hepta_neuron::NeuronRuntimeMeasurementV2;
use codex_hepta_neuron::NeuronRuntimeV2;
use codex_hepta_neuron::NeuronRuntimeV2Error;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

include!("neuron_runtime_v2_base.rs");
include!("neuron_runtime_v2_shared.rs");
include!("neuron_runtime_v2_owner_handle.rs");
include!("neuron_runtime_v2_operational.rs");
include!("neuron_runtime_v2_errors.rs");
include!("neuron_runtime_v2_durable_state.rs");
include!("neuron_runtime_v2_controller.rs");
include!("neuron_runtime_v2_failed_recovery.rs");
include!("neuron_runtime_v2_modules.rs");
