"""Small AST controls for the source-only oracle-gap review."""

import tempfile
import textwrap
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_oracle_gap.static_review import (
    inspect_adapter,
    inspect_candidate,
    inspect_legacy_oracle,
)


def source_file(root, name, source):
    path = Path(root) / name
    path.write_text(textwrap.dedent(source))
    return path


class StaticReviewTest(unittest.TestCase):
    def test_candidate_surface_detects_output_and_pending(self):
        with tempfile.TemporaryDirectory() as root:
            path = source_file(
                root,
                "candidate.py",
                """
                class Packet:
                    source: str
                    output: tuple
                class Capsule:
                    packets: tuple
                def _template(packet):
                    return packet.output
                def _advance(state, pending):
                    return pending
                def _run_lane(state, pending):
                    return pending
                """,
            )
            observed = inspect_candidate(path)
            self.assertTrue(observed["packet_has_output"])
            self.assertTrue(observed["advance_accepts_pending"])
            self.assertTrue(observed["template_reads_packet_output"])
            self.assertTrue(observed["run_lane_accepts_pending"])
            self.assertTrue(observed["capsule_has_packets"])

    def test_legacy_surface_exposes_missing_current_state_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = source_file(
                root,
                "legacy.py",
                """
                class OraclePacket:
                    identity: str
                    alpha: object
                def _advance_segment(state, left, right):
                    return state
                def _run_lane(lane, times, state):
                    return state
                def _coordinate_stream(lane, time, state):
                    return state.active
                """,
            )
            observed = inspect_legacy_oracle(path)
            self.assertFalse(observed["packet_has_output"])
            self.assertFalse(observed["advance_accepts_pending"])
            self.assertFalse(observed["run_lane_accepts_pending"])
            self.assertFalse(observed["coordinate_stream_mentions_packet"])
            self.assertFalse(observed["imports_serializer"])

    def test_serializer_import_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            path = source_file(
                root,
                "legacy.py",
                """
                from package.serializer import encode
                class OraclePacket:
                    output: object
                def _advance_segment(state, pending): return pending
                def _run_lane(state, pending): return pending
                def _coordinate_stream(state, packets): return packets
                """,
            )
            self.assertTrue(inspect_legacy_oracle(path)["imports_serializer"])

    def test_input_adapter_does_not_become_a_numeric_oracle(self):
        with tempfile.TemporaryDirectory() as root:
            path = source_file(
                root,
                "adapter.py",
                """
                import json
                def load_authentic_input(root):
                    return json.loads(root)
                """,
            )
            observed = inspect_adapter(path)
            self.assertEqual(observed["numerical_import_roots"], ())
            self.assertFalse(observed["has_numeric_propagation_entry"])


if __name__ == "__main__":
    unittest.main()
