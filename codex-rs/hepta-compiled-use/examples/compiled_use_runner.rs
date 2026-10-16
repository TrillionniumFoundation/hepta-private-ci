//! Local smoke runner for the proposal-only compiled-use ABI.
//!
//! It validates and queues one click action, then demonstrates that the
//! default sandbox rejects execution.  A future product caller must provide a
//! separately reviewed sandbox implementation and capability grant.

use codex_hepta_compiled_use::ActionArgumentsV1;
use codex_hepta_compiled_use::ActionFrameV1;
use codex_hepta_compiled_use::ActionVerifierV1;
use codex_hepta_compiled_use::CapabilityGrantV1;
use codex_hepta_compiled_use::DenyByDefaultSandboxV1;
use codex_hepta_compiled_use::SandboxActionPortV1;
use codex_hepta_compiled_use::SharedMemoryQueueV1;
use codex_hepta_types::Digest32;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let grant = CapabilityGrantV1 {
        digest: Digest32::of_bytes(b"runner-grant"),
        allowed: 1 | 2 | 4 | 8 | 16,
    };
    let verifier = ActionVerifierV1 {
        generation: 1,
        grant,
    };
    let action = ActionFrameV1 {
        generation: 1,
        sequence: 1,
        capability_digest: grant.digest,
        arguments: ActionArgumentsV1::Click {
            target_digest: Digest32::of_bytes(b"element"),
            x: 1,
            y: 1,
        },
    };
    let mut queue = SharedMemoryQueueV1::new(verifier, 8)?;
    queue.push(action.clone())?;
    let verified = queue.pop()?;
    let mut sandbox = DenyByDefaultSandboxV1;
    let result = sandbox.submit(verified);
    println!(
        "queued_click={:?} sandbox_result={result:?}",
        action.arguments
    );
    Ok(())
}
