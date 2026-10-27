"""Load pinned original generators/observers without loading any source-role data."""

import json
from pathlib import Path

import torch

from ..v6.neural import parameter_hash
from ..v6.observer import Recognizer
from ..v6.plan_training import ControlledSnapshot
from .training_common import file_hash, require


ORIGINAL_ARCHIVE = "ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e"
PINNED = {
    "ndu-data/t10k-images-idx3-ubyte.gz": "8d422c7b0a1c1c79245a5bcf07fe86e33eeafee792b84584aec276f5a2dbc4e6",
    "ndu-data/t10k-labels-idx1-ubyte.gz": "f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6",
    "ndu-data/train-images-idx3-ubyte.gz": "440fcabf73cc546fa21475e81ea370265605f56be210a4024d2ca8f203523609",
    "ndu-data/train-labels-idx1-ubyte.gz": "3552534a0a558bbed6aed32b30c495cca23d567ec52cac8be1a0730e8010255c",
    "ndu-runs/full-002/audit-observer.pt": "cd560d4ec2f45cef6a0f4db9809b902ea68833c8693798f7597135a83a6e3589",
    "ndu-runs/full-002/reward-observer.pt": "a9cfe78a08b9192ba9d8fe9c144de29ef5d3b1e9cd6ed236d01d170d32034210",
    "ndu-runs/full-002/seed-17-terminal_entropic_ndu.pt": "8fa76a13cdeee48e41b84e29211659a065d9573e2fdfecc4281f882248b508b6",
    "ndu-runs/full-002/seed-29-terminal_entropic_ndu.pt": "e92dc06cec18ee279b8367a2fd194ba91978197150e5edcdede1c0d9fde2b11c",
    "ndu-runs/full-002/seed-43-terminal_entropic_ndu.pt": "1a38524e474d35ff9eb1ad584b1714ea2ef7f7f8d0c502a6b3b2172252ddabf9"}


def load_assets(asset_root, seeds, observer_names):
    root = Path(asset_root)
    receipt = json.loads((root / "RESTORATION.json").read_text())
    require(receipt["archive_sha256"] == ORIGINAL_ARCHIVE, "Original asset archive changed")
    registry = {entry["path"]: entry["sha256"] for entry in receipt["selected_files"]}
    for name, expected in PINNED.items():
        require(registry[name] == expected and file_hash(root / name) == expected, f"Original asset changed: {name}")
    require(set(seeds) <= {17, 29, 43} and set(observer_names) <= {"reward", "audit"}, "Unknown historical model/observer")
    originals, observers, identities = {}, {}, {}
    for seed in seeds:
        name = f"ndu-runs/full-002/seed-{seed}-terminal_entropic_ndu.pt"
        snapshot = ControlledSnapshot.load(root / name, expected_file_sha256=PINNED[name])
        originals[seed] = snapshot._base._model.cpu().eval().requires_grad_(False)
        identities[str(seed)] = {"file_sha256": PINNED[name], "parameter_sha256": parameter_hash(originals[seed]),
                                 "config": originals[seed].config}
    for name in observer_names:
        record = torch.load(root / f"ndu-runs/full-002/{name}-observer.pt", map_location="cpu", weights_only=True)
        observer = Recognizer().eval().requires_grad_(False)
        observer.load_state_dict(record["state_dict"] if "state_dict" in record else record)
        observers[name] = observer
    return originals, observers, {"models": identities, "original_archive_sha256": ORIGINAL_ARCHIVE,
                                  "pinned_files": PINNED, "loaded_observers": list(observer_names)}
