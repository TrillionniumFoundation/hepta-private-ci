"""Protocol tests for the fail-closed Reader fixture adapter.

These tests use a tiny fake evaluator only to exercise adapter mechanics. They
are not Reader efficacy evidence and never substitute for the registered
repository fixture or a frozen model run.
"""

from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.reader_fixture_bridge import (  # noqa: E402
    ARM_NAMES,
    ReaderFixtureError,
    build_four_condition_requests,
    build_request,
    load_reader_evaluator,
)


MANIFEST_DIGEST = "a" * 64


def task() -> dict:
    return {
        "id": "task_reader_a",
        "question": "Which cited fact is supported by the source excerpt?",
        "choices": {"A": "first fact", "B": "second fact", "C": "third fact", "D": "fourth fact"},
        "gold": "A",
        "source": {"path": "docs/source.md", "blob_sha": "1" * 40, "quote": "supported source fact", "line": 1},
        "withheld_control": {"path": "docs/source.md", "blob_sha": "1" * 40, "quote": "withheld context", "line": 1},
    }


def good_module() -> SimpleNamespace:
    def evidence_for(corpus, case, arm):
        return ("evidence:" + arm, "docs/source.md")

    def construct_request(corpus, case, arm):
        return (
            {"question": case["question"], "repository_source": "docs/source.md", "source_excerpt_untrusted": "evidence:" + arm},
            {"answer": {"criteria": {**case["choices"], "UNKNOWN": "not enough evidence"}}},
        )

    return SimpleNamespace(evidence_for=evidence_for, construct_request=construct_request)


class ReaderFixtureBridgeTests(unittest.TestCase):
    def test_four_condition_adapter_keeps_exact_arm_order(self):
        requests = tuple(build_request(good_module(), {"manifest_sha256": MANIFEST_DIGEST}, task(), arm) for arm in ARM_NAMES)
        self.assertEqual(tuple(request.arm for request in requests), ARM_NAMES)
        self.assertEqual([request.source_path for request in requests], ["docs/source.md"] * 4)
        self.assertNotIn("gold", str(requests[0].to_model_payload()).lower())

    def test_unknown_arm_is_rejected(self):
        with self.assertRaises(ReaderFixtureError):
            build_request(good_module(), {"manifest_sha256": MANIFEST_DIGEST}, task(), "injection")

    def test_gold_key_in_model_payload_is_rejected(self):
        module = good_module()

        def construct_request(corpus, case, arm):
            return ({"gold": case["gold"]}, {"answer": {}})

        module.construct_request = construct_request
        with self.assertRaises(ReaderFixtureError):
            build_request(module, {"manifest_sha256": MANIFEST_DIGEST}, task(), "full")

    def test_evidence_source_mismatch_is_rejected(self):
        module = good_module()

        def construct_request(corpus, case, arm):
            return ({"repository_source": "other.md"}, {})

        module.construct_request = construct_request
        with self.assertRaises(ReaderFixtureError):
            build_request(module, {"manifest_sha256": MANIFEST_DIGEST}, task(), "none")

    def test_evidence_text_mismatch_is_rejected(self):
        module = good_module()

        def construct_request(corpus, case, arm):
            return (
                {"repository_source": "docs/source.md", "source_excerpt_untrusted": "different"},
                {},
            )

        module.construct_request = construct_request
        with self.assertRaises(ReaderFixtureError):
            build_request(module, {"manifest_sha256": MANIFEST_DIGEST}, task(), "full")

    def test_missing_registered_script_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReaderFixtureError):
                load_reader_evaluator(Path(directory))

    def test_registered_fake_evaluator_is_only_protocol_smoke(self):
        evaluator = textwrap.dedent(
            """
            SCHEMA = 'hepta.sngr.reader-evidence-fixture.v1'
            ARM_NAMES = ('none', 'distractor', 'withheld', 'full')
            FROZEN_CASE_SHA256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            def load_cases(path):
                return {'manifest_sha256': FROZEN_CASE_SHA256, 'tasks': [
                    {'id': 'task_reader_a', 'question': 'Which cited fact is supported by the source excerpt?',
                     'choices': {'A': 'first fact', 'B': 'second fact', 'C': 'third fact', 'D': 'fourth fact'},
                     'gold': 'A'}]}
            def evidence_for(corpus, case, arm):
                if arm not in ARM_NAMES: raise ValueError('arm')
                return 'evidence:' + arm, 'docs/source.md'
            def construct_request(corpus, case, arm):
                return ({'question': case['question'], 'repository_source': 'docs/source.md',
                         'source_excerpt_untrusted': 'evidence:' + arm},
                        {'answer': {'criteria': {'A': 'first fact', 'B': 'second fact',
                                                 'C': 'third fact', 'D': 'fourth fact',
                                                 'UNKNOWN': 'not enough evidence'}}})
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "hepta_sngr_reader_eval.py").write_text(evaluator, encoding="utf-8")
            (root / "scripts" / "hepta_sngr_reader_cases.json").write_text("{}\n", encoding="utf-8")
            requests = build_four_condition_requests(root, "task_reader_a")
            self.assertEqual(tuple(request.arm for request in requests), ARM_NAMES)
            self.assertTrue(all(request.manifest_sha256 == MANIFEST_DIGEST for request in requests))


if __name__ == "__main__":
    unittest.main()
