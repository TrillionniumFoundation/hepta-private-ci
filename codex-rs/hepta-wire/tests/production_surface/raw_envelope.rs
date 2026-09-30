use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::HardenedManagedWireSession;

fn bypass(owner: &mut HardenedManagedWireSession, envelope: &DecodedEnvelope) {
    let _ = owner.seal_envelope(envelope);
}

fn main() {}
