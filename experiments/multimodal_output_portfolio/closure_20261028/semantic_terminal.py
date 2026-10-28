"""Qualified independent semantic observers on physically reopened emissions.

Video and audio classification are empirically qualified separately. The image
measure remains reconstruction and frame consistency, not a calibrated semantic
image classifier. No cached target feature enters a generated-output score.
"""
import copy
import json
from pathlib import Path

import numpy as np
import torch

from .control_episode import MediaFailure
from .data_sources import digest
from .natural_media import SCORE_SPEC, caption, reopen, score
from .natural_model import parameter_hash
from .natural_port import NaturalPort, array_hash
from .semantic_observer import SPEC, load_state, mlp, predict

TERMINAL_SPEC = {
    "schema": "hepta.closure.qualified-natural-terminal.v1",
    "base": SCORE_SPEC,
    "weights": {"joint_reconstruction": .7, "video_action": .1,
                "audio_sound": .1, "joint_caption_action_sound": .1},
    "action": "frozen independent observer top-1 on actual delivered video equals event action annotation",
    "sound": "frozen independent observer top-1 on actual delivered waveform equals event sound annotation",
    "joint_semantics": "action and sound both correct and actual UTF-8 caption exactly equals both official templates",
    "image_scope": "physical RGB reconstruction and consistency with delivered video frame 8 only; no semantic image classifier claim",
    "failure_utility": 0.,
    "observer_gate": "both frozen independent 64-original-video accuracies >=0.6 and each above its own training-majority control",
    "adequacy_scope": "empirical point gate; calibration uncertainty is retained, no universal accuracy guarantee",
    "cost": "all actual feature extraction and observer computation are inside complete self+children CPU charge",
}


class SemanticJudge:
    def __init__(self, *, assets, observer_directory, tsm, pann):
        self.assets, self.directory = Path(assets), Path(observer_directory)
        self.tsm, self.pann = tsm, pann
        self.freeze = json.loads((self.directory / "OBSERVER_FREEZE.json").read_text())
        self.calibration = json.loads((self.directory / "OBSERVER_CALIBRATION.json").read_text())
        protocol = json.loads((self.directory / "PROTOCOL.json").read_text())
        source = json.loads((self.assets / "SOURCE_PROTOCOL.json").read_text())
        expected = {**SPEC, "source_protocol_sha256": source["protocol_sha256"],
                    "implementation_sha256": digest(Path(__file__).with_name("semantic_observer.py").read_bytes()),
                    "backbone_source_sha256": digest(Path(__file__).with_name("semantic_backbones.py").read_bytes())}
        if (protocol != expected or digest(protocol) != self.freeze["protocol_sha256"]
                or self.freeze["source_protocol_sha256"] != source["protocol_sha256"]
                or self.calibration["observer_freeze_sha256"] != digest(self.freeze)
                or self.calibration["source_protocol_sha256"] != source["protocol_sha256"]
                or self.calibration["thresholds_unchanged"] != SPEC["adequacy"]):
            raise ValueError("Independent semantic observer binding changed")
        if set(self.calibration["observers"])!={"action","sound"}:
            raise ValueError("Both independent semantic observers are required")
        if not self.calibration["adequate"] or not all(
                row["sources"] == 64 and row["events"] == 64
                and row["source_uniform_accuracy"] >= .6
                and row["source_uniform_accuracy"] > row["majority_control"]["source_uniform_accuracy"]
                for row in self.calibration["observers"].values()):
            raise ValueError("The independently frozen semantic observers did not qualify")
        self.ontology = copy.deepcopy(source["ontology"])
        self.ontology_sha256 = digest(self.ontology)
        self.states = {}
        self.bindings = {"fixed_task_ontology_sha256": self.ontology_sha256,"observer_freeze_sha256": digest(self.freeze),
                         "observer_calibration_sha256": digest(self.calibration),
                         "source_protocol_sha256": source["protocol_sha256"],
                         "terminal_specification": TERMINAL_SPEC,
                         "checkpoint_sha256": {}}
        for kind in ("action", "sound"):
            selected = self.freeze["selected"][kind]
            path = self.directory / selected["checkpoint_file"]
            pin = digest(path.read_bytes())
            if pin != selected["checkpoint_sha256"]:
                raise ValueError("Frozen semantic classifier bytes changed")
            self.states[kind] = load_state(path)
            self.bindings["checkpoint_sha256"][kind] = pin

    def public_context_scores(self, public):
        # Frozen independently trained maps of public context. These are actor
        # statistics, not a claim that the softmax scores are calibrated posteriors.
        action = public["video_features"].detach().numpy()
        if self.states["action"]["feature_family"] == "action_s3d":
            frames = np.uint8(public["video"].detach().numpy().transpose(0,1,3,4,2)*255+.5)
            action = self.pann.video_features(frames)
        features = {"action": action, "sound": public["audio_features"].detach().numpy()}
        probabilities = {}
        for kind, raw in features.items():
            state = self.states[kind]
            x = np.clip((raw-state["mean"])/state["scale"],-8,8)
            if state["kind"] == "ridge":
                scores = np.c_[x,np.ones(len(x))] @ state["weights"]
            else:
                with torch.no_grad():
                    scores = mlp(state).eval()(torch.tensor(x,dtype=torch.float32)).numpy()
            exponent = np.exp(scores-scores.max(1,keepdims=True))
            probabilities[kind] = exponent/exponent.sum(1,keepdims=True)
        return probabilities

    def evaluate(self, delivered, event):
        frames = np.uint8(np.clip(delivered["video"], 0, 1) * 255 + .5)[None]
        family = self.states["action"]["feature_family"]
        if family == "action_tsm":
            action_features = self.tsm.features(frames)
        elif family == "action_s3d":
            action_features = self.pann.video_features(frames)
        else:
            raise ValueError("Unregistered semantic video feature family")
        sound_features = self.pann.audio_features(delivered["audio"][None])
        action = int(predict(self.states["action"], action_features)[0])
        sound = int(predict(self.states["sound"], sound_features)[0])
        action_ok, sound_ok = action == event["action_id"], sound == event["sound_id"]
        text_ok = delivered["text"] == caption(event["action_id"], event["sound_id"], self.ontology)
        return {"video_action_prediction": action, "audio_sound_prediction": sound,
                "video_action_correct": action_ok, "audio_sound_correct": sound_ok,
                "exact_caption": text_ok, "joint_caption_action_sound": action_ok and sound_ok and text_ok,
                "generated_features_recomputed_from_actual_media": True,
                "static_image_semantic_accuracy_claimed": False}


