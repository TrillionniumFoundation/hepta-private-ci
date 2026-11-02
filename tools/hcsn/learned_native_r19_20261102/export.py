"""Export all sixteen original analytic fits; no model selection or training."""
import hashlib
import json
from pathlib import Path
import time

import torch

HERE = Path(__file__).resolve().parent
LEARNED = HERE.parents[2] / "experiments/hcsn_learned_core_r19_20261102"


def main():
    started = time.process_time()
    choices = json.loads((LEARNED / "run_01/SELECTION_FREEZE.json").read_text())
    destination = HERE / "profiles_v2"
    destination.mkdir(exist_ok=False)
    fields = dict(Q="Q", PHASE="phase_prior", SYMBOL="symbol.weight", H0W="head.0.weight",
        H0B="head.0.bias", H2W="head.2.weight", H2B="head.2.bias", CHANNEL="channel", DURATIONS="durations")
    records = []
    for name, sha in sorted(choices["checkpoints"].items()):
        if not name.endswith("_analytic"):
            continue
        checkpoint = LEARNED / "run_01" / f"weights_{name}.pt"
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == sha
        state = torch.load(checkpoint, weights_only=True)
        control = name.split("_")[1]
        threshold = choices["selections"][name]["threshold"]
        lines = [f"LEARNED2\t{sha}\t{control}\t{threshold:.9g}"]
        for field, key in fields.items():
            precision = 17 if state[key].dtype == torch.float64 else 9
            lines.append(field + "\t" + "\t".join(format(v, f".{precision}g")
                for v in state[key].flatten().tolist()))
        lines.append("GAMMA\t" + format(float(state["log_scale"].exp()), ".17g"))
        constants = dict(ENCODED=state["symbol.weight"].T.contiguous().softmax(-1),
                         EMISSION=.01 + .96 * state["symbol.weight"].softmax(-1))
        for field, array in constants.items():
            lines.append(field + "\t" + "\t".join(format(v, ".9g") for v in array.flatten().tolist()))
        raw = ("\n".join(lines) + "\n").encode()
        path = destination / f"{name}.model"
        path.write_bytes(raw)
        records.append(dict(name=name, control=control, threshold=threshold,
            checkpoint_sha256=sha, profile_sha256=hashlib.sha256(raw).hexdigest(),
            profile=path.relative_to(HERE).as_posix(), bytes=len(raw)))
    assert len(records) == 16
    manifest = dict(profiles=records, source_selection_sha256=hashlib.sha256(
        (LEARNED / "run_01/SELECTION_FREEZE.json").read_bytes()).hexdigest(),
        no_new_training=True, export_cpu_seconds=time.process_time() - started)
    if (HERE / "PROFILE_MANIFEST.json").exists():
        (HERE / "PROFILE_MANIFEST.json").rename(HERE / "PROFILE_MANIFEST_v1.json")
    (HERE / "PROFILE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(exported_profiles=16, cpu_seconds=manifest["export_cpu_seconds"])))


if __name__ == "__main__":
    main()
