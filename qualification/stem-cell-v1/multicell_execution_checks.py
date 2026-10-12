"""Real tensor tests; synthetic tensors are not pretrained-Encoder evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import torch

from development_tensors import BasisCellHeads, parameter_digest
from shared_cell_execution import forward_shared
from multicell_learning_study import execute, review, probe, folded_parameters, train_population


class PopulationStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def test_cell_training_has_distinct_updates_and_shared_basis(self):
        g = torch.Generator().manual_seed(3)
        x = torch.randn(24, 8, generator=g)
        y = (x[:,0]>0).long()
        old, new, work = train_population(x,y,((x[:12],y[:12]),(x[12:],y[12:])),classes=2,rank=4,steps=20)
        torch.testing.assert_close(old.coefficients[0],old.coefficients[1],atol=0,rtol=0)
        self.assertFalse(torch.equal(new.coefficients[0],new.coefficients[1]))
        self.assertTrue(torch.equal(old.basis,new.basis))
        self.assertEqual(work["total_optimizer_steps"],60)
        self.assertEqual(work["parameter_counts"]["cell_local"],18)

    def test_invalid_training_data_refused(self):
        x,y = torch.ones(8,4),torch.zeros(8,dtype=torch.long)
        for z in (y.float(),torch.full((8,),3),y[:1]):
            with self.assertRaises(ValueError):
                train_population(x,y,((x,z),(x,y)),classes=2,steps=1)

    def test_gate_overflow_is_not_silent_sigmoid_saturation(self):
        bank = BasisCellHeads(4,2,2,("c",))
        with torch.no_grad():
            bank.gate_axes.fill_(2); bank.gates.fill_(torch.finfo(torch.float32).max)
        with self.assertRaisesRegex(ValueError,"gate score"):
            forward_shared(bank,torch.ones(1,4),torch.zeros(1,dtype=torch.long),torch.zeros(1,dtype=torch.long))

    def test_folded_storage_cap_precedes_allocation(self):
        bank = BasisCellHeads(512,128,1,tuple(f"c{i}" for i in range(4096)))
        with self.assertRaisesRegex(ValueError,"64 MiB"):
            folded_parameters(bank)

    def test_balanced_probe_keeps_strong_folded_control(self):
        bank = BasisCellHeads(8,2,4,("a","b"))
        x = torch.ones(2,8)
        result = probe(bank,x,torch.arange(64)%2,torch.arange(64)%2)
        self.assertEqual(result["shared_projection_rows_per_trial"],4)
        self.assertEqual(result["expanded_input_rows_per_trial"],64)
        self.assertEqual(result["active_distinct_cells"],2)
        for method in ("expanded_batch","shared_features","folded_dense"):
            self.assertEqual(sorted(t["position"] for t in result["trials"] if t["method"]==method),[0,1,2])
        self.assertEqual(result["folded_compilation"]["additional_tensor_bytes"],2*(8*2+8+1)*4)
        self.assertGreater(result["complete_probe_wall_ns"],sum(t["wall_ns"] for t in result["trials"]))

    def fixture(self):
        rows = []
        for i in range(80):
            phase = "base" if i<32 else "adapt" if i<48 else "extra" if i<64 else None
            rows.append({"sample_id":str(i),"source_group":f"fixture-{i:03}","label":i%4,
                         "training_phase":phase,"split":"train" if phase else "held_out"})
        x = torch.randn(80,8,generator=torch.Generator().manual_seed(7))
        x[:,:4] += torch.nn.functional.one_hot(torch.arange(80)%4,4)*3
        return rows,x,SimpleNamespace(classes=4)

    def test_heldout_labels_do_not_change_training_or_predictions(self):
        rows,x,config = self.fixture()
        changed = deepcopy(rows)
        for row in changed:
            if row["split"]=="held_out": row["label"]=(row["label"]+1)%4
        with tempfile.TemporaryDirectory() as tmp, patch("multicell_learning_study.load_reference",return_value=({},[],x,{},{})):
            paths = [Path(tmp)/"a",Path(tmp)/"b"]
            for data,out in zip((rows,changed),paths):
                with patch("multicell_learning_study.derive_study",return_value=(data,x,config)):
                    execute("fixture",out)
            for name in ("learned.safetensors","inherited.safetensors","normalizer.safetensors","predictions.json"):
                self.assertEqual((paths[0]/name).read_bytes(),(paths[1]/name).read_bytes())

    def test_separate_score_rejects_rehashed_fake_predictions_and_failed_runs(self):
        data = self.fixture()
        with tempfile.TemporaryDirectory() as tmp, patch("multicell_learning_study.load_reference",return_value=({},[],data[1],{},{})), patch("multicell_learning_study.derive_study",return_value=data):
            root=Path(tmp)/"run"; execute("fixture",root)
            result=review("fixture",root,Path(tmp)/"scores.json")
            self.assertEqual(result["prediction_rows"],64)
            self.assertEqual(result["unique_test_inputs"],16)
            predictions=json.loads((root/"predictions.json").read_text())
            predictions[0]["logits"][0] += 1
            raw=json.dumps(predictions).encode(); (root/"predictions.json").write_bytes(raw)
            run=json.loads((root/"result.json").read_text())
            run["all_files_sha256"]["predictions.json"]=hashlib.sha256(raw).hexdigest()
            (root/"result.json").write_text(json.dumps(run))
            with self.assertRaisesRegex(ValueError,"affine"):
                review("fixture",root,Path(tmp)/"fake-scores.json")
            (root/"FAILED.json").write_text("{}")
            with self.assertRaisesRegex(ValueError,"failed study"):
                review("fixture",root,Path(tmp)/"failed-scores.json")

    def test_append_only_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                execute("not-read",Path(tmp))


if __name__ == "__main__":
    unittest.main()
