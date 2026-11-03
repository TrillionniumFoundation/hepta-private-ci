"""The learned route changes with past co-access, while support stays bounded."""

from copy import deepcopy
from hashlib import sha256
import unittest

from allocation import freeze_trace, learn_routes


def sha(text):
    return sha256(text.encode()).hexdigest()


def trace_for(groups):
    return freeze_trace(sha("owner cut"), [
        {"sequence": index + 1, "request_digest": sha(f"request {index}"),
         "readout_digest": sha(f"observed readout {index}"), "addresses": sorted(group)}
        for index, group in enumerate(groups)])


class CausalAllocationTests(unittest.TestCase):
    def test_observed_coaccess_changes_partition_without_changing_capacity(self):
        support = sorted(sha(f"entity {index}") for index in range(8))
        interleaved = trace_for([support[::2], support[1::2]] * 4)
        contiguous = trace_for([support[:4], support[4:]] * 4)
        learned, receipt = learn_routes(support, 2, interleaved)
        other, _ = learn_routes(support, 2, contiguous)
        self.assertNotEqual(learned, other)
        self.assertEqual([sum(value == index for value in learned.values()) for index in range(2)], [4, 4])
        self.assertGreater(receipt["same_shard_training_weight"], receipt["hash_rank_training_weight"])
        self.assertFalse(receipt["causal_execution_verified_by_learner"])
        self.assertFalse(receipt["independent_future_task_gain_established"])

    def test_tampering_stale_cut_or_out_of_support_observation_is_rejected(self):
        support = sorted(sha(f"entity {index}") for index in range(8))
        trace = trace_for([support[:4], support[4:]])
        for mutation in (lambda value: value.update(source_cut_digest=sha("different cut")),
                         lambda value: value["observations"][0].update(readout_digest=sha("invented read")),
                         lambda value: value["observations"][0].update(sequence=9)):
            changed = deepcopy(trace)
            mutation(changed)
            with self.assertRaises(ValueError):
                learn_routes(support, 2, changed)
        foreign = trace_for([[sha("foreign")]])
        with self.assertRaises(ValueError):
            learn_routes(support, 2, foreign)

    def test_digest_is_not_authority_for_a_reauthored_observation(self):
        support = sorted(sha(f"entity {index}") for index in range(4))
        original = trace_for([support])
        invented = deepcopy(original["observations"])
        invented[0]["readout_digest"] = sha("caller invented data")
        rehashed = freeze_trace(original["source_cut_digest"], invented)
        routes, receipt = learn_routes(support, 2, rehashed)
        self.assertEqual(set(routes), set(support))
        self.assertFalse(receipt["authority"])
        self.assertFalse(receipt["causal_execution_verified_by_learner"])


if __name__ == "__main__":
    unittest.main()
