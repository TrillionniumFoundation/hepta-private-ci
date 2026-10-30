"""Actual raw-input-to-logits costs for the prespecified first training seed."""
import json
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from next.full_kernel import as_jax_table
from third.encoder.models import make_apply
from third.encoder.prepare import CACHE, Encoder, source_rows, verify_freeze


def main():
    verify_freeze()
    protocol = json.loads((HERE/"protocol.json").read_text())
    report = dict(scope="Shared CPU wall costs, batch1, all raw encoding and analytical lookup included; not energy or equal-quality cost frontier", datasets={})
    for dataset in protocol["datasets"]:
        source = json.loads((HERE/(dataset+"_results.json")).read_text())
        assert source["complete"]
        manifest = json.loads((HERE/(dataset+"_manifest.json")).read_text())
        feature = np.load(CACHE/(dataset+"_features.npz"))
        wanted = [r["source_row"] for r in manifest["selection"]["test"][:12]]
        pool = source_rows(dataset, "test")
        inputs = [pool[index][1] for index in wanted]
        del pool
        encoder = Encoder(dataset)
        projection, center, scale = (feature[key] for key in ("projection", "center", "scale"))
        encoded = encoder(inputs)
        values = ((encoded-center)@projection)/scale
        reconstruction_error = float(np.max(np.abs(values-feature["test_x"][:len(inputs)])))
        assert reconstruction_error < .002
        table = as_jax_table(dict(np.load(ROOT/"next/full_kernel/baseline_table.npz")))
        linear = {key: jnp.asarray(value) for key, value in np.load(HERE/"checkpoints"/dataset/"linear.npz").items()}
        rows = [row for row in source["runs"] if row["seed"] == protocol["training_seeds"][0]]
        timings = []
        for row in rows:
            params = {k: jnp.asarray(v) for k, v in np.load(HERE/row["checkpoint_file"]).items()}
            apply = make_apply(row["kind"], table, linear if row["regime"] == "linear_plus_dynamic" else None)
            x = jnp.asarray(values[:1], jnp.float32)
            dt = jnp.ones(x.shape[:2], jnp.float32)
            compiled = jax.jit(apply).lower(params, x, dt).compile()
            for _ in range(3):
                compiled(params, x, dt).block_until_ready()
            samples = []
            for value in inputs:
                begin = time.perf_counter()
                tokens = encoder([value])
                middle = time.perf_counter()
                x = jnp.asarray(((tokens-center)@projection)/scale, jnp.float32)
                compiled(params, x, dt).block_until_ready()
                end = time.perf_counter()
                samples.append(dict(total_ms=1000*(end-begin), raw_encoder_ms=1000*(middle-begin),
                                    projection_transfer_head_ms=1000*(end-middle)))
            timings.append(dict(kind=row["kind"], regime=row["regime"], seed=row["seed"],
                                samples=samples, median_total_ms=float(np.median([s["total_ms"] for s in samples])),
                                p95_total_ms=float(np.percentile([s["total_ms"] for s in samples], 95))))
        report["datasets"][dataset] = dict(reconstruction_max_error=reconstruction_error,
                                            fixed_input_count=len(inputs), timings=timings)
        print(dataset, [(r["regime"], r["kind"], r["median_total_ms"]) for r in timings], flush=True)
    (HERE/"runtime.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
