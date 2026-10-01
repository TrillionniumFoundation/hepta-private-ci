use codex_hepta_wire::BoundPayloadCodec;
use codex_hepta_wire::HardenedManagedWireSession;
use codex_hepta_wire::HardenedRecordStream;
use codex_hepta_wire::HardenedRecordStreamBudget;
use codex_hepta_wire::WireSessionMetadata;

fn accepts_only_bound_stream<C: BoundPayloadCodec>() {
    let _ = core::mem::size_of::<Option<HardenedRecordStream<C>>>();
}

fn main() {
    let _ = core::mem::size_of::<HardenedManagedWireSession>();
    let _ = core::mem::size_of::<WireSessionMetadata>();
    let _ = HardenedRecordStreamBudget::new(1, 1);
    let _ = accepts_only_bound_stream::<NeverCodec>;
}

struct NeverCodec;

impl codex_hepta_wire::PayloadCodec for NeverCodec {
    type Value = ();

    fn descriptor(&self) -> &codex_hepta_wire::SchemaDescriptor {
        unreachable!()
    }

    fn encode_value(
        &self,
        _value: &Self::Value,
    ) -> Result<Vec<u8>, codex_hepta_wire::SchemaCodecError> {
        unreachable!()
    }

    fn decode_value(
        &self,
        _payload: &[u8],
    ) -> Result<Self::Value, codex_hepta_wire::SchemaCodecError> {
        unreachable!()
    }
}

impl BoundPayloadCodec for NeverCodec {
    fn schema_revision(&self) -> codex_hepta_types::Digest32 {
        unreachable!()
    }

    fn canonicalization_profile(
        &self,
    ) -> codex_hepta_wire::CanonicalizationProfile {
        unreachable!()
    }
}
