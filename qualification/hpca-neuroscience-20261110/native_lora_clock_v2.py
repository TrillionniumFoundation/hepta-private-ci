#!/usr/bin/env python3
"""Real CPU SmolLM2-135M/LoRA exploratory clock contrast, NOT an owner/effect gate.

Uses matched group-level source exposures from a pre-locked V2 plan; public fixture, no independent evaluator,
no authorized owner, no production task, no 2x2 NDU, no deployment.
"""
import argparse
from dataclasses import asdict
import datetime
import gc
import hashlib
import json
import os
from pathlib import Path
import random
import re
import resource
import statistics
import sys
import time

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def io_counts():
    try:
        rows = Path("/proc/self/io").read_text().splitlines()
        return {a.strip():int(b.strip()) for line in rows if ":" in line
                for a,b in [line.split(":",1)]}
    except (OSError, ValueError):
        return {}

def delta(before, after):
    return {key: after[key]-before.get(key,0) for key in after}

C_TASKS = (
    ("Is zero an even integer?", "yes"),
    ("Is liquid water a chemical element?", "no"),
    ("Does a hexagon have exactly six sides?", "yes"),
    ("Does the Earth have two natural moons?", "no"),
    ("Is 7 a prime number?", "yes"),
    ("Is a square a type of triangle?", "no"),
    ("Does iron have the chemical symbol Fe?", "yes"),
    ("Is a blue whale a kind of fish?", "no"),
)
def prompt(text):
    return text.strip() + "\nAnswer:"

def load_fixture(path):
    data = json.loads(Path(path).read_text())
    rows = data["tasks"]
    known = {}
    for row in rows:
        assert row["partition"] in ("training","calibration","evaluation")
        assert row["expected_output"] in ("yes","no")
        assert hashlib.sha256(row["prompt"].encode()).hexdigest() == row["prompt_sha256"]
        assert row["id"] not in known
        known[row["id"]] = row
    # Public partitions are disjoint as strings, not independent future custody.
    split = {x: [r for r in rows if r["partition"]==x] for x in
             ("training","calibration","evaluation")}
    assert all(split.values())
    assert len({r["id"] for rows in split.values() for r in rows}) == len(rows)
    for q, _ in C_TASKS:
        assert q not in {r["prompt"] for r in rows}
    return split

