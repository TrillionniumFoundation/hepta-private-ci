"""Exact historical V6 custody and explicitly old validation materialization."""

from dataclasses import replace
import ast
import hashlib
import json
from pathlib import Path

import torch

from ...v6.data import Observation, SourceCorpus, SourceSplit, make_batch
from ...v6.forecast import ForecastArtifact
from ...v6.neural import parameter_hash
from ...v6.observer import Recognizer
from ...v6.plan_training import ControlledSnapshot
from ...v7.sources import _read_cache, read_manifest


HERE = Path(__file__).resolve().parent
AREA = HERE.parents[1]
EXPECTED = {
    "seed-17-terminal_entropic_ndu.pt": "8fa76a13cdeee48e41b84e29211659a065d9573e2fdfecc4281f882248b508b6",
    "seed-17-terminal_entropic_ndu-forecast.pt": "6c058399c0f66a21af873a80a554fd78b1017db97bd74344705fb5bd3cab1cae",
    "reward-observer.pt": "a9cfe78a08b9192ba9d8fe9c144de29ef5d3b1e9cd6ed236d01d170d32034210",
    "audit-observer.pt": "cd560d4ec2f45cef6a0f4db9809b902ea68833c8693798f7597135a83a6e3589",
    "training.json": "ae3016eee4e08574a1524c7d05c0c44b6f89222a3df28a48973a34352be1fffa",
    "forecast.json": "5f6690d0843fc6882c1be8272af608fd4e37c3bcddb6e157af8e383338dccf89",
    "observer.json": "3c5062afeff0f9cbaff333c48f7899ae486e5eca67f60103bad68e1b12897f7d",
    "protocol.json": "b45d60a3dcd4de13493c20be5b8649692163ebe0674b58d8957c3919097e7de5",
}
MANIFEST_SHA = "60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058"
ARCHIVE_SHA = "ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e"
VIEWS = ("clean", "occlusion", "missing", "heavy_noise", "wrong_hint", "missing_no_hint")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def source_pins():
    paths = list(HERE.glob("*.py")) + list((AREA / "v6").glob("*.py"))
    paths += [HERE.parent / "sources.py", HERE.parent / "supplement_sources.py", AREA / "v7/sources.py"]
    return {str(p.resolve()): sha(p) for p in sorted(paths)}


def load_original(directory):
    directory = Path(directory)
    for name, expected in EXPECTED.items():
        if sha(directory / name) != expected:
            raise ValueError("Historical V6 file mismatch: " + name)
    protocol = json.loads((directory / "protocol.json").read_text())
    for name in ("data", "neural", "conditioned", "plan_training", "observer", "forecast", "distribution", "control"):
        relative = f"experiments/multimodal_output_portfolio/v6/{name}.py"
        if sha(AREA / "v6" / (name + ".py")) != protocol["source"]["files"][relative]:
            raise ValueError("Historical runtime implementation changed: " + name)
    # Later run.py only extended custody collection. Its invoked rollout body
    # must remain exactly the original source, independently of that extension.
    historical = directory / "historical-run.py"
    if sha(historical) != protocol["source"]["files"]["experiments/multimodal_output_portfolio/v6/run.py"]:
        raise ValueError("Historical runner source changed")
    bodies = []
    for path in (historical, AREA / "v6/run.py"):
        source = path.read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "rollout")
        bodies.append(ast.get_source_segment(source, node))
    if bodies[0] != bodies[1]:
        raise ValueError("Historical rollout function changed")
    label = "seed-17-terminal_entropic_ndu"
    snapshot = ControlledSnapshot.load(directory / (label + ".pt"), expected_file_sha256=EXPECTED[label + ".pt"])
    forecast = ForecastArtifact.load(directory / (label + "-forecast.pt"), expected_file_sha256=EXPECTED[label + "-forecast.pt"])
    training = json.loads((directory / "training.json").read_text())[label]
    if (snapshot.fingerprint != training["snapshot_sha256"]
            or snapshot._base.fingerprint != training["pretraining"]["final_snapshot_sha256"]
            or parameter_hash(snapshot._base._model) != training["pretraining"]["final_parameter_sha256"]
            or snapshot._gate_hash != training["content_plan"]["final_gate_sha256"]
            or forecast.snapshot_digest != snapshot.fingerprint):
        raise ValueError("Historical base, gate, or forecast semantic identity changed")
    observers = {}
    for name in ("reward", "audit"):
        model = Recognizer()
        model.load_state_dict(torch.load(directory / (name + "-observer.pt"), weights_only=True), strict=True)
        observers[name] = model.eval().requires_grad_(False)
    identity = {
        "archive_sha256": ARCHIVE_SHA, "file_sha256": EXPECTED,
        "snapshot_sha256": snapshot.fingerprint, "base_snapshot_sha256": snapshot._base.fingerprint,
        "base_parameters_sha256": parameter_hash(snapshot._base._model), "gate_parameters_sha256": snapshot._gate_hash,
        "forecast_sha256": forecast.fingerprint, "historical_fixed_sequence": list(forecast.static_sequence),
        "observer_parameters_sha256": {k: parameter_hash(v) for k, v in observers.items()},
        "training_reexecuted": False, "training_seeds": [17],
        "historical_rollout_source_exact": True,
        "rollout_source_sha256": hashlib.sha256(bodies[0].encode()).hexdigest(),
    }
    return snapshot, forecast, observers, identity


def old_validation(cache, manifest_path, original):
    if sha(manifest_path) != MANIFEST_SHA:
        raise ValueError("Original source registration changed")
    manifest = read_manifest(manifest_path)
    protocol = json.loads((Path(original) / "protocol.json").read_text())
    old = protocol["dataset_manifest"]["splits"]
    start, count = old["train"]["count"], old["validation"]["count"]
    ids = tuple(manifest["roles"]["excluded_v6_train"]["source_ids"][start:start + count])
    if hashlib.sha256("\n".join(ids).encode()).hexdigest() != old["validation"]["identity_sha256"]:
        raise ValueError("Historical validation identities changed")
    pixels, labels, hashes = _read_cache(cache)["train"]
    indices = [int(v.split(":")[2]) for v in ids]
    if any(v != f"mnist:train:{i}:{hashes[i]}" for v, i in zip(ids, indices)):
        raise ValueError("Original validation pixels changed")
    images = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(-1, 1, 28, 28)
    source = SourceSplit(images[indices].clone(), torch.tensor(list(labels), dtype=torch.long)[indices].clone(), ids,
                         tuple(hashes[i] for i in indices))
    return SourceCorpus({"validation": source}, protocol["dataset_manifest"])


def case_batch(corpus, role, case, offset, observation_seed):
    view = VIEWS[case % len(VIEWS)]
    actual = "missing" if view in ("wrong_hint", "missing_no_hint") else view
    batch = make_batch(corpus, role, 1, observation_seed + case, actual,
                       offset=offset + case, drop_hint=view == "missing_no_hint")
    if view == "wrong_hint":
        tokens = batch.observation.text_tokens.clone()
        for pos in (3, 5):
            if int(tokens[0, pos]) >= 14:
                tokens[0, pos] = 14 + (int(tokens[0, pos]) - 14 + 1) % 10
        batch = replace(batch, observation=Observation(batch.observation.pixels, batch.observation.mask, tokens))
    return batch, view
