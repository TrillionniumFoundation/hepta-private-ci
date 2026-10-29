import copy
import math
import unittest
from mechanism import matched_directions, frozen_gate

CFG = dict(learning_rate=.001, beta1=.9, beta2=.999, epsilon=1e-8)

def group(g=(2., -3.), m=(.1, -.2), v=(.2, .3), t=4):
    return {'x': dict(gradient=list(g), first=list(m), second=list(v), clock=t)}

def cells():
    return [dict(paired_seed_slot=s, anchor=a, trained_mode=m, requests=20,
                 sentinel_text_improvement_count=11,
                 median_sentinel_text_native_minus_matched=.01,
                 median_sentinel_text_history_cosine=.2,
                 mean_sentinel_total_matched_minus_native=-.01)
            for s in (1, 2) for a in ('C', 'E') for m in ('S', 'A', 'N')]

class MechanismTests(unittest.TestCase):
    def test_native_exact_formula(self):
        r = matched_directions(group(), **CFG)
        for i, (g, m, v) in enumerate(zip((2., -3.), (.1, -.2), (.2, .3))):
            want = -.001*((.9*m+.1*g)/(1-.9**5))/(math.sqrt((.999*v+.001*g*g)/(1-.999**5))+1e-8)
            self.assertAlmostEqual(r['native']['x'][i], want, places=15)
            self.assertAlmostEqual(r['current']['x'][i]+r['history']['x'][i], want, places=15)

    def test_full_norm_and_fresh_step(self):
        r = matched_directions(group(), **CFG)
        self.assertAlmostEqual(math.hypot(*r['matched_current']['x']), r['native_norm'], places=15)
        r = matched_directions(group(m=(0., 0.), v=(0., 0.), t=0), **CFG)
        for a,b in zip(r['native']['x'],r['matched_current']['x']): self.assertAlmostEqual(a,b,places=15)

    def test_zero_undefined_and_zero_both(self):
        with self.assertRaises(ValueError):
            matched_directions(group(g=(0., 0.)), **CFG)
        r = matched_directions(group(g=(0., 0.), m=(0., 0.), v=(0., 0.), t=0), **CFG)
        self.assertEqual(r['native_norm'], 0.)
        self.assertEqual(r['norm_matching_factor'], 0.)

    def test_input_immutable(self):
        g = group(); original = copy.deepcopy(g)
        matched_directions(g, **CFG)
        self.assertEqual(g, original)

    def test_invalid_state(self):
        for g in (group(v=(-1., .3)), group(t=True), group(g=(float('nan'), 2.)), group(t=0), {}):
            with self.assertRaises(ValueError): matched_directions(g, **CFG)
        with self.assertRaises(ValueError): matched_directions(group(), **{**CFG, 'epsilon': 0.})

    def test_both_seeds_and_strict_threshold(self):
        c = cells(); self.assertTrue(frozen_gate(c)['any_gate'])
        for x in c:
            if x['paired_seed_slot'] == 2 and x['trained_mode'] == 'N':
                x['sentinel_text_improvement_count'] = 10
        self.assertFalse(frozen_gate(c)['any_gate'])

    def test_all_four_conditions(self):
        for key, value in (('median_sentinel_text_native_minus_matched', 1e-10),
                           ('median_sentinel_text_history_cosine', 1e-12),
                           ('mean_sentinel_total_matched_minus_native', 2e-10)):
            c = cells()
            for x in c:
                if x['trained_mode'] == 'N': x[key] = value
            self.assertFalse(frozen_gate(c)['any_gate'])

    def test_complete_inventory(self):
        for c in (cells()[:-1], cells()+cells()[:1]):
            with self.assertRaises(ValueError): frozen_gate(c)
        c = cells(); c[0]['requests'] = 19
        with self.assertRaises(ValueError): frozen_gate(c)

if __name__ == '__main__': unittest.main()
