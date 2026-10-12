"""Complete saved-file audit/mutation tests on a small explicit numerical fixture."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import random
import tempfile
import time
import unittest

from four_gate_common import digest, write_once
from fbsde_coupled import CoupledProfile
from fbsde_continuation import TARGET, compile_bank
from fbsde_workspace import choose_candidate
from fbsde_workspace_audit import audit, check_result


class WorkspaceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        p = CoupledProfile(steps=2); cls.p = p
        ctx = {'scope':'unit-numerical','generation':1,'objective':digest(TARGET)}
        start = time.process_time_ns(); prep_start = start
        bank = compile_bank(p,[-1.,0.,1.],**ctx)
        prep = [{'profile_sha256':digest(asdict(p)),'bank_sha256':bank.identity,'cpu_ns':time.process_time_ns()-prep_start}]
        cs = [{'id':'a','x0':.2,'cost':.2},{'id':'b','x0':.6,'cost':.9}]
        methods = ['cold_all','warm_all','verified_search']; times = []; outputs = {}
        for repeat in range(3):
            order = methods[:]; random.Random(f'65537:fixture:{repeat}').shuffle(order)
            for position, mode in enumerate(order):
                cpu,wall = time.process_time_ns(),time.perf_counter_ns()
                r = choose_candidate(p,cs,bank,mode=mode,**ctx)
                cpu,wall = time.process_time_ns()-cpu,time.perf_counter_ns()-wall
                if repeat == 0: outputs[mode] = r
                times.append({'case_id':'fixture','method':mode,'repeat':repeat,'position':position,
                              'cpu_ns':cpu,'wall_ns':wall,'output_sha256':digest(r)})
        entries = [{'id':'fixture','methods':outputs}]
        totals = {m:sum(t['cpu_ns'] for t in times if t['method']==m) for m in methods}
        doc = {'design':{'methods':methods,'repeats':3,'seed':65537,'gap_tolerance':1e-8,'binding':ctx,
                         'cases':[{'id':'fixture','profile':asdict(p),'candidates':cs}]},
               'outputs':entries,'timings':times,'preparation':prep,
               'summary':{'outputs_sha256':digest(entries),'timings_sha256':digest(times),
                          'preparation_sha256':digest(prep),'query_cpu_ns':totals,
                          'standalone_component_cpu_ns':{m:v+(0 if m=='cold_all' else prep[0]['cpu_ns']) for m,v in totals.items()},
                          'unique_case_refinements':{m:r['refinements'] for m,r in outputs.items()},
                          'raw_proposal_wrong_selections':int(max(outputs['verified_search']['rows'],key=lambda r:r['initial_score'])['candidate']['id'] != outputs['cold_all']['selected']),
                          'verified_disagrees_with_complete_exact':0,'cpu_envelope_ns':time.process_time_ns()-start}}
        for name,value in doc.items(): write_once(cls.root/f'{name}.json',value)
        write_once(cls.root/f'bank-{digest(asdict(p))}.json',{**bank.payload(),'sha256':bank.identity})
        cls.cs = cs; cls.outputs = outputs

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_complete_artifact(self):
        r = audit(self.root)
        self.assertEqual((r['cases'],r['timed_queries']),(1,9))
        self.assertFalse(r['production_promotion_permitted'])

    def test_changed_bank_after_rehash_rejected(self):
        p = next(self.root.glob('bank-*.json')); original = p.read_bytes()
        try:
            b = json.loads(original); b['anchors'][0]['dy_dx0'][0] += 1
            b['sha256'] = digest({k:v for k,v in b.items() if k != 'sha256'})
            p.write_text(json.dumps(b))
            with self.assertRaisesRegex(ValueError,'tangent'): audit(self.root)
        finally: p.write_bytes(original)

    def test_forged_speedup_rejected(self):
        p = self.root/'summary.json'; original = p.read_bytes()
        try:
            b = json.loads(original); b['standalone_component_cpu_ns']['verified_search'] = 0
            p.write_text(json.dumps(b))
            with self.assertRaisesRegex(ValueError,'preparation'): audit(self.root)
        finally: p.write_bytes(original)

    def test_edited_early_decision_rejected(self):
        r = copy.deepcopy(self.outputs['verified_search'])
        r['selected'] = 'b' if r['selected']=='a' else 'a'; r['text'] = f"Select {r['selected']}."
        with self.assertRaises(ValueError): check_result(asdict(self.p),self.cs,r,1e-8)

    def test_refinement_order_cannot_use_later_information(self):
        r = copy.deepcopy(self.outputs['cold_all']); r['events'].reverse()
        with self.assertRaisesRegex(ValueError,'noncausal'): check_result(asdict(self.p),self.cs,r,1e-8)

    def test_missing_query_work_after_rehash_rejected(self):
        p = self.root/'timings.json'; s = self.root/'summary.json'; originals = p.read_bytes(),s.read_bytes()
        try:
            ts = json.loads(originals[0]); ts.pop(); summary = json.loads(originals[1]); summary['timings_sha256'] = digest(ts)
            p.write_text(json.dumps(ts)); s.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError,'missing timed'): audit(self.root)
        finally: p.write_bytes(originals[0]); s.write_bytes(originals[1])

    def test_saved_result_cannot_claim_language_or_production(self):
        for flag in ('semantic_correctness_claimed','production_promotion_permitted'):
            r = copy.deepcopy(self.outputs['verified_search']); r[flag] = True
            with self.assertRaises(ValueError): check_result(asdict(self.p),self.cs,r,1e-8)

    def test_write_once_does_not_replace_first_observation(self):
        p = self.root/'summary.json'; before = p.read_bytes()
        with self.assertRaises(FileExistsError): write_once(p,{'pass':True})
        self.assertEqual(before,p.read_bytes())
