"""Independent seeded owner replay; imports no execution/model/generator modules."""

import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).parent
NAMESPACE = {"confirm":53, "rotor":71, "vocabulary":89}


def reproduce(split, generator, index):
    code = NAMESPACE[split]
    latent_rng = np.random.default_rng(np.random.SeedSequence([18011773, code, generator, 991]))
    pi = latent_rng.dirichlet(np.full(4, .7))
    sticky = 0. if latent_rng.random() < .5 else latent_rng.uniform(.55, .95)
    key_mixture = latent_rng.uniform()
    rng = np.random.default_rng(np.random.SeedSequence([18011773, code, generator, index, 317]))
    values = [int(rng.choice(4, p=pi))]
    for _ in range(5):
        if split == "rotor":
            next_value = (values[-1] + 1) % 4 if rng.random() < .95 else int(rng.integers(4))
        else:
            next_value = values[-1] if rng.random() < sticky else int(rng.choice(4, p=pi))
        values.append(next_value)
    keys = list(rng.permutation(4))
    if rng.random() < key_mixture:
        keys.extend(rng.permutation(4)[:2])
    else:
        keys.extend(rng.integers(4, size=2))
    length = 6 + int(rng.choice([8, 24]))
    where = sorted(map(int, rng.choice(length, 6, replace=False)))
    tokens = []
    for _ in range(length):
        tokens.append((2, int(rng.integers(4)), int(rng.integers(4))))
    targets = [None] * 4
    for position, key, value in zip(where, keys, values, strict=True):
        tokens[position] = (0, int(key), value)
        targets[key] = value
    hidden = np.zeros((length, 24), dtype=np.int8)
    for position, (kind, key, value) in enumerate(tokens):
        hidden[position, [key, 4 + value, 12 + kind, 16]] = 1
    mask = np.ones(length, dtype=bool)
    missing = int(rng.choice([2, 3, 4]))
    mask[rng.choice(length, missing, replace=False)] = False
    prefix = hidden.copy()
    prefix[~mask] = 0
    alias_map = rng.permutation(4)
    bridge_tokens = []
    for alias in rng.permutation(4):
        token = np.zeros(24, dtype=np.int8)
        token[[alias_map[alias], 15, 16, 17, 19 + alias]] = 1
        bridge_tokens.append(token.tolist())
    alias = int(rng.integers(4))
    query = np.zeros(24, dtype=np.int8)
    query[[13, 17, 19 + alias]] = 1
    dt = rng.choice([.25, .5, 1.], length)
    dt[-1] += float(rng.choice([20., 100.]))
    if split == "vocabulary":
        position = next(i for i in where if mask[i])
        prefix[position, 4:12] = 0
        prefix[position, 8] = 1
    return dict(public=dict(prefix=prefix.tolist(), observed=mask.tolist(), bridges=bridge_tokens,
                            query=query.tolist(), dt=dt.tolist()),
                target=targets[alias_map[alias]], price=float(rng.choice([.02, .12, .3, .6])),
                hidden=hidden)


def main():
    start = time.process_time()
    archive_index = ROOT / "confirmation_01/ARCHIVES.json"
    rows = []
    for entry in json.loads(archive_index.read_text()):
        path = ROOT / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["compressed_sha256"]
        data = gzip.decompress(path.read_bytes())
        assert hashlib.sha256(data).hexdigest() == entry["raw_sha256"]
        rows.extend(json.loads(data))
    identities, reads = set(), 0
    for row in rows:
        identity = row["split"], row["generator"], row["index"]
        assert identity not in identities
        identities.add(identity)
        owner = reproduce(*identity)
        assert row["public"] == owner["public"]
        assert row["target"] == owner["target"]
        assert row["price"] == owner["price"]
        for model in row["predictions"].values():
            for prediction in model.values():
                if prediction["read_index"] is not None:
                    index = prediction["read_index"]
                    assert not owner["public"]["observed"][index]
                    assert prediction["actual_read"] == owner["hidden"][index].tolist()
                    reads += 1
    assert len(rows) == 1184
    result = dict(schema="hcsn.r18.independent-owner-replay.v1", worlds=len(rows), indexed_reads_verified=reads,
                  complete_public_prefix_masks_aliases_queries_clocks_prices_and_owner_targets_match=True,
                  archives_bound_to_recorded_hashes=True, cpu_seconds=time.process_time() - start,
                  scope="Independent seeded owner generation, not inference or model optimality proof")
    with (ROOT / "INDEPENDENT_OWNER_REPLAY.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
