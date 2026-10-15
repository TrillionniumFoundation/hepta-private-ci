"""Adversarial research contract tests; ALL features/PNG pixels here are synthetic.

The CPU SGD and f64 ridge solves are physically executed, but these tests NEVER
claim pretrained DINO/Granite, natural ScienceQA accuracy or production authority.
"""
from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from e3_scienceqa_contract import (
    ARMS, DATASET_REVISION, E3Error, SIZES, canonical, decode,
    read_jsonl, read_pinned, sha, source_row, unit_probabilities,
    validate_labels, validate_probabilities, validate_source, write_new, write_jsonl,
)
from e3_scienceqa_stage import select, prepare, public_record, source
from e3_scienceqa_review import score, two_sided_mcnemar
from e3_granite_dino_real import fit_and_predict, input_prompts


def study():
    import torch
    import torch.nn.functional as F
    torch.set_num_threads(2)
    rng = torch.Generator().manual_seed(20261015)
    sources, fit, held, labels = [], [], [], {}
    for split in SIZES:
        for i in range(SIZES[split]):
            identity = sha(canonical([split, i]))
            label = (i * 7 + len(split)) % 4
            sources.append({"id": identity, "group": sha(f"pixels/{split}/{i}".encode()),
                            "image": sha(f"file/{split}/{i}".encode()), "split": split,
                            "scope": "public-scienceqa-e3-research",
                            "question": f"Question {split}-{i}?", "hint": "",
                            "choices": [f"Option {k}" for k in range(4)]})
            label_row = {"id": identity, "group": sources[-1]["group"],
                         "split": split, "label": label}
            (held if split == "test" else fit).append(label_row)
            labels[identity] = label
    N = len(sources)
    q = F.normalize(torch.randn(N,384,generator=rng),dim=-1)
    c = F.normalize(torch.randn(N,4,384,generator=rng),dim=-1)
    v = torch.stack([c[i, labels[sources[i]["id"]]] for i in range(N)])
    v = F.normalize(v + .08 * torch.randn(v.shape,generator=rng),dim=-1)
    return sources, fit, held, q, c, v


