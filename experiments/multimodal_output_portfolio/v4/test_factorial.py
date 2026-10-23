import unittest
from factorial import ArmRow, audit_factorial
from finite_portfolio import InvalidModel


class AttributionTests(unittest.TestCase):
    def test_external_reconstruction_and_required_four_arms(self):
        base = dict(world_id='source-001', truth=0,
                    measured_cost=1.0, cost_unit='measured_cpu_seconds')
        rows = [ArmRow(training=t, inference=i,
                       outputs=(1,1,1,1) if (t,i) == ('baseline','static') else (0,0,0,0), **base)
                for t in ('baseline','ndu') for i in ('static','dynamic')]
        result = audit_factorial(rows)
        self.assertEqual(result['worlds'], 1)
        self.assertAlmostEqual(result['external_loss_interaction'], 1.0)
        with self.assertRaises(InvalidModel):
            audit_factorial(rows[:-1])
        with self.assertRaises(InvalidModel):
            audit_factorial(rows + rows[:1])
        with self.assertRaises(InvalidModel):
            audit_factorial([ArmRow(**{**r.__dict__, 'cost_unit':'proxy_MAC'}) for r in rows])
        with self.assertRaises(InvalidModel):
            audit_factorial([ArmRow(**{**r.__dict__, 'truth':(1 if r.training=='ndu' else 0)}) for r in rows])

if __name__=='__main__': unittest.main()
