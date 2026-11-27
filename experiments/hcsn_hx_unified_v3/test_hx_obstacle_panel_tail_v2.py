"""Verify corrected HX panel is deterministic, fail-closed and no-drop."""
import unittest
from .hx_obstacle_panel_tail_v2 import audit_panel,panel_parameters

class HXPanelV2Tests(unittest.TestCase):
    def test_adverse_and_regular_cases_retained(self):
        a=audit_panel(count=2)
        self.assertEqual([x['index'] for x in a['items']],[0,1])
        self.assertEqual(a['items'][0]['parameters']['sale_fraction'],.015)
        self.assertEqual(a['items'][1]['parameters']['sale_fraction'],.2)
        self.assertEqual(a['items'][1]['verdict'],'OBSERVED_EXTRA_STOP')
        self.assertEqual(sum(a['counts'].values()),2)
        self.assertFalse(a['global_certification'])
        self.assertFalse(a['production_activation'])

    def test_reproducible_24_case_panel(self):
        a=audit_panel()
        self.assertEqual(len(a['items']),24)
        self.assertEqual(sum(a['counts'].values()),24)
        self.assertEqual(a,audit_panel())
        self.assertTrue(all(x['index']==i for i,x in enumerate(a['items'])))
        self.assertTrue(all(x['verdict'] in a['counts'] for x in a['items']))

    def test_invalid_audit_limits_rejected(self):
        for kw in ({'count':1},{'coarse_nodes':20},{'fine_nodes':102},
                   {'log_upper':10},{'wide_log_upper':1},
                   {'max_frontier_log_spread':1.}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):
                audit_panel(**kw)
        with self.assertRaises(ValueError): panel_parameters(count=1)

if __name__=='__main__':
    unittest.main()
