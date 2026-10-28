"""One actual complete episode interface for all new natural study arms."""
from dataclasses import asdict
import json
import hashlib
import io

import torch
from pathlib import Path

from ..continuation_20261027.control.client import sha
from ..unified_20261028.profile import digest
from .control_actor import MomentActor
from .control_episode import execute_episode
from .natural_model import LAW, parameter_hash
from .natural_protocol import STUDY
from .profile_contract import Prices, WorkBudget, continuation_contract, cpu_seconds, make_profile
from .semantic_terminal import QualifiedNaturalPort


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def implementation_paths():
    package = Path(__file__).resolve().parent
    names = ("natural_episode.py", "natural_protocol.py", "natural_gradient.py", "natural_evaluate.py",
             "natural_study.py", "natural_train.py", "natural_model.py", "natural_media.py", "natural_port.py",
             "semantic_terminal.py", "semantic_observer.py", "semantic_tsm.py", "semantic_backbones.py",
             "data_sources.py", "data_v3_contract.py", "data_prepare_v3.py", "data_prepare_v2.py", "data_prepare.py",
             "natural_train_microbatch.py", "natural_proxy_data.py", "control_episode.py", "control_actor.py", "profile_contract.py")
    paths = [package / name for name in names]
    paths += [package.parent / "unified_20261028" / name for name in ("profile.py", "control.py")]
    paths += [package.parent / "continuation_20261027/control/client.py"]
    return paths


def profile_family(*, assets, binary, initial_checkpoint, judge, gamma):
    package = Path(__file__).resolve().parent
    owner = package.parent / "closure_v2_20261027/control/evidence/development-001"
    frozen = json.loads((owner / "FROZEN.json").read_text())
    if sha(binary) != frozen["binary_sha256"]:
        raise ValueError("Natural study requires the unchanged original-owner binary")
    source = json.loads((Path(assets) / "SOURCE_PROTOCOL.json").read_text())
    body = dict(source)
    if body.pop("protocol_sha256") != digest(body):
        raise ValueError("Natural source manifest changed")
    paths = implementation_paths()
    code = {str(path.relative_to(package.parent)): sha(path) for path in paths}
    budget, prices = WorkBudget(), Prices()
    authority = {"binary_sha256": sha(binary), "readout_sha256": sha(owner / "MODEL.json"),
                 "calibration_sha256": sha(owner / "ENCODER_DOMAIN_PROOF.json"),
                 "owner_unchanged": True, "authority": "DENY_ALL"}
    emission = {"law": LAW, "initial_warmstart_checkpoint_sha256": sha(initial_checkpoint),
                "source_protocol_sha256": source["protocol_sha256"],
                "study_registration": STUDY, "current_parameters": "actual prepare binds current parameter SHA; each episode binds its current checkpoint bytes",
                "retry": "fresh joint four-media draw, advanced episode RNG; every executed density counted once",
                "pretrained_context": "recomputed from public context and physically charged on every episode",
                "controls": "declared deterministic interpolation, neural means and frozen stochastic warmstart; no stochastic density claimed for deterministic controls"}
    continuation = continuation_contract(authority=authority, emission=emission,
                                         source_hashes=code, budget=budget, prices=prices)
    continuation["frozen_actor_estimator"] = "positive complete-moment loglink, fixed source-uniform training rule"
    profile, objective = make_profile(observer=judge.bindings, continuation=continuation, gamma=gamma)
    return profile, {"objective": objective, "observer": judge.bindings, "continuation": continuation,
                     "source_hashes": code, "work_budget": budget.to_dict(), "prices": asdict(prices)}, owner


def initial_actor(profile):
    return MomentActor(profile.digest, (0.,) * 19, (1.,) * 19,
                       ((0.,) * 20, (0.,) * 20),
                       digest({"initial_equal_moment_prior": True}), (), 0)


class InterventionActor:
    """Paired complete action sampling with the full reference actor overhead."""
    def __init__(self, reference, action):
        if action not in ("keep", "swap"):
            raise ValueError("Unknown intervention action")
        self.reference, self.action = reference, action
        self.profile_sha256 = reference.profile_sha256

    @property
    def digest(self):
        return digest({"reference_actor_sha256": self.reference.digest, "paired_intervention": self.action,
                       "prediction_is_actually_computed": True, "source_sha256": sha(__file__)})

    def choose(self, context):
        _, report = self.reference.choose(context)
        return self.action, {**report, "policy_sha256": self.digest, "selected_action": self.action,
                             "training_intervention": True, "reference_actor_sha256": self.reference.digest}



