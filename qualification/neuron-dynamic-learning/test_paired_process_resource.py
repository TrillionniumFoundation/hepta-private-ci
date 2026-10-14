"""No real-model claim: deterministic malformed GNU time resource fixtures."""
from __future__ import annotations
import copy
from pathlib import Path
import tempfile
import unittest

from paired_process_resource import ResourceEvidenceError, read_gnu_time, audit


def sample_time(mode: str='gemma',**values) -> str:
    measured={
        'Command being timed': f'"/tmp/env/bin/python qualification/neuron-dynamic-learning/agnews_paired_shadow.py --mode {mode} --panel /tmp/panel.json --confirmatory-panel /tmp/new.json --confirmatory-output /tmp/out.json --output /tmp/baseline.json"',
        'User time (seconds)': '5.19',
        'System time (seconds)': '0.40',
        'Elapsed (wall clock) time (h:mm:ss or m:ss)': '0:08.80',
        'Maximum resident set size (kbytes)': '2000000',
        'Exit status': '0'
    }
    measured.update(values)
    return '\n'.join(f'{key}: {value}' for key,value in measured.items())+'\n'


def reports():
    meta={'backend':'google/embeddinggemma-2','stem_digest':'a'*64}
    return ([{'arm_id':k, 'schema':'test', 'production_promotion':'DENY_ALL',
              'real_model_execution_claim':True,
              'model_execution_independently_attested':False, 'metadata':dict(meta)}
             for k in ('gemma2_frozen_head','gemma2_trained_head')],
            {'arm_id':'laya421_frozen', 'production_promotion':'DENY_ALL',
             'real_model_execution_claim':True,
             'model_execution_independently_attested':False,
             'metadata':{'backend':'convaiinnovations/laya', 'trainable_parameters':0}})


class ProcessResource(unittest.TestCase):
    def test_gnu_time_accepted_only_for_exact_executed_matching_workload(self):
        with tempfile.TemporaryDirectory() as folder:
            g=Path(folder)/'g';g.write_text(sample_time())
            l=Path(folder)/'l';l.write_text(sample_time(mode='laya'))
            parsed=audit(g,l,*reports())
            self.assertEqual(parsed['production_promotion'],'DENY_ALL')
            self.assertFalse(parsed['model_lifetime_cost_equalization_proven'])
            self.assertEqual(parsed['measurements']['gemma']['process_peak_rss_bytes'],2_000_000*1024)
            self.assertAlmostEqual(parsed['measurements']['gemma']['wall_seconds_including_model_load'],8.8)
            self.assertEqual(len(parsed['paired_model_reports_sha256']),3)

    def test_bad_or_overclaimed_model_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            g=Path(folder)/'g';g.write_text(sample_time())
            l=Path(folder)/'l';l.write_text(sample_time(mode='laya'))
            for typ in ('unsigned_claim','missing_head','substituted_laya','unknown_backend'):
                gemma,laya=reports()
                if typ=='unsigned_claim':gemma[0]['model_execution_independently_attested']=True
                elif typ=='missing_head':gemma.pop()
                elif typ=='substituted_laya':laya['arm_id']='unknown'
                else:gemma[0]['metadata']['backend']='unknown'
                with self.subTest(typ=typ),self.assertRaises(ResourceEvidenceError):
                    audit(g,l,gemma,laya)

    def test_nonzero_exit_bad_cpu_peak_or_misbound_command_rejected(self):
        bad=[('Exit status','1'),('Maximum resident set size (kbytes)','0'),
             ('Maximum resident set size (kbytes)','nan'),
             ('Elapsed (wall clock) time (h:mm:ss or m:ss)','0:00.00'),
             ('Elapsed (wall clock) time (h:mm:ss or m:ss)','3:62.12'),
             ('User time (seconds)','nan'),
             ('User time (seconds)','-1.0'),
             ('Command being timed','"/tmp/env/bin/python bad.py --mode gemma --confirmatory-panel x --confirmatory-output y"'),
             ('Command being timed','"/tmp/env/bin/python qualification/neuron-dynamic-learning/agnews_paired_shadow.py --mode laya --confirmatory-panel x --confirmatory-output y"'),
             ('Command being timed','"/tmp/env/bin/python qualification/neuron-dynamic-learning/agnews_paired_shadow.py --confirmatory-panel x --confirmatory-output y --mode"')]
        for key,value in bad:
            with self.subTest(key=key,val=value),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'g';path.write_text(sample_time(**{key:value}))
                with self.assertRaises(ResourceEvidenceError): read_gnu_time(path,'gemma')

    def test_gnu_time_duplicate_or_missing_fields_and_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'g'
            for text in (sample_time()+'Exit status: 0\n',
                         sample_time().replace('Exit status: 0\n',''),
                         sample_time().replace('Command being timed: ','Unknown: '),
                         sample_time().replace('0:08.80','0:bogus')):
                p.write_text(text)
                with self.assertRaises(ResourceEvidenceError):read_gnu_time(p,'gemma')
            p.write_text(sample_time());link=Path(folder)/'alias';link.symlink_to(p)
            with self.assertRaises(ResourceEvidenceError):read_gnu_time(link,'gemma')


if __name__=='__main__':unittest.main()
