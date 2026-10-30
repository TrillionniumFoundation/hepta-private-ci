"""Measure genuine raw-to-logits latency for a fixed representative seed."""
from functools import partial
import json
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.v2_models import apply_model
from raw_pipeline import RawPipeline
from feature_utils import CACHE,FOLDER,sha


def distribution(values):
    values=np.asarray(values)*1000
    return dict(median_ms=float(np.median(values)),p95_ms=float(np.percentile(values,95)),
                p99_ms=float(np.percentile(values,99)),mean_ms=float(values.mean()))


def main():
    record=dict(protocol=dict(seed=0,inputs_per_model=50,batch_size=1,warmup_inputs=3,
        model_selection="Fixed seed0, never best test score",
        included="tokenization or PNG decode/resize, encoder, pooling, frozen PCA, CPU tensor conversion and Head logits",
        excluded="source file I/O, model/session loading, JIT compilation, classification metrics",
        scope="Shared CPU reference latency, not equal-quality or energy comparison"),datasets={},complete=False)
    for dataset in ("ag_news","cifar10"):
        start=time.perf_counter();pipeline=RawPipeline(dataset);load_seconds=time.perf_counter()-start
        values=pipeline.selected_test_inputs(50)
        raw=np.load(CACHE/(dataset+"_features.npz"))
        feature_errors=[]
        for index,value in enumerate(values[:8]):
            feature,_=pipeline(value)
            feature_errors.append(float(np.max(np.abs(feature[0]-raw["test_x"][index]))))
        # Batch1 and batch16 encoder arithmetic can differ by a few float32 ulps.
        assert max(feature_errors)<2e-4,(dataset,feature_errors)
        result=json.loads((FOLDER/(dataset+"_baseline_results.json")).read_text())
        rows=[r for r in result["runs"] if r["seed"]==0]
        rows.append(result["linear_reference"])
        measured=[]
        for row in rows:
            checkpoint=FOLDER/row["checkpoint_file"]
            assert sha(checkpoint)==row["checkpoint_sha256"]
            saved=np.load(checkpoint)
            compilation=0.
            if row["kind"]=="global_mean_logistic_reference":
                def predict(x):
                    return x[:,-1]@saved["coef"].T+saved["intercept"]
            else:
                p={k:jnp.asarray(v) for k,v in saved.items()}
                apply=partial(apply_model,kind=row["kind"])
                start=time.perf_counter()
                compiled=jax.jit(apply).lower(p,jnp.zeros((1,17,64),jnp.float32),jnp.ones((1,17),jnp.float32)).compile()
                compilation=time.perf_counter()-start
                def predict(x):
                    return compiled(p,jnp.asarray(x),jnp.ones((1,17),jnp.float32)).block_until_ready()
            for value in values[:3]:
                feature,_=pipeline(value);predict(feature)
            totals=[];components={k:[] for k in ("preprocessing_seconds","encoder_seconds","pooling_projection_seconds","head_seconds")}
            for value in values:
                start=time.perf_counter();feature,parts=pipeline(value)
                before=time.perf_counter();predict(feature);parts["head_seconds"]=time.perf_counter()-before
                totals.append(time.perf_counter()-start)
                for key in components:components[key].append(parts[key])
            measured.append(dict(kind=row["kind"],parameter_count=row["parameter_count"],
                head_compile_seconds=compilation,end_to_end=distribution(totals),
                components={k:distribution(v) for k,v in components.items()}))
        record["datasets"][dataset]=dict(model_session_load_seconds=load_seconds,
            batch1_vs_cached_batch16_feature_max_abs_error=max(feature_errors),
            measurement=measured,features_sha256=sha(CACHE/(dataset+"_features.npz")))
    record["complete"]=True
    record["source_sha256"]={p.name:sha(p) for p in (Path(__file__),FOLDER/"raw_pipeline.py")}
    (FOLDER/"pipeline_latency.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps({name:{r["kind"]:r["end_to_end"] for r in data["measurement"]}
                      for name,data in record["datasets"].items()},indent=2))


if __name__=="__main__":
    main()
