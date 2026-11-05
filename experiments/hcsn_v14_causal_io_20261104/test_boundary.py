"""Independent adversarial checks; all media/features here are synthetic fixtures.

These checks establish I/O, identity, acquisition, and persistence behavior only.
They do not establish encoder quality, semantic retrieval, independent recordings,
learned identity binding, analytic-core benefit, or deployment admission.
"""

import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from .boundary import BoundaryError, FrozenInput, Packet, historical_overlap


def h(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()



def source(source_id="fixture-source", **changes):
    result = {
        "source_id": source_id,
        "family_id": "fixture-family",
        "session_id": "fixture-recording-session",
        "world_id": "fixture-world",
        "clock_id": "fixture-source-clock",
        "sha256": h("fixture-only raw bytes " + source_id),
        "max_end_ns": 1000000,
        "sync_uncertainty_ns": 0,
        "release_offset_ns": 0,
        "origin": "fixture",
        "encoders": {
            modality: {"sha256": h("fixture-only " + modality + " encoder"), "width": 2}
            for modality in ("text", "audio", "video", "image")
        },
    }
    result.update(changes)
    return result



def document(*sources):
    return {
        "schema": "hcsn-v14-frozen-input.v1",
        "role": "development",
        "arrival_clock_id": "fixture-arrival-clock",
        "sources": list(sources or [source()]),
    }



def packet(modality="text", content="fixture text: α\nexact bytes", **changes):
    spec = source()
    result = {
        "source_id": spec["source_id"],
        "modality": modality,
        "source_sha256": spec["sha256"],
        "encoder_sha256": spec["encoders"][modality]["sha256"],
        "clock_id": spec["clock_id"],
        "start_ns": 0,
        "end_ns": 10,
        "sample_times_ns": (0, 5, 10),
        "features": (0.25, -0.5),
        "content": content,
        "status": "ok",
    }
    result.update(changes)
    return Packet(**result)



class FixtureCore:
    """A counter, not a trained model or a surrogate scientific baseline."""

    model_id = h("fixture-counter-core-v1")

    def initial(self):
        return {"accepted": 0, "elapsed_ns": 0, "last_modality": None}

    def step(self, state, observation, dt_ns):
        return {
            "accepted": state["accepted"] + 1,
            "elapsed_ns": state["elapsed_ns"] + dt_ns,
            "last_modality": observation.modality,
        }

    def output(self, state):
        return dict(state)



class PacketBoundaryTests(unittest.TestCase):
    def test_future_duplicate_or_reversed_samples_are_rejected(self):
        for times in ((0, 11), (-1, 5), (5, 5), (8, 2), (True, 5)):
            with self.subTest(times=times), self.assertRaises(BoundaryError):
                packet(sample_times_ns=times)

    def test_missing_inputs_cannot_carry_hidden_content(self):
        for status in ("missing", "corrupt", "unsupported", "ood", "denied", "unknown", "timeout"):
            with self.subTest(status=status):
                empty = packet(status=status, sample_times_ns=(), features=(), content="")
                FrozenInput(document()).verify(empty)
                for extra in ({"content": "leaked answer"}, {"features": (0.1, 0.2)},
                              {"sample_times_ns": (5,)}):
                    with self.subTest(extra=extra), self.assertRaises(BoundaryError):
                        replace(empty, **extra)

    def test_nonfinite_and_untyped_features_are_rejected(self):
        for features in ((float("nan"), 0.0), (float("inf"), 0.0),
                         (True, 0.0), ("0.0", 0.0), ([0.0], 0.0)):
            with self.subTest(features=features), self.assertRaises(BoundaryError):
                packet(features=features)

    def test_packet_copies_mutable_inputs(self):
        times, features = [0, 5, 10], [0.25, -0.5]
        accepted = packet(sample_times_ns=times, features=features)
        times[-1], features[0] = 1000, 99
        self.assertEqual(accepted, packet())
        with self.assertRaises(FrozenInstanceError):
            accepted.content = "changed"

    def test_frozen_source_and_encoder_identity_are_checked(self):
        frozen = FrozenInput(document())
        cases = (
            {"source_id": "unfrozen"},
            {"source_sha256": h("changed source")},
            {"encoder_sha256": h("changed encoder")},
            {"clock_id": "other clock"},
            {"features": (0.1,)},
            {"end_ns": 1000001},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(BoundaryError):
                frozen.verify(packet(**changes))

    def test_frozen_input_resists_all_exposed_nested_mutations(self):
        caller_doc = document()
        frozen = FrozenInput(caller_doc)
        original_digest = frozen.sha256
        caller_doc["sources"][0]["sha256"] = h("modified original")
        frozen.verify(packet())
        for view in (frozen.sources["fixture-source"], frozen.verify(packet())):
            for target, key, value in (
                (view, "sha256", h("modified exposed source")),
                (view["encoders"]["text"], "sha256", h("modified exposed encoder")),
                (view["encoders"]["text"], "width", 3),
            ):
                try:
                    target[key] = value
                except (TypeError, FrozenInstanceError):
                    pass
                self.assertEqual(frozen.sha256, original_digest)
                frozen.verify(packet())
        with self.assertRaises(BoundaryError):
            frozen.verify(packet(source_sha256=h("modified exposed source")))

    def test_temporal_compatibility_does_not_cross_session_or_family(self):
        a = packet(modality="audio")
        sources = [source(), source("second")]
        b = packet(modality="video", source_id="second", source_sha256=sources[1]["sha256"])
        self.assertTrue(FrozenInput(document(*sources)).aligned(a, b, tolerance_ns=0))
        for field in ("family_id", "session_id", "clock_id", "world_id"):
            modified = copy.deepcopy(sources)
            modified[1][field] = "other-" + field
            candidate = replace(b, clock_id=modified[1]["clock_id"])
            with self.subTest(field=field):
                self.assertFalse(FrozenInput(document(*modified)).aligned(a, candidate, tolerance_ns=10))
        sources[1]["sync_uncertainty_ns"] = 11
        self.assertFalse(FrozenInput(document(*sources)).aligned(a, b, tolerance_ns=10))

    def test_reencoding_does_not_erase_historical_source_group_overlap(self):
        history = FrozenInput(document())
        candidate_source = source("reencoded", sha256=h("different bytes"))
        candidate = FrozenInput(document(candidate_source))
        overlap = historical_overlap(candidate, [history])
        self.assertEqual(overlap["status"], "OVERLAP")
        self.assertEqual(overlap["overlaps"]["sha256"], [])
        self.assertEqual(overlap["overlaps"]["family_id"], ["fixture-family"])
        self.assertFalse(overlap["independence_established"])
        self.assertEqual(historical_overlap(candidate, []), {
            "status": "UNKNOWN", "overlaps": {}, "independence_established": False,
        })
        unsupported = document()
        unsupported["role"] = "independent_confirmation"
        with self.assertRaises(BoundaryError):
            FrozenInput(unsupported)



class CheckedSourceBytesTests(unittest.TestCase):
    def test_actual_bytes_hash_size_and_path_bound_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            raw = b"fixture-only recorded bytes; this is not genuine recorded media"
            target = root / "source.bin"
            target.write_bytes(raw)
            outside = Path(directory) / "outside.bin"
            outside.write_bytes(raw)
            frozen = FrozenInput(document(source(sha256=hashlib.sha256(raw).hexdigest())))
            self.assertEqual(frozen.read_bytes(root, "source.bin", "fixture-source"), raw)
            for name, maximum in (("../outside.bin", len(raw)), (str(outside), len(raw)),
                                  ("source.bin", len(raw) - 1)):
                with self.subTest(name=name, maximum=maximum), self.assertRaises(BoundaryError):
                    frozen.read_bytes(root, name, "fixture-source", max_bytes=maximum)
            target.write_bytes(raw + b" changed after freeze")
            with self.assertRaises(BoundaryError):
                frozen.read_bytes(root, "source.bin", "fixture-source")



if __name__ == "__main__":
    unittest.main()
