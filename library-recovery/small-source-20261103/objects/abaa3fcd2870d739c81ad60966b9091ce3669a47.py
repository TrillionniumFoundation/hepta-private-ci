"""Frozen toy counterexample, not a foundation-model experiment."""
import json
from pathlib import Path
import numpy as np
from decoded_risk import Criterion, compare_actual_decoded_output

z = -np.ones(11, dtype=float)
public = {"z": z, "delta": 2*np.ones(11, dtype=float)}
truth = np.ones(11, dtype=float)

def decode(inputs, weights):
    latent = inputs["z"] + weights[0] * inputs["delta"]
    # Nonlinear decoder maps the endpoints (-1, +1) to the same correct value,
    # but the 50/50 latent mixture to the wrong output.
    return {m:latent**2 for m in ("text","audio","image","video")}

def scorer(raw, targets):
    err = (raw["text"]-targets)**2
    return {"loss":err,"quality":(err<.01).astype(float),
            "ambiguity":np.zeros_like(err),"inconsistency":np.zeros_like(err)}

r = compare_actual_decoded_output(
    public_inputs=public, independent_targets=truth,
    episode_ids=[str(i) for i in range(11)],
    draw_episode_ids=[str(i) for i in range(11)], draws_per_episode=1,
    weights=[.5],generate=decode,external_score=scorer,
    objective_digest="toy-binary-task",frozen_model_digest="toy-nonlinear-frozen",
    input_cohort_digest="toy-11-worlds",criteria=Criterion(max_cvar90=.4,
       max_ambiguity=.5,min_quality=.5,max_inconsistency=.5,
       max_wall_seconds_per_episode=1,max_quality_drop=.2,max_cvar_increase=.4))
out=Path(__file__).with_name('nonlinear_counterexample_receipt.json')
out.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({"status":r["status"],"baseline_cvar90":r["baseline"]["cvar90"],"selected_cvar90":r["selected"]["cvar90"],"selected_quality":r["selected"]["mean_quality"],"authority":r["authority"]},indent=2))
assert r["status"]=="REJECT_OBSERVED_OUTPUT"