def clock_schedule(arm, steps):
    assert steps % 4 == 0
    if arm == "uniform":
        return (0,1) * (steps//2)
    if arm == "heterogeneous":
        return (0,0,0,1) * (steps//4)
    raise ValueError(arm)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seeds", default="11,17,23,29")
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--threads", type=int, default=4)
    args=parser.parse_args()
    assert args.steps == 12, "V2 requires exact 12-step paired opportunity plan"
    assert 1<=args.threads<=16
    seeds=[int(s) for s in args.seeds.split(",")]
    assert len(set(seeds)) == len(seeds) and len(seeds)>=2
    # CPU-only: ensure process does not quietly inherit GPU opportunities.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    import torch.nn.functional as F
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model, PeftModel
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    assert not torch.cuda.is_available()
    model_dir=Path(args.model)
    for path in ("config.json","model.safetensors","tokenizer.json"):
        assert (model_dir/path).is_file()
    split=load_fixture(args.fixture)
    out=Path(args.out);out.mkdir(parents=True, exist_ok=False)
    identities={"script_sha256": digest(__file__), "model_safetensors_sha256": digest(model_dir/"model.safetensors"),
                "config_sha256":digest(model_dir/"config.json"),
                "tokenizer_sha256":digest(model_dir/"tokenizer.json"),
                "exposed_fixture_sha256":digest(args.fixture)}
    tok=AutoTokenizer.from_pretrained(model_dir,local_files_only=True)
    yes_ids=tok.encode(" yes",add_special_tokens=False)
    no_ids=tok.encode(" no",add_special_tokens=False)
    assert len(yes_ids)==len(no_ids)==1 and yes_ids[0]!=no_ids[0]
    class_ids=torch.tensor([yes_ids[0],no_ids[0]],dtype=torch.long)
    def encode(row):
        return tok.encode(prompt(row["prompt"]),add_special_tokens=True)
    train=sorted(split["training"],key=lambda r:r["id"])
    calibration=sorted(split["calibration"],key=lambda r:r["id"])
    b_eval=sorted(split["evaluation"],key=lambda r:r["id"])
    c_eval=[{"id":"OOD-C"+str(i),"prompt":"Answer yes or no. "+q,"expected_output":a}
            for i,(q,a) in enumerate(C_TASKS)]
    def make_base():
        return AutoModelForCausalLM.from_pretrained(model_dir,local_files_only=True,
                    dtype=torch.float32,attn_implementation="eager")
    def predict(model, rows):
        model.eval();outrows=[]; started=time.perf_counter()
        with torch.inference_mode():
            for r in rows:
                ids=torch.tensor([encode(r)],dtype=torch.long)
                logits=model(input_ids=ids,use_cache=False).logits[0,-1,class_ids]
                prob_yes=F.softmax(logits.float(),dim=0)[0].item()
                pred="yes" if prob_yes>=0.5 else "no"
                outrows.append({"id":r["id"],"truth":r["expected_output"],
                                "prediction":pred,"p_yes":round(prob_yes,9),
                                "correct":pred==r["expected_output"],
                                "prompt_sha256":hashlib.sha256(r["prompt"].encode()).hexdigest()})
        return {"accuracy":sum(r["correct"] for r in outrows)/len(outrows),
                "rows":outrows,"wall_seconds":time.perf_counter()-started}
    from clock_pairing_v2 import TrainingEvent, make_cohort, verify_pair
    train_events=tuple(TrainingEvent(r["id"], hashlib.sha256(
        json.dumps(r,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
        len(encode(r))) for r in train)
    train_by_id={r["id"]:r for r in train}
    salt="hpca-20261111-v2-plan-locked-before-actual-evaluation"
    cohort=make_cohort(tuple(seeds),train_events,
        model_digest=identities["model_safetensors_sha256"],
        source_tree_digest=hashlib.sha256(b"ba243385e821f5722612ffb7129d479c49d34c17").hexdigest(),
        randomization_salt=salt)
    for p in cohort: verify_pair(p)
    (out/"FROZEN_PLANS.json").write_text(json.dumps(
        {"parent_git_head":"ba243385e821f5722612ffb7129d479c49d34c17",
         "source_script_sha256":identities["script_sha256"],
         "clock_module_sha256":digest(Path(__file__).with_name("clock_pairing_v2.py")),
         "salt":salt,"cohort":[asdict(p) for p in cohort]},
        indent=2,sort_keys=True,allow_nan=False)+"\n")
    start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows=[];seed_summaries=[]
    baseline=make_base()
    parent={k:predict(baseline, rr) for k,rr in
            (("calibration",calibration),("B_exposed_eval",b_eval),("C_operator_constructed",c_eval))}
    del baseline;gc.collect()
    for seed in seeds:
        pair_plan=next(p for p in cohort if p.seed==seed)
        losses={}
        for arm in pair_plan.arm_order:
            tick=time.perf_counter(); cpu=time.process_time(); io_before=io_counts()
            torch.manual_seed(seed)
            model=get_peft_model(make_base(),LoraConfig(r=4,lora_alpha=8,
                      lora_dropout=0.0,bias="none",target_modules=["q_proj"]))
            grouped={0:[],1:[]}
            for name,par in model.named_parameters():
                if "lora_" not in name:
                    assert not par.requires_grad
                    continue
                match=re.search(r"\.layers\.(\d+)\.",name)
                assert match, name
                layer=int(match.group(1))
                assert 0<=layer<30
                grouped[0 if layer<15 else 1].append((name,par))
            pcounts={k:sum(p.numel() for _,p in v) for k,v in grouped.items()}
            assert pcounts[0]==pcounts[1]>0
            assert len(grouped[0])==len(grouped[1])==30
            planned_steps=getattr(pair_plan,arm)
            schedule=tuple(s.group for s in planned_steps)
            optimizer=torch.optim.AdamW([p for members in grouped.values()
                                         for _,p in members],lr=0.001,weight_decay=0)
            seen=[];step_logs=[]
            for i,group in enumerate(schedule):
                for g, members in grouped.items():
                    for _, par in members:
                        par.requires_grad_(g==group)
                model.train()
                optimizer.zero_grad(set_to_none=True)
                row=train_by_id[planned_steps[i].event_id]
                assert hashlib.sha256(json.dumps(row,sort_keys=True,
                    separators=(",",":")).encode()).hexdigest()==planned_steps[i].source_sha256
                ids=torch.tensor([encode(row)],dtype=torch.long)
                assert int(ids.numel())==planned_steps[i].input_tokens
                logits=model(input_ids=ids,use_cache=False).logits[0,-1,class_ids]
                truth=torch.tensor([0 if row["expected_output"]=="yes" else 1])
                loss=F.cross_entropy(logits.unsqueeze(0),truth)
                assert bool(torch.isfinite(loss))
                loss.backward()
                optimizer.step()
                seen.append(row["id"])
                step_logs.append({"i":i,"group":group,"source_id":row["id"],
                                  "source_sha256":planned_steps[i].source_sha256,
                                  "input_tokens":int(ids.numel()),
                                  "loss":round(float(loss.detach()),9)})
            for _,p in model.named_parameters():
                p.requires_grad_(False)
            measured={k:predict(model, rr) for k,rr in
                      (("calibration",calibration),("B_exposed_eval",b_eval),
                       ("C_operator_constructed",c_eval))}
            checkpoint=out/("seed"+str(seed)+"-"+arm+"-adapter")
            model.save_pretrained(checkpoint,safe_serialization=True)
            files={p.name:{"sha256":digest(p),"bytes":p.stat().st_size}
                   for p in sorted(checkpoint.iterdir()) if p.is_file()}
            del model,optimizer
            gc.collect()
            cold_start=time.perf_counter()
            reloaded=PeftModel.from_pretrained(make_base(),checkpoint,is_trainable=False)
            after_cold={k:predict(reloaded, rr) for k,rr in
                        (("B_exposed_eval",b_eval),("C_operator_constructed",c_eval))}
            cold_time=time.perf_counter()-cold_start
            max_difference=max(abs(x["p_yes"]-y["p_yes"]) for k in after_cold
                               for x,y in zip(after_cold[k]["rows"],measured[k]["rows"]))
            assert max_difference<=1e-5, max_difference
            del reloaded;gc.collect()
            item={"seed":seed,"arm":arm,"steps":args.steps,"schedule":list(schedule),
                  "plan_digest":pair_plan.plan_digest,
                  "arm_order":list(pair_plan.arm_order),
                  "all_source_events":seen,"step_log":step_logs,
                  "adapter_parameters_total":sum(pcounts.values()),
                  "equal_group_parameters":pcounts,
                  "actual_updated_parameter_elements":args.steps*pcounts[0],
                  "input_tokens_train":sum(r["input_tokens"] for r in step_logs),
                  "train_evaluate_save_reload_wall_seconds":time.perf_counter()-tick,
                  "process_cpu_seconds":time.process_time()-cpu,
                  "io_delta":delta(io_before,io_counts()),
                  "ru_maxrss_kib_process_peak":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "cold_reload_plus_B_C_wall_seconds":cold_time,
                  "cold_reload_max_p_yes_difference":max_difference,
                  "checkpoint_files":files,"scores":measured,
                  "cold_reloaded_scores":after_cold}
            rows.append(item)
            print("COMPLETE",seed,arm,"B",measured["B_exposed_eval"]["accuracy"],
                  "C",measured["C_operator_constructed"]["accuracy"],
                  "seconds",round(item["train_evaluate_save_reload_wall_seconds"],3),flush=True)
        pair={arm:next(r for r in rows if r["seed"]==seed and r["arm"]==arm)
              for arm in ("interleaved","bursty")}
        assert pair["interleaved"]["actual_updated_parameter_elements"]==pair["bursty"]["actual_updated_parameter_elements"]
        for g in (0,1):
            def projection(a):
                return tuple((s["source_id"],s["source_sha256"],s["input_tokens"])
                             for s in pair[a]["step_log"] if s["group"]==g)
            assert projection("interleaved")==projection("bursty")
            assert len(projection("bursty"))==6
        seed_summaries.append({"seed":seed,"arm_order":list(pair_plan.arm_order),
          "bursty_minus_interleaved_B_accuracy":pair["bursty"]["scores"]["B_exposed_eval"]["accuracy"]-pair["interleaved"]["scores"]["B_exposed_eval"]["accuracy"],
          "bursty_minus_interleaved_C_accuracy":pair["bursty"]["scores"]["C_operator_constructed"]["accuracy"]-pair["interleaved"]["scores"]["C_operator_constructed"]["accuracy"]})
    report={"schema":"HPCA-REAL-CPU-LORA-CLOCK-V2-MATCHED","authority":"CANDIDATE_ONLY_DENY_ALL_HOLD_NO_GO",
       "started_utc":start_utc,"ended_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
       "model":"SmolLM2-135M-Instruct CPU float32 frozen backbone + trainable q_proj LoRA rank 4",
       "sources":"PRE-EXPOSED operator-controlled fixture; B is NOT independent; C is operator-written, NOT future independent",
       "torch":torch.__version__,"transformers":__import__("transformers").__version__,
       "peft":__import__("peft").__version__, "cpu_threads":args.threads,
       "steps_per_arm":args.steps,"seeds":seeds,"identities":identities,
       "question_c_manifest_sha256":hashlib.sha256(json.dumps(C_TASKS,sort_keys=True).encode()).hexdigest(),
       "training_source_ids":sorted(r["id"] for r in train),
       "B_source_ids":sorted(r["id"] for r in b_eval),
       "parent_scores":parent,"runs":rows,
       "paired_seed_deltas":seed_summaries,
       "B_descriptive_mean_delta":statistics.fmean(x["bursty_minus_interleaved_B_accuracy"] for x in seed_summaries),
       "C_descriptive_mean_delta":statistics.fmean(x["bursty_minus_interleaved_C_accuracy"] for x in seed_summaries),
       "not_measured":["actual authority source/action/feedback signatures","external independent B","real production C effect","seven lineage controllers",
           "sparse/dense delayed ACT feedback","2x2 NDU","energy","host-cold owner recovery","network/storage acquisition and failure cost"],
       "paired_clock_plan_digest_per_seed":{str(p.seed):p.plan_digest for p in cohort},
       "clock_module_sha256":digest(Path(__file__).with_name("clock_pairing_v2.py")),
       "clock_plan_sha256":digest(out/"FROZEN_PLANS.json"),
       "comparison":"group-opportunity/exposure-matched interleaved-vs-bursty; exposed evaluation only",
       "selection":"NO_UPDATE_RECOMMENDED_NOT_OWNER_DECISION",
       "decision":"HOLD_NO_GO"}
    (out/"RESULT.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("RESULT",str(out/"RESULT.json"),"B_DELTA",report["B_descriptive_mean_delta"],
          "C_DELTA",report["C_descriptive_mean_delta"],"HOLD_NO_GO",flush=True)

if __name__=="__main__":
    main()

