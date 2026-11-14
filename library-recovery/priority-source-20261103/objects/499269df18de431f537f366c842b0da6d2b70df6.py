"""Tests protect against silent promotion of scoped research to production."""
import copy
import unittest
from .admission import pending_ledger,evaluate_ledger,EvidenceError,REQUIRED


def declared_pass():
    p=pending_ledger()
    for stage in REQUIRED:
        for k in REQUIRED[stage]:
            p['stages'][stage][k]=dict(result='PASS',real_execution=True,
                source_sha='a'*40,result_sha256='b'*64,run_log_sha256='c'*64)
    return p


class GatebookTests(unittest.TestCase):
    def test_empty_research_ledger_remains_deny(self):
        got=evaluate_ledger(pending_ledger())
        self.assertEqual(got['decision'],'DENY_ALL_OFFLINE_RESEARCH_ONLY')
        self.assertEqual(got['blocking_stages'],['P0','P1','P2','P3','P4','P5'])
        self.assertFalse(got['production_activation_allowed'])

    def test_claim_all_pass_but_github_403_still_deny(self):
        got=evaluate_ledger(declared_pass())
        self.assertFalse(got['production_activation_allowed'])
        self.assertFalse(got['all_blockers_closed'])
        self.assertEqual(got['remote_verification'],'UNVERIFIED_REMOTE_SOURCE')

    def test_fabricated_sha_rejected(self):
        data=declared_pass();data['stages']['P0']['global_obstacle']['result_sha256']='not-a-sha'
        with self.assertRaises(EvidenceError): evaluate_ledger(data)

    def test_skipped_or_synthetic_cannot_report_pass(self):
        data=declared_pass();data['stages']['P1']['matched_information_and_derivatives']['real_execution']=False
        with self.assertRaises(EvidenceError): evaluate_ledger(data)

    def test_p1_failed_never_qualified(self):
        data=declared_pass();data['stages']['P1']['incremental_call_risk_margin_gain']['result']='FAIL'
        got=evaluate_ledger(data)
        self.assertIn('P1',got['blocking_stages'])
        self.assertEqual(got['stages'][1]['status'],'FAILED')

    def test_p4_requires_real_four_scale_rows(self):
        got=evaluate_ledger(declared_pass())
        self.assertIn('P4',got['blocking_stages'])
        self.assertFalse(got['four_hardware_scales_complete'])

    def test_missing_one_scale_retains_p4_block(self):
        d=declared_pass()
        row=dict(p95_ms=1.,p99_ms=1.5,rss_mib=10.,vram_mib=1.,
                 joules=.5,throughput_cell_s=1000.,recovery_ms=10.,run_log_sha256='1'*64)
        for n in (64,256,1024):d['hardware']['scale_runs'][str(n)]=row
        self.assertIn('P4',evaluate_ledger(d)['blocking_stages'])

    def test_zero_energy_or_impossible_p99_rejected(self):
        for field,value in (('joules',0.),('p99_ms',-.1),('p95_ms',2.)):
            d=declared_pass()
            row=dict(p95_ms=1.,p99_ms=1.5,rss_mib=10.,vram_mib=1.,
                     joules=.5,throughput_cell_s=1000.,recovery_ms=10.,run_log_sha256='1'*64)
            row[field]=value
            d['hardware']['scale_runs']['64']=row
            with self.subTest(field=field),self.assertRaises(EvidenceError):
                evaluate_ledger(d)

    def test_false_remote_verification_does_not_release(self):
        d=declared_pass();d['source_status']='VERIFIED_EXTERNAL';d['main_sha']='a'*40
        self.assertFalse(evaluate_ledger(d)['production_activation_allowed'])

    def test_extra_unknown_gate_refused(self):
        d=pending_ledger();d['stages']['P5']['silently_skip_matched_baseline']=dict(
            result='MISSING',real_execution=False,source_sha=None,
            result_sha256=None,run_log_sha256=None)
        with self.assertRaises(EvidenceError):evaluate_ledger(d)

    def test_missing_main_sha_is_explicit(self):
        got=evaluate_ledger(pending_ledger())
        self.assertEqual(got['remote_verification'],'UNVERIFIED_REMOTE_SOURCE')

    def test_bad_repo_or_stage_alias_denied(self):
        d=pending_ledger();d['repository']='other/target'
        with self.assertRaises(EvidenceError):evaluate_ledger(d)
        d=pending_ledger();d['stages']['P6']={}
        with self.assertRaises(EvidenceError):evaluate_ledger(d)


if __name__=='__main__': unittest.main()
