import copy
import hashlib
import unittest

import cohort_firewall as cf


def image(index):
    return {
        'source_id': f'coco:val2017:{index}',
        'task_id': f'task-{index}',
        'image_sha256': hashlib.sha256(f'image-{index}'.encode()).hexdigest(),
        'decoded_rgb_sha256': hashlib.sha256(f'rgb-{index}'.encode()).hexdigest(),
        'dhash64': f'{int.from_bytes(hashlib.sha256(f"fingerprint-{index}".encode()).digest()[:8], "big"):016x}',
    }


def manifest(offset=0):
    return {'schema': 'hepta.grounded-cohort.v1', 'splits': {
        split: {'count': 1, 'sources': [image(offset + k)]}
        for k, split in enumerate(cf.SPLITS)
    }}


class CrossHistoryProof(unittest.TestCase):
    def test_baseline_cross_cohort_alias_is_denied(self):
        historical = manifest(0)
        candidate = manifest(32)
        candidate['splits']['dev']['sources'][0]['task_id'] = historical['splits']['train']['sources'][0]['task_id']
        self.assertNotEqual(candidate['splits']['dev']['sources'][0]['source_id'], historical['splits']['train']['sources'][0]['source_id'])
        with self.assertRaisesRegex(cf.CohortContractError, 'candidate task_id aliases historical'):
            cf.check_cohort(candidate, [historical])

    def test_distinct_historical_manifests_cannot_repeat_task_keys(self):
        prior, second = manifest(0), manifest(20000)
        second['splits']['test']['sources'][0]['task_id'] = prior['splits']['train']['sources'][0]['task_id']
        with self.assertRaisesRegex(cf.CohortContractError, 'duplicate task_id across historical'):
            cf.check_cohort(manifest(10000), [prior, second])

    def test_historical_exclusions_do_not_invent_task_ids(self):
        wrapper = {'schema': 'hepta.ndu.historical-exclusions.v1',
                   'source_sample': {'images': [{**image(50000), 'image_id': 50000}]}}
        result = cf.check_cohort(manifest(20000), [wrapper])
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(result['independent_history_trust_established'])

    def test_strict_json_parser_rejects_double_keys(self):
        with self.assertRaisesRegex(cf.CohortContractError, 'duplicate JSON'):
            cf.decode_unambiguous_json(b'{"task_id":"one","task_id":"two"}')

    def test_strict_json_parser_rejects_nonfinite(self):
        for source in (b'{"x":NaN}', b'{"x":1e999999}'):
            with self.assertRaises(cf.CohortContractError):
                cf.decode_unambiguous_json(source)

    def test_normal_new_and_history_still_pass_source_isolation(self):
        result = cf.check_cohort(manifest(32), [manifest(0)])
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(result['real_world_entity_disjointness_attested'])

    def test_source_id_identity_collision_is_denied(self):
        candidate = manifest(32)
        candidate['splits']['train']['sources'][0]['source_id'] = 'coco:val2017:0'
        result = cf.check_cohort(candidate, [manifest(0)])
        self.assertEqual(result['status'], 'fail')

    def test_duplicate_task_key_inside_candidate_denied(self):
        candidate = manifest(32)
        candidate['splits']['test']['sources'][0]['task_id'] = candidate['splits']['train']['sources'][0]['task_id']
        with self.assertRaisesRegex(cf.CohortContractError, 'duplicate task_id'):
            cf.check_cohort(candidate, [manifest(0)])

class FullRostersAndCustody(unittest.TestCase):
    def test_640_history_with_cross_historical_task_alias(self):
        first = {'schema': 'hepta.grounded-cohort.v1', 'splits': {}}
        idx = 0
        for split, count in zip(cf.SPLITS, cf.V1_SPLIT_COUNTS):
            first['splits'][split] = {
                'count': count, 'sources': [image(idx + k) for k in range(count)]
            }
            idx += count
        historical_wrapper = {
            'schema': 'hepta.ndu.historical-exclusions.v1',
            'source_sample': {'images': [
                {**image(1000 + k), 'image_id': 1000 + k}
                for k in range(384)
            ]},
        }
        untouched = manifest(10000)
        self.assertEqual(cf.check_cohort(untouched, [first, historical_wrapper],
                                        require_complete_history=True)['status'], 'pass')
        aliased = manifest(10000)
        aliased['splits']['test']['sources'][0]['task_id'] = first['splits']['train']['sources'][0]['task_id']
        with self.assertRaisesRegex(cf.CohortContractError, 'candidate task_id aliases historical'):
            cf.check_cohort(aliased, [first, historical_wrapper], require_complete_history=True)

    def test_late_symlink_or_hardlink_does_not_modify_frozen_source(self):
        import json, os, tempfile
        from pathlib import Path
        from unittest import mock
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                root=Path(d)
                source=root/'source.json'
                output=root/'report.json'
                source.write_bytes(b'original frozen bytes')
                original_replace=os.replace
                def intercepted(tmp, target):
                    if kind=='symlink':output.symlink_to(source)
                    else:output.hardlink_to(source)
                    return original_replace(tmp,target)
                with mock.patch('cohort_firewall.os.replace',side_effect=intercepted):
                    cf.write_receipt_atomically(output,{'status':'fail'},[source])
                self.assertEqual(source.read_bytes(),b'original frozen bytes')
                self.assertFalse(output.is_symlink())
                self.assertEqual(json.loads(output.read_bytes())['status'],'fail')

    def test_posix_fifo_candidate_denied_without_waiting_for_writer(self):
        import os, json, tempfile, sys, subprocess
        from pathlib import Path
        if not hasattr(os,'mkfifo'):self.skipTest('POSIX mkfifo missing')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); f=root/'fifo.json';os.mkfifo(f)
            h=root/'history.json';raw=json.dumps(manifest(0)).encode();h.write_bytes(raw)
            output=root/'report.json'
            p=subprocess.run([sys.executable,str(Path(cf.__file__).resolve()),
               '--candidate',str(f),'--historical',str(h),
               '--historical-sha256',hashlib.sha256(raw).hexdigest(),
               '--output',str(output)],capture_output=True,text=True,timeout=3)
            self.assertEqual(p.returncode,2,p.stdout+p.stderr)
            self.assertIn('regular file',output.read_text())

if __name__ == '__main__':
    unittest.main()
