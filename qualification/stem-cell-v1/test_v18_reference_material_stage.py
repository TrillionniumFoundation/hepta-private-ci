"""No-network physical-byte and unknown-gold V18 admission regressions."""
from __future__ import annotations

import copy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import v18_reference_material_stage as stage
import v17_reference_reader_physical as physical
import v17_reference_independent_review as review
from test_v17_reference_reader import make_plan, paired


def publisher(revision=physical.REVISION, missing=False, mismatched=False):
    files = list(physical.REQUIRED)
    if missing:
        files.remove('tokenizer.json')
    siblings = []
    for name in files:
        payload = ('test-only original bytes ' + name).encode()
        publisher_hash = sha256(payload).hexdigest()
        if name == 'model.safetensors' and mismatched:
            publisher_hash = '0' * 64
        siblings.append(SimpleNamespace(rfilename=name,
            lfs={'sha256': publisher_hash} if name == 'model.safetensors' else None))
    return SimpleNamespace(sha=revision, siblings=siblings)


class Material(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.sources = {}
        for name in physical.REQUIRED:
            path = self.cache / name
            path.write_bytes(('test-only original bytes ' + name).encode())
            self.sources[name] = path
        self.destination = self.root / 'admitted-model'
        self.manifest = self.root / 'manifest.json'

    def stage(self, info=None):
        return stage.materialize(lambda: info or publisher(),
                                 lambda fname: self.sources[fname],
                                 self.destination, self.cache, self.manifest)

    def test_real_physical_file_bytes_and_private_manifest(self):
        spec = self.stage()
        self.assertEqual(set(spec['files_sha256']), set(physical.REQUIRED))
        self.assertEqual(physical.verify_model_files(self.destination, spec), physical.digest(spec))
        for f in self.destination.iterdir():
            self.assertFalse(f.is_symlink())
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o600)
        self.assertFalse(spec['production_authorized'])

    def test_refuse_mutated_remote_revision(self):
        with self.assertRaises(ValueError): self.stage(publisher(revision='main'))
        self.assertFalse(self.destination.exists())

    def test_refuse_missing_weights_or_tokenizer(self):
        with self.assertRaises(ValueError): self.stage(publisher(missing=True))
        self.assertFalse(self.destination.exists())

    def test_refuse_weight_hash_mismatch_and_purge_partial(self):
        with self.assertRaises(ValueError): self.stage(publisher(mismatched=True))
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_refuse_cache_symlink_escape(self):
        external = self.root / 'external'
        external.write_bytes(self.sources['config.json'].read_bytes())
        self.sources['config.json'].unlink()
        self.sources['config.json'].symlink_to(external)
        with self.assertRaises(ValueError): self.stage()
        self.assertFalse(self.destination.exists())

    def test_refuse_reuse_without_mutation(self):
        self.stage()
        manifest = self.manifest.read_bytes()
        with self.assertRaises(ValueError): self.stage()
        self.assertEqual(self.manifest.read_bytes(), manifest)

    def test_refuse_duplicate_publisher_entry(self):
        info = publisher()
        info.siblings.append(info.siblings[0])
        with self.assertRaises(ValueError): self.stage(info)

    def test_refuse_missing_publisher_weight_digest(self):
        info = publisher()
        info.siblings[-1].lfs = None
        with self.assertRaises(ValueError): self.stage(info)


class LabelCensoring(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()
        self.candidate = {rid: {'answer_text':'unknown'} for rid in self.plan['requests']}
        self.reference = {rid: {'answer_text':'Stockholm'} for rid in self.plan['requests']}
        self.golds = []
        for fam in physical.ROOTS:
            self.golds.append({'sample_id':fam, 'qa':[{'answer':'Stockholm'} for _ in range(8)]})
        self.golds.extend({'sample_id':f'extra-{i}', 'qa':[]} for i in range(6))

    def score(self):
        return review.weak_gold_compare(self.plan, self.candidate, self.reference, self.golds)

    def test_missing_five_not_scored_in_denominator(self):
        # A fixed historical 32-case panel: five nonliteral missing gold fields.
        for fam, idx in [('conv-47',4),('conv-47',5),('conv-48',4),
                         ('conv-49',5),('conv-50',7)]:
            next(x for x in self.golds if x['sample_id']==fam)['qa'][idx].pop('answer')
        packet = self.score()
        self.assertEqual(packet['per_cohort_arm'][physical.GROUPS[1]]['witness'],
                         {'cases':16,'publisher_answer_known':11,'publisher_answer_unknown':5,
                          'candidate_substring':0,'reference_substring':11,
                          'candidate_exact':0,'reference_exact':11})
        self.assertIsNone(packet['independent_grounded_task_success'])
        self.assertFalse(packet['human_reviewed_evidence_sufficiency'])

    def test_empty_gold_is_unknown(self):
        self.golds[0]['qa'][4]['answer']='  '
        res=self.score()['per_cohort_arm'][physical.GROUPS[1]]['retrieved']
        self.assertEqual(res['publisher_answer_unknown'],1)
        self.assertEqual(res['publisher_answer_known'],15)

    def test_malformed_nonstring_gold_rejected(self):
        self.golds[0]['qa'][4]['answer']=True
        with self.assertRaises(ValueError):self.score()

    def test_extra_gold_root_rejected(self):
        self.golds.append({'sample_id':'external','qa':[]})
        with self.assertRaises(ValueError):self.score()

    def test_report_allows_no_false_positive_from_missing(self):
        self.golds[0]['qa'][4].pop('answer')
        res=self.score()['per_cohort_arm'][physical.GROUPS[1]]['witness']
        self.assertEqual(res['reference_substring'],15)
        self.assertEqual(res['publisher_answer_known'],15)
        self.assertEqual(res['publisher_answer_unknown'],1)


if __name__ == '__main__': unittest.main()
