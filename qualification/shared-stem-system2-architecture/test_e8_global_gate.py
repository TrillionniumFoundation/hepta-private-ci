"""Exact independent E8 action-gap contract and global stitching adversaries."""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction as Q
import unittest

from e8_global_gate import Bound, Segment, certify, decide, fq


def valid_segments():
    h=Q(1,4)
    return [
        Segment(h,Q(1),Q(2),Q(3,2),Q(2),Q(2),Q(4,3)),
        Segment(h,Q(3,2),Q(2),Q(2),Q(2),Q(4,3),Q(1)),
    ]


def wrong_reset():
    h=Q(1,4)
    return [
        Segment(h,Q(1),Q(0),Q(1),Q(0),Q(0),Q(0)),
        Segment(h,Q(1),Q(4,3),Q(4,3),Q(4,3),Q(4,3),Q(1)),
    ]


class ExactGlobalGate(unittest.TestCase):
    def test_true_unique_global_solution_full_path(self):
        cert=certify(1,1,valid_segments())
        self.assertTrue(cert.globally_solved)
        self.assertEqual(cert.case,'unique_regular')
        self.assertEqual((cert.max_dynamics_error,cert.max_interface_error,
                          cert.max_field_error,cert.max_terminal_error),(Q(0),)*4)

    def test_unique_local_segments_plus_terminal_do_not_globally_solve(self):
        c=certify(1,1,wrong_reset())
        self.assertFalse(c.globally_solved)
        self.assertEqual(c.max_dynamics_error,0)
        self.assertEqual(c.max_terminal_error,0)
        self.assertGreater(c.max_interface_error,0)
        self.assertGreater(c.max_field_error,0)

    def test_no_solution_and_nonunique_boundary(self):
        p=valid_segments()
        self.assertEqual(certify(1,2,p).case,'no_solution')
        self.assertEqual(certify(0,2,p).case,'non_unique')
        self.assertFalse(certify(1,2,p).globally_solved)
        self.assertFalse(certify(0,2,p).globally_solved)

    def test_algebraic_unique_but_nonregular_is_not_admitted(self):
        c=certify(1,3,valid_segments())
        self.assertEqual(c.case,'nonregular_unique')
        self.assertFalse(c.globally_solved)

    def test_wrong_y_interface_fails_even_when_forward_and_leaf_hold(self):
        wrong=wrong_reset()
        c=certify(1,1,wrong)
        self.assertEqual(c.max_dynamics_error,0)
        self.assertEqual(c.max_terminal_error,0)
        self.assertFalse(c.globally_solved)

    def test_mismatched_x_or_field_fails_closed(self):
        cases=[(0,'x_end',Q(7,4)),(1,'field_end',Q(7,8)),(0,'y_start',Q(5,2))]
        for idx,field,value in cases:
            segments=valid_segments()
            segments[idx]=replace(segments[idx],**{field:value})
            with self.subTest(field=field):
                self.assertFalse(certify(1,1,segments).globally_solved)

    def test_strict_cost_adjusted_certificate_allows_only_toy_candidate(self):
        bounds=[Bound('stop',Q(2,5),Q(1,2)),Bound('explore',Q(4,5),Q(9,10))]
        out=decide(bounds,'stop','explore',Q(1,10),x0=1,g=1,segments=valid_segments())
        self.assertEqual(out.selected,'explore')
        self.assertTrue(out.global_check_executed)
        self.assertEqual(out.reason,'certified_toy_action_gap_only')
        self.assertEqual(out.certified_margin,Q(1,5))
        self.assertIs(out.production_accepted,False)

    def test_tight_gap_skips_global_certification(self):
        bounds=[Bound('stop',Q(2,5),Q(1,2)),Bound('explore',Q(4,5),Q(9,10))]
        out=decide(bounds,'stop','explore',Q(1,2),x0='not-parsed-when-abstaining',g=1,segments=[])
        self.assertEqual(out.selected,'stop')
        self.assertFalse(out.global_check_executed)
        self.assertEqual(out.global_fbsde_case,'not_checked')

    def test_wrong_reset_still_denied_even_with_huge_utility_gap(self):
        bounds=[Bound('stop',Q(0),Q(1,4)),Bound('explore',Q(7),Q(15,2))]
        out=decide(bounds,'stop','explore',Q(0),x0=1,g=1,segments=wrong_reset())
        self.assertEqual(out.selected,'stop')
        self.assertTrue(out.global_check_executed)
        self.assertEqual(out.reason,'no_globally_regular_solution')

    def test_hard_infeasibility_precedes_math_or_utility(self):
        b=[Bound('stop',Q(0),Q(1)),Bound('explore',Q(6),Q(7),False)]
        out=decide(b,'stop','explore',0,x0=1,g=1,segments=valid_segments())
        self.assertEqual(out.reason,'candidate_hard_infeasible')
        self.assertFalse(out.global_check_executed)

    def test_nonstrict_gap_is_not_acceptance(self):
        b=[Bound('stop',Q(0),Q(1,2)),Bound('explore',Q(3,5),Q(9,10))]
        out=decide(b,'stop','explore',Q(1,10),x0=1,g=1,segments=valid_segments())
        self.assertFalse(out.global_check_executed)
        self.assertEqual(out.selected,'stop')

    def test_reject_duplicate_or_incomplete_actions(self):
        for b in ([Bound('a',Q(1),Q(2)),Bound('a',Q(2),Q(3))],
                  [Bound('a',Q(1),Q(2)),Bound('b',Q(3),Q(2))],
                  [Bound('a',Q(1),Q(2),True),Bound('b',Q(2),Q(3),1)],
                  [Bound('A B',Q(1),Q(2)),Bound('b',Q(3),Q(4))]):
            with self.subTest(b=b),self.assertRaises(ValueError):
                decide(b,'a','b',0,x0=1,g=1,segments=valid_segments())
        with self.assertRaises(ValueError):
            decide([Bound('a',Q(0),Q(1))],'a','b',0,x0=1,g=1,segments=valid_segments())

    def test_reject_bool_float_noncanonical_fraction_or_too_big(self):
        for x in (True,0.1,'02','1/02','1/0','1/2 ','nan',2**130):
            with self.subTest(x=x),self.assertRaises((ValueError,ZeroDivisionError)):
                fq(x)

    def test_reject_fabricated_negative_cost(self):
        b=[Bound('stop',Q(0),Q(1)),Bound('explore',Q(3),Q(4))]
        for cost in (-1,True,3.1,101):
            with self.subTest(cost=cost),self.assertRaises(ValueError):
                decide(b,'stop','explore',cost,x0=1,g=1,segments=valid_segments())

    def test_corrupted_duration_and_unbounded_segments_rejected(self):
        for segs in ([],[replace(valid_segments()[0],duration=Q(0))],
                     valid_segments()*17):
            with self.subTest(size=len(segs)),self.assertRaises(ValueError):
                certify(1,1,segs)


if __name__=='__main__':
    unittest.main()
