"""Exercise the participant command and fail-closed owner path of a built binary."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

BINARY = Path(sys.argv.pop()).resolve()
STUDY = "11" * 32
FIRST = "22" * 32
SECOND = "33" * 32


def run(args, payload):
    return subprocess.run([BINARY, *args], input=payload, capture_output=True, timeout=15)


def request(scope, **extra):
    return json.dumps(dict(study_sha256=STUDY, scope=scope, **extra)).encode()


class ParticipantStatementTests(unittest.TestCase):
    def test_training_bytes(self):
        result = run(["--print-statement"], request(
            dict(use="train", failure=FIRST, correction=SECOND)))
        expected = (f"Hepta paired learning consent v1\nStudy SHA-256: {STUDY}\n"
                    "I authorize Hepta to train the study candidate using only these records.\n"
                    f"Failure SHA-256: {FIRST}\nCorrection SHA-256: {SECOND}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected.encode())
        self.assertEqual(result.stderr, b"")

    def test_evaluation_bytes(self):
        result = run(["--print-statement"], request(
            dict(use="evaluate_only", freeze=FIRST, task=SECOND)))
        expected = (f"Hepta paired learning consent v1\nStudy SHA-256: {STUDY}\n"
                    "I authorize Hepta to evaluate the frozen pair on this task. "
                    "Training on this task is prohibited.\n"
                    f"Pair freeze SHA-256: {FIRST}\nTask SHA-256: {SECOND}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected.encode())

    def test_rejects_invalid_or_mixed_request(self):
        good = dict(use="train", failure=FIRST, correction=SECOND)
        for payload in (
            request(dict(good, failure="zz" * 32)),
            request(dict(good, task=SECOND)),
            request(dict(use="evaluate_only", task=SECOND)),
            request(good, delivery_id=FIRST),
            b"[]",
            b" " * 32769,
        ):
            with self.subTest(length=len(payload)):
                result = run(["--print-statement"], payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")

    def test_consumer_request_and_outcome_domains(self):
        common = dict(operation="44"*32, pair="55"*32, candidate="66"*32, task="77"*32)
        start = dict(use="request_consumer_run", **common)
        finish = dict(use="report_consumer_outcome", **common, run_receipt="88"*32,
                      output="99"*32, effect="aa"*32, outcome="accepted")
        def render(scope):
            r = run(["--print-statement"], request(scope))
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.decode()
        self.assertIn("request one use", render(start))
        original = render(finish)
        self.assertTrue(original.endswith("My decision: accepted"))
        self.assertIn("neither training nor payment", original)
        for k in (*common, "run_receipt", "output", "effect"):
            with self.subTest(field=k):
                self.assertNotEqual(original, render(dict(finish, **{k:"bb"*32})))
        self.assertNotEqual(original, render(dict(finish, outcome="rejected")))
        self.assertNotEqual(original, render(start))
        for scope in (dict(start, outcome="accepted"), dict(finish,outcome="yes"),
                      dict(finish,output="AA"*32), {k:v for k,v in finish.items() if k!="effect"}):
            r=run(["--print-statement"],request(scope))
            self.assertNotEqual(r.returncode,0)
            self.assertEqual(r.stdout,b"")

    def test_verification_still_requires_original_descriptors(self):
        result = run(["1", "/missing-study-home", "/missing-route"],
                     request(dict(use="train", failure=FIRST, correction=SECOND),
                             delivery_id=FIRST))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"inherited private Root socket", result.stderr)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
