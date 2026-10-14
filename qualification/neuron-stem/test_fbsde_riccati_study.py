"""Run the real deterministic study through its existing entrypoint; reject edits."""
from pathlib import Path
import tempfile
from unittest import TestCase, main

from four_gate_common import canonical, digest, strict_loads
from fbsde_study import run
from fbsde_riccati_audit import audit


class RiccatiStudyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)/'study'
        run(cls.root,'riccati_solver_v1')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_complete_cost_and_solution_audit(self):
        report=audit(self.root)
        self.assertEqual((report['cases'],report['timed_solves']),(24,672))
        self.assertLessEqual(report['max_independently_recomputed_error_bound'],1.002e-10)
        self.assertFalse(report['semantic_superiority_established'])

    def mutate_and_reject(self,name,transform,pattern):
        path=self.root/name; original=path.read_bytes()
        try:
            data=strict_loads(original); transform(data); path.write_bytes(canonical(data))
            with self.assertRaisesRegex(ValueError,pattern):audit(self.root)
        finally:path.write_bytes(original)

    def test_forged_total_cost_rejected(self):
        self.mutate_and_reject('summary.json',lambda d:d.update(solver_cpu_ns=0),'cost sum')

    def test_missing_numerical_control_rejected(self):
        self.mutate_and_reject('solutions.json',lambda d:d[0]['solutions'].pop('cold_picard'),'digest')

    def test_rehashed_nonlinear_answer_mutation_rejected(self):
        p=self.root/'solutions.json';s=self.root/'summary.json'
        oldp,olds=p.read_bytes(),s.read_bytes()
        try:
            vals=strict_loads(oldp);vals[0]['solutions']['cold_riccati_newton']['y'][0]+=.01
            summary=strict_loads(olds);summary['solution_sha256']=digest(vals)
            p.write_bytes(canonical(vals));s.write_bytes(canonical(summary))
            with self.assertRaisesRegex(ValueError,'ORIGINAL'):audit(self.root)
        finally:p.write_bytes(oldp);s.write_bytes(olds)

    def test_rehashed_truncated_forward_trajectory_rejected(self):
        p=self.root/'solutions.json';s=self.root/'summary.json'
        oldp,olds=p.read_bytes(),s.read_bytes()
        try:
            vals=strict_loads(oldp);vals[0]['solutions']['cold_picard']['x'].pop()
            summary=strict_loads(olds);summary['solution_sha256']=digest(vals)
            p.write_bytes(canonical(vals));s.write_bytes(canonical(summary))
            with self.assertRaisesRegex(ValueError,'forward-state inventory'):audit(self.root)
        finally:p.write_bytes(oldp);s.write_bytes(olds)

    def test_fake_performance_ratio_rejected(self):
        def change(d):d['case_summaries'][0]['cold_picard_over_cold_newton_cpu_ratio']=999.
        self.mutate_and_reject('summary.json',change,'performance')

    def test_write_once_entrypoint(self):
        before=(self.root/'summary.json').read_bytes()
        with self.assertRaises(FileExistsError):run(self.root,'riccati_solver_v1')
        self.assertEqual(before,(self.root/'summary.json').read_bytes())

    def test_positive_and_expensive_complementary_controls(self):
        d=strict_loads((self.root/'complementary-control.json').read_bytes())
        low,high=d['cases']
        self.assertEqual(low['one_step_action'],'abstain')
        self.assertEqual(low['multi_step_action'],'read:1')
        self.assertGreater(low['multi_step_value'],.79)
        self.assertEqual(high['multi_step_action'],'abstain')
        self.assertEqual(high['multi_step_value'],0.)


if __name__=='__main__':main()
