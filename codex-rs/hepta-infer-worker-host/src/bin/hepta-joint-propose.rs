//! Pure proposal process for the explicitly selected Linux FP64 JointGenerator.
//! It writes only unpublished proposals; the admitted host retains every Cell owner.

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
#[path = "../joint_generation/resident.rs"]
mod resident;
#[cfg(target_os = "linux")]
#[path = "../joint_generation/state.rs"]
pub mod state;

fn main() {
    #[cfg(target_os = "linux")]
    let result = match std::env::args_os().skip(1).collect::<Vec<_>>().as_slice() {
        [] => proposal::run_stdio(),
        [argument] if argument == "--resident-v1" => resident::run_stdio(),
        _ => Err("unknown proposal transport arguments".into()),
    };
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
