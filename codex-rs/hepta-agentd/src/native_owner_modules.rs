// Same original owners, with statically selected Native configuration/lifecycle wrappers.
#[path = "config_native.rs"]
mod config;
#[path = "control_native.rs"]
mod control;
#[path = "objective_runtime_native.rs"]
mod objective_runtime;
#[path = "production_writer_native.rs"]
mod production_writer_host;
#[path = "state_native.rs"]
mod state;

include!("shared_owner_modules.rs");
