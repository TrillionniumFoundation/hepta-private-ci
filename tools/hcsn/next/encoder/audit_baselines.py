"""Replay held-out predictions and source/data fingerprints without retraining."""
from functools import partial
import json
from pathlib import Path
import sys

import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.v2_models import apply_model
from next.common import evaluate_model,classification_metrics
from feature_utils import FOLDER,CACHE,sha


def main():
    report=dict(training_repeated=False,datasets={},all_passed=True)
    for name in ("ag_news","cifar10"):
        result=json.loads((FOLDER/(name+"_baseline_results.json")).read_text())
        manifest=json.loads((FOLDER/(name+"_manifest.json")).read_text())
        assert result["complete"] and len(result["runs"])==20
        path=CACHE/(name+"_features.npz")
        assert sha(path)==result["metadata"]["features_sha256"]==manifest["features_sha256"]
        raw=np.load(path)
        assert all(np.isfinite(raw[k]).all() for k in raw.files)
        data={s:{k:raw[s+"_"+k] for k in ("x","dt","y")}
              for s in ("train","validation","test","corrupted_test")}
        for split in ("train","validation","test"):
            assert np.array_equal(data[split]["y"],[r["label"] for r in manifest["selection"][split]])
        assert np.array_equal(data["test"]["y"],data["corrupted_test"]["y"])
        for source,digest in result["metadata"]["source_sha256"].items():
            assert sha(ROOT/source)==digest,(name,source)
        errors=[]
        for run in result["runs"]:
            checkpoint=FOLDER/run["checkpoint_file"]
            assert sha(checkpoint)==run["checkpoint_sha256"]
            params={k:jnp.asarray(v) for k,v in np.load(checkpoint).items()}
            apply=partial(apply_model,kind=run["kind"])
            maximum=0.
            for split in ("test","corrupted_test"):
                metrics=evaluate_model(apply,params,data[split])
                maximum=max(maximum,max(abs(metrics[k]-run["metrics"][split][k]) for k in metrics))
            assert maximum<1e-10,(name,run["kind"],run["seed"],maximum)
            errors.append(dict(kind=run["kind"],seed=run["seed"],max_metric_difference=maximum))
        linear=result["linear_reference"]
        path=FOLDER/linear["checkpoint_file"]
        assert sha(path)==linear["checkpoint_sha256"]
        p=np.load(path);linear_error=0.
        for split in ("test","corrupted_test"):
            logits=data[split]["x"][:,-1]@p["coef"].T+p["intercept"]
            metrics=classification_metrics(logits,data[split]["y"])
            linear_error=max(linear_error,max(abs(metrics[k]-linear[split][k]) for k in metrics))
        assert linear_error<1e-12
        report["datasets"][name]=dict(checkpoints_replayed=len(errors),runs=errors,
            linear_max_metric_difference=linear_error,features_sha256=sha(CACHE/(name+"_features.npz")),
            source_hashes_match=True,labels_match_manifest=True,
            exact_split_overlap=manifest["selected_exact_overlap"],
            global_corrupted_feature_changed_fraction=manifest["global_feature_changed_fraction"])
    (FOLDER/"baseline_audit.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
