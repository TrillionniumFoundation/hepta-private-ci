//! Pure proposal process for the explicitly selected Linux FP64 JointGenerator.
//! It reads one bounded request and writes one unpublished result to stdout.

#[cfg(target_os = "linux")]
#[path = "../joint_generation/bridge_state.rs"]
mod bridge_state;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/codec.rs"]
pub mod codec;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/decoder.rs"]
mod decoder;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/math.rs"]
pub mod math;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/model.rs"]
pub mod model;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/proposal.rs"]
mod proposal;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/protocol.rs"]
mod protocol;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/state.rs"]
pub mod state;

fn main() {
    #[cfg(target_os = "linux")]
    let result = proposal::run_stdio();
    #[cfg(not(target_os = "linux"))]
    let result: Result<(), String> = Err("fp64-linux-libm-v1 requires Linux".into());
    if let Err(error) = result {
        eprintln!("hepta-joint-propose: {error}");
        std::process::exit(2);
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "../joint_generation/proposal_tests.rs"]
mod tests;
