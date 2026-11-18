"""Admission rejects model substitution and source replacement before numerical loading."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from cell_experiments import data
from cell_experiments.online_v4 import current_credit_pool_v4 as pool


class CurrentCreditAdmissionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3]
        path = (
            root
            / "qualification/cell-blind-panel-b2-20261118/release-weights/training/verified_credit/manifest.json"
        )
        self.credit = data._parse(path.read_bytes())
        self.manifests = {"P": self.credit["parent_manifest"], "C": self.credit}

    def test_changed_manifest_never_loads_a_base(self):
        changed = copy.deepcopy(self.manifests)
        changed["C"]["objective"] = "all_observed"
        with mock.patch.object(pool.matched, "verify_manifest") as old_admission:
            with mock.patch.object(
                pool.CurrentCreditAdapterPool, "_initialize"
            ) as load:
                with self.assertRaises(ValueError):
                    pool.CurrentCreditAdapterPool(
                        changed, Path("."), Path("."), Path(".")
                    )
                old_admission.assert_not_called()
                load.assert_not_called()

    def test_substituted_loader_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            sentinel = source / "unexpected-code-ran"
            (source / "current_credit.py").write_text(
                "from pathlib import Path\nPath("
                + repr(str(sentinel))
                + ").write_text('bad')\n"
            )
            with self.assertRaises(ValueError):
                pool.load_current(source, self.credit)
            self.assertFalse(sentinel.exists())

    def test_changed_manifest_cannot_select_python_source(self):
        changed = copy.deepcopy(self.credit)
        changed["candidate_files"]["current_credit.py"] = "0" * 64
        with mock.patch.object(pool.importlib.util, "spec_from_file_location") as load:
            with self.assertRaises(ValueError):
                pool.load_current(Path("not-present"), changed)
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
