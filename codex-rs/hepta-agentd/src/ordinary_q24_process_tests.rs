//! Ordinary binary process qualification. Private setup modules provide
//! explicit input data; no setup routine certifies a task or learning result.

#[path = "ordinary_q24_process_deployment_tests.rs"]
mod deployment;
#[path = "ordinary_q24_process_fixture_tests.rs"]
mod fixture;
#[path = "ordinary_q24_process_inputs_tests.rs"]
mod inputs;
#[path = "ordinary_q24_process_launch_tests.rs"]
mod launch;
#[path = "ordinary_q24_process_root_tests.rs"]
mod root;

