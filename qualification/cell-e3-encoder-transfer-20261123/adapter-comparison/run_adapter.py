import argparse
import importlib.util
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import torch
from encoder import Encoder, file_sha
from lowrank import Student


def teacher_train(work, source):
    from panel import old as old_rows, partition
    data = partition("fit", 1381) + old_rows("old-train")
    spec = importlib.util.spec_from_file_location("previous_panel", source / "panel.py")
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    pre = [r for r in original.panel() if r["split"] == "train"]
    train = [r for r in data if r["split"] == "train"]
    old = [r for r in data if r["split"] == "old-train"]
    ys = {}
    archived = source/"evidence/completion-run.zip"
    assert file_sha(archived) == "4e9dc2f83b79db9a1076f107d1c610c9b4ad4e61d24d0ed1aaaa53dea870b508"
    with zipfile.ZipFile(archived) as z:
        for n in ("t5","smol"):
            past = {r["id"]:r for r in json.loads(z.read(f"teacher-fit-{n}.json"))["rows"]}
            cur = {r["id"]:r for r in json.loads((work/f"teacher-fit-{n}.json").read_bytes())["rows"]}
            scores = [past[r["id"]] for r in pre] + [cur[r["id"]] for r in train]
            ys[n] = np.tanh([s["mean_logprobs"][1]-s["mean_logprobs"][0] for s in scores])
    ys["mix"] = (ys["t5"] + ys["smol"]) / 2
    ys["shuffled"] = np.random.default_rng(245).permutation(ys["mix"])
    ys["gold"] = np.array([2*r["label"]-1 for r in pre + train])
    old_y = [2*r["label"]-1 for r in old]
    return pre+train+old, {n:np.concatenate([v, old_y]) for n,v in ys.items()}


def parent_scores(encoder, rows, work):
    x, g, margin = encoder.features(rows)
    with np.load(work / "heads.npz", allow_pickle=False) as weights:
        base = margin + x @ weights["parent"]
        gate = g @ weights["gate"]
    return base,gate


def fit(work, enc, source):
    rows, targets = teacher_train(work,source)
    e = Encoder(enc)
    frozen = json.loads((work/"freeze.json").read_bytes())
    assert e.info == frozen["encoder"]
    assert file_sha(work/"heads.npz") == frozen["heads_sha256"]
    base,_ = parent_scores(e,rows,work)
    summary = {}
    for name,y in targets.items():
        torch.manual_seed(2501)
        learner = Student(e)
        rng = np.random.default_rng(257)
        clock,cpu = time.perf_counter(),time.process_time()
        optimizer = torch.optim.AdamW(learner.trainable.values(),lr=0.003)
        updates,tokens = 0,0
        for _ in range(2):
            order = rng.permutation(len(rows))
            for start in range(0,len(rows),16):
                ix = order[start:start+16]
                pred, count = learner.margins([rows[i] for i in ix])
                bias = torch.from_numpy(base[ix].astype(np.float32))
                target = torch.from_numpy(y[ix].astype(np.float32))
                loss = ((pred + bias - target)**2).mean()
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(learner.trainable.values(),1.0)
                optimizer.step()
                updates += 1
                tokens += count
        output = work/("lora-"+name+".npz")
        learner.save(output)
        assert np.count_nonzero(learner.trainable["query_up"].detach().numpy()) and np.count_nonzero(learner.trainable["value_up"].detach().numpy())
        summary[name] = dict(sha256=file_sha(output), updates=updates, input_tokens=tokens,
                            parameters=sum(p.numel() for p in learner.trainable.values()),
                            count=len(rows), wall_seconds=time.perf_counter()-clock,
                            cpu_seconds=time.process_time()-cpu)
        learner.detach()
    identity = dict(heads=summary, primary_freeze=file_sha(work/"freeze.json"),
                    shared_encoder=e.info, confirmation_seed=file_sha(work/"confirmation-seed.json"))
    (work/"adapter-freeze.json").write_text(json.dumps(identity,sort_keys=True))
    print("E3_ADAPTER_FROZEN",file_sha(work/"adapter-freeze.json"), summary)


def cold(work, enc, arm):
    tic,cpu=time.perf_counter(),time.process_time()
    nets=sorted(f.name for f in Path("/sys/class/net").iterdir())
    assert nets == ["lo"]
    def traffic():
        return sum(int((Path("/sys/class/net/lo/statistics")/p).read_text()) for p in ("tx_bytes","rx_bytes"))
    assert traffic()==0
    e=Encoder(enc)
    freeze=json.loads((work/"adapter-freeze.json").read_bytes())
    assert e.info == freeze["shared_encoder"]
    assert file_sha(work/"freeze.json") == freeze["primary_freeze"]
    primary=json.loads((work/"freeze.json").read_bytes())
    assert file_sha(work/"heads.npz") == primary["heads_sha256"] and file_sha(work/"policy.json") == primary["policy_sha256"]
    rows=json.loads((work/"blind.json").read_bytes())
    assert all(set(r)=={"id","query","domain","candidates"} for r in rows)
    policy=json.loads((work/"policy.json").read_bytes())
    base,gate=parent_scores(e,rows,work)
    if arm=="sparse":
        choices=np.where(gate>0,"smol","t5")
    elif arm=="fixed":
        choices=np.array([policy["fixed"].get(r["domain"],policy["best"]) for r in rows])
    else:
        name={"best_single":policy["best"],"without_t5":"smol","without_smol":"t5"}.get(arm,arm)
        choices=np.array([name]*len(rows))
    logits=base.copy()
    extra_inputs=extra_tokens=0
    with torch.inference_mode():
        for name in np.unique(choices):
            if name=="parent":
                continue
            f=work/("lora-"+str(name)+".npz")
            assert file_sha(f)==freeze["heads"][str(name)]["sha256"]
            decoder=Student(e)
            decoder.restore(f)
            ix=np.flatnonzero(choices==name)
            for start in range(0,len(ix),16):
                indexes=ix[start:start+16]
                score,nt=decoder.margins([rows[i] for i in indexes])
                logits[indexes]+=score.numpy()
                extra_tokens+=nt
                extra_inputs+=len(indexes)*2
            decoder.detach()
    assert traffic()==0
    out=dict(arm=arm,rows=[dict(id=r["id"],answer=int(v>0),margin=float(v),expert=str(n))
                            for r,v,n in zip(rows,logits,choices,strict=True)],
             network_bytes=traffic(),network_interfaces=nets,freeze_sha256=file_sha(work/"adapter-freeze.json"),
             wall_seconds=time.perf_counter()-tic,cpu_seconds=time.process_time()-cpu,
             encoder_inputs=e.presentations+extra_inputs, input_tokens=e.input_tokens+extra_tokens)
    (work/("cold-"+arm+".json")).write_text(json.dumps(out,separators=(",",":")))


if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("mode",choices=("fit","cold"))
    ap.add_argument("work",type=Path)
    ap.add_argument("encoder",type=Path)
    ap.add_argument("arg")
    a=ap.parse_args()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    if a.mode=="fit":
        fit(a.work,a.encoder,Path(a.arg))
    else:
        cold(a.work,a.encoder,a.arg)
