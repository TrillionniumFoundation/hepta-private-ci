"""Model-free calibration and held-out information contracts."""
import unittest
from fbsde_tracking_novelty import tokens, support_from_training, features, alpha_for, smooth
from fbsde_tracking_novelty_data import FAMILIAR, CALIBRATION, HELDOUT, local_rows, generate, exact_pair
from fbsde_tracking import training_rows


class NoveltyTests(unittest.TestCase):
    def setUp(self):
        self.q = [[.98,.01,.01]]*3
        self.support = support_from_training([t for t,_ in training_rows()])

    def test_support_uses_raw_order_not_head_confidence(self):
        known = features('Then, Dara and Elio swap books.', ['Dara','Elio','Faye'], self.q, self.support)
        new = features('Faye observes Dara trading parcels with Elio.', ['Dara','Elio','Faye'], self.q, self.support)
        self.assertEqual(known[1:3],[0.,0.]); self.assertGreater(new[2],0)
        self.assertEqual(known[3:],new[3:])

    def test_names_do_not_make_new_support(self):
        self.assertEqual(tokens('Dara and Elio swap books.', ['Dara','Elio']),
                         tokens('Mira and Nolan swap books.', ['Mira','Nolan']))

    def test_negation_and_order_are_not_erased(self):
        self.assertNotEqual(tokens('Dara does not swap.'),tokens('Dara does swap.'))
        self.assertNotEqual(tokens('Dara observes Elio.'),tokens('Elio observes Dara.'))

    def test_member_permutation_does_not_change_gate_features(self):
        q = [[.9,.05,.05],[.1,.8,.1],[.2,.3,.5]]
        a = features('Dara trades with Elio.', ['Dara','Elio'],q,self.support)
        b = features('Dara trades with Elio.', ['Dara','Elio'],list(reversed(q)),self.support)
        for x,y in zip(a,b):self.assertAlmostEqual(x,y)

    def test_smoothing_is_not_a_rank_repair(self):
        for a in (0.,.1,.9,.999):
            r = smooth(self.q,a)
            self.assertEqual(max(range(3),key=r[0].__getitem__),0)
            self.assertAlmostEqual(sum(r[0]),1.)
        self.assertEqual(smooth(self.q,1.)[0],[1/3]*3)

    def test_smoothing_supplies_missing_alternatives(self):
        q = [[1.,0.,0.]]*3
        self.assertGreater(smooth(q,.2)[0][1],0)

    def test_invalid_mass_rejected(self):
        for a in (True,-.1,1.1,float('nan')):
            with self.assertRaises(ValueError):smooth(self.q,a)

    def test_bad_laws_rejected(self):
        for q in ([[.1,.1,.1]]*3, [[1.,0.,float('nan')]]*3):
            with self.assertRaises(ValueError):smooth(q,.2)

    def test_stable_extreme_gate(self):
        self.assertEqual(alpha_for([1.,0.,0.,0.,0.,0.],{'weights':[10000.,0.,0.,0.,0.,0.]}),1.)
        self.assertEqual(alpha_for([1.,0.,0.,0.,0.,0.],{'weights':[-10000.,0.,0.,0.,0.,0.]}),0.)

    def test_no_empty_text_or_implicit_label_fields(self):
        with self.assertRaises(ValueError):tokens('...')
        with self.assertRaises(ValueError):support_from_training([{'text':'x','label':1}])

    def test_whole_templates_are_disjoint_not_only_names(self):
        fit = {tokens(r['text'],r['names']) for r in local_rows(FAMILIAR+CALIBRATION)}
        test = {tokens(r['text'],r['names']) for r in local_rows(HELDOUT)}
        self.assertFalse(fit & test)
        self.assertEqual(len(test),4)

    def test_full_generator_inventory_not_selected_on_error(self):
        rows = generate()
        self.assertEqual(len(rows),156)
        self.assertEqual(sum(r['split']=='heldout' for r in rows),96)
        self.assertEqual(rows,generate())
        for r in local_rows(FAMILIAR+CALIBRATION+HELDOUT):
            self.assertEqual(list(exact_pair(r['text'],r['names'])),r['pair'])

if __name__=='__main__':unittest.main()
