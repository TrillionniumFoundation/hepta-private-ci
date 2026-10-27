"""A post-codec semantic probability is bound to its actual generating policy."""

import json
from pathlib import Path

from .acceptance_calibrate import public_category
from .acceptance_features import observed_semantics
from .acceptance_head import predicted, public_vector
from .adapter import PublicTask
from .binding import BoundCritic, ast_hash
from .protocol import digest, sha
from .selective_metrics import confidence, final_choice


CALIBRATOR_SHA256 = "e55cff31eaad9308642b1df415c11a7f6737f8fcc2f1c5d7032f92e0b48a2122"
BOUND_MODULES = ("acceptance_calibrate.py", "acceptance_features.py", "acceptance_head.py",
    "selective_metrics.py", "selective_protocol.py", "verify_media.py")


class BoundAdmission:
    """Never accepts a private Target, candidate grade, or future feedback."""

    def __init__(self, calibration, development, generator, binary, assets):
        self.calibration = Path(calibration)
        self.continuation = BoundCritic(development, generator, binary)
        self.model_path = self.calibration / "CALIBRATOR.json"
        self.model = json.loads(self.model_path.read_text())
        frozen = json.loads((self.calibration / "FROZEN_CALIBRATOR.json").read_text())
        if sha(self.model_path) != CALIBRATOR_SHA256 or frozen["calibrator_sha256"] != CALIBRATOR_SHA256:
            raise ValueError("Only the pre-qualification frozen calibration002 is deployable")
        self.observer_path = Path(assets) / "ndu-runs/full-002/reward-observer.pt"
        restore = json.loads((Path(assets) / "RESTORATION.json").read_text())
        observer_pin = next(r["sha256"] for r in restore["selected_files"] if r["path"] == "ndu-runs/full-002/reward-observer.pt")
        self.expected = {"calibrator_sha256": CALIBRATOR_SHA256,
            "continuation_runtime_sha256": self.continuation.fingerprint,
            "calibration_protocol_sha256": frozen["protocol_sha256"], "public_observer_sha256": observer_pin,
            "algorithm_ast_sha256": {name: ast_hash((self.calibration / "executed-source" / name).read_text()) for name in BOUND_MODULES}}
        if self.model["generator_checkpoint_sha256"] != self.continuation.expected["generator_checkpoint_sha256"]:
            raise ValueError("A new generator requires new semantic calibration")
        if self.model["native_readout_sha256"] != self.continuation.expected["owner_readout_sha256"]:
            raise ValueError("A new delayed policy requires new semantic calibration")
        self.fingerprint = digest(self.expected)
        self.verify()

    def verify(self):
        actual = {"calibrator_sha256": sha(self.model_path),
            "continuation_runtime_sha256": self.continuation.verify(),
            "calibration_protocol_sha256": sha(self.calibration / "PROTOCOL.json"),
            "public_observer_sha256": sha(self.observer_path),
            "algorithm_ast_sha256": {name: ast_hash(Path(__file__).with_name(name).read_text()) for name in BOUND_MODULES}}
        if actual != self.expected:
            raise ValueError("Admission/runtime identity mismatch: fit and validate again before prediction")
        return self.fingerprint

    def predict(self, initial, candidate, arrived_scalar, public, observer):
        self.verify()
        if not isinstance(public, PublicTask):
            raise TypeError("Only a PublicTask can enter semantic admission")
        features = observed_semantics(initial, candidate, arrived_scalar, public.observation, observer)
        vector = public_vector(candidate, features, observer)
        head = self.model["head_model"]
        raw = float(predicted(head, vector[None])[0])
        selector = self.model["selector"]
        category = public_category(features, raw, selector["head_threshold"], selector["minimum_public_digit_probability"])
        probability = self.model["categories"][category]["probability"]
        commit, moment = final_choice(probability, category)
        return {"public_features": features, "public_vector": vector.tolist(), "raw_head_probability": raw,
            "category": category, "probability": probability, "confidence_ppm": confidence(probability),
            "commit": commit, "predicted_commit_moment": moment,
            "bound_admission_sha256": self.fingerprint, "private_target_received": False,
            "probability_event": self.model["probability_event"]}
