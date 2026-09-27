"""Protocol tests use supplied fake scores, never real Laya/model evidence."""
import copy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

from scripts import hepta_retrieval_wire as wire
from scripts.hepta_laya_worker import score_frame


def request():
    text = "alpha"
    return {
        "operation_id": "op.1", "workspace_id": "ws.1", "generation": 3,
        "objective_digest": "1" * 64, "observation_digest": "2" * 64,
        "bundle_digest": "3" * 64, "deadline_ms": 9000, "query": "q",
        "sources": [{"source_id": "src.1", "revision": 7,
                     "content_sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text}],
    }


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def score(value):
    result = {
        "schema": "hepta.laya.retrieval.v1", "operation_id": value["operation_id"],
        "workspace_id": value["workspace_id"], "generation": value["generation"],
        "bundle_digest": value["bundle_digest"], "observation_digest": value["observation_digest"],
        "request_digest": checksum(value), "production_authority": False,
        "labels": (None, *sorted(s["source_id"] for s in value["sources"])),
        "prediction_ppm": [100000, 900000], "input_tokens": 12, "output_tokens": 0,
        "latency_us": 7,
    }
    result["result_digest"] = checksum(result)
    return result


class WireTests(unittest.TestCase):
    def test_known_request_digest_and_reply(self):
        encoded = wire.encode_request(request())
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                         "268a20079cee413b0d086ada8cb77a6e677a4759f66f40e6b6424fa4a915a2ef")
        self.assertEqual(wire.decode_request(encoded), request())
        reply = score_frame(encoded, score, now_ms=lambda: 100)
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
        reply = score_frame(raw, score, now_ms=lambda: 100)
        for length in range(len(reply)):
            with self.subTest(length=length), self.assertRaises(wire.WireError):
                wire.decode_reply(reply[:length], raw)

    def test_trailing_bytes_wrong_versions_and_oversize(self):
        raw = wire.encode_request(request())
        for malformed in (raw + b"\0", b"HPTARQ\x02\0" + raw[8:], b"x" * (wire.MAX_FRAME + 1)):
            with self.subTest(), self.assertRaises(wire.WireError):
                wire.decode_request(malformed)
        reply = score_frame(raw, score, now_ms=lambda: 100)
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
        reply = score_frame(raw, score, now_ms=lambda: 100)
        for field, value in (("operation_id", "op.2"), ("workspace_id", "ws.2"),
                             ("generation", 4), ("query", "other"),
                             ("bundle_digest", "4" * 64), ("deadline_ms", 10000)):
            changed = request()
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(wire.WireError):
                wire.decode_reply(reply, wire.encode_request(changed))

    def test_reply_mass_shape_and_counter_bounds(self):
        raw = wire.encode_request(request())
        decoded = wire.decode_reply(score_frame(raw, score, now_ms=lambda: 100), raw)
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


class LeafTests(unittest.TestCase):
    def test_expired_before_entry_never_calls_scorer(self):
        calls = []
        with self.assertRaises(wire.WireError):
            score_frame(wire.encode_request(request()), lambda r: calls.append(r), now_ms=lambda: 9000)
        self.assertEqual(calls, [])

    def test_expiry_after_entry_never_returns_success(self):
        clock = iter([100, 9000])
        with self.assertRaises(wire.WireError):
            score_frame(wire.encode_request(request()), score, now_ms=lambda: next(clock))

    def test_input_mutation_rejected_even_with_recomputed_scores(self):
        def mutate(value):
            value["query"] = "new query"
            return score(value)
        with self.assertRaises(wire.WireError):
            score_frame(wire.encode_request(request()), mutate, now_ms=lambda: 100)

    def test_error_is_not_retried(self):
        calls = []
        def broken(value):
            calls.append(value)
            raise OSError("lost worker output")
        with self.assertRaises(OSError):
            score_frame(wire.encode_request(request()), broken, now_ms=lambda: 100)
        self.assertEqual(len(calls), 1)

    def test_changed_result_binding_or_authority_rejected(self):
        for field, value in (("production_authority", True), ("generation", True),
                             ("workspace_id", "ws.2"), ("labels", ("src.1", None)),
                             ("request_digest", "a" * 64)):
            def altered(req):
                result = score(req)
                result[field] = value
                result.pop("result_digest")
                result["result_digest"] = checksum(result)
                return result
            with self.subTest(field=field), self.assertRaises(wire.WireError):
                score_frame(wire.encode_request(request()), altered, now_ms=lambda: 100)

    def test_result_digest_tamper_rejected(self):
        def altered(req):
            result = score(req)
            result["prediction_ppm"] = [0, 1000000]
            return result
        with self.assertRaises(wire.WireError):
            score_frame(wire.encode_request(request()), altered, now_ms=lambda: 100)

    def test_invalid_clock_is_not_zero_or_success(self):
        for clock in (True, -1, 0.5, 2**63):
            with self.subTest(clock=clock), self.assertRaises(wire.WireError):
                score_frame(wire.encode_request(request()), score, now_ms=lambda: clock)

    def test_real_process_rejects_malformed_bytes_without_loading_model(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([
            sys.executable, str(root / "scripts/hepta_laya_worker.py"),
            "--model-root", "/nonexistent/model", "--bundle", "/nonexistent/bundle",
            "--bundle-digest", "3" * 64,
        ], input=b"not a request", capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"WireError", result.stderr)
        self.assertNotIn(b"ModuleNotFoundError", result.stderr)

    def test_real_process_rejects_expired_input_before_bundle_access(self):
        root = Path(__file__).resolve().parents[2]
        value = request()
        value["deadline_ms"] = 1
        result = subprocess.run([
            sys.executable, str(root / "scripts/hepta_laya_worker.py"),
            "--model-root", "/nonexistent/model", "--bundle", "/nonexistent/bundle",
            "--bundle-digest", "3" * 64,
        ], input=wire.encode_request(value), capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"expired request", result.stderr)
        self.assertNotIn(b"FileNotFoundError", result.stderr)

    def test_real_process_rejects_wrong_bundle_before_runtime_import(self):
        root = Path(__file__).resolve().parents[2]
        value = request()
        value["deadline_ms"] = 2**63 - 1
        result = subprocess.run([
            sys.executable, str(root / "scripts/hepta_laya_worker.py"),
            "--model-root", "/nonexistent/model", "--bundle", "/nonexistent/bundle",
            "--bundle-digest", "4" * 64,
        ], input=wire.encode_request(value), capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"wrong selected bundle", result.stderr)
        self.assertNotIn(b"ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
