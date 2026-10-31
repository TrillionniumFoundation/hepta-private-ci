"""Check the new NumPy executor against real frozen Torch source execution."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from . import finite
from .frozen import FrozenR7
from .run import MODES, REPO, SEEDS, UPSTREAM, checkpoint, write


PROGRAM = r'''
import json, sys
from pathlib import Path
import torch
from experiments.analytic_event_neuron.round7.model import load_model
torch.set_num_threads(1)
request=json.loads(Path(sys.argv[1]).read_text())
x=torch.tensor(request["inputs"], dtype=torch.float64)
records=[]
for item in request["models"]:
    model,_=load_model(item["path"])
    with torch.no_grad():
        content,drive=model.encode(x)
        q=model.state_action_values(x,content)[:,:,1]
        if model.mode=="direct":
            matrix=torch.eye(model.core.n_states,dtype=torch.float64).expand(len(x),-1,-1)
            events=torch.zeros(len(x),model.core.n_states,dtype=torch.float64)
        else:
            matrix,reward=model.core.transition_matrix(drive)
            events=reward.sum(-1)
    records.append(dict(mode=model.mode,seed=item["seed"],q=q.tolist(),matrix=matrix.tolist(),events=events.tolist()))
Path(sys.argv[2]).write_text(json.dumps(dict(torch=torch.__version__,records=records)))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--torch-python", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    graph = finite.build_graph(finite.configurations())
    indices = sorted(set(graph["starts"] + list(map(int, np.linspace(0, len(graph["states"]) - 1, 24, dtype=int)))))
    inputs = graph["x"][indices]
    request = {"inputs": inputs.tolist(), "models": [{"mode": m, "seed": s,
        "path": str(checkpoint(m, s))} for m in MODES for s in SEEDS]}
    with tempfile.TemporaryDirectory(prefix="r8-value-parity-") as temp:
        source, result = Path(temp) / "request.json", Path(temp) / "result.json"
        write(source, request)
        process = subprocess.run([args.torch_python, "-c", PROGRAM, str(source), str(result)],
            cwd=REPO, capture_output=True, text=True, check=True)
        reference = json.loads(result.read_text())
    rows = []
    for record in reference["records"]:
        model = FrozenR7(checkpoint(record["mode"], record["seed"]))
        matrix, events = model.kernels(inputs)
        errors = {"q": float(abs(model.old_q(inputs) - record["q"]).max()),
            "matrix": float(abs(matrix - record["matrix"]).max()),
            "events": float(abs(events - record["events"]).max())}
        rows.append({"mode": model.mode, "seed": record["seed"], "errors": errors})
    passed = all(max(r["errors"].values()) < 1e-11 for r in rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write(args.output, {"passed": passed, "torch": reference["torch"], "numpy": np.__version__,
        "public_state_indices": indices, "models": rows, "tolerance": 1e-11,
        "reference_program_sha256": hashlib.sha256(PROGRAM.encode()).hexdigest(),
        "inputs": request, "subprocess_stderr": process.stderr,
        "scope": "Actual Torch forward execution of 15 frozen Round7 checkpoints, no new training"})
    if not passed:
        raise AssertionError(rows)


if __name__ == "__main__":
    main()
