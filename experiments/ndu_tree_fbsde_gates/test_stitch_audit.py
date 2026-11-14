import unittest
from dataclasses import replace
from fractions import Fraction as Q
from stitch_audit import (Segment, rational, boundary_case, continuation_fields,
                          construct_regular, audit)

class StitchAuditTests(unittest.TestCase):
    def test_correct_different_grids_exact(self):
        for grid in ([Q(4,5)], [Q(2,5)]*2, [Q(1,5)]*4, [Q(1,10)]*8):
            with self.subTest(grid=grid):
                p=construct_regular(1,1,grid)
                a=audit(1,1,p)
                self.assertTrue(a.globally_solved)
                self.assertEqual(a.boundary_case,"unique_regular")
                self.assertEqual(a.dynamics_residual,0)
                self.assertEqual(a.field_residual,0)
                self.assertEqual(a.x_interface_residual,0)
                self.assertEqual(a.y_interface_residual,0)
                self.assertEqual(p[0].y_start,5)
    def test_wrong_reset_exact_local_zero_global_failure(self):
        # Each half-interval uniquely solves YT=X_T, but no T=1 global solution.
        a=Segment(Q(1,2),1,2,2,2,2,1)
        b=Segment(Q(1,2),2,4,4,4,2,1)
        report=audit(1,1,(a,b))
        self.assertEqual(report.boundary_case,"no_solution")
        self.assertEqual(report.terminal_residual,0)
        self.assertEqual(report.dynamics_residual,0)
        self.assertEqual(report.y_interface_residual,2)
        self.assertFalse(report.proposed_trajectory_valid)
        self.assertFalse(report.globally_solved)
    def test_wrong_final_leaf_rejected(self):
        good=construct_regular(1,1,[Q(2,5),Q(2,5)])
        bad=good[:1]+(replace(good[-1],y_end=good[-1].y_end+1),)
        self.assertGreater(audit(1,1,bad).terminal_residual,0)
        self.assertFalse(audit(1,1,bad).globally_solved)
    def test_missing_x_interface_rejected(self):
        good=construct_regular(1,1,[Q(2,5),Q(2,5)])
        bad=good[:1]+(replace(good[-1],x_start=good[-1].x_start+1),)
        self.assertGreater(audit(1,1,bad).x_interface_residual,0)
        self.assertFalse(audit(1,1,bad).globally_solved)
    def test_field_mismatch_rejected_even_with_perfect_trajectory(self):
        good=construct_regular(1,1,[Q(2,5),Q(2,5)])
        bad=(replace(good[0],field_end=2),)+good[1:]
        a=audit(1,1,bad)
        self.assertTrue(a.proposed_trajectory_valid)
        self.assertGreater(a.field_residual,0)
        self.assertFalse(a.globally_solved)
    def test_nonunique_has_trajectory_but_not_qualification(self):
        one=(Segment(Q(1),0,0,0,0,1,1),)
        a=audit(0,1,one)
        self.assertEqual(a.boundary_case,'non_unique')
        self.assertTrue(a.proposed_trajectory_valid)
        self.assertFalse(a.globally_solved)
    def test_nonregular_unique_has_trajectory_not_field(self):
        one=(Segment(Q(3,2),1,-2,-2,-2,0,0),)
        a=audit(1,1,one)
        self.assertTrue(a.proposed_trajectory_valid)
        self.assertEqual(a.boundary_case,'nonregular_unique')
        self.assertFalse(a.globally_solved)
        with self.assertRaises(ValueError): continuation_fields(1,[Q(3,2)])
    def test_cross_timeline_no_new_terminal(self):
        grid=[Q(1,5)]*4
        fields=continuation_fields(1,grid)
        self.assertEqual(fields[0],5)
        self.assertEqual(fields[-1],1)
        self.assertNotEqual(fields[-2],1)
    def test_strict_rational_input(self):
        for v in (True,1.0,"1/01","01","3/2 ","nan", "1/0", 10**30):
            with self.subTest(v=v),self.assertRaises(ValueError): rational(v)
    def test_unbounded_horizon_refused(self):
        with self.assertRaises(ValueError): construct_regular(1,1,[Q(1,100)]*40)
        with self.assertRaises(ValueError): construct_regular(1,1,[5])
    def test_bad_segment_structure_refused(self):
        with self.assertRaises(ValueError): audit(1,1,[{"x":1}])
        with self.assertRaises(ValueError): audit(1,1,[])
    def test_q24_rounding_not_confused_with_exact(self):
        good=construct_regular(1,1,[Q(2,5),Q(2,5)])
        # A small rounded numerical perturbation is still an exact nonzero residual.
        altered=(replace(good[0],x_end=good[0].x_end+Q(1,2**24)),)+good[1:]
        self.assertFalse(audit(1,1,altered).globally_solved)

if __name__=='__main__': unittest.main()