class Contract(unittest.TestCase):
    def setUp(self):
        self.sources, self.fit, self.held, self.q, self.c, self.v = study()

    def test_source_exact_no_label_target(self):
        self.assertEqual(validate_source(self.sources), SIZES)
        row = dict(self.sources[0], answer=2)
        with self.assertRaises(E3Error):
            source_row(row)

    def test_source_duplicated_case(self):
        rows = copy.deepcopy(self.sources)
        rows[1]["id"] = rows[0]["id"]
        with self.assertRaises(E3Error):
            validate_source(rows)

    def test_source_group_cross_fold(self):
        rows = copy.deepcopy(self.sources)
        rows[-1]["group"] = rows[0]["group"]
        with self.assertRaises(E3Error):
            validate_source(rows)

    def test_cross_fold_identical_question(self):
        rows = copy.deepcopy(self.sources)
        rows[-1]["question"] = rows[0]["question"]
        rows[-1]["choices"] = rows[0]["choices"]
        with self.assertRaises(E3Error):
            validate_source(rows)

    def test_invalid_explicit_target(self):
        rows = copy.deepcopy(self.sources)
        rows[0]["label"] = 0
        with self.assertRaises(E3Error):
            validate_source(rows)

    def test_missing_holdout_label(self):
        with self.assertRaises(E3Error):
            validate_labels(self.sources, self.held[:-1], {"test"})

    def test_label_forbidden_future_in_fit(self):
        with self.assertRaises(E3Error):
            validate_labels(self.sources, self.fit+self.held[:1], {"train","validation"})

    def test_duplicate_label_id_rejected(self):
        rows = copy.deepcopy(self.held)
        rows[1] = rows[0]
        with self.assertRaises(E3Error):
            validate_labels(self.sources, rows, {"test"})

    def test_logits_nan_and_bool_rejected(self):
        for v in ([float('nan')]*4, [True,0.,0.,0.], [0.,0.,1.], [1e999,0.,0.,0.]):
            with self.assertRaises(E3Error):
                unit_probabilities(v)
        with self.assertRaises(E3Error):
            validate_probabilities([.5,.5,.5,-.5])

    def test_double_key_and_overflow_json(self):
        for raw in (b'{"k":1,"k":2}', b'{"k":1e999}', b'{"x":NaN}'):
            with self.assertRaises(E3Error):
                decode(raw)

    def test_pinned_create_only_and_hash_tamper(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'sealed.json'
            digest = write_new(p,{"x":1})
            with self.assertRaises(FileExistsError):
                write_new(p,{"x":2})
            self.assertEqual(read_pinned(p,digest), canonical({"x":1}))
            with self.assertRaises(E3Error):
                read_pinned(p,'0'*64)

    def test_original_question_prompts_have_no_answer_label(self):
        row = self.sources[0]
        texts = input_prompts(row)
        self.assertEqual(len(texts),5)
        self.assertEqual(set(texts[0].split()),set(["query:","Question", "train-0?"]))
        self.assertTrue(all(str(c) in text for c,text in zip(row['choices'],texts[1:])))

    def test_pair_exact_p(self):
        self.assertEqual(two_sided_mcnemar(5,0),.0625)
        self.assertEqual(two_sided_mcnemar(4,0),.125)
        self.assertEqual(two_sided_mcnemar(0,0),1.0)


class PhysicalRidgeAndHead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples, cls.fit, cls.held, cls.q,cls.c,cls.v=study()
        cls.out,cls.receipt=fit_and_predict(cls.samples,cls.fit,cls.q,cls.c,cls.v,steps=30)
        cls.sources_sha=sha(b''.join(canonical(row) for row in cls.samples))
        cls.held_sha=sha(b''.join(canonical(row) for row in cls.held))
        cls.sealed={"schema":"hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions",
           "source_sha256":cls.sources_sha,"arms":list(ARMS),
           "stem_model":{"repo":"ibm-granite/granite-embedding-97m-multilingual-r2",
                         "revision":"835ad14087e140460703cf0fae09f97d469d65c2"},
           "vision_model":{"repo":"facebook/dinov2-small",
                           "revision":"ed25f3a31f01632728cabb09d1542f84ab7b0056"},
           "held_labels_visible_to_inference":False,"physical_text_forward_batches":1,
           "physical_vision_forward_batches":1,"production_accepted":False,
           "fit":dict(cls.receipt,cell_optimizer_updates=30),"predictions":cls.out}

    def test_real_cpu_f64_ridge_and_torch_updates(self):
        self.assertEqual(self.receipt["private_cell_head_parameters"],769)
        self.assertEqual(self.receipt["cell_optimizer_updates"],30)
        self.assertEqual(self.receipt["organ_bridge_parameter_count"],147840)
        self.assertNotEqual(self.receipt['organ_fitted_bridge_sha256'],self.receipt['organ_shuffled_bridge_sha256'])

    def test_sealed_predictions_complete_and_mask_exact(self):
        self.assertEqual(len(self.out),64)
        for row in self.out:
            self.assertEqual(set(row['arms']),set(ARMS))
            self.assertEqual(row['arms']['text_only'],row['arms']['image_masked'])
            for p in row['arms'].values(): validate_probabilities(p)

    def test_scoring_complete_independent_process(self):
        readout=score(self.samples,self.held,self.sealed,source_sha=self.sources_sha,
                      target_sha=self.held_sha,predictions_sha='1'*64)
        self.assertEqual(readout['original_heldout_cases'],64)
        self.assertFalse(readout['production_accepted'])
        self.assertFalse(readout['visual_necessity_ground_truth_adjudicated'])
        self.assertEqual(readout['arms']['text_only'],readout['arms']['image_masked'])
        self.assertIsNone(readout['stem_winner'])

    def test_train_head_invariant_to_changed_calibration_labels(self):
        future=copy.deepcopy(self.fit)
        for x in future:
            if x['split']=='validation':x['label']=(x['label']+1)%4
        _,after=fit_and_predict(self.samples,future,self.q,self.c,self.v,steps=30)
        self.assertEqual(self.receipt['gate_sha256'],after['gate_sha256'])
        self.assertEqual(self.receipt['organ_fitted_bridge_sha256'],after['organ_fitted_bridge_sha256'])

    def test_training_label_change_changes_bridge(self):
        prior=copy.deepcopy(self.fit)
        prior[0]['label']=(prior[0]['label']+1)%4
        _,changed=fit_and_predict(self.samples,prior,self.q,self.c,self.v,steps=30)
        self.assertNotEqual(self.receipt['organ_fitted_bridge_sha256'],changed['organ_fitted_bridge_sha256'])

    def test_reject_held_targets_in_producer(self):
        with self.assertRaises(E3Error):
            fit_and_predict(self.samples,self.fit+self.held,self.q,self.c,self.v,steps=1)

    def test_reject_fabricated_held_result(self):
        counterfeit=copy.deepcopy(self.sealed)
        counterfeit['predictions'][0]['arms']['train_gate']=[1.2,-.2,0.,0.]
        with self.assertRaises(E3Error):
            score(self.samples,self.held,counterfeit,source_sha=self.sources_sha,
                  target_sha=self.held_sha,predictions_sha='1'*64)
        # Even if a valid 4-way prob is substituted, digest pinning is enforced
        # at the file-level entrypoint. This pure scorer cannot authenticate a
        # malicious label-blind producer's semantically fabricated predictions.

    def test_reject_incomplete_arm(self):
        bad=copy.deepcopy(self.sealed)
        bad['predictions'][0]['arms'].pop('rotated_equal_fusion')
        with self.assertRaises(E3Error):
            score(self.samples,self.held,bad,source_sha=self.sources_sha,
                  target_sha=self.held_sha,predictions_sha='1'*64)

    def test_reject_changed_source_group(self):
        bad=copy.deepcopy(self.sealed)
        bad['predictions'][0]['group']='f'*64
        with self.assertRaises(E3Error):
            score(self.samples,self.held,bad,source_sha=self.sources_sha,
                  target_sha=self.held_sha,predictions_sha='1'*64)

    def test_reject_forged_exact_model(self):
        bad=copy.deepcopy(self.sealed)
        bad['vision_model']['revision']='f'*40
        with self.assertRaises(E3Error):
            score(self.samples,self.held,bad,source_sha=self.sources_sha,
                  target_sha=self.held_sha,predictions_sha='1'*64)

    def test_masked_image_not_equal_text_control(self):
        bad=copy.deepcopy(self.sealed)
        bad['predictions'][0]['arms']['image_masked']=[.25]*4
        with self.assertRaises(E3Error):
            score(self.samples,self.held,bad,source_sha=self.sources_sha,
                  target_sha=self.held_sha,predictions_sha='1'*64)


class StageBoundary(unittest.TestCase):
    def test_genuine_image_bytes_staged_before_any_label_read(self):
        from PIL import Image
        data={k:[] for k in SIZES}
        for j,(split,total) in enumerate(SIZES.items()):
            for i in range(total):
                n=j*96+i
                image=Image.new('RGB',(4,4),((n)%256,(n//2)%256,(n//3)%256))
                raw=io.BytesIO();image.save(raw,format='PNG')
                data[split].append({"question":f"Task {split}/{i}","hint":"",
                  "choices":["A","B","C","D"],"image":{"bytes":raw.getvalue()}})
        chosen=select(data)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'staged'
            opened=[]
            def answer(split,index):
                self.assertTrue((root/'inputs'/'cohort-before-labels.json').exists())
                self.assertTrue((root/'inputs'/'sources.jsonl').exists())
                opened.append((split,index))
                return index%4
            src,fit,held=prepare(chosen,answer,root)
            self.assertEqual(len(opened),sum(SIZES.values()))
            sources=read_jsonl(root/'inputs'/'sources.jsonl',src)
            self.assertEqual(validate_source(sources),SIZES)
            self.assertFalse(any('answer' in r or 'label' in r or 'solution' in r for r in sources))
            fitlabels=read_jsonl(root/'inputs'/'fit_labels.jsonl',fit)
            heldlabels=read_jsonl(root/'private_labels'/'test_labels.jsonl',held)
            self.assertEqual(len(fitlabels),128)
            self.assertEqual(len(heldlabels),64)
            self.assertEqual(len(list((root/'images').iterdir())),192)

    def test_malicious_answer_field_rejected_at_selection(self):
        with self.assertRaises(E3Error):
            public_record({"question":"x","hint":"","choices":["A","B","C","D"],
                           "image":{"bytes":b'garbage'},"answer":0})

    def test_invalid_image_rejected(self):
        with self.assertRaises(E3Error):
            source({"bytes":b'not a PNG'})


if __name__=='__main__':unittest.main()
