"""V29 source-only route-isolation tests: no pretrained inference or claim."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v28_physical_lazy_vision as v28
import v29_route_only as v29
from test_v28_physical_lazy_vision import plan as synthetic_full


def synthetic_pair():
    full = synthetic_full()
    raw = v28.canonical(full)
    # Only inside these source tests: mock an isolated synthetic source digest.
    with patch.object(v28, 'PLAN_SHA', v28.sha(raw)):
        rows=v28.validate_plan(full)
        slim={'schema':v29.SCHEMA,'v27_plan_sha256':v28.PLAN_SHA,
              'source_sha256':v28.STEM_SOURCE,'policy':v29.POLICY,
              'threshold':0.005,
              'rows':[{'id':x['id'],'group':x['group'],
                       'trigger_vision':x['trigger_vision']} for x in rows],
              'prelabel_only':True,'no_precomputed_vision_outputs':True,
              'actual_encoder_executed':False,'production_authorized':False}
        minimal=v28.canonical(slim)
    return raw,full,minimal,slim


class Contracts(unittest.TestCase):
    def check(self, mutate=None):
        raw, full, minimal, doc=synthetic_pair()
        if mutate:
            mutate(doc)
        data=v28.canonical(doc)
        with patch.object(v28,'PLAN_SHA',v28.sha(raw)), \
                patch.object(v29,'MINIMAL_SHA256',v28.sha(data)):
            return v29.validate_model_plan(data)

    def reject(self,mutate):
        # Do not merely trip the digest: set a matching *test-only* digest so
        # schema validators must independently reject the invalid payload.
        with self.assertRaises(v28.Reject):
            self.check(mutate)

    def test_original_64_inputs_and_21_only_model_router(self):
        rows=self.check()
        self.assertEqual(len(rows),64)
        self.assertEqual(sum(r['trigger_vision'] for r in rows),21)
        self.assertEqual(set(rows[0]),{'id','group','trigger_vision'})
        self.assertTrue(all('image_class' not in r and 'selected_class' not in r
                            and 'text_class' not in r for r in rows))

    def test_no_cached_vision_predictions_in_minimal_serialization(self):
        _,_,minimal,_=synthetic_pair()
        for excluded in (b'image_class',b'selected_class',b'text_class',
                         b'probabilities',b'labels',b'question',b'choices'):
            self.assertNotIn(excluded,minimal)

    def test_wrong_full_route_digest_rejected(self):
        raw,_,_,_=synthetic_pair()
        with self.assertRaises(v28.Reject):v29.project_original(raw)

    def test_real_reference_pins_remain_original(self):
        self.assertEqual(v28.PLAN_SHA,'c8f3f3d03ef9bdc9722d1197aaa807d901a4d5cda2e6c40d20f8ddcf7d2b8ad2')
        self.assertEqual(v29.MINIMAL_SHA256,'d8a555bef8f95680cd35a16cf3dbe7f8e9ab717fe626e4dc82e6fd61538773a6')

    def test_projection_recomputes_rows_without_emitting_classes(self):
        raw,_,_,_=synthetic_pair()
        # Synthetic tests never loosen public CLI / reference SHA.
        with patch.object(v28,'PLAN_SHA',v28.sha(raw)):
            # Validate output's ordinary routing subset independently before
            # bypassing only the global immutable SHA for this synthetic test.
            x=v28.strict_json(raw);rows=v28.validate_plan(x)
            self.assertEqual(len(rows),64)
            self.assertEqual(sum(a['selected_class']!=a['text_class'] for a in rows),19)

    def test_model_route_rejects_full_v27_envelope(self):
        raw,_,_,_=synthetic_pair()
        with patch.object(v29,'MINIMAL_SHA256',v28.sha(raw)):
            with self.assertRaises(v28.Reject):v29.validate_model_plan(raw)

    def test_noncanonical_json_rejected_even_when_digest_matches(self):
        _,_,minimal,_=synthetic_pair()
        raw=minimal[:-1]+b'  \n'
        with patch.object(v29,'MINIMAL_SHA256',v28.sha(raw)):
            with self.assertRaises(v28.Reject):v29.validate_model_plan(raw)

    def test_extra_score_field_rejected(self):
        self.reject(lambda d:d['rows'][0].update(image_class=1))

    def test_embedded_label_rejected(self):
        self.reject(lambda d:d['rows'][0].update(label=2))

    def test_embedded_media_sha_field_rejected(self):
        self.reject(lambda d:d['rows'][0].update(image='f'*64))

    def test_modified_frozen_policy_rejected(self):
        self.reject(lambda d:d.update(policy='fake_improved_heldout_route'))

    def test_modified_threshold_rejected(self):
        self.reject(lambda d:d.update(threshold=0.1))

    def test_boolean_threshold_rejected(self):
        self.reject(lambda d:d.update(threshold=True))

    def test_wrong_parent_digest_rejected(self):
        self.reject(lambda d:d.update(v27_plan_sha256='f'*64))

    def test_fake_authorization_rejected(self):
        self.reject(lambda d:d.update(production_authorized=True))

    def test_fake_model_execution_rejected(self):
        self.reject(lambda d:d.update(actual_encoder_executed=True))

    def test_fabricated_exposure_rejected(self):
        self.reject(lambda d:d.update(no_precomputed_vision_outputs=False))

    def test_trigger_count_drift_rejected(self):
        self.reject(lambda d:d['rows'][0].update(trigger_vision=False))

    def test_boolean_trigger_required(self):
        self.reject(lambda d:d['rows'][0].update(trigger_vision=1))

    def test_duplicate_group_rejected(self):
        self.reject(lambda d:d['rows'][1].update(group=d['rows'][0]['group']))

    def test_case_duplicate_rejected(self):
        self.reject(lambda d:d['rows'][1].update(id=d['rows'][0]['id']))

    def test_extra_envelope_field_rejected(self):
        self.reject(lambda d:d.update(allow_finaluse=True))

    def test_missing_case_rejected(self):
        self.reject(lambda d:d['rows'].pop())

    def test_write_create_only_with_exact_mode(self):
        _,_,raw,doc=synthetic_pair()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'minimal.json'
            v28.safe_write(path,doc)
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):v28.safe_write(path,doc)

    def test_workflow_cannot_pass_original_full_route_to_model(self):
        flow=(Path(__file__).resolve().parents[2]/'.github'/'workflows'/'hepta-stem-v29-model-route-only.yml').read_text()
        required=('v27_conditional_vision_replay.py seal',
                  'v29_route_only.py', 'd8a555bef8f95680cd35a16cf3dbe7f8e9ab717fe626e4dc82e6fd61538773a6',
                  'rm -f "$RUNNER_TEMP/private-v29-full-plan.json"',
                  'test ! -e "$RUNNER_TEMP/private-v29-full-plan.json"',
                  'v29_physical_lazy_vision.py',
                  '--plan "$RUNNER_TEMP/v29-model-only-route.json"',
                  '--predictor-source-only',
                  "github.event_name == 'push'",'DENY_ALL')
        for item in required:self.assertIn(item,flow)
        self.assertNotIn('--plan "$RUNNER_TEMP/private-v29-full-plan.json" \\\n            --source-dir',flow)
        self.assertLess(flow.index('v27_conditional_vision_replay.py seal'),
                        flow.index('python qualification/stem-cell-v1/v29_route_only.py'))
        self.assertLess(flow.index('python qualification/stem-cell-v1/v29_route_only.py'),
                        flow.index('rm -f "$RUNNER_TEMP/private-v29-full-plan.json"'))
        self.assertLess(flow.index('test ! -e "$RUNNER_TEMP/private-v29-full-plan.json"'),
                        flow.index('python qualification/stem-cell-v1/v29_physical_lazy_vision.py'))


if __name__=='__main__': unittest.main()
