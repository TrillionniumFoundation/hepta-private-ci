use codex_hepta_wire::HardenedManagedWireSession;

fn escape(owner: &HardenedManagedWireSession) {
    let _ = owner.session();
}

fn main() {}
