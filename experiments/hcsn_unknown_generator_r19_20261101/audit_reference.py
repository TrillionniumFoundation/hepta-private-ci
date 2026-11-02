"""Independent scalar completion reference, plus raw owner/fee/statistics checks."""

from itertools import product
import gzip
import json
from pathlib import Path
import time

import numpy as np

from .model import infer
from .world import sample

ROOT = Path(__file__).parent


def reference(prefix, mask, particles):
    absent = list(np.flatnonzero(~mask))
    known = [(i, int(x[:4].argmax()), int(x[4:8].argmax())) for i, x in enumerate(prefix) if mask[i] and x[12] == 1]
    rows = []
    for codes in product(range(-1, 16), repeat=len(absent)):
        writes = sorted(known + [(i, c // 4, c % 4) for i, c in zip(absent, codes, strict=True) if c >= 0])
        if len(writes) != 6 or len({w[1] for w in writes[:4]}) != 4:
            continue
        weight = 0.
        for p in particles:
            factor = (1 - p["q"]) / 16 + p["q"] / 12 * (writes[4][1] != writes[5][1])
            value = p["initial"][writes[0][2]]
            for a, b in zip(writes[:-1], writes[1:], strict=True):
                value *= p["transition"][a[2]][b[2]]
            weight += factor * value / len(particles)
        final = [0] * 4
        for _, k, v in writes:
            final[k] = v
        rows.append((tuple(codes), final, weight))
    total = sum(r[2] for r in rows)
    return [(h, f, w / total) for h, f, w in rows]


def marginal(rows, key):
    p = np.zeros(4)
    for _, final, weight in rows:
        p[final[key]] += weight
    return p


def main():
    start = time.process_time()
    rng = np.random.default_rng(1903321)
    particles = [dict(initial=rng.dirichlet(np.ones(4)).tolist(),
        transition=np.stack([rng.dirichlet(np.ones(4)) for _ in range(4)]).tolist(), q=q) for q in (.1, .8)]
    checks, maximum, worlds, actions = 0, 0., 0, 0
    for generator in range(48):
        world = sample("train", generator, 513)
        if (~world["observed"]).sum() > 3:
            continue
        state = infer(world["prefix"], world["observed"], particles)
        rows = reference(world["prefix"], world["observed"], particles)
        for key in range(4):
            error = float(np.abs(state.probability(key) - marginal(rows, key)).max())
            maximum = max(maximum, error)
            assert error < 2e-12
            checks += 4
            for threshold in (.65, .95):
                for price in (.02, .6):
                    p = marginal(rows, key)
                    expected = 2 * p.max() - 1 if p.max() >= threshold else 0.
                    chosen = None
                    for col, index in enumerate(state.missing):
                        branch_value = -price
                        for code in sorted({r[0][col] for r in rows}):
                            branch = [r for r in rows if r[0][col] == code]
                            mass = sum(r[2] for r in branch)
                            posterior = marginal(branch, key) / mass
                            branch_value += mass * (2 * posterior.max() - 1 if posterior.max() >= threshold else 0.)
                        if branch_value > expected + 1e-12:
                            chosen, expected = index, branch_value
                    assert state.choose(key, price, threshold)[0] == chosen
                    actions += 1
        for col, index in enumerate(state.missing):
            event = world["owner_events"][index]
            code = int(event[:4].argmax()) * 4 + int(event[4:8].argmax()) if event[12] == 1 else -1
            branch = [r for r in rows if r[0][col] == code]
            mass = sum(r[2] for r in branch)
            acquired = state.acquire(index, event)
            assert acquired.acquire(index, event) is acquired
            for key in range(4):
                error = float(np.abs(acquired.probability(key) - marginal(branch, key) / mass).max())
                maximum = max(maximum, error)
                assert error < 2e-12
                checks += 4
        worlds += 1
        if worlds == 12:
            break
    owner_checks = 0
    for directory in (ROOT / "prepare_01", ROOT / "confirm_01"):
        if not (directory / "ARCHIVES.json").exists():
            continue
        for archive in json.loads((directory / "ARCHIVES.json").read_text()):
            if "training" in archive["path"]:
                continue
            for row in json.loads(gzip.decompress((ROOT / archive["path"]).read_bytes())):
                public = row["public"]
                full, prefix, mask = np.array(public["owner_events"]), np.array(public["prefix"]), np.array(public["observed"])
                assert np.array_equal(full[mask], prefix[mask]) and not np.any(prefix[~mask])
                alias = int(np.array(public["query"])[19:23].argmax())
                key = next(int(np.array(b)[:4].argmax()) for b in public["bridges"] if b[19 + alias])
                target = next(int(x[4:8].argmax()) for x in full[::-1] if x[12] == 1 and x[key] == 1)
                assert target == row["target"]
                for model in row["predictions"].values():
                    for value in model.values():
                        assert not value["invalid"]
                        index = value["read_index"]
                        assert value["fee"] == (row["price"] if index is not None else 0)
                        assert value["payoff"] == (2 * value["correct"] - 1 if value["accepted"] else 0) - value["fee"]
                        assert value["correct"] == (int(np.argmax(value["probability"])) == target)
                        if index is not None:
                            assert not mask[index] and np.array_equal(value["actual_read"], full[index])
                        owner_checks += 1
    result = dict(reference_worlds=worlds, marginal_components=checks, independent_action_comparisons=actions,
        maximum_absolute_error=maximum, raw_owner_prediction_checks=owner_checks,
        process_cpu_seconds=time.process_time() - start, passed=True)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
