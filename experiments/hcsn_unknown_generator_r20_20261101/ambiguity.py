"""Explicit finite observation-identification limit with one paid missing-token READ."""

import json
import numpy as np

from experiments.hcsn_unknown_generator_r18_20261101.world import token


def verify():
    worlds = []
    for query_write_position in (4, 5):
        for hidden_value in (0, 1):
            full = np.stack([token(2, 2, 0) for _ in range(14)])
            for key in range(4):
                full[key] = token(0, key, 0)
            full[query_write_position] = token(0, 0, hidden_value)
            full[9 - query_write_position] = token(0, 1, 0)
            public = full.copy()
            public[4:6] = 0
            worlds.append(dict(full=full, public=public, target=hidden_value))
    assert all(np.array_equal(w["public"], worlds[0]["public"]) for w in worlds)
    collisions = {}
    for read in (4, 5):
        groups = {}
        for index, world in enumerate(worlds):
            receipt = tuple(map(int, world["full"][read]))
            groups.setdefault(receipt, []).append(index)
        unresolved = [indices for indices in groups.values() if len({worlds[i]["target"] for i in indices}) == 2]
        assert len(unresolved) == 1 and len(unresolved[0]) == 2
        collisions[str(read)] = dict(world_indices=unresolved[0], targets=[worlds[i]["target"] for i in unresolved[0]],
            identical_read_receipt=worlds[unresolved[0][0]]["full"][read].tolist())
    return dict(passed=True, public_prefixes_identical=4, query_address=0,
        mask=[i not in (4, 5) for i in range(14)], worlds=[dict(target=w["target"], full=w["full"].tolist()) for w in worlds],
        unresolved_pairs=collisions, uniform_four_world_prior=dict(unresolved_probability_after_any_one_read=.5,
            best_accuracy_if_answer_every_world=.75, unresolved_conditional_accuracy=.5),
        scope="Concrete oneREAD observation limit. A deterministic policy chooses the same read on the commonprefix; its unresolved pair has identical acquiredtranscript and differenttargets. Uniform prior also covers randomizedreadchoices. No universal90%fractional-answer guarantee or all-abstain coverage qualification.")


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
