import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_calibrated_curve import sha_file
from run_calibrated_cells import run_study
from run_full_text_lexical import run_companion, verify_reuse
import test_run_calibrated_cells as driver_fixtures


class FullTextCompanionTests(unittest.TestCase):
    def fixture(self, root):
        dataset, features = driver_fixtures.CalibratedDriverTests().fixture(root)
        main = root/"main"
        protocol = dict(budgets=[8], seeds=[7], checkpoints=[2, 4], l2_grid=[.1])
        run_study(dataset, features, main, holdout_use="new_operational_holdout", protocol=protocol)
        return dataset, features, main, protocol

    def test_short_source_parity_and_all_fits_precede_operational_scoring(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features, main, protocol = self.fixture(root)
            out = root/"complete"
            result = run_companion(dataset, main, out)
            self.assertEqual(result["status"], "prepared")
            self.assertTrue((out/"selection-seal.json").exists())
            self.assertFalse((out/"first/evaluation").exists())
            pins = {t: sha_file(out/t/"prepared/seal.json") for t in ("first", "second")}
            run_study(dataset, features, main, phase="evaluate", holdout_use="new_operational_holdout", protocol=protocol)
            report = run_companion(dataset, main, out, phase="evaluate")
            self.assertEqual(report["tasks_evaluated"], ["first", "second"])
            cost = json.loads((out/"evaluation-source-load-cost.json").read_bytes())
            self.assertFalse(cost["reused_from_same_invocation_preparation"])
            self.assertGreater(cost["wall_ns"], 0)
            for task in ("first", "second"):
                self.assertEqual(sha_file(out/task/"prepared/seal.json"), pins[task])
                for arm in ("exact", "bm25"):
                    path = Path(task)/"evaluation/seed-7_n-8"/f"{arm}.npz"
                    with np.load(main/path, allow_pickle=False) as a, np.load(out/path, allow_pickle=False) as b:
                        for field in ("logits", "probabilities", "eligible"):
                            self.assertTrue(np.array_equal(a[field], b[field]))
            self.assertEqual(report, run_companion(dataset, main, out, phase="evaluate"))
            with self.assertRaisesRegex(ValueError, "before main heldout scoring"):
                run_companion(dataset, main, root/"late-companion")

    def test_source_mutation_and_unprepared_scoring_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, _, main, _ = self.fixture(root)
            out = root/"complete"
            with self.assertRaisesRegex(ValueError, "requires frozen preparation"):
                run_companion(dataset, main, out, phase="evaluate")
            run_companion(dataset, main, out)
            dataset.write_bytes(dataset.read_bytes()+b" ")
            with self.assertRaisesRegex(ValueError, "differs from complete-source"):
                run_companion(dataset, main, out, phase="evaluate")
            self.assertFalse((out/"first/evaluation").exists())

    def test_valid_resealed_wrong_budget_does_not_replace_frozen_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            from cell_calibrated_curve import inventory, write_json
            root = Path(temporary)
            dataset, _, main, _ = self.fixture(root)
            out = root/"complete"
            run_companion(dataset, main, out)
            prepared = out/"first/prepared"
            path = prepared/"frozen.json"
            frozen = json.loads(path.read_bytes())
            frozen["runs"][0]["budget"] = 32
            path.write_text(json.dumps(frozen))
            (prepared/"seal.json").unlink()
            write_json(prepared/"seal.json", {"schema": "hepta.full-text-lexical-preparation-seal.v1",
                                             "files": inventory(prepared)})
            with self.assertRaisesRegex(ValueError, "source draws or labels differ"):
                run_companion(dataset, main, out)

    def test_encoder_reuse_requires_identical_actual_source_draws(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features, main, protocol = self.fixture(root)
            out, other = root/"complete", root/"other"
            run_companion(dataset, main, out, phase="all")
            cost = json.loads((out/"evaluation-source-load-cost.json").read_bytes())
            self.assertEqual(cost["wall_ns"], 0)
            self.assertTrue(cost["reused_from_same_invocation_preparation"])
            run_study(dataset, features, other, holdout_use="new_operational_holdout",
                      protocol=protocol, condition="other encoder condition")
            report = verify_reuse(out, other, root/"reuse.json")
            self.assertEqual(report["numerical_refitting_count"], 0)
            plan_path = other/"study-plan.json"
            plan = json.loads(plan_path.read_bytes())
            plan["protocol"]["seeds"] = [17]
            plan_path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "matching dataset, tasks and fixed protocol"):
                verify_reuse(out, other, root/"invalid-reuse.json")

    def test_missing_task_cannot_fit_after_main_scoring_started(self):
        with tempfile.TemporaryDirectory() as temporary:
            import shutil
            root = Path(temporary)
            dataset, _, main, _ = self.fixture(root)
            out = root/"complete"
            run_companion(dataset, main, out)
            shutil.rmtree(out/"second/prepared")
            (out/"selection-seal.json").unlink()
            (main/"first/evaluation").mkdir()
            with self.assertRaisesRegex(ValueError, "missing operational lexical task"):
                run_companion(dataset, main, out)
            self.assertFalse((out/"second/prepared").exists())

    def test_mid_score_prepared_mutation_prevents_summary_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            import run_full_text_lexical as companion
            root = Path(temporary)
            dataset, _, main, _ = self.fixture(root)
            out = root/"complete"
            run_companion(dataset, main, out)
            record = companion._record
            def change_preparation(*args, **kwargs):
                (out/"first/prepared/unexpected.txt").write_text("mid-score mutation")
                return record(*args, **kwargs)
            with patch("run_full_text_lexical._record", side_effect=change_preparation):
                with self.assertRaisesRegex(ValueError, "preparation changed"):
                    run_companion(dataset, main, out, phase="evaluate")
            self.assertFalse((out/"summary.json").exists())


if __name__ == "__main__":
    unittest.main()
