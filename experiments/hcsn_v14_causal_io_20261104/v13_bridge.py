"""Stateless I/O adapter around the exact historical V13 neural checkpoints.

Only accepted audio/video row55 packets enter the network. Text/image payloads
and stronger audio representations need separately trained, qualified adapters.
The inherited classifier saw at most six steps in training. A sliding six-row
readout with persistent recurrent state permits engineering restart/length
checks; it makes no long-context accuracy or independent-world claim.
"""

import hashlib
import io
import json
import math
from pathlib import Path

from .boundary import BoundaryError, Packet, canonical, integer


ROOT = Path(__file__).resolve().parents[2]
BASE_COMMIT = "3b9a136c56e9e743d7ecba852d621e1ecabf6bba"
ROSTER_SHA256 = "9dbb8423c54e902a509ea85331c3b617eb97971f429c10a684169c251fc57215"
SCHEMA = "hcsn-v14-v13-core-state.v1"
ROW, WINDOW, HIDDEN, CELLS = 55, 6, 32, 8


def verify_candidates(candidate_dir):
    """Return checked in-memory bytes anchored to the published V13 roster.

    This explicit verification does not invoke the original assertion-based
    publication gates. Only the selected candidate is needed locally. Exact
    source bytes, metadata, normalization and weights are all checked before
    deserialization. This is artifact identity, never scientific admission.
    """
    directory = Path(candidate_dir).resolve()
    roster_bytes = (directory.parent / "CANDIDATES.json").read_bytes()
    if hashlib.sha256(roster_bytes).hexdigest() != ROSTER_SHA256:
        raise BoundaryError("Unrecognized frozen V13 candidate roster")
    roster = json.loads(roster_bytes)
    rows = [r for r in roster["models"] if r["directory"] == directory.name]
    if len(rows) != 1:
        raise BoundaryError("Candidate absent or ambiguous in published roster")
    record = rows[0]
    contents = {name: (directory / name).read_bytes()
                for name in ("TRAIN.json", "weights.pt", "NORMALIZATION.npz")}
    metadata = json.loads(contents["TRAIN.json"])
    expected = {"TRAIN.json": record["train_metadata_sha256"],
                "weights.pt": record["weights_sha256"],
                "NORMALIZATION.npz": metadata["normalization_sha256"]}
    if any(hashlib.sha256(contents[name]).hexdigest() != sha
           for name, sha in expected.items()):
        raise BoundaryError("Frozen candidate metadata, weights or normalization changed")
    if (metadata["family"] != record["family"] or metadata["task"] != record["task"]
            or metadata["seed"] != record["seed"]
            or metadata["weights_sha256"] != expected["weights.pt"]):
        raise BoundaryError("Candidate metadata contradicts the published roster")
    if (metadata["plan_sha256"] != roster["plan_sha256"]
            or hashlib.sha256((directory.parent / "PLAN.json").read_bytes()).hexdigest() != roster["plan_sha256"]):
        raise BoundaryError("Original V13 training plan differs from the published roster")
    for relative, expected_sha in metadata["source_sha256"].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
            raise BoundaryError("Frozen V13 source missing or changed: " + relative)
    identity = hashlib.sha256()
    for name, data in sorted(contents.items()):
        identity.update(name.encode() + b"\0" + len(data).to_bytes(8, "big") + data)
    return {"model_id": identity.hexdigest(), "metadata": metadata, "contents": contents}


