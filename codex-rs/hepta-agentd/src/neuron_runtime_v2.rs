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
use std::io::Read;
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

use codex_hepta_agent_components::neuron::AnchorWitnessStore;
use codex_hepta_agent_components::neuron::DecisionCellInvocationV2;
use codex_hepta_agent_components::neuron::DecisionCellRuntimeV2Error;
use codex_hepta_agent_components::neuron::DurableInferenceControlModelPort;
use codex_hepta_agent_components::neuron::DurableNeuronInferenceControlPort;
use codex_hepta_agent_components::neuron::NeuronAdmissionError;
use codex_hepta_agent_components::neuron::NeuronAdmissionGuard;
use codex_hepta_agent_components::neuron::NeuronOperationStatusV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeCapacityV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeCommitV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeConfigV1;
use codex_hepta_agent_components::neuron::NeuronRuntimeIndexError;
use codex_hepta_agent_components::neuron::NeuronRuntimeMeasurementV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeV2Error;
use codex_hepta_agent_components::neuron::NeuronTickInputV1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use serde::Deserialize;
use serde::Serialize;

include!("neuron_runtime_v2_identity.rs");
include!("neuron_runtime_v2_base.rs");
include!("neuron_runtime_v2_shared.rs");
include!("neuron_runtime_v2_owner_handle.rs");
include!("neuron_runtime_v2_operational.rs");
include!("neuron_runtime_v2_errors.rs");
include!("neuron_runtime_v2_durable_state.rs");
include!("neuron_runtime_v2_controller.rs");
include!("neuron_runtime_v2_startup_recovery.rs");
include!("neuron_runtime_v2_failed_recovery.rs");
include!("neuron_runtime_v2_modules.rs");
include!("neuron_runtime_v2_product.rs");
#[path = "neuron_runtime_v2_decision_cell.rs"]
mod decision_cell;

#[cfg(test)]
#[path = "neuron_runtime_v2_error_action_tests.rs"]
mod error_action_tests;
