"""Protocol tests use supplied fake scores, never real Laya/model evidence."""
import copy
import hashlib
import random
import unittest

import hepta_retrieval_wire as wire


def request():
    text = "alpha"
    return {
        "operation_id": "op.1", "workspace_id": "ws.1", "generation": 3,
        "objective_digest": "1" * 64, "observation_digest": "2" * 64,
        "bundle_digest": "3" * 64, "deadline_ms": 9000, "query": "q",
        "sources": [{"source_id": "src.1", "revision": 7,
                     "content_sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text}],
    }


def reply_for(raw):
    value = wire.decode_request(raw)
    return wire.encode_reply({
        "request_sha256": hashlib.sha256(raw).hexdigest(), "bundle_digest": value["bundle_digest"],
        "prediction_ppm": [100000, 900000], "input_tokens": 12, "output_tokens": 0, "latency_us": 7,
    })


class WireTests(unittest.TestCase):
    def test_known_request_digest_and_reply(self):
        encoded = wire.encode_request(request())
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                         "268a20079cee413b0d086ada8cb77a6e677a4759f66f40e6b6424fa4a915a2ef")
        self.assertEqual(wire.decode_request(encoded), request())
        reply = reply_for(encoded)
        self.assertEqual(wire.decode_reply(reply, encoded), {
            "request_sha256": hashlib.sha256(encoded).hexdigest(), "bundle_digest": "3" * 64,
            "prediction_ppm": [100000, 900000], "input_tokens": 12, "output_tokens": 0,
            "latency_us": 7,
        })

    def test_every_truncated_request_rejected(self):
        raw = wire.encode_request(request())
        for length in range(len(raw)):
            with self.subTest(length=length), self.assertRaises(wire.WireError):
                wire.decode_request(raw[:length])

    def test_every_truncated_reply_rejected(self):
        raw = wire.encode_request(request())
        reply = reply_for(raw)
        for length in range(len(reply)):
            with self.subTest(length=length), self.assertRaises(wire.WireError):
                wire.decode_reply(reply[:length], raw)

    def test_trailing_bytes_wrong_versions_and_oversize(self):
        raw = wire.encode_request(request())
        for malformed in (raw + b"\0", b"HPTARQ\x02\0" + raw[8:], b"x" * (wire.MAX_FRAME + 1)):
            with self.subTest(), self.assertRaises(wire.WireError):
                wire.decode_request(malformed)
        reply = reply_for(raw)
        with self.assertRaises(wire.WireError):
            wire.decode_reply(reply + b"\0", raw)

    def test_oversized_length_rejected_before_allocation(self):
        raw = bytearray(wire.encode_request(request()))
        raw[8:12] = b"\xff" * 4
        with self.assertRaises(wire.WireError):
            wire.decode_request(bytes(raw))

    def test_digests_and_source_bytes_checked(self):
        for value in ("0" * 64, "A" * 64, "x", None):
            changed = request()
            changed["bundle_digest"] = value
            with self.subTest(value=value), self.assertRaises(wire.WireError):
                wire.encode_request(changed)
        changed = request()
        changed["sources"][0]["text"] += "!"
        with self.assertRaises(wire.WireError):
            wire.encode_request(changed)

    def test_integer_confusion_and_ranges_rejected(self):
        for field in ("generation", "deadline_ms"):
            for value in (True, 1.0, 0, -1, 2**63):
                changed = request()
                changed[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(wire.WireError):
                    wire.encode_request(changed)

    def test_unknown_fields_duplicates_and_zero_candidates_rejected(self):
        changed = request()
        changed["authority"] = True
        with self.assertRaises(wire.WireError):
            wire.encode_request(changed)
        changed = request()
        changed["sources"] *= 2
        with self.assertRaises(wire.WireError):
            wire.encode_request(changed)
        changed["sources"] = []
        with self.assertRaises(wire.WireError):
            wire.encode_request(changed)

    def test_unicode_bytes_not_character_limits(self):
        changed = request()
        changed["query"] = "检索" * 400
        with self.assertRaises(wire.WireError):
            wire.encode_request(changed)
        changed["query"] = "\ud800"
        with self.assertRaises(wire.WireError):
            wire.encode_request(changed)

    def test_scoped_reply_cannot_follow_a_different_request(self):
        raw = wire.encode_request(request())
        reply = reply_for(raw)
        for field, value in (("operation_id", "op.2"), ("workspace_id", "ws.2"),
                             ("generation", 4), ("query", "other"),
                             ("bundle_digest", "4" * 64), ("deadline_ms", 10000)):
            changed = request()
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(wire.WireError):
                wire.decode_reply(reply, wire.encode_request(changed))

    def test_reply_mass_shape_and_counter_bounds(self):
        raw = wire.encode_request(request())
        decoded = wire.decode_reply(reply_for(raw), raw)
        for probs in ([1, 2], [True, 999999], [1000001, -1], [1000000], [float("nan"), 0]):
            with self.subTest(probs=probs), self.assertRaises(wire.WireError):
                wire.encode_reply({**decoded, "prediction_ppm": probs})
        wrong_shape = wire.encode_reply({**decoded, "prediction_ppm": [0, 0, 1000000]})
        with self.assertRaises(wire.WireError):
            wire.decode_reply(wrong_shape, raw)
        for field, value in (("input_tokens", 0), ("output_tokens", True), ("latency_us", -1)):
            with self.subTest(field=field), self.assertRaises(wire.WireError):
                wire.encode_reply({**decoded, field: value})

    def test_deterministic_generated_unicode_roundtrips(self):
        rng = random.Random(731)
        for case in range(100):
            value = request()
            value["query"] = "".join(rng.choice("ab检索🙂\n\t") for _ in range(rng.randint(1, 120)))
            value["sources"] = []
            for index in range(rng.randint(1, 15)):
                text = f"记录 {case} {index} " + "".join(rng.choice("XY🙂") for _ in range(20))
                value["sources"].append({"source_id": f"s.{index}", "revision": index + 1,
                                          "text": text, "content_sha256": hashlib.sha256(text.encode()).hexdigest()})
            self.assertEqual(wire.decode_request(wire.encode_request(value)), value)

    def test_source_order_is_bound_even_when_model_order_is_canonical(self):
        value = request()
        second = copy.deepcopy(value["sources"][0])
        second["source_id"] = "aaa"
        value["sources"].append(second)
        first = wire.encode_request(value)
        value["sources"].reverse()
        self.assertNotEqual(wire.encode_request(value), first)


if __name__ == "__main__":
    unittest.main()
