"""Replay the original PR4542 tapes; this is not a new confirmation sample."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..audit import choose_actor
from ..run import verify
from ..upstream.cell import Cell
from ..upstream.data import generate_episode_tapes,EpisodeOwner
from ..upstream.estimators import restore_model
from ..upstream.task_value import ExactBeliefDP


BASE=Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    verify()
    out=BASE/"evidence/historical_replay"
    if (out/"SUMMARY.json").exists():
        raise FileExistsError("Historical replay already recorded")
    protocol=json.loads((BASE/"PROTOCOL.json").read_text())
    source_hash=sha(Path(__file__))
    started=time.process_time();rows=[]
    for seed in protocol["seeds"]:
        fits={k:json.loads((BASE/"upstream/checkpoints"/str(seed)/(k+".json")).read_text())["selected_model"] for k in ("hx_distribution","continuous_diagonal_ssm")}
        fitted=restore_model(fits["hx_distribution"]).build_cell();truth=Cell()
        for domain in protocol["domains"]:
            folder=out/str(seed)/domain
            old=json.loads((folder/"INPUT.json").read_text())
            if old["freeze_hash"]!=sha(BASE/"upstream/CANDIDATE_FREEZE.json"):
                raise ValueError("Historical result refers to a different candidate freeze")
            tapes=generate_episode_tapes(old["episode_seed"],old["episode_count"],3,protocol["domains"][domain])
            record=dict(seed=seed,domain=domain,input_sha256=sha(folder/"INPUT.json"),arms={})
            for arm in "ABCD":
                kind="continuous_diagonal_ssm" if arm in "AB" else "hx_distribution"
                control="fixed_read" if arm in "AC" else "value"
                model=restore_model(fits[kind]);planner=ExactBeliefDP(fitted)
                if planner.model_identity!=old["arms"][arm]["controller_identity"]:
                    raise ValueError("Historical fitted planner identity differs")
                mismatch=[];maximum={key:0. for key in ("utility","reward","cost","elapsed","final_estimated_bit_probability")};utilities=[]
                for index,tape in enumerate(tapes):
                    owner=EpisodeOwner(truth,tape);model.start(fitted.prior);actions=[]
                    while True:
                        action=choose_actor(model,planner,owner.remaining_schedule,owner.remaining_reads,control)
                        actions.append(action)
                        if action.startswith("STOP"):
                            row=owner.finish(int(action[-1]));break
                        observation=owner.advance(action);model.step(observation["input"])
                    row.update(actions=actions,final_estimated_bit_probability=float(model.current[1::2].sum()))
                    previous=old["arms"][arm]["episodes"][index]
                    if any(row[key]!=previous[key] for key in ("actions","counts","state","label","correct","steps")):
                        mismatch.append(dict(episode=index,old=previous,new=row))
                    for key in maximum:
                        maximum[key]=max(maximum[key],abs(row[key]-previous[key]))
                    utilities.append(row["utility"])
                record["arms"][arm]=dict(episodes=len(tapes),action_and_terminal_mismatches=mismatch,
                    maximum_absolute_errors=maximum,mean_utility=float(np.mean(utilities)),
                    mean_utility_error=abs(float(np.mean(utilities))-old["arms"][arm]["mean_utility"]))
            (folder/"REPLAY_RESULT.json").write_text(json.dumps(record,indent=2,sort_keys=True)+"\n")
            rows.append(record)
    result=dict(schema="hcsn.r14.historical-tape-replay.v1",source_sha256=source_hash,
        cases=len(rows),rollouts=sum(a["episodes"] for r in rows for a in r["arms"].values()),
        action_and_terminal_mismatch_count=sum(len(a["action_and_terminal_mismatches"]) for r in rows for a in r["arms"].values()),
        max_numeric_error=max(v for r in rows for a in r["arms"].values() for v in a["maximum_absolute_errors"].values()),
        max_mean_error=max(a["mean_utility_error"] for r in rows for a in r["arms"].values()),
        cpu_seconds=time.process_time()-started,
        original_D_minus_B={d:float(np.mean([r["arms"]["D"]["mean_utility"]-r["arms"]["B"]["mean_utility"] for r in rows if r["domain"]==d])) for d in protocol["domains"]},
        scope="The original old tapes are replayed through the pinned R14 original actors. Zero new fits or independent confirmations. Tests executor/source consistency; does not replace any old or new statistical conclusion.")
    (out/"SUMMARY.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result))
    if result["action_and_terminal_mismatch_count"] or result["max_numeric_error"]>2e-12:
        raise AssertionError("Historical executor mismatch; preserve findings")


if __name__=="__main__":
    main()
