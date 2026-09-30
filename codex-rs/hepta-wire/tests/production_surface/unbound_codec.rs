use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::HardenedManagedWireSession;
use codex_hepta_wire::PayloadCodec;

fn bypass<C: PayloadCodec>(
    owner: &mut HardenedManagedWireSession,
    producer: StableId,
    generation: Generation,
    codec: &C,
    value: &C::Value,
) {
    let _ = owner.seal_bound_typed(producer, generation, codec, value);
}

fn main() {}