class DeferredScore:
    """Replay only after both deployment-equivalent actual episodes have ended."""
    def __init__(self, adapter, receipt, directory):
        self.adapter,self.receipt,self.directory=adapter,receipt,Path(directory)

    def evaluate(self):
        started=cpu_seconds()
        try:
            score,checks=self.adapter.replay_score()
            actual=[row["sampled_sha256"] for row in self.receipt["samples"]]
            replayed=[row["sampled_sha256"] for row in checks["checks"]]
            if actual!=replayed or checks["draws_replayed"]!=len(actual):
                raise ValueError("Likelihood replay does not cover every actual registered sample in order")
            checks["every_registered_sample_replayed_in_order"]=True
        except Exception as exc:
            save(self.directory/"EPISODE_REPLAY_FAILURE.json",{"complete_physical_episode":self.receipt,
                 "error":str(exc),"actual_return_was_not_replaced":True})
            raise
        self.receipt["training_score_replay"]={"performed":True,**checks,
            "cpu_seconds_outside_episode":cpu_seconds()-started,
            "order":"after both actual episodes and before optimizer update",
            "cost_scope":"optimizer computation only; separately reported in total training CPU"}
        return score


class EpisodeRunner:
    def __init__(self, *, assets, binary, judge, tsm, pann, profile, owner):
        self.assets, self.binary, self.owner = map(Path, (assets, binary, owner))
        self.judge, self.tsm, self.pann, self.profile = judge, tsm, pann, profile
        self.paths, self.budget, self.prices = implementation_paths(), WorkBudget(), Prices()

    def complete(self, *, model, checkpoint, event_directory, seed, route, actor,
                 output, case, forced_action=None, intervention=None, training_score=False):
        episode_started_cpu = cpu_seconds()  # Before any per-episode seed/adapter/public setup.
        checkpoint_payload = Path(checkpoint).read_bytes()
        checkpoint_sha = hashlib.sha256(checkpoint_payload).hexdigest()
        checkpoint_state = torch.load(io.BytesIO(checkpoint_payload),map_location="cpu",weights_only=True)
        h = hashlib.sha256()
        for name,tensor in sorted(checkpoint_state["model"].items()):
            h.update(name.encode());h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
        current_parameters = parameter_hash(model)
        if (checkpoint_state["ontology"]!=self.judge.ontology or model.ontology!=self.judge.ontology
                or model.action_ids!=sorted(map(int,self.judge.ontology["action"]))
                or model.sound_ids!=sorted(map(int,self.judge.ontology["sound"]))):
            raise ValueError("Actual generator or checkpoint metadata differs from the independently frozen task vocabulary")
        if (h.hexdigest()!=checkpoint_state["parameter_sha256"] or current_parameters!=h.hexdigest()
                or checkpoint_state["emission_law"]!=LAW):
            raise ValueError("Actual in-memory generator differs from its bound physical checkpoint/law")
        del checkpoint_state,checkpoint_payload
        adapter = QualifiedNaturalPort(model=model, event_directory=event_directory,
                                       tsm=self.tsm, pann=self.pann, judge=self.judge,
                                       seed=seed, route=route, actor_features=forced_action is None)
        actual_actor = InterventionActor(actor, intervention) if intervention is not None else actor
        host_law = (actual_actor.digest if forced_action is None else
                    digest({"profile_sha256":self.profile.digest,"training_intervention":forced_action,
                            "actor_source":sha(Path(__file__).with_name("control_actor.py"))}))
        binding = {"profile_sha256":self.profile.digest,"host_selection_law_sha256":host_law,
                   "generator_checkpoint_sha256":checkpoint_sha,"generator_parameter_sha256":current_parameters,
                   "observer_sha256":self.profile.observer_sha256,"emission_law_sha256":digest(LAW),
                   "runtime_implementation_sha256":digest({str(p):sha(p) for p in self.paths}),
                   "generation_route":route, "task_ontology_sha256":self.judge.ontology_sha256,
                   "action_ids":list(model.action_ids), "sound_ids":list(model.sound_ids)}
        complete_policy_sha = digest(binding)
        with torch.no_grad():
            logp, value, receipt = execute_episode(
                profile=self.profile, actor=actual_actor, prepare=adapter.prepare, emit=adapter.emit,
                terminal_score=adapter.terminal_score, binary=self.binary,
                readout=self.owner / "MODEL.json", calibration=self.owner / "ENCODER_DOMAIN_PROOF.json",
                checkpoint=checkpoint, directory=Path(output) / case, case=case,
                implementation_paths=self.paths, episode_started_cpu=episode_started_cpu,
                budget=self.budget, prices=self.prices, expires=7, media_budget=2,
                forced_action=forced_action)
        receipt.update(generation_route=route, actual_seed=seed,
                       frozen_source_protocol_sha256=self.judge.bindings["source_protocol_sha256"])
        receipt["complete_policy_binding"] = binding
        receipt["complete_policy_sha256"] = complete_policy_sha
        receipt["delivery_forward_autograd"] = False
        receipt["actor_only_features_computed"] = forced_action is None
        receipt["training_score_replay"] = {"performed":False,"cpu_seconds_outside_episode":0.}
        if training_score:
            logp = DeferredScore(adapter, receipt, Path(output)/case)
            receipt["training_score_replay"]["deferred_until_after_actual_pair"] = True
        if intervention is not None:
            receipt["sampling_design"] = "paired_complete_actions"
        return logp, value, receipt
