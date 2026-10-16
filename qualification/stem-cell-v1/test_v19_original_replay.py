"""Must physically reopen original material; never run as fake source-only pass."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from v19_independent_numpy_review import Invalid, review


class OriginalReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = {}
        for key, var in [('input', 'HEPTA_V19_INPUTS'),
                         ('report', 'HEPTA_V19_REPORT'),
                         ('private', 'HEPTA_V19_PRIVATE')]:
            path = os.getenv(var)
            if not path:
                raise RuntimeError('cannot run original data checks without '+var)
            cls.paths[key] = Path(path)
        cls.public = json.loads(cls.paths['report'].read_text())
        cls.private = json.loads(cls.paths['private'].read_text())

    def test_actual_forward_numeric_replay(self):
        r = review(self.paths['input'], self.paths['report'], self.paths['private'])
        self.assertEqual(r['decision'], 'HOLD_SOURCE_ONLY_OOF_NO_PROSPECTIVE_AUTHORITY')
        self.assertEqual(r['original_case_bound_records'], 105)
        self.assertEqual([r['seed_results'][s]['oof_selected_budget'] for s in (41, 47, 53)],
                         [8, 4, 8])

    def bad(self, public=None, private=None):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d, 'report.json')
            raw = Path(d, 'private.json')
            report.write_text(json.dumps(self.public if public is None else public))
            raw.write_text(json.dumps(self.private if private is None else private))
            with self.assertRaises((Invalid, KeyError, ValueError)):
                review(self.paths['input'], report, raw)

    def test_tamper_source_id(self):
        p = copy.deepcopy(self.private)
        p['records'][0]['case_ids'][0] = 'forged'
        self.bad(private=p)

    def test_tamper_report_selection(self):
        p = copy.deepcopy(self.public)
        p['seeds'][0]['train_only_chosen_budget'] = 80
        self.bad(public=p)

    def test_spoof_future(self):
        p = copy.deepcopy(self.public)
        p['prospective_window_count'] = 2
        self.bad(public=p)

    def test_spoof_authority(self):
        p = copy.deepcopy(self.public)
        p['cell_split_authorized'] = True
        self.bad(public=p)

    def test_blind_label_spoof(self):
        p = copy.deepcopy(self.private)
        p['publisher_labels_for_blind'] = True
        self.bad(private=p)

    def test_delete_physical_record(self):
        p = copy.deepcopy(self.private)
        p['records'].pop()
        self.bad(private=p)

    def test_tampered_logit_and_rehash(self):
        p = copy.deepcopy(self.private)
        r = p['records'][0]
        r['logits'][0][0] += .25
        logits = np.asarray(r['logits'], dtype='<f4')
        r['logit_sha256'] = hashlib.sha256(logits.tobytes()).hexdigest()
        self.bad(private=p)

    def test_tampered_weight_and_rehash(self):
        p = copy.deepcopy(self.private)
        r = p['records'][0]
        r['weight'][0][0] += .5
        w, b = (np.asarray(r[k], dtype='<f4') for k in ('weight', 'bias'))
        r['weights_sha256'] = hashlib.sha256(w.tobytes() + b.tobytes()).hexdigest()
        self.bad(private=p)

    def test_tampered_brier(self):
        p = copy.deepcopy(self.public)
        p['seeds'][0]['fold_train_only_oof_scores']['8']['brier'] = 0.0
        self.bad(public=p)

    def test_cost_nondurable(self):
        p = copy.deepcopy(self.private)
        p['records'][0]['cumulative_training_cpu_ns'] = 0
        self.bad(private=p)


if __name__ == '__main__':
    unittest.main()
