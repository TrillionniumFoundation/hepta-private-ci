// The worker is split into bounded source units that compile as one binary
// crate. The generated source registry hashes every part and this loader.
include!("worker_parts/00_core.rs");
include!("worker_parts/10_dispatch.rs");
include!("worker_parts/20_runtime.rs");
include!("worker_parts/30_protocol_bridge.rs");
include!("worker_parts/40_observation_helpers.rs");
include!("worker_parts/50_validation_tests.rs");
