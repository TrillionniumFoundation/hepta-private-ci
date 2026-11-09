"""Public-only byte contracts using actual create-once catalog files."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from . import content_chain as chain
from .metering import canonical_sha


class ContentChainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = {
            "case_id": "public-case",
            "step": 0,
            "text_committed": False,
            "observation": {
                "path": "overview.png",
                "sha256": "a" * 64,
                "bbox": [0, 0, 8, 8],
                "kind": "overview",
            },
            "delivery": {
                "schema": "ndu.real.delivery.v1",
                "case_id": "public-case",
                "text": None,
                "image": None,
            },
        }
        self.candidates = [{"text": "42", "bbox": [0, 0, 8, 8], "origin": "pixel_ocr"}]
        self.action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": "42"},
        }

    def test_catalog_is_create_only_bound_and_public(self):
        receipt = chain.publish_selection(
            self.root, self.state, self.candidates, 0, self.action
        )
        self.assertEqual(
            chain.verify_selection(self.root, self.state, self.action, receipt), receipt
        )
        self.assertEqual(receipt["selected_text_sha256"], canonical_sha("42"))
        catalog = json.loads((self.root / receipt["catalog"]["path"]).read_bytes())
        self.assertEqual(
            set(catalog),
            {"schema", "case_id", "step", "observation_sha256", "candidates"},
        )
        with self.assertRaises(FileExistsError):
            chain.publish_selection(
                self.root, self.state, self.candidates, 0, self.action
            )
        (self.root / receipt["catalog"]["path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "registered bytes"):
            chain.verify_selection(self.root, self.state, self.action, receipt)

    def test_bounded_catalog_refuses_size_index_and_extra_fields(self):
        for candidates, index in (
            (self.candidates * 129, 0),
            ([{**self.candidates[0], "text": "a" * 8193}], 0),
            ([{**self.candidates[0], "text": "🙂" * 8192}] * 128, 0),
            (self.candidates, -1),
            (self.candidates, True),
            ([{**self.candidates[0], "hidden_target": "never"}], 0),
        ):
            with self.subTest(index=index, count=len(candidates)):
                with self.assertRaises(ValueError):
                    chain.publish_selection(
                        self.root, self.state, candidates, index, self.action
                    )
        self.assertEqual(list(self.root.iterdir()), [])

    def test_receipt_cannot_move_between_steps_observations_or_deliveries(self):
        receipt = chain.publish_selection(
            self.root, self.state, self.candidates, 0, self.action
        )
        for field in ("case_id", "step", "observation", "delivery"):
            state = copy.deepcopy(self.state)
            if field == "case_id":
                state[field] = "different-case"
            elif field == "step":
                state[field] += 1
            elif field == "observation":
                state[field]["sha256"] = "b" * 64
            else:
                state[field]["text"] = "earlier-content-changed"
            with self.assertRaises(ValueError):
                chain.verify_selection(self.root, state, self.action, receipt)

    def test_empty_stop_and_committed_text_have_explicit_sources(self):
        stop = {**self.action, "action": "STOP", "arguments": {}}
        receipt = chain.publish_selection(self.root, self.state, [], None, stop)
        self.assertIsNone(receipt["selected_index"])
        self.assertIsNone(receipt["selected_candidate_sha256"])
        chain.verify_selection(self.root, self.state, stop, receipt)
        self.state["step"] = 1
        self.state["delivery"]["text"] = "committed"
        self.state["text_committed"] = True
        action = {**self.action, "arguments": {"text": "committed"}}
        receipt = chain.publish_selection(
            self.root, self.state, self.candidates, 0, action
        )
        chain.verify_selection(self.root, self.state, action, receipt)
        with self.assertRaisesRegex(ValueError, "selected or committed"):
            chain.verify_selection(self.root, self.state, self.action, receipt)

    def test_image_rename_changes_raw_identity_only(self):
        delivery = copy.deepcopy(self.state["delivery"])
        delivery["image"] = {
            "path": "rendered.png",
            "sha256": "f" * 64,
            "bytes": 20,
            "bbox": [0, 0, 8, 8],
        }
        renamed = copy.deepcopy(delivery)
        renamed["image"]["path"] = "delivered.png"
        self.assertEqual(
            chain.delivery_semantic_sha(delivery), chain.delivery_semantic_sha(renamed)
        )
        self.assertNotEqual(canonical_sha(delivery), canonical_sha(renamed))
        renamed["image"]["sha256"] = "c" * 64
        self.assertNotEqual(
            chain.delivery_semantic_sha(delivery), chain.delivery_semantic_sha(renamed)
        )


if __name__ == "__main__":
    unittest.main()
