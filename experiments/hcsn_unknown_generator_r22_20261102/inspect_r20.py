"""Read-only development diagnostics from R20 saved arrays; no world-generator imports."""

import gzip
from itertools import permutations, product
import json
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).parent.parent / "hcsn_unknown_generator_r20_20261101"


def inspect():
    start = time.process_time()
    models = json.loads(gzip.decompress((ROOT / "prepare_01/MODELS.json.gz").read_bytes()))
    sequences = np.array(list(product(range(4), repeat=6)))
    powers = np.array([1024, 256, 64, 16, 4, 1])
    symmetry = {}
    for name, model in models.items():
        absolute, relative = 0., 0.
        for permutation in permutations(range(4)):
            indices = np.array(permutation)[sequences] @ powers
            for column in ("same", "distinct"):
                a = np.array(model[column])
                difference = np.abs(a - a[indices])
                absolute, relative = max(absolute, float(difference.max())), max(relative, float((difference / a).max()))
        symmetry[name] = dict(maximum_absolute_difference=absolute, maximum_relative_difference=relative,
                             sequences=4096, permutations=24, key_columns=2)
    panels, samples = {}, {}
    for panel, seed in (("lag2", 220571), ("relabeled_lag2", 220573)):
        meta = json.loads((ROOT / "confirm_v2_01" / panel / "CLUSTER_STATS_ARCHIVE.json").read_text())
        raw = json.loads(gzip.decompress((ROOT / meta["path"]).read_bytes()))
        stats = np.array(raw["context_orbit"])
        n, rng = len(stats), np.random.default_rng(seed)
        draws = []
        for _ in range(64):
            indices = rng.integers(n, size=(64, n))
            count, error = stats[:, 2][indices].sum(1), stats[:, 3][indices].sum(1)
            draws.extend(np.divide(error, count, out=np.ones(64), where=count > 0))
        samples[panel] = np.array(draws)
        panels[panel] = dict(generators=n, fractional=int(stats[:, 2].sum()), errors=int(stats[:, 3].sum()),
            error_generator_clusters=int((stats[:, 3] > 0).sum()), maximum_cluster_errors=float(stats[:, 3].max()),
            development_only_risk_ci95=np.quantile(draws, [.025, .975]).tolist())
    difference = samples["relabeled_lag2"] - samples["lag2"]
    return dict(scope="ExistingR20developmentonly; no new generator calls/confirmation, no original gate changes",
        symmetry=symmetry, panels=panels, development_risk_difference_ci95=np.quantile(difference, [.025, .975]).tolist(),
        resampling="4096independentgeneratorcluster draws perexistingpanel, distinctseeds220571/220573, batch64",
        process_cpu_seconds=time.process_time() - start, original_r20_files_modified=False)


if __name__ == "__main__":
    print(json.dumps(inspect(), sort_keys=True))
