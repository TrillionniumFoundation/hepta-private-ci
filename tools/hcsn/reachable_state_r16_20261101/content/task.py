"""Owner-generated public feature streams, isolated from private key identities."""

import hashlib
import itertools
import json

import numpy as np


DIMENSION = 16
CLASSES = 8
SLOTS = 8
QUERIES = 24
WRITE_FEE = .002
QUERY_FEE = .001
DOMAINS = ("iid", "long_gap", "noise_interference")


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def registry(seed):
    """Compositional keys with disjoint train/selection/confirmation key sets.

    Four categorical attributes each have four values. Two unknown orthogonal
    views encode their concatenated one-hot vectors. Models receive only noisy
    paired views or public streams, never these attributes or transforms.
    """
    rng = np.random.default_rng(seed)
    latent = np.zeros((256, DIMENSION))
    for index, attributes in enumerate(itertools.product(range(4), repeat=4)):
        latent[index, np.arange(4) * 4 + attributes] = .5
    transforms = [np.linalg.qr(rng.normal(size=(DIMENSION, DIMENSION)))[0] for _ in range(2)]
    permutation = rng.permutation(256)
    return dict(views=[latent @ transform for transform in transforms],
                pools=dict(train=permutation[:96], selection=permutation[96:160],
                           confirmation=permutation[160:]), identity=int(seed))


def paired_views(owner, phase, seed, repeats=6):
    """Supervised pairing conveys identity equivalence, not a canonical address."""
    if phase not in ("train", "selection"):
        raise ValueError("Encoder fitting cannot request confirmation pairs")
    rng = np.random.default_rng(seed)
    keys = np.repeat(owner["pools"][phase], repeats)
    rng.shuffle(keys)
    a = owner["views"][0][keys] + rng.normal(0, .03, (len(keys), DIMENSION))
    b = owner["views"][1][keys] + rng.normal(0, .03, (len(keys), DIMENSION))
    return a, b


def episode(owner, phase, seed, domain="iid"):
    """Public stream has no key id, slot id, target, attributes or latent state.

    The separately returned owner record is used only for scoring and the
    explicitly privileged exact-address upper bound. Contents change only on
    public WRITE. Distractors are typed; unknown-distractor classification is
    outside this task. Query targets are fixed before predictions are made.
    """
    if phase not in ("selection", "confirmation", "development") or domain not in DOMAINS:
        raise ValueError("Unknown task phase or domain")
    rng = np.random.default_rng(seed)
    pool = owner["pools"]["selection" if phase == "development" else phase]
    keys = list(map(int, rng.choice(pool, SLOTS, replace=False)))
    truth = {key: int(rng.integers(CLASSES)) for key in keys}
    public, private_ids, targets, query_ids = [], [], [], []
    query_noise = .12 if domain == "noise_interference" else .03
    distractors = 8 if domain == "noise_interference" else 2
    time_scale = 10. if domain == "long_gap" else 1.

    def append(kind, key, value=None):
        modality = 1 if kind == "QUERY" else 0
        noise = query_noise if kind == "QUERY" else .03
        feature = owner["views"][modality][key] + rng.normal(0, noise, DIMENSION)
        event = dict(kind=kind, feature=feature.tolist(), dt=float(rng.uniform(.25, 1.5) * time_scale))
        if kind != "QUERY":
            event["value"] = int(value)
        public.append(event)
        private_ids.append(int(key))

    for key in rng.permutation(keys):
        append("WRITE", int(key), truth[int(key)])
    for query in range(QUERIES):
        if query and query % 4 == 0:
            key = int(rng.choice(keys))
            truth[key] = (truth[key] + int(rng.integers(1, CLASSES))) % CLASSES
            append("WRITE", key, truth[key])
        for _ in range(distractors):
            key = int(rng.choice(pool))
            append("DISTRACTOR", key, int(rng.integers(CLASSES)))
        # A scheduled repetition tests state reuse; other queries are sampled.
        key = query_ids[-1] if query % 5 == 1 else int(rng.choice(keys))
        append("QUERY", key)
        query_ids.append(key)
        targets.append(truth[key])
    owner_record = dict(key_ids=private_ids, targets=targets, query_ids=query_ids,
                        seed=int(seed), domain=domain, public_sha256=digest(public))
    return public, owner_record


def exact_address_oracle(public, key_ids):
    """Privileged identity routing upper bound; receives no future target values."""
    memory, answers = {}, []
    for event, key in zip(public, key_ids, strict=True):
        if event["kind"] == "WRITE":
            memory[key] = event["value"]
        elif event["kind"] == "QUERY":
            answers.append(memory[key])
    return answers


def task_fee(public):
    return (WRITE_FEE * sum(e["kind"] == "WRITE" for e in public)
            + QUERY_FEE * sum(e["kind"] == "QUERY" for e in public)) / QUERIES
