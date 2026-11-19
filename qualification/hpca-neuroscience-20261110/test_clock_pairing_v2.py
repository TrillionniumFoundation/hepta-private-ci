import unittest
from dataclasses import replace
from hashlib import sha256
from clock_pairing_v2 import (ARMS, PlanError, TrainingEvent, make_cohort,
                              verify_pair)


def h(x):
    return sha256(x.encode()).hexdigest()


def sample():
    return tuple(TrainingEvent(f"train-{i}", h(f"source-{i}"), 4 + i)
                 for i in range(7))


def plan():
    return make_cohort((11, 17, 23, 29), sample(), model_digest=h("model"),
                       source_tree_digest=h("source-tree"),
                       randomization_salt="preregister-before-eval")


class ClockPlanTests(unittest.TestCase):
    def test_two_arm_real_model_inputs_not_outcome_fixture(self):
        cohort = plan()
        self.assertEqual(len(cohort), 4)
        self.assertEqual([p.seed for p in cohort], [11, 17, 23, 29])
        self.assertEqual(sum(p.arm_order == ARMS for p in cohort), 2)
        self.assertEqual(sum(p.arm_order == tuple(reversed(ARMS)) for p in cohort), 2)
        for pair in cohort:
            verify_pair(pair)
            self.assertEqual(pair.authority, "DENY_ALL")
            self.assertEqual(pair.inference_status, "NOT_RUN")
            self.assertEqual(len(pair.interleaved), 12)
            for group in (0, 1):
                a = [s for s in pair.interleaved if s.group == group]
                b = [s for s in pair.bursty if s.group == group]
                self.assertEqual([(x.event_id, x.source_sha256, x.input_tokens) for x in a],
                                 [(x.event_id, x.source_sha256, x.input_tokens) for x in b])
                self.assertEqual(len(a), 6)

    def test_deterministic_even_after_input_permutation(self):
        a = plan()
        b = make_cohort((29, 23, 17, 11), tuple(reversed(sample())),
                        model_digest=h("model"), source_tree_digest=h("source-tree"),
                        randomization_salt="preregister-before-eval")
        self.assertEqual(a, b)

    def test_order_and_stream_change_under_new_salt(self):
        a = plan()
        b = make_cohort((11, 17, 23, 29), sample(),
                        model_digest=h("model"), source_tree_digest=h("source-tree"),
                        randomization_salt="new-preregistered-salt")
        self.assertNotEqual(tuple(p.plan_digest for p in a),
                            tuple(p.plan_digest for p in b))

    def test_tampered_exposure_refused(self):
        p = plan()[0]
        tampered = list(p.bursty)
        tampered[0] = replace(tampered[0], event_id="injected")
        with self.assertRaises(PlanError):
            verify_pair(replace(p, bursty=tuple(tampered)))

    def test_tampered_order_or_digest_refused(self):
        p = plan()[0]
        for changed in (replace(p, arm_order=("bursty", "bursty")),
                        replace(p, plan_digest=h("forged")),
                        replace(p, source_tree_digest=h("other"))):
            with self.assertRaises(PlanError):
                verify_pair(changed)

    def test_invalid_or_uneven_seeds_refused(self):
        for seeds in ((1,), (1, 1), (1, 2, 3), (True, 2), (-1, 2)):
            with self.subTest(seeds=seeds), self.assertRaises(PlanError):
                make_cohort(seeds, sample(), model_digest=h("model"),
                            source_tree_digest=h("source-tree"),
                            randomization_salt="pre")

    def test_bad_inventory_refused(self):
        bad = (TrainingEvent("x", h("x"), 2), TrainingEvent("x", h("y"), 3))
        with self.assertRaises(PlanError):
            make_cohort((1, 2), bad, model_digest=h("model"),
                        source_tree_digest=h("source-tree"), randomization_salt="pre")
        with self.assertRaises(PlanError):
            make_cohort((1, 2), (TrainingEvent("x", h("x"), 0),),
                        model_digest=h("model"), source_tree_digest=h("source-tree"),
                        randomization_salt="pre")


if __name__ == "__main__":
    unittest.main()
