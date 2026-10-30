"""Independent replay of every test32 checkpoint and data/budget provenance."""
import json
from pathlib import Path
import sys

import jax.numpy as jnp
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from next.common import evaluate_model
from next.sequence.run import make_suite
from next.ridge.models import apply_model,count_parameters
from next.ridge.run import verify_freeze,sha


def main():
    frozen=verify_freeze()
    trained=json.loads((HERE/"results.json").read_text())
    if not trained["complete"]:raise RuntimeError("Confirmation incomplete")
    p=trained["metadata"]["protocol"]
    applies={kind:(lambda pp,x,dt,k=kind:apply_model(pp,x,dt,k)) for kind in p["models"]}
    checks=[]
    for task in p["tasks"]:
        for seed in p["training_seeds"]:
            _,suite,hashes=make_suite(task,seed,p)
            for row in trained["runs"]:
                if row["task"]!=task or row["seed"]!=seed:continue
                path=HERE/row["checkpoint_file"]
                params={key:jnp.asarray(value) for key,value in np.load(path).items()}
                metrics=evaluate_model(applies[row["kind"]],params,suite["test_32"])
                error=max(abs(metrics[key]-row["metrics"]["test_32"][key]) for key in metrics)
                best=min(row["history"],key=lambda h:h["validation"]["loss"])["step"]
                timing=row["timing"]
                passed=(sha(path)==row["checkpoint_sha256"] and hashes==row["data_sha256"]
                    and count_parameters(params)==row["parameter_count"] and error<1e-10
                    and timing["steps"]==600 and timing["warmup_optimizer_updates"]==0
                    and timing["train_examples_seen"]==19200 and timing["optimizer_signature_stable"]
                    and timing["strong_initial_parameters"] and timing["best_step"]==best)
                checks.append(dict(task=task,seed=seed,kind=row["kind"],passed=bool(passed),
                    replay_max_metric_error=float(error),checkpoint_hash=sha(path),best_step=best))
    expected=len(p["models"])*len(p["tasks"])*len(p["training_seeds"])
    result=dict(passed=len(checks)==expected and all(c["passed"] for c in checks),checks=checks,
        expected_runs=expected,freeze_sha256=sha(HERE/"freeze.json"),source_manifest=frozen["source_sha256"],
        replay_scope="Every checkpoint test32 loss/accuracy/Brier/ECE, all data fingerprints and budgets; test64/128 retained from frozen runner")
    (HERE/"audit_results.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(dict(passed=result["passed"],runs=len(checks),max_metric_error=max(c["replay_max_metric_error"] for c in checks))))


if __name__=="__main__":main()
