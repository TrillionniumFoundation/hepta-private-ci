import unittest
from fractions import Fraction as Q
from global_consistency import global_boundary,wrong_reset,belief_tree

class GlobalObstruction(unittest.TestCase):
    def test_locally_exact_globally_impossible(self):
        c=global_boundary(1,1,[Q(1,2),Q(1,2)])
        bad=wrong_reset(1,1,[Q(1,2),Q(1,2)])
        self.assertEqual(c.status,"no_solution")
        self.assertFalse(c.globally_solved)
        self.assertEqual(bad["slopes"],(2,4))
        self.assertEqual(bad["local_terminal_residuals"],(0,0))
        self.assertEqual(bad["interface_jumps"],(2,))
        self.assertEqual(bad["terminal_residual"],0)
        self.assertFalse(bad["globally_solved"])
    def test_global_non_unique(self):
        c=global_boundary(0,1,[Q(1,2),Q(1,2)])
        self.assertEqual(c.status,"non_unique")
        self.assertFalse(c.globally_solved)
    def test_regular_global(self):
        c=global_boundary(1,1,[Q(2,5),Q(2,5)])
        self.assertEqual(c.status,"unique_regular")
        self.assertEqual(c.initial_y,5)
        self.assertEqual(c.interface_jumps,(0,))
        self.assertEqual(c.terminal_residual,0)
        self.assertTrue(c.globally_solved)
    def test_algebraically_unique_nonregular(self):
        c=global_boundary(1,1,[Q(3,4),Q(3,4)])
        self.assertEqual(c.status,"nonregular_unique")
        self.assertEqual(c.initial_y,-2)
        self.assertFalse(c.globally_solved)
    def test_invalid_duration(self):
        for hs in ([],[0],[-1],[Q(1,2),0]):
            with self.subTest(hs=hs),self.assertRaises(ValueError):
                global_boundary(1,1,hs)
    def test_tree_cheap_algebra_no_observation(self):
        r=belief_tree((Q(1,2),Q(1,2)),(2,2))
        self.assertEqual((r["action"],r["value"]),("false",Q(1,2)))
    def test_tree_information_value(self):
        r=belief_tree((Q(1,2),Q(1,2)),(0,0))
        self.assertEqual(r["value"],1)
        self.assertTrue(r["action"].startswith("observe_"))
    def test_tree_rejects_invalid_law(self):
        for p,c in [((2,Q(1,2)),(0,0)),((Q(1,2),Q(1,2)),(-1,0)),((0,),(0,0))]:
            with self.assertRaises(ValueError):
                belief_tree(p,c)

if __name__=="__main__":
    unittest.main()