class QualifiedNaturalPort(NaturalPort):
    def __init__(self, *, judge, **kwargs):
        super().__init__(**kwargs)
        self.judge = judge

    def prepare(self):
        if (self.model.ontology!=self.judge.ontology
                or self.model.action_ids!=sorted(map(int,self.judge.ontology['action']))
                or self.model.sound_ids!=sorted(map(int,self.judge.ontology['sound']))):
            raise ValueError("Generator vocabulary differs from the independently frozen task ontology")
        public = super().prepare()
        if not self.compute_actor_features:
            return public
        self.actor_scores = self.judge.public_context_scores(self.public)
        self.caption_labels = {caption(a,s,self.judge.ontology):(a,s)
                               for a in self.model.action_ids for s in self.model.sound_ids}
        if len(self.caption_labels) != len(self.model.action_ids)*len(self.model.sound_ids):
            raise ValueError("Public caption templates are not uniquely decodable")
        public["frozen_actor_context_scores_sha256"] = array_hash(self.actor_scores)
        public["actor_context_model_sha256"] = self.judge.bindings["checkpoint_sha256"]
        return public

    def emit(self, action, public, output_dir, register_sample, write_file):
        try:
            receipt = super().emit(action, public, output_dir, register_sample, write_file)
            if not self.compute_actor_features:
                return receipt
            # Read actual emitted text, not unsampled logits or model hidden state.
            payload = Path(receipt["artifact_refs"]["text"]).read_bytes()
            if digest(payload) != receipt["artifact_sha256"]["text"]:
                raise ValueError("Caption changed before public actor feature extraction")
            labels = self.caption_labels[payload.decode("utf8")]
            features = list(receipt["public_features"])
            for index, kind in enumerate(("action","sound")):
                values = self.actor_scores[kind][0]
                label_index = list(self.judge.states[kind]["classes"]).index(labels[index])
                features[index] = float(values[label_index])
                features[12+index] = float(-np.sum(values*np.log(np.maximum(values,1e-30)))/np.log(len(values)))
            receipt["public_features"] = features
            return receipt
        except MediaFailure as exc:
            # A declared deterministic baseline can fail physically too. Its
            # failure remains deterministic, with incurred writes/CPU charged.
            if self.route == "stochastic":
                raise
            return {"terminal_kind": "failed", "stochastic": False,
                    "public_feedback": -1, "failure": {"kind": "actual_media_failure", "message": str(exc)[:300]}}

    def terminal_score(self, final):
        if (parameter_hash(self.model)!=self.prepared_binding
                or digest(self.model.ontology)!=self.judge.ontology_sha256
                or digest(self.judge.ontology)!=self.judge.ontology_sha256):
            raise ValueError("Generator parameters or independent task ontology changed before scoring")
        delivered, actual = reopen(final["artifact_refs"])
        if actual != final["artifact_sha256"]:
            raise ValueError("Final physical media changed before semantic scoring")
        with np.load(self.directory / "EVENT.npz") as data:
            reference = {"image": data["target_image"].astype(np.float32) / 255,
                         "video": data["target_video"].astype(np.float32) / 255,
                         "audio": data["target_audio"]}
        event = json.loads((self.directory / "RECEIPT.json").read_text())["events"][0]
        if any(event[key] != self.metadata[key] for key in ("event_id", "source_id", "role")):
            raise ValueError("Private semantic reference belongs to another public source")
        reconstruction = score(delivered, reference, caption(event["action_id"], event["sound_id"], self.judge.ontology))
        semantic = self.judge.evaluate(delivered, event)
        utility = (.7 * reconstruction["utility"] + .1 * semantic["video_action_correct"]
                   + .1 * semantic["audio_sound_correct"] + .1 * semantic["joint_caption_action_sound"])
        return {"utility": float(utility), "joint_reconstruction": reconstruction["utility"],
                "reconstruction": reconstruction, "semantic": semantic,
                "semantic_observer_freeze_sha256": self.judge.bindings["observer_freeze_sha256"]}
