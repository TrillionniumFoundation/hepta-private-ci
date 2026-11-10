"""Original-memory/selector sidecar bindings, with no model execution claim."""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .candidate_memory import CandidateScope
from .candidate_runtime import CandidateRuntime
from .candidate_selector import BINDINGS, PROFILE
from .objective import canonical_sha
from .selector_runtime import SelectorRuntime, read_selector_audit


def setup():
    scope = CandidateScope("operation", "case", "a" * 64, 100, 100)
    memory = CandidateRuntime(
        {
            "schema": "ndu.real.candidate-memory-profile.v1",
            "mode": "bounded",
            "max_entries": 128,
            "max_serialized_bytes": 524288,
        },
        scope,
        {k: "b" * 64 for k in BINDINGS},
    )
    profile = {
        "schema": PROFILE["schema"],
        "mode": "public_rule",
        "profile_sha256": canonical_sha(PROFILE),
    }
    selector = SelectorRuntime(profile, memory)
    state = {
        "step": 0,
        "observation": {
            "path": "overview.png",
            "sha256": "c" * 64,
            "bbox": [0, 0, 100, 100],
            "kind": "overview",
        },
    }
    candidates = [
        {"text": "noise", "bbox": [0, 0, 50, 10], "origin": "pixel_ocr"},
        {"text": "12.50", "bbox": [0, 80, 50, 90], "origin": "pixel_ocr"},
    ]
    vector = [0.0] * 126
    vector[119] = 1.0
    features = [vector, list(vector)]
    return memory, selector, state, candidates, features


def expected(selector, state, action, memory_binding, previous=None):
    return {
        "scope": asdict(selector.scope),
        "bindings": selector.bindings,
        "profile": selector.profile,
        "profile_sha256": selector.profile_sha256,
        "step": state["step"],
        "observation": state["observation"],
        "action": action,
        "memory_audit_sha256": memory_binding["sha256"],
        "previous_audit_sha256": previous,
    }


def write_mutation(path, value):
    raw = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=True,
        )
        + "\n"
    ).encode()
    path.write_bytes(raw)
    return {
        "path": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


class SelectorRuntimeTests(unittest.TestCase):
    def test_actual_selection_bound_to_memory_and_caller_mutation_isolated(self):
        memory, selector, state, candidates, features = setup()
        offered, vectors = memory.offer(0, candidates, features)
        index = selector.select(0, "total", offered, vectors, [2.0, 1.0])
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": offered[index]["text"]},
        }
        offered[0]["text"], vectors[0][0] = "caller mutation", 0.5
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mb = memory.record(root, state, action, index)
            sb = selector.record(root, state, action, mb)
            ma = json.loads((root / mb["path"]).read_text())
            audit = read_selector_audit(
                root, sb, expected(selector, state, action, mb), ma
            )
            self.assertEqual(audit["candidates"][0]["text"], "noise")
            self.assertEqual(
                (
                    audit["receipt"]["frozen_neural_index"],
                    audit["receipt"]["selected_index"],
                ),
                (0, 1),
            )
            for key, replacement in (
                ("step", 1),
                ("memory_audit_sha256", "d" * 64),
                ("previous_audit_sha256", "d" * 64),
            ):
                wrong = expected(selector, state, action, mb)
                wrong[key] = replacement
                with self.subTest(key=key), self.assertRaises(ValueError):
                    read_selector_audit(root, sb, wrong, ma)

    def test_unprocessed_stop_is_unknown_and_preserves_original_chain(self):
        memory, selector, state, _, _ = setup()
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "STOP",
            "arguments": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = None
            for step in range(2):
                state["step"] = step
                mb = memory.record(root, state, action)
                sb = selector.record(root, state, action, mb)
                ma = json.loads((root / mb["path"]).read_text())
                audit = read_selector_audit(
                    root, sb, expected(selector, state, action, mb, previous), ma
                )
                self.assertEqual(
                    (
                        audit["observation_processed"],
                        audit["receipt"],
                        audit["candidates"],
                    ),
                    (False, None, []),
                )
                previous = sb["sha256"]

    def test_rebound_mutations_cannot_change_choices_features_or_support(self):
        memory, selector, state, candidates, features = setup()
        offered, vectors = memory.offer(0, candidates, features)
        index = selector.select(0, "total", offered, vectors, [2.0, 1.0])
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": offered[index]["text"]},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mb = memory.record(root, state, action, index)
            sb = selector.record(root, state, action, mb)
            ma = json.loads((root / mb["path"]).read_text())
            original = json.loads((root / sb["path"]).read_text())
            wrong_memory = copy.deepcopy(ma)
            wrong_memory["selected_index"] = True
            with self.assertRaises(ValueError):
                read_selector_audit(
                    root, sb, expected(selector, state, action, mb), wrong_memory
                )
            mutations = [
                lambda x: x["receipt"].__setitem__("public_rule_index", 0),
                lambda x: x["features"][0].__setitem__(0, 0.5),
                lambda x: x["receipt"].__setitem__("selection_cpu_seconds", -1.0),
                lambda x: x["receipt"].__setitem__(
                    "selection_wall_seconds", float("nan")
                ),
                lambda x: x.__setitem__("unknown_label", True),
            ]
            for i, mutate in enumerate(mutations):
                altered = copy.deepcopy(original)
                mutate(altered)
                rebound = write_mutation(root / sb["path"], altered)
                with self.subTest(i=i), self.assertRaises(ValueError):
                    read_selector_audit(
                        root, rebound, expected(selector, state, action, mb), ma
                    )

    def test_order_wrong_memory_and_direct_child_limits_fail_closed(self):
        memory, selector, state, candidates, features = setup()
        with self.assertRaises(ValueError):
            selector.select(1, "total", candidates, features, [2.0, 1.0])
        offered, vectors = memory.offer(0, candidates, features)
        selector.select(0, "total", offered, vectors, [2.0, 1.0])
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": offered[0]["text"]},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mb = memory.record(root, state, action, 0)
            with self.assertRaises(ValueError):
                selector.record(root, state, action, mb)
            ma = json.loads((root / mb["path"]).read_text())
            for invalid in (
                {"path": "../selector-audit-00.json", "bytes": 1, "sha256": "a" * 64},
                {
                    "path": "selector-audit-00.json",
                    "bytes": 4 * 1024**2 + 1,
                    "sha256": "a" * 64,
                },
            ):
                with self.assertRaises(ValueError):
                    read_selector_audit(
                        root, invalid, expected(selector, state, action, mb), ma
                    )


if __name__ == "__main__":
    unittest.main()