class V13Core:
    """Pure state transitions: the caller owns atomic persistence and requests."""

    def __init__(self, candidate_dir, *, device="cpu"):
        verified = verify_candidates(candidate_dir)
        import numpy as np
        import torch
        from experiments.hcsn_v13_followup_20261102.joint_core.model import Model
        from experiments.hcsn_v13_followup_20261102.joint_core.data import Normalization

        self.torch = torch
        self.device = torch.device(device)
        self.model_id = verified["model_id"]
        self.bridge_id = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.execution = {"bridge_sha256": self.bridge_id, "torch": torch.__version__,
                          "numpy": np.__version__, "dtype": "float64",
                          "device_type": self.device.type, "device_index": self.device.index,
                          "cpu_threads": torch.get_num_threads(),
                          "interop_threads": torch.get_num_interop_threads(),
                          "deterministic_algorithms": torch.are_deterministic_algorithms_enabled()}
        if self.device.type == "cuda":
            self.execution.update(device_name=torch.cuda.get_device_name(self.device),
                                  device_capability=list(torch.cuda.get_device_capability(self.device)),
                                  cuda_version=torch.version.cuda)
        self.execution_id = hashlib.sha256(canonical(self.execution)).hexdigest()
        self.metadata = verified["metadata"]
        with torch.random.fork_rng(devices=[]):
            model = Model(self.metadata["family"], self.metadata["classes"])
        weights = torch.load(io.BytesIO(verified["contents"]["weights.pt"]),
                             map_location="cpu", weights_only=True)
        model.load_state_dict(weights, strict=True)
        if (sum(p.numel() for p in model.parameters()) != self.metadata["parameter_count"]
                or any(not torch.isfinite(t).all() for t in model.state_dict().values())):
            raise BoundaryError("Invalid frozen model tensors or parameter count")
        with np.load(io.BytesIO(verified["contents"]["NORMALIZATION.npz"]), allow_pickle=False) as arrays:
            norm = Normalization(arrays["center"], arrays["scale"])
        self.center = torch.tensor(norm.center, dtype=torch.float64, device=self.device)
        self.scale = torch.tensor(norm.scale, dtype=torch.float64, device=self.device)
        self.model = model.to(self.device).eval().requires_grad_(False)

    def initial(self):
        return {"schema": SCHEMA, "model_id": self.model_id, "bridge_id": self.bridge_id,
                "execution_id": self.execution_id,
                "steps": 0, "rows": [], "h": [0.0] * HIDDEN,
                "membrane": [-0.25] * CELLS, "cooldown": [0.0] * CELLS}

    def _validate(self, state):
        expected = {"schema", "model_id", "bridge_id", "execution_id", "steps", "rows", "h", "membrane", "cooldown"}
        if (not isinstance(state, dict) or set(state) != expected
                or state["schema"] != SCHEMA or state["model_id"] != self.model_id
                or state["bridge_id"] != self.bridge_id or state["execution_id"] != self.execution_id):
            raise BoundaryError("Restored core identity or schema mismatch")
        steps = integer(state["steps"])
        rows = state["rows"]
        if not isinstance(rows, list) or len(rows) != min(steps, WINDOW):
            raise BoundaryError("Restored visible-history length contradicts step count")
        for value, size in [(state["h"], HIDDEN), (state["membrane"], CELLS),
                            (state["cooldown"], CELLS), *[(r, ROW) for r in rows]]:
            if (not isinstance(value, list) or len(value) != size
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)):
                raise BoundaryError("Restored core tensor shape or finite-value violation")
        if any(x < 0 or x > 0.5 for x in state["cooldown"]):
            raise BoundaryError("Restored refractory clock outside the V13 range")
        if steps == 0 and state != self.initial():
            raise BoundaryError("Empty-history restore must be the exact initial state")
        torch = self.torch
        tensors = tuple(torch.tensor([state[k]], dtype=torch.float64, device=self.device)
                        for k in ("h", "membrane", "cooldown"))
        history = [torch.tensor([r], dtype=torch.float64, device=self.device) for r in rows]
        return tensors, history

    def step(self, state, packet, dt_ns):
        integer(dt_ns)
        if type(packet) is not Packet or packet.status != "ok" or packet.modality not in ("audio", "video"):
            raise BoundaryError("V13 core requires an accepted audio/video packet")
        raw = packet.features
        if (len(raw) != ROW or any(type(x) not in (int, float) or not math.isfinite(x) for x in raw)
                or raw[34] != dt_ns / 1_000_000_000):
            raise BoundaryError("V13 row55/source-delta contract mismatch")
        flags = (1.0, 0.0) if packet.modality == "audio" else (0.0, 1.0)
        if tuple(raw[51:53]) != flags:
            raise BoundaryError("V13 row modality flags contradict the accepted packet")
        tensors, _ = self._validate(state)
        steps = integer(state["steps"] + 1)
        torch = self.torch
        row = torch.tensor([raw], dtype=torch.float64, device=self.device)
        row = (row - self.center) / self.scale
        with torch.inference_mode():
            updated, _ = self.model.step(row, tensors)
        result = {"schema": SCHEMA, "model_id": self.model_id, "bridge_id": self.bridge_id,
                  "execution_id": self.execution_id,
                  "steps": steps, "rows": (state["rows"] + [row[0].cpu().tolist()])[-WINDOW:]}
        for key, value in zip(("h", "membrane", "cooldown"), updated, strict=True):
            result[key] = value[0].cpu().tolist()
        self._validate(result)
        # Roundtrip provides independent lists: no caller-held state can alias a
        # newly returned result or mutate the immutable transition retrospectively.
        return json.loads(canonical(result))

    def output(self, state):
        tensors, history = self._validate(state)
        if not history:
            return {"probabilities": None}
        with self.torch.inference_mode():
            logits = self.model.classify(history, tensors)
            probabilities = self.torch.softmax(logits, dim=-1)[0].cpu().tolist()
        if (len(probabilities) != self.metadata["classes"]
                or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities)
                or not math.isclose(sum(probabilities), 1.0, abs_tol=1e-12)):
            raise BoundaryError("V13 content output is not a finite probability distribution")
        return {"probabilities": probabilities}
