"""Replay every saved next-stage sequence checkpoint and verify paired receipts."""
import hashlib
import json
from pathlib import Path
import sys

import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.v2_models import apply_model as v2_apply
from next.common import evaluate_model
from next.full_kernel import as_jax_table,full_gates
from next.sequence.models import apply_model
from next.sequence.with_operators import apply_operator_model
from next.sequence.run import make_suite


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    folder=Path(__file__).parent
    source=json.loads((folder/"results.json").read_text())
    assert source["complete"] and len(source["runs"])==90
    protocol=source["metadata"]["protocol"]
    assert source["metadata"]["protocol_sha256"]==sha(folder/"protocol.json")
    applies={kind:(lambda p,x,dt,k=kind:apply_model(p,x,dt,k)) for kind in protocol["models"]}
    table_path=ROOT/"next/full_kernel/baseline_table.npz"
    table=as_jax_table(dict(np.load(table_path)),jnp.float32)
    applies["hcsn_v2_reference"]=lambda p,x,dt:v2_apply(p,x,dt,"hcsn")
    applies["full_hx"]=lambda p,x,dt:apply_operator_model(p,x,dt,lambda z:full_gates(z,table))
    records={"results.json":source}
    for name in ("v2_reference_results.json","full_results.json"):
        records[name]=json.loads((folder/name).read_text())
        assert records[name]["complete"] and len(records[name]["runs"])==15
    expected_table=records["full_results.json"]["metadata"]["full_protocol"]["table_sha256"]
    assert sha(table_path)==expected_table
    all_rows=[row for record in records.values() for row in record["runs"]]
    source_checks=[]
    for name,record in records.items():
        for path,digest in record["metadata"]["source_sha256"].items():
            assert sha(ROOT/path)==digest,(name,path)
            source_checks.append((name,path))
    checks=[]
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            _,suite,hashes=make_suite(task,seed,protocol)
            for row in all_rows:
                if row["task"]!=task or row["seed"]!=seed:continue
                assert row["data_sha256"]==hashes,(task,seed,row["kind"])
                timing=row["timing"]
                assert timing["steps"]==600 and timing["train_examples_seen"]==19200
                assert timing["warmup_optimizer_updates"]==0
                assert timing["compiled_training_shapes"]==3 and timing["optimizer_signature_stable"]
                path=folder/row["checkpoint_file"]
                assert sha(path)==row["checkpoint_sha256"]
                params={name:jnp.asarray(value) for name,value in np.load(path).items()}
                assert sum(a.size for a in params.values())==row["parameter_count"]
                metrics=evaluate_model(applies[row["kind"]],params,suite["test_32"])
                deltas={key:abs(metrics[key]-row["metrics"]["test_32"][key]) for key in metrics}
                assert max(deltas.values())<1e-7,(row["kind"],deltas)
                checks.append(dict(task=task,seed=seed,kind=row["kind"],
                    checkpoint_sha256=row["checkpoint_sha256"],metric_absolute_deltas=deltas,
                    paired_data_fingerprints_match=True,optimizer_budget_matches=True))
    result=dict(passed=True,checkpoints_replayed=len(checks),source_hash_pairs_verified=len(source_checks),
        fixed_full_table_sha256=expected_table,checks=checks,
        max_metric_absolute_error=max(max(c["metric_absolute_deltas"].values()) for c in checks),
        evaluation="Replay test_32 from the saved checkpoint; data hashes also cover curriculum, validation and all OOD sets",
        scope="Artifact integrity and budget equivalence, not superiority or global scientific validity")
    (folder/"checkpoint_audit.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="checks"},indent=2))


if __name__=="__main__":
    main()
