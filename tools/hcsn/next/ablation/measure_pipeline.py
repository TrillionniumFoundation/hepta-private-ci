"""Complete-kernel raw-input pipeline timing with preload and explicit warmup."""
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
FOLDER=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"next/encoder"))
from next.ablation.models import apply_model
from next.full_kernel import as_jax_table
from raw_pipeline import RawPipeline
from feature_utils import CACHE


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def distribution(values):
    values=np.asarray(values)*1000
    return dict(median_ms=float(np.median(values)),p95_ms=float(np.percentile(values,95)),
                p99_ms=float(np.percentile(values,99)),mean_ms=float(values.mean()))


def main():
    started=time.perf_counter();table_file=ROOT/"next/full_kernel/baseline_table.npz"
    before=time.perf_counter()
    with np.load(table_file) as archive:table=as_jax_table({k:archive[k] for k in archive.files},jnp.float32)
    table_load_seconds=time.perf_counter()-before
    record=dict(protocol=dict(variants=["full","full_sigmoid","memory_only"],seed=0,
        inputs_per_model=50,batch_size=1,warmup_inputs=3,
        input_selection="First50 clean test inputs in the already frozen manifest, same inputs for every model",
        included="Raw tokenization or PNG decode/resize, real frozen encoder, pooling/PCA, CPU tensor conversion, model logits",
        excluded="Source dataset file reading, model/table/checkpoint loading, graph compilation, classification metrics",
        checkpoint_arrays_materialized_before_timing=True,financial_table_fixed_before_timing=True,
        scope="Shared CPU reference; six sequential model blocks; no equal-quality, energy, or significant speed claim"),
        table_load_seconds=table_load_seconds,table_sha256=sha(table_file),datasets={},complete=False,
        cpu_affinity=sorted(os.sched_getaffinity(0)),source_sha256_base="Paths relative to hcsn_research root")
    for dataset in ("ag_news","cifar10"):
        result_path=FOLDER/(dataset+"_results.json")
        result=json.loads(result_path.read_text());assert result["complete"] and len(result["runs"])==35
        assert result["metadata"]["table_sha256"]==sha(table_file)
        before=time.perf_counter();pipeline=RawPipeline(dataset);model_load_seconds=time.perf_counter()-before
        values=pipeline.selected_test_inputs(50);feature_file=CACHE/(dataset+"_features.npz")
        assert sha(feature_file)==result["metadata"]["feature_sha256"]
        cached=np.load(feature_file);feature_error=0.
        for index,value in enumerate(values[:8]):
            feature,_=pipeline(value)
            feature_error=max(feature_error,float(np.max(np.abs(feature[0]-cached["test_x"][index]))))
        assert feature_error<2e-4
        measured=[]
        for variant in record["protocol"]["variants"]:
            row=next(r for r in result["runs"] if r["variant"]==variant and r["seed"]==0)
            checkpoint=FOLDER/row["checkpoint_file"];assert sha(checkpoint)==row["checkpoint_sha256"]
            before=time.perf_counter()
            with np.load(checkpoint) as archive:p={k:jnp.asarray(archive[k]) for k in archive.files}
            checkpoint_load_seconds=time.perf_counter()-before
            apply=partial(apply_model,variant=variant,table=table)
            before=time.perf_counter()
            compiled=jax.jit(apply).lower(p,jnp.zeros((1,17,64),jnp.float32),jnp.ones((1,17),jnp.float32)).compile()
            compilation=time.perf_counter()-before
            def predict(feature):
                return compiled(p,jnp.asarray(feature),jnp.ones((1,17),jnp.float32)).block_until_ready()
            for value in values[:3]:feature,_=pipeline(value);predict(feature)
            totals=[];outputs=[]
            components={k:[] for k in ("preprocessing_seconds","encoder_seconds","pooling_projection_seconds","head_seconds")}
            for value in values:
                before=time.perf_counter();feature,parts=pipeline(value)
                head_start=time.perf_counter();output=predict(feature);parts["head_seconds"]=time.perf_counter()-head_start
                totals.append(time.perf_counter()-before);outputs.append(output)
                for key in components:components[key].append(parts[key])
            predictions=np.concatenate([np.asarray(value) for value in outputs]).argmax(1)
            assert np.array_equal(predictions,row["test_predictions"][:50])
            measured.append(dict(variant=variant,seed=0,trainable_parameters=row["parameter_count"],
                checkpoint_sha256=sha(checkpoint),checkpoint_load_seconds=checkpoint_load_seconds,
                compilation_seconds=compilation,end_to_end=distribution(totals),
                components={k:distribution(v) for k,v in components.items()},
                stored_clean_predictions_equal=True))
            print(dataset,variant,measured[-1]["end_to_end"],flush=True)
        record["datasets"][dataset]=dict(model_session_load_seconds=model_load_seconds,
            raw_vs_cached_feature_max_abs=feature_error,measurement=measured,
            training_results_sha256=sha(result_path),features_sha256=sha(feature_file))
    paths=[Path(__file__),FOLDER/"models.py",ROOT/"next/encoder/raw_pipeline.py",ROOT/"next/encoder/feature_utils.py"]
    paths+=list((ROOT/"next/full_kernel").glob("*.py"))
    record["source_sha256"]={str(p.relative_to(ROOT)):sha(p) for p in paths}
    record.update(complete=True,elapsed_seconds=time.perf_counter()-started)
    (FOLDER/"pipeline_latency.json").write_text(json.dumps(record,indent=2)+"\n")


if __name__=="__main__":
    main()
