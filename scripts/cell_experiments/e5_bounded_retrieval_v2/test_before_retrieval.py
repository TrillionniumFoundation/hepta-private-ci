import copy
import json
import tempfile
import unittest
from pathlib import Path

from retrieve_once import select_once
from test_support import visible
from v2_common import Refusal, canonical, sha
from v2_legacy import visible_material


class BeforeRetrievalTests(unittest.TestCase):
    def test_deterministic_view_independent_of_receipt_timing(self):
        first, first_cost = select_once(visible())
        second, second_cost = select_once(visible())
        self.assertEqual(first, second)
        self.assertEqual(first_cost["ranking"], second_cost["ranking"])
        self.assertEqual(first["payload"]["runtime_units"][0]["qualname"], "bug")

    def test_rejects_after_or_future_api_channels(self):
        for key in [
            "after",
            "target",
            "runtime_patches",
            "future_B_C",
            "material_store",
        ]:
            with self.subTest(key=key), self.assertRaises(Refusal):
                data = visible()
                data[key] = "not an allowed source of input selection"
                select_once(data)

    def test_tampered_original_task_and_cases_rejected(self):
        data = visible()
        data["task"]["tests/test_core.py"] += b"# changed\n"
        with self.assertRaises(Refusal):
            select_once(data)
        data = visible()
        data["cases"][0]["failure"] = "another before diagnostic"
        with self.assertRaises(Refusal):
            select_once(data)

    def test_unsafe_source_path_rejected_even_with_self_consistent_identity(self):
        with self.assertRaises(Refusal):
            select_once(
                visible(runtime={"../escape.py": b"def bug():\n    return 'old'\n"})
            )

    def test_complete_decorated_parameter_test_is_not_sliced(self):
        raw = b"@pytest.mark.parametrize('value', [1, 2, 3])\ndef test_bug(value):\n    assert bug(value) == 'new'\n"
        data = visible(task={"tests/test_core.py": raw})
        view, _ = select_once(data)
        self.assertEqual(view["payload"]["task_items"][0]["text"].encode(), raw)

    def test_mandatory_large_unit_refuses_instead_of_slicing_or_falling_back(self):
        raw = b"def bug(value):\n    return 'old" + b"x" * 13000 + b"'\n"
        with self.assertRaisesRegex(Refusal, "highest-ranked complete runtime"):
            select_once(visible(runtime={"pkg/core.py": raw}))

    def test_source_file_cost_cap_precedes_parsing(self):
        raw = b"#" + b"x" * 4194304
        with self.assertRaisesRegex(Refusal, "runtime_file_bytes"):
            select_once(visible(runtime={"pkg/core.py": raw}))

    def test_cython_counterpart_is_visible_or_refused(self):
        raw = b"def bug(value):\n    return 'old'\n"
        data = visible(runtime={"pkg/core.py": raw, "pkg/core.pyx": raw})
        view, _ = select_once(data)
        self.assertEqual(
            {u["path"] for u in view["payload"]["runtime_units"]},
            {"pkg/core.py", "pkg/core.pyx"},
        )
        data = visible(
            runtime={
                "pkg/core.py": raw,
                "pkg/core.pyx": b"def unrelated():\n    return 1\n",
            }
        )
        with self.assertRaisesRegex(Refusal, "coupled complete"):
            select_once(data)

    def test_original_material_loader_does_not_read_after_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "blobs").mkdir()

            def put(raw, path=None):
                binding = {"sha256": sha(raw), "bytes": len(raw)}
                if path:
                    binding["path"] = path
                (root / "blobs" / binding["sha256"]).write_bytes(raw)
                return binding

            before = put(b"def bug(value):\n    return 'old'\n", "pkg/core.py")
            test = put(
                b"def test_bug():\n    assert bug(1) == 'new'\n", "tests/test_core.py"
            )
            execution = put(canonical([{**test, "role": "original_after_fixture"}]))
            intent = put(canonical({"after_tests_and_fixtures_unchanged": True}))
            junit = put(
                b'<testsuite><testcase classname="tests.test_core" name="test_bug"><failure>pkg/core.py:2: in bug\nE - old\nE + new\n</failure></testcase></testsuite>'
            )
            record = {
                "source_id": "synthetic:before-only",
                "before_commit": "a" * 40,
                "runtime_roots": ["pkg"],
                "native_test_selector": "test_bug",
                "native_test_files": [test],
                "snapshots": {
                    "before": [before],
                    "after": [{"path": "pkg/core.py", "sha256": "0" * 64, "bytes": 99}],
                },
                "native_receipts": {
                    "before": {
                        "PYTEST_INTENT.json": intent,
                        "EXECUTION_MANIFEST.json": execution,
                        "junit.xml": junit,
                    }
                },
            }
            poisoned = copy.deepcopy(record)
            poisoned["snapshots"]["after"][0]["sha256"] = "f" * 64
            poisoned["runtime_patches"] = "forbidden answer"
            first = visible_material.load_visible(root, record)
            second = visible_material.load_visible(root, poisoned)
            self.assertEqual(first, second)
            self.assertEqual(select_once(first)[0], select_once(second)[0])
