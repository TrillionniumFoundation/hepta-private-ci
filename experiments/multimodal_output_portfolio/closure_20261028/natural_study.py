"""Frozen staged execution of the new complete-episode natural study.

Each expensive phase is independently archivable. Completed held-out phases are
never used to select a new policy; resource-interrupted phases remain explicit
rather than silently replacing their evidence with a favorable execution.
"""
import argparse
import json
from pathlib import Path
import shutil
import time

import torch

from ..unified_20261028.profile import digest
from .control_actor import MomentActor
from .data_prepare_v2 import validate_freeze
from .data_sources import digest as file_digest
from .natural_episode import EpisodeRunner, implementation_paths, profile_family, save
from .natural_evaluate import evaluate_grid, paired_comparison, selected_policy_calibration
from .natural_gradient import fit_actual_policy, train_arm
from .natural_protocol import STUDY
from .natural_train import generator_rows, load_checkpoint
from .profile_contract import cpu_seconds, support_status
from .semantic_backbones import SemanticBackbones
from .semantic_terminal import SemanticJudge
from .semantic_tsm import TsmObserver


def sha(path):
    return file_digest(Path(path).read_bytes())


class Study:
    def __init__(self, *, assets, observers, warmstart, binary, output):
        self.assets,self.observers,self.warmstart,self.binary,self.output=map(Path,(assets,observers,warmstart,binary,output))
        # Check the empirical gate before allocating models or touching any new
        # generator evaluation source. A failed observer is a scientific block.
        calibration=json.loads((self.observers/"OBSERVER_CALIBRATION.json").read_text())
        if not calibration.get("adequate"):
            raise ValueError("Independent semantic observer adequacy failed; new qualification remains unopened")
        self.source=json.loads((self.assets/"SOURCE_PROTOCOL.json").read_text())
        if self.source["protocol_sha256"]!=STUDY["source_protocol_sha256"] or self.source["roles"]!=STUDY["source_roles"]:
            raise ValueError("Study source roles differ from the approved training-only expansion")
        warm=json.loads((self.warmstart/"WARMSTART_RESULT.json").read_text())
        warm_protocol=json.loads((self.warmstart/"WARMSTART_PROTOCOL.json").read_text())
        expected_sources=sorted(row["source_id"] for row in self.source["selected"] if row["role"]=="generator_train")
        if (warm["optimizer_steps"]!=2048 or warm["training_source_count"]!=256
                or warm["protocol_sha256"]!=digest(warm_protocol)
                or warm["source_protocol_sha256"]!=self.source["protocol_sha256"]
                or warm_protocol["source_protocol_sha256"]!=self.source["protocol_sha256"]
                or sorted(warm_protocol["training_sources"])!=expected_sources):
            raise ValueError("Complete warmstart budget, source identities or protocol binding changed")
        if [item["step"] for item in warm["checkpoints"]]!=[0,256,1024,2048]:
            raise ValueError("All preregistered warmstart snapshots are required")
        for item in warm["checkpoints"]:
            path=self.warmstart/item["file"]
            if sha(path)!=item["sha256"]:raise ValueError("Warmstart snapshot bytes changed")
            model,state=load_checkpoint(path)
            if state["warmstart_protocol_sha256"]!=warm["protocol_sha256"] or state["step"]!=item["step"]:
                raise ValueError("A checkpoint was trained under another warmstart protocol")
            del model,state
        torch.set_num_threads(2)
        torch.use_deterministic_algorithms(True)
        self.pann=SemanticBackbones(self.assets/"pretrained");self.tsm=TsmObserver(self.assets/"pretrained")
        self.judge=SemanticJudge(assets=self.assets,observer_directory=self.observers,tsm=self.tsm,pann=self.pann)
        self.profiles={};self.runners={};self.definitions={}
        for name,gamma in (("risk",2.),("mean",0.)):
            profile,definition,owner=profile_family(assets=self.assets,binary=self.binary,
                initial_checkpoint=self.warmstart/"warmstart-0000.pt",judge=self.judge,gamma=gamma)
            self.profiles[name],self.definitions[name]=profile,definition
            self.runners[name]=EpisodeRunner(assets=self.assets,binary=self.binary,judge=self.judge,
                                             tsm=self.tsm,pann=self.pann,profile=profile,owner=owner)
        self._training=None
        if (self.output/"PROTOCOL.json").exists():
            stored=json.loads((self.output/"PROTOCOL.json").read_text())
            if (stored["study"]!=STUDY or stored["profile_sha256"]!={name:p.digest for name,p in self.profiles.items()}
                    or stored["source_protocol_sha256"]!=self.source["protocol_sha256"]
                    or stored["implementation_sha256"]!={str(p):sha(p) for p in implementation_paths()}):
                raise ValueError("Frozen actual-study objective, sources or implementation changed")

    @property
    def training(self):
        # Post-training evaluation may restore training arrays from their
        # archive, but must not require those arrays to stay resident forever.
        if self._training is None:
            _,self._training=generator_rows(self.assets,"generator_train")
        return self._training

    def initialize(self):
        self.output.mkdir(parents=True,exist_ok=False)
        for role in ("policy_calibration","qualification"):
            if list((self.assets/"prepared"/role).glob("*")):
                raise ValueError("A held-out source was accessed before this complete study initialization")
        root=self.assets.parent
        amendments=[p for p in root.glob("*AMENDMENT.json")]
        protocol={"schema":"hepta.closure.natural-experiment.v1","study":STUDY,
                  "source_protocol_sha256":self.source["protocol_sha256"],
                  "profile_sha256":{name:p.digest for name,p in self.profiles.items()},
                  "implementation_sha256":{str(p):sha(p) for p in implementation_paths()},
                  "preregistration_file_sha256":sha(root/"NATURAL_ACTUAL_REGISTRATION.json"),
                  "pre_execution_amendments":{p.name:sha(p) for p in sorted(amendments)},
                  "warmstart_result_sha256":sha(self.warmstart/"WARMSTART_RESULT.json"),
                  "independent_observer_calibration_sha256":sha(self.observers/"OBSERVER_CALIBRATION.json"),
                  "observer_development_selection_already_performed":True,
                  "generator_development_metrics_before_this_protocol":0,
                  "new_policy_calibration_access":False,"new_qualification_access":False,
                  "cost_limit":"common original-owner17-kernel port; not an engineering-optimal fixed-runtime comparison",
                  "risk_neutral_control":"gamma0 training has an explicit distinct profile; all later portfolio evaluation actually executes gamma2"}
        save(self.output/"PROTOCOL.json",protocol)
        for name,profile in self.profiles.items():
            save(self.output/f"PROFILE_{name.upper()}.json",profile.to_dict())
            save(self.output/f"DEFINITION_{name.upper()}.json",self.definitions[name])
        return {"phase":"initialized","profiles":protocol["profile_sha256"]}

    def warm_select(self):
        _,development=generator_rows(self.assets,"development")
        configurations={f"warm_{step:04d}":{"checkpoint":str(self.warmstart/f"warmstart-{step:04d}.pt"),
                         "route":"deterministic","forced_action":"keep"} for step in (0,256,1024,2048)}
        configurations["initial_interpolation"]={"checkpoint":str(self.warmstart/"warmstart-0000.pt"),
                                                "route":"interpolation","forced_action":"keep"}
        _,summaries=evaluate_grid(runner=self.runners["risk"],configurations=configurations,
            source_rows=development,draws=2,phase="warm_selection",output=self.output/"warm_selection",seed=279110)
        prior=summaries["initial_interpolation"]["source_mean_reconstruction_quality"]
        candidates=[]
        for step in (0,256,1024,2048):
            item=summaries[f"warm_{step:04d}"]
            retained=all(item["source_mean_reconstruction_quality"][k]>=prior[k]-.02 for k in ("image","video","audio"))
            candidates.append({"step":step,"ce":item["population_ce"],"retained":retained})
        eligible=[row for row in candidates if row["retained"]]
        chosen=max(eligible,key=lambda row:row["ce"]) if eligible else candidates[0]
        path=self.warmstart/f"warmstart-{chosen['step']:04d}.pt"
        shutil.copyfile(path,self.output/"COMMON_WARMSTART.pt")
        result={"schema":"hepta.closure.warmstart-selection.v1","profile_sha256":self.profiles["risk"].digest,
                "candidates":candidates,"selected_step":chosen["step"],"checkpoint_sha256":sha(path),
                "selection_role":"original development only; no calibration or qualification selection"}
        save(self.output/"WARMSTART_SELECTION.json",result)
        for kind in ("risk","mean"):
            model,_=load_checkpoint(self.output/"COMMON_WARMSTART.pt");model.eval()
            fit_actual_policy(runner=self.runners[kind],model=model,checkpoint=self.output/"COMMON_WARMSTART.pt",
                source_rows=self.training,output=self.output/f"actor_initial_{kind}",seed=379110)
        return result

    def training_arm(self, arm, resume=False):
        kind,raw_seed=arm.split("_");seed=int(raw_seed)
        if kind not in ("risk","mean") or seed not in STUDY["actual_training"]["seeds"]:
            raise ValueError("Unregistered actual-training arm")
        actor=MomentActor.from_dict(json.loads((self.output/f"actor_initial_{kind}/ACTOR.json").read_text()))
        final,result=train_arm(runner=self.runners[kind],warmstart=self.output/"COMMON_WARMSTART.pt",
            actor=actor,source_rows=self.training,output=self.output/arm,seed=seed,resume=resume)
        checkpoints=self.output/"checkpoints";checkpoints.mkdir(exist_ok=True)
        destination=checkpoints/(arm+".pt");shutil.copyfile(final["path"],destination)
        model,_=load_checkpoint(destination);model.eval()
        reference=MomentActor.from_dict(json.loads((self.output/"actor_initial_risk/ACTOR.json").read_text()))
        _,fit,_=fit_actual_policy(runner=self.runners["risk"],model=model,checkpoint=destination,
            source_rows=self.training,output=self.output/(arm+"_final_actor"),seed=479110,
            reference_actor=reference)
        result={**result,"final_evaluation_actor_fit":fit,
                "trained_under_profile_sha256":self.profiles[kind].digest,
                "evaluated_under_profile_sha256":self.profiles["risk"].digest,
                "migration":"same fixed generator tensors/emission law; final actor refit uses actual gamma2 complete returns, as registered"}
        save(self.output/(arm+"_RESULT.json"),result)
        return result

    def configurations(self):
        common=str(self.output/"COMMON_WARMSTART.pt")
        result={"interpolation":{"checkpoint":common,"route":"interpolation","forced_action":"keep"},
                "frozen_mean":{"checkpoint":common,"route":"deterministic","forced_action":"keep"},
                "frozen_stochastic":{"checkpoint":common,"route":"stochastic","forced_action":"keep"}}
        for seed in STUDY["actual_training"]["seeds"]:
            for kind in ("risk","mean"):
                arm=f"{kind}_{seed}"
                result[arm]={"checkpoint":str(self.output/"checkpoints"/(arm+".pt")),"route":"stochastic",
                             "actor":str(self.output/(arm+"_final_actor")/"ACTOR.json"),
                             "trained_under_profile_sha256":self.profiles[kind].digest}
        for action,name in (("keep","risk_811_fixed_keep"),("swap","risk_811_fixed_retry")):
            result[name]={"checkpoint":str(self.output/"checkpoints/risk_811.pt"),"route":"stochastic",
                          "forced_action":action,"trained_under_profile_sha256":self.profiles["risk"].digest}
        if set(result)!=set(STUDY["qualification"]["arms"]):raise ValueError("Registered arm family changed")
        return result

    def evaluate_development(self):
        _,sources=generator_rows(self.assets,"development")
        _,summary=evaluate_grid(runner=self.runners["risk"],configurations=self.configurations(),source_rows=sources,
            draws=2,phase="development",output=self.output/"development",seed=579110)
        return {"phase":"development","arms":summary,"policy_changes_after_development":False}

    def freeze(self):
        development=json.loads((self.output/"development/SUMMARY.json").read_text())
        configurations=self.configurations()
        paths=set(implementation_paths())|{self.assets/"SOURCE_PROTOCOL.json",self.assets/"FEATURE_PROTOCOL.json",
               self.output/"PROTOCOL.json",self.output/"WARMSTART_SELECTION.json",
               self.output/"PROFILE_RISK.json",self.output/"PROFILE_MEAN.json",
               self.observers/"OBSERVER_FREEZE.json",self.observers/"OBSERVER_CALIBRATION.json"}
        for selected in self.judge.freeze["selected"].values():paths.add(self.observers/selected["checkpoint_file"])
        for config in configurations.values():
            paths.add(Path(config["checkpoint"]))
            if config.get("actor"):paths.add(Path(config["actor"]))
        if development["profile_sha256"]!=self.profiles["risk"].digest:raise ValueError("Development evaluated another objective")
        expected_policies={}
        for arm in configurations:
            cases=sorted((self.output/"development").glob(f"*-{arm}/EPISODE.json"))
            # Exact arm fields, not a suffix collision with fixed keep/retry.
            rows=[json.loads(p.read_text()) for p in cases]
            rows=[row for row in rows if row["arm"]==arm]
            identities={row["complete_policy_sha256"] for row in rows}
            if len(rows)!=128 or len(identities)!=1:raise ValueError("Complete frozen development policy evidence is missing")
            expected_policies[arm]=next(iter(identities))
        result={"schema":"hepta.closure.natural-policy-freeze.v1",
                "source_protocol_sha256":self.source["protocol_sha256"],"profile_sha256":self.profiles["risk"].digest,
                "independent_observer_adequate":True,"observer_gate_scope":"empirical64-source point gate, not future population certification",
                "frozen_files":[{"path":str(p),"sha256":sha(p)} for p in sorted(paths)],
                "configurations":configurations,"complete_policy_sha256":expected_policies,
                "new_policy_calibration_access":False,"new_qualification_access":False,
                "selection_after_holdout":False,"training_seeds_never_pooled_as_environment_draws":True,
                "strict_future_NDU_tail_certificate":False}
        save(self.output/"POLICY_FREEZE.json",result)
        return result

    def heldout(self, role):
        if role=="qualification" and not (self.output/"POLICY_CALIBRATION.json").exists():
            raise ValueError("Report the independent fixed-policy calibration before reading qualification")
        freeze_path=self.output/"POLICY_FREEZE.json"
        validate_freeze(self.source,[role],freeze_path)
        freeze=json.loads(freeze_path.read_text())
        for path in (self.assets/"prepared"/role).glob("*/RECEIPT.json"):
            if json.loads(path.read_text())["heldout_freeze_sha256"]!=sha(freeze_path):
                raise ValueError("Held-out source was opened under another policy freeze")
        _,sources=generator_rows(self.assets,role)
        actual_hashes={event["source_sha256"] for _,event in sources}
        prior_roles=["generator_train","observer_train","development","observer_calibration"]
        if role=="qualification":prior_roles.append("policy_calibration")
        prior_hashes=set()
        for prior_role in prior_roles:
            for receipt_path in (self.assets/"prepared"/prior_role).glob("*/RECEIPT.json"):
                receipt=json.loads(receipt_path.read_text())
                prior_hashes.update(row["source_sha256"] for row in receipt["events"])
        if actual_hashes & prior_hashes:
            raise ValueError("Held-out original source bytes overlap an earlier role")
        configurations=freeze["configurations"]
        if role=="policy_calibration":configurations={"risk_811":configurations["risk_811"]}
        rows,summaries=evaluate_grid(runner=self.runners["risk"],configurations=configurations,
            source_rows=sources,draws=2,phase=role,output=self.output/role,
            seed=679110 if role=="policy_calibration" else 779110)
        for arm,items in rows.items():
            if {row["complete_policy_sha256"] for row in items}!={freeze["complete_policy_sha256"][arm]}:
                raise ValueError("Selected-policy law changed after its complete freeze")
        if role=="policy_calibration":
            result=selected_policy_calibration(rows["risk_811"],self.profiles["risk"])
            save(self.output/"POLICY_CALIBRATION.json",result)
            return result
        primary=rows["risk_811"]
        comparisons={arm:paired_comparison(primary,rows[arm],self.profiles["risk"])
                     for arm in ("interpolation","frozen_mean","frozen_stochastic","mean_811",
                                 "risk_811_fixed_keep","risk_811_fixed_retry")}
        generator_comparators=("interpolation","frozen_mean","frozen_stochastic","mean_811")
        generator_pass=(all(comparisons[arm]["empirical_superiority_lower_above_zero"]
                            and comparisons[arm]["reconstruction_noninferiority_margin_0_01"] for arm in generator_comparators)
                        and summaries["risk_811"]["source_mean_joint_semantic_correctness"]>=.6)
        controller_pass=all(comparisons[arm]["empirical_superiority_lower_above_zero"]
                            for arm in ("risk_811_fixed_keep","risk_811_fixed_retry"))
        result={"schema":"hepta.closure.natural-qualification.v1","source_protocol_sha256":self.source["protocol_sha256"],
                "policy_freeze_file_sha256":sha(freeze_path),"profile_sha256":self.profiles["risk"].digest,
                "actual_original_video_sources":64,"actual_episodes":sum(len(items) for items in rows.values()),
                "arms":summaries,"primary_comparisons":comparisons,
                "passed_registered_primary_generator_gate":generator_pass,
                "passed_registered_dynamic_controller_value_gate":controller_pass,
                "training_seeds_reported_separately":True,"new_policy_selection_from_qualification":False,
                "strict_NDU_tail_certificate":False,"global_optimality_proved":False,
                "scope":"natural same-event bounded reconstruction with qualified empirical video/audio observers; not open-domain generation or calibrated static-image semantics",
                "resource_support":support_status(self.runners["risk"].budget,self.runners["risk"].prices)}
        save(self.output/"QUALIFICATION_RESULT.json",result)
        return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("assets","observers","warmstart","binary","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--phase",choices=("initialize","warm_select","train","development","freeze","policy_calibration","qualification"),required=True)
    parser.add_argument("--arm");parser.add_argument("--resume",action="store_true")
    args=parser.parse_args();started=time.monotonic();cpu=cpu_seconds()
    study=Study(assets=args.assets,observers=args.observers,warmstart=args.warmstart,binary=args.binary,output=args.output)
    if args.phase=="initialize":result=study.initialize()
    elif args.phase=="warm_select":result=study.warm_select()
    elif args.phase=="train":result=study.training_arm(args.arm,args.resume)
    elif args.phase=="development":result=study.evaluate_development()
    elif args.phase=="freeze":result=study.freeze()
    else:result=study.heldout(args.phase)
    save(study.output/f"PHASE_RESOURCE_{args.phase}_{args.arm or 'all'}_{time.time_ns()}.json",
         {"phase":args.phase,"arm":args.arm,"actual_total_process_self_children_CPU_seconds":cpu_seconds(),
          "module_import_CPU_seconds_before_dispatch":cpu,
          "wall_seconds_after_module_imports":time.monotonic()-started,
          "includes_all_import_setup_observer_replay_optimizer_and_reporting_before_final_resource_receipt":True})
    print(json.dumps({"phase":args.phase,"arm":args.arm,"output":str(study.output),"completed":True}),flush=True)
