"""P0 panel coverage, failed-case retention and deterministic audit schema."""
import unittest

from .hx_obstacle_panel_audit import audit_panel, audit_json, generate_panel


class HXObstaclePanelAuditTests(unittest.TestCase):
    def test_mandatory_adverse_and_regular_retained(self):
        p=generate_panel(count=2)
        self.assertEqual(p[0].sale_fraction,.015)
        self.assertEqual(p[1].sale_fraction,.2)
        a=audit_panel(count=2)
        self.assertEqual(len(a['items']),2)
        self.assertEqual([i['index'] for i in a['items']],[0,1])
        self.assertEqual(sum(a['counts'].values()),2)
        self.assertEqual(a['items'][1]['verdict'],'OBSERVED_EXTRA_STOP')
        self.assertFalse(a['global_certification'])
        self.assertFalse(a['production_activation'])

    def test_same_seed_reproducible(self):
        a=audit_panel(count=2)
        b=audit_panel(count=2)
        self.assertEqual(a,b)
        self.assertIn('"sha256"',audit_json(count=2))

    def test_invalid_contract_rejected(self):
        for opts in ({'count':1},{'count':1025},{'coarse_nodes':100},
                     {'fine_nodes':101},{'max_relative_frontier':0},
                     {'seed':-1}):
            with self.subTest(opts=opts),self.assertRaises(ValueError):
                audit_panel(**opts)


if __name__=='__main__':
    unittest.main()
