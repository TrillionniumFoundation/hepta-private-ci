"""Candidate content, independent labels, real Head updates and sealed evaluation."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import torch
from torch.nn import functional as F

from experiments.shared_stem_cell import choice_fusion as c
from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_media as p
from experiments.shared_stem_cell import media_execution as m


def features(n=8, width=4):
    g = torch.Generator().manual_seed(121)
    text = F.normalize(torch.randn(n, 4, width, generator=g), dim=-1)
    image = F.normalize(torch.randn(n, 1, width, generator=g), dim=-1).expand(-1, 4, -1)
    return torch.cat([text, image], -1)


class ChoiceTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.x = features()
        self.y = torch.arange(8) % 4

    def fitted(self):
        return c.fit_choices(self.x, self.y, self.x, self.y, logit_scale=10, steps=2)

    def test_no_gold_or_ordinal_in_candidate_text(self):
        row = {"question": "Which object?", "hint": "Use the image.",
               "choices": ["tree", "house", "boat", "car"], "image": {}}
        texts = c.candidate_texts(row)
        self.assertEqual(texts, ["Which object?\nUse the image.\nAnswer: " + a for a in row["choices"]])
        self.assertEqual(c.candidate_texts({**row, "choices": list(reversed(row["choices"]))}), list(reversed(texts)))
        with self.assertRaises(e.InputError):
            c.candidate_texts({**row, "answer": 2})

    def test_exact_prior_preservation(self):
        h = c.ChoiceHead(4, "visual_prior", 10)
        text, image = self.x.chunk(2, -1)
        self.assertTrue(torch.equal(h(self.x.flatten(1)), 10 * (text * image).sum(-1)))
        for mode in ("visual_zero", "text_only"):
            self.assertTrue(torch.equal(c.ChoiceHead(4, mode, 10)(self.x.flatten(1)), torch.zeros(8, 4)))

    def test_real_training_updates_without_extra_steps(self):
        original = torch.optim.AdamW.step
        calls = []
        def step(opt, *a, **kw):
            calls.append(True)
            return original(opt, *a, **kw)
        with patch.object(torch.optim.AdamW, "step", step):
            models, selection = self.fitted()
        self.assertEqual(len(calls), 6)
        for mode in c.MODES:
            self.assertNotEqual(e.parameters(models[mode+":final"]), e.parameters(models[mode+":frozen"]))
        self.assertEqual({v["steps"] for v in selection["training_costs"].values()}, {2})

    def test_option_permutation_equivariance_after_learning(self):
        models, selection = self.fitted()
        result = c.predict_choices(models, selection, self.x)
        self.assertTrue(all(v["within_tolerance"] for v in result["option_permutation"].values()))
        perm = torch.tensor([3, 1, 0, 2])
        for model in models.values():
            torch.testing.assert_close(model(self.x[:, perm].flatten(1)), model(self.x.flatten(1))[:, perm])

    def test_permuted_supervision_preserves_objective(self):
        model = c.ChoiceHead(4, "visual_prior", 10)
        perm = torch.tensor([3, 0, 2, 1])
        inverse = perm.argsort()
        a = F.cross_entropy(model(self.x.flatten(1)), self.y)
        b = F.cross_entropy(model(self.x[:, perm].flatten(1)), inverse[self.y])
        torch.testing.assert_close(a, b)

    def test_text_control_cannot_consume_image(self):
        models, _ = self.fitted()
        x = self.x.clone()
        x[..., 4:] = F.normalize(torch.ones(8, 1, 4), dim=-1).expand(-1, 4, -1)
        self.assertTrue(torch.equal(models["text_only:final"](x.flatten(1)),
                                    models["text_only:final"](self.x.flatten(1))))

    def test_all_invalid_preflight_precedes_optimizer(self):
        bad = self.x.clone(); bad[-1, -1, 0] = float("nan")
        with patch.object(torch.optim, "AdamW", side_effect=AssertionError("optimizer entered")):
            for x, y, scale in ((bad, self.y, 10), (self.x, self.y.float(), 10),
                                 (self.x, self.y, float("nan"))):
                with self.assertRaises(e.InputError):
                    c.fit_choices(self.x, self.y, x, y, logit_scale=scale, steps=2)

    def test_image_must_be_shared_and_norms_valid(self):
        for offset in (0, 4):
            x = self.x.clone(); x[-1, -1, offset:] = 0
            with self.assertRaises(e.InputError):
                c.validate(x)

    def test_rng_features_and_labels_unchanged(self):
        before = self.x.clone(), self.y.clone(), torch.random.get_rng_state()
        self.fitted()
        for x, y in zip(before, (self.x, self.y, torch.random.get_rng_state())):
            self.assertTrue(torch.equal(x, y))

    def test_selection_ranking_recomputed_on_calibration(self):
        _, selection = self.fitted()
        rows = [r for h in selection["histories"].values() for r in h]
        for r in rows:
            self.assertEqual(c.score(torch.tensor(r["probabilities"]), self.y)["correct"], r["correct"])
        best = min(rows, key=lambda r: (-r["correct"], r["nll"], r["step"], r["key"]))
        self.assertEqual(selection["selected_key"], best["key"])
        self.assertEqual({r["step"] for r in rows}, {0, 2})

    def test_model_drift_rejects_before_any_prediction(self):
        models, selection = self.fitted()
        models["text_only:final"].head.base.bias.data[0] += 1
        with patch.object(c.ChoiceHead, "forward", side_effect=AssertionError("prediction entered")):
            with self.assertRaises(e.InputError):
                c.predict_choices(models, selection, self.x)

    def test_absent_arm_and_unbound_selected_key_reject(self):
        models, selection = self.fitted()
        for value in ({**selection, "selected_key": "fabricated"},
                      {**selection, "model_identities": {}}):
            with self.assertRaises(e.InputError):
                c.predict_choices(models, value, self.x)

    def test_large_preceding_cohort_excludes_all_272_records(self):
        # Same existing selector; support both previous finite cohorts, no unbounded history.
        prior = tuple({"text": f"old-{i}", "pixel_sha256": e.sha(str(i).encode())} for i in range(272))
        tiny = {s: [{"question": "q", "hint": "", "choices": ["a","b","c","d"], "image": {"bytes": b"x"}}] for s in p.SIZES}
        with patch.object(p, "source_image", return_value=b"image"), patch.object(p.media, "image_bytes", return_value=Image.new("RGB", (2,2))):
            # Cannot invent three disjoint same-content cases; failure must be cardinality, not history cap.
            with self.assertRaisesRegex(e.InputError, "insufficient eligible validation"):
                p.choose(tiny, lambda *a, **kw: {"input_ids": [1]}, sizes={s:1 for s in p.SIZES}, excluded=prior)

    def test_whole_real_file_entrypoint_seals_selection_before_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rows=[]; public={s:[] for s in p.SIZES}; cohort={s:[] for s in p.SIZES}
            for i, split in enumerate(("train", "train", "validation", "validation", "test", "test")):
                image=root/f"{i}.png"; Image.new("RGB", (8,8), (i,0,0)).save(image)
                raw=image.read_bytes(); idx=len(public[split])
                row={"image":{"bytes":raw}, "question":f"q{i}", "hint":"", "choices":["a","b","c","d"]}
                public[split].append(row); cohort[split].append({"source_split":split,"source_index":idx})
                rows.append({"case_id":f"scienceqa:{split}:{idx}","group":str(i),
                    "split":{"validation":"calibration","test":"holdout"}.get(split,split),
                    "scope":"test-only","observed_at":None,"label":i%4,
                    "inputs":{"text":p.prompt(row),"image":{"path":image.name,"sha256":e.sha(raw)}}})
            raw=b"".join(e.canonical(r) for r in rows);(root/'data.jsonl').write_bytes(raw)
            config={"dataset":{"path":"data.jsonl","sha256":e.sha(raw)},"models":{}}
            class Towers:
                simulated=True
                def __init__(self,*a):
                    self.calls={"clip":0};self.identities={"clip":"fixture"}
                    self.processors={"clip":SimpleNamespace(tokenizer=lambda *a, **kw: {"input_ids":[1]})}
                    self.models={"clip":SimpleNamespace(logit_scale=torch.tensor(2.0))}
                def encode_choices(self,*a):
                    self.calls["clip"]+=2
                    return features(1)[0]
                def close(self): pass
            original=c.predict_choices
            def predict(models,selection,x):
                self.assertTrue((root/'out/selection.json').is_file())
                self.assertFalse((root/'out/predictions.json').exists())
                return original(models,selection,x)
            with patch.object(m,"LocalTowers",Towers), patch.object(c,"predict_choices",predict):
                report=c.run(root,root/'out',public,cohort,config)
            self.assertEqual(report['tower_calls'],{'clip':12})
            self.assertEqual(report['text_candidate_rows'],24)
            self.assertTrue(report['simulated_towers'])
            self.assertEqual(len(report['scores']),6)
            self.assertEqual(report['prediction_sha256'],e.sha((root/'out/predictions.json').read_bytes()))


if __name__ == "__main__":
    unittest.main()
