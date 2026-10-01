use codex_hepta_wire::AuthenticatedWireSession;
use codex_hepta_wire::ManagedAuthenticatedWireSession;
use codex_hepta_wire::ManagedRecordStream;
use codex_hepta_wire::WireSession;

fn main() {
    let _ = core::mem::size_of::<AuthenticatedWireSession>();
    let _ = core::mem::size_of::<ManagedAuthenticatedWireSession>();
    let _ = core::mem::size_of::<ManagedRecordStream>();
    let _ = core::mem::size_of::<WireSession>();
}
