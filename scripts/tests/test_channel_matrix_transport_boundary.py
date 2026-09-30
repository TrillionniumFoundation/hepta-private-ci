from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "codex-rs/hepta-matrix-sdk/src"


class ChannelMatrixTransportBoundaryTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_public_transport_trait_cannot_override_authorized_entry(self) -> None:
        source = self.read("codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs")
        start = source.index("pub trait MatrixOutboundTransport")
        end = source.index("\n}\n\n/// Final, module-private permit adapter", start)
        public_trait = source[start:end]
        self.assertNotIn("send_authorized", public_trait)
        self.assertIn("trait MatrixAuthorizedTransport", source)
        self.assertIn(
            "impl<T: MatrixOutboundTransport + ?Sized> MatrixAuthorizedTransport for T {}",
            source,
        )
        self.assertEqual(source.count("permit.validate(record, &identity)"), 1)
        self.assertIn(
            "Ok(self.send(record, MatrixRawSendSeal { _private: () }))", source
        )

    def test_permit_is_private_to_outbound_gate(self) -> None:
        library = self.read("codex-rs/hepta-matrix-sdk/src/lib.rs")
        outbound = self.read("codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs")
        permit = self.read("codex-rs/hepta-matrix-sdk/src/outbound_v2/permit.rs")
        self.assertNotIn("pub use outbound_v2::MatrixSendPermit", library)
        self.assertNotIn("pub use permit::MatrixSendPermit", outbound)
        self.assertIn("pub(super) struct MatrixSendPermit", permit)
        self.assertIn("pub(super) fn validate(", permit)

    def test_permit_constructor_does_not_repeat_boundary_validation(self) -> None:
        permit = self.read("codex-rs/hepta-matrix-sdk/src/outbound_v2/permit.rs")
        gate = self.read("codex-rs/hepta-matrix-sdk/src/outbound_v2/gate.rs")
        start = permit.index("pub(super) fn new(")
        end = permit.index("pub(super) fn validate(", start)
        constructor = permit[start:end]
        self.assertIn(") -> Self {", constructor)
        self.assertNotIn("Result<", constructor)
        self.assertNotIn(".validate(", constructor)
        self.assertEqual(permit.count("outbound_payload_digest(record)"), 1)
        self.assertIn("let permit = MatrixSendPermit::new(", gate)
        constructor_call = gate[
            gate.index("let permit = MatrixSendPermit::new(") : gate.index(
                "self.preflight(grant, stats)?;",
                gate.index("let permit = MatrixSendPermit::new("),
            )
        ]
        self.assertNotIn("map_err", constructor_call)

    def test_entered_outcome_is_read_only_outside_gate(self) -> None:
        gate = self.read("codex-rs/hepta-matrix-sdk/src/outbound_v2/gate.rs")
        settlement = self.read(
            "codex-rs/hepta-matrix-sdk/src/outbound_v2/settlement.rs"
        )
        start = gate.index("pub(super) struct EnteredSend")
        end = gate.index("impl<'claim> EnteredSend", start)
        entered = gate[start:end]
        self.assertIn("result: Result<", entered)
        self.assertNotIn("pub(super) result", entered)
        self.assertIn("pub(super) fn outcome(", gate)
        self.assertIn("match entered.outcome()", settlement)
        self.assertNotIn("entered.result", settlement)

    def test_real_sdk_uses_only_the_sealed_raw_seam(self) -> None:
        facade = self.read("codex-rs/hepta-matrix-sdk/src/sdk.rs")
        self.assertNotIn("fn send_authorized", facade)
        self.assertIn("fn send<'a>(", facade)
        self.assertIn("_seal: MatrixRawSendSeal", facade)
        self.assertIn("Box::pin(async move", facade)
        self.assertIn(".send_raw(ROOM_MESSAGE_EVENT_TYPE, content)", facade)

    def test_future_construction_occurs_inside_a_live_gated_poll(self) -> None:
        gate = self.read("codex-rs/hepta-matrix-sdk/src/outbound_v2/gate.rs")
        poll = gate.index("let gated = poll_fn")
        adapter = gate.index(".send_authorized(self.record, permit)", poll)
        preflight_before = gate.rfind("self.preflight(grant, stats)", poll, adapter)
        preflight_after = gate.index("self.preflight(grant, stats)", adapter)
        transport_poll = gate.index("send.as_mut().poll(context)", preflight_after)
        self.assertGreaterEqual(preflight_before, poll)
        self.assertLess(preflight_before, adapter)
        self.assertLess(adapter, preflight_after)
        self.assertLess(preflight_after, transport_poll)
        self.assertIn("let mut permit = Some(permit);", gate)
        self.assertIn("let mut send: Option<MatrixSendFuture<'_>> = None;", gate)


if __name__ == "__main__":
    unittest.main()
