"""Clock and original-attempt replay contracts; no fixed performance assertions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from four_gate_common import digest
from fbsde_cpu_replay import PhaseClock, select_attempt, run
from fbsde_cpu_replay_audit import verify_clocks


class ClockReplayTests(unittest.TestCase):
    def pair(self):
        samples=[{'process_cpu_ns':100+i*10,'thread_cpu_ns':100+i*11,
                  'wall_ns':100+i*20,'voluntary_switches':i,
                  'involuntary_switches':0,'minor_faults':0,'gc_collections':0} for i in range(5)]
        intervals=[{**{k:b[k]-a[k] for k in a},'process_minus_caller_thread_cpu_ns':-1}
                   for a,b in zip(samples,samples[1:])]
        probe={'sequence':0,'status':'returned','samples':samples,'intervals':intervals}
        attempt={'sequence':0,'status':'returned','cpu_ns':40,
                 'phase_cpu_ns':{k+'_cpu_ns':10 for k in ('text','encoder','head','receipt')}}
        return probe,attempt

    def test_signed_other_thread_differences_are_retained(self):
        p,a=self.pair();verify_clocks(p,a)
        self.assertEqual(p['intervals'][0]['process_minus_caller_thread_cpu_ns'],-1)

    def test_thread_budget_cannot_replace_process_budget(self):
        p,a=self.pair();a['cpu_ns']=44
        with self.assertRaisesRegex(ValueError,'view CPU'):verify_clocks(p,a)

    def test_modified_phase_is_rejected(self):
        p,a=self.pair();a['phase_cpu_ns']['head_cpu_ns']=11
        with self.assertRaisesRegex(ValueError,'phase CPU'):verify_clocks(p,a)

    def test_clamped_difference_is_rejected(self):
        p,a=self.pair();p['intervals'][0]['process_minus_caller_thread_cpu_ns']=0
        with self.assertRaisesRegex(ValueError,'arithmetic'):verify_clocks(p,a)

    def test_missing_endpoint_is_rejected(self):
        p,a=self.pair();p['samples'].pop()
        with self.assertRaisesRegex(ValueError,'endpoints'):verify_clocks(p,a)

    def test_real_clock_api_records_no_perf_guarantee(self):
        c=PhaseClock();a=c();b=c()
        self.assertGreaterEqual(b,a);self.assertEqual(len(c.report()['samples']),2)

    def test_first_failure_not_label_or_best_runtime_is_selected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);previous=None;rows=[]
            for i,status in enumerate(('returned','budget_exceeded','returned')):
                r={'sequence':i,'previous_sha256':previous,'split':'test','status':status}
                previous=digest(r);rows.append({**r,'attempt_sha256':previous})
            path=root/'test-view-attempts.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            self.assertEqual(select_attempt(root)['sequence'],1)
            raw=path.read_bytes();path.write_bytes(raw[:-1])
            with self.assertRaisesRegex(ValueError,'partial'):select_attempt(root)

    def test_corrupt_chain_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'test-view-attempts.jsonl').write_text(json.dumps({'sequence':0,
                'previous_sha256':None,'split':'test','status':'returned','attempt_sha256':'0'*64})+'\n')
            with self.assertRaisesRegex(ValueError,'chain'):select_attempt(root)

    def test_no_unbounded_diagnostic_launch(self):
        with self.assertRaisesRegex(ValueError,'bounded'):
            run(Path('/unused'),evidence_dir=Path('/unused'),repeats=1025)




class LiveClockBindingTests(unittest.TestCase):
    def files(self, root):
        from fbsde_cpu_replay_audit import audit_live
        probe, attempt = ClockReplayTests().pair()
        attempt.update(split='test',arm='test',id='source',view=0,limit_ns=100_000_000,
            prediction_returned=True,wall_ns=80,previous_sha256=None,text_sha256=digest('x'),head_sha256=digest('h'))
        key=digest(attempt)
        (root/'test-view-attempts.jsonl').write_text(json.dumps({**attempt,'attempt_sha256':key})+'\n')
        probe.update(split='test',arm='test',id='source',view=0,source_sequence=0,
            source_attempt_sha256=key,previous_sha256=None)
        path=root/'test-parallel-clocks.jsonl';path.write_text(json.dumps({**probe,'attempt_sha256':digest(probe)})+'\n')
        return path,probe,audit_live

    def test_bound_live_attempt_is_recomputed(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,audit=self.files(Path(d))
            self.assertEqual(audit(Path(d))['matched_attempts'],1)

    def test_rehashed_wrong_original_attempt_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path,probe,audit=self.files(Path(d));probe['source_attempt_sha256']=digest('other')
            path.write_text(json.dumps({**probe,'attempt_sha256':digest(probe)})+'\n')
            with self.assertRaisesRegex(ValueError,'binding'):audit(Path(d))

    def test_missing_live_clock_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path,_,audit=self.files(Path(d));path.write_text('')
            with self.assertRaisesRegex(ValueError,'coverage'):audit(Path(d))

    def test_rehashed_context_cannot_be_reassigned(self):
        with tempfile.TemporaryDirectory() as d:
            path,probe,audit=self.files(Path(d));probe['view']=1
            path.write_text(json.dumps({**probe,'attempt_sha256':digest(probe)})+'\n')
            with self.assertRaisesRegex(ValueError,'context'):audit(Path(d))


if __name__=='__main__':unittest.main()
