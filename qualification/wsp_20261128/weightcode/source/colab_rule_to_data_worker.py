"""Public-only finite Colab rule-to-data reproduction, resumable within 600s jobs.

The bootstrap supplies PROTOCOL, AMENDMENT and WSP_DELTA_B64. The trusted worker
never receives private Hepta data. It keeps source/optimizer checkpoints across
immediate bounded chunks; no job changes the frozen quality method.
"""
from __future__ import annotations
import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "2"
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
import base64, hashlib, importlib.util, io, json, platform, resource, subprocess, sys, tarfile, time
from pathlib import Path
JOB_START = time.monotonic()
ARTIFACT_DIR = Path.cwd()
ROOT = Path("/content/hepta_weightcode_20261128_cd3d")
ROOT.mkdir(exist_ok=True)
OUT = ROOT / "evidence"
OUT.mkdir(exist_ok=True)

def sha_bytes(x): return hashlib.sha256(x).hexdigest()
def sha_file(x): return sha_bytes(Path(x).read_bytes())
def save(path, obj):
    path = Path(path)
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    temp.replace(path)
def log(text): print(text, flush=True)
def remaining(): return AMENDMENT["execution_changes"]["per_job_soft_wall_seconds"]-(time.monotonic()-JOB_START)
COUNTS = {"numpy_rows":0,"torch_inference_rows":0,"torch_gradient_rows":0,"gradient_microbatches":0,"optimizer_steps":0}
JOB_RECORD = {"started_unix":time.time(),"counts":COUNTS,"status":"starting"}
jobs_file = OUT / "job_records.json"
jobs = json.loads(jobs_file.read_text()) if jobs_file.exists() else []
if len(jobs) >= AMENDMENT["execution_changes"]["maximum_jobs"]:
    raise RuntimeError("Frozen eight-job limit exhausted; no additional work permitted by this protocol")
JOB_INDEX = len(jobs)
jobs.append(JOB_RECORD)
save(jobs_file,jobs)
save(OUT/"protocol.json",PROTOCOL)
save(OUT/"execution_amendment.json",AMENDMENT)

class BudgetYield(Exception): pass
def budget_check(reserve=30):
    if remaining() < reserve:
        raise BudgetYield("Checkpointed finite job yield; fixed remaining steps continue under original budget")
def package(status, detail=None):
    JOB_RECORD.update(status=status, wall_seconds=time.monotonic()-JOB_START,
                      cpu_seconds=time.process_time(), detail=detail, max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(jobs_file,jobs)
    summary_path=OUT/"summary.json"
    summary=json.loads(summary_path.read_text()) if summary_path.exists() else None
    result={"status":status,"job_index":JOB_INDEX,"job_record":JOB_RECORD,"summary":summary,
            "artifact_scope":"Only public WeightCode/SCAN and derived scientific checkpoints","evidence_root":str(OUT)}
    save(ARTIFACT_DIR/"result.json",result)
    # Whole evidence, including partial optimizer state and every failed chunk.
    target=ARTIFACT_DIR/"evidence.tar.gz"
    with tarfile.open(target,"w:gz") as archive:
        archive.add(OUT,arcname="weightcode_rule_to_data")
    save(ARTIFACT_DIR/"artifact_manifest.json",{"result_sha256":sha_file(ARTIFACT_DIR/"result.json"),
          "archive_sha256":sha_file(target),"archive_bytes":target.stat().st_size})
    log(json.dumps({"status":status,"job_index":JOB_INDEX,"archive_bytes":target.stat().st_size,
                    "wall_seconds":JOB_RECORD["wall_seconds"]}))

try:
    import numpy as np
    import torch
    import torch.nn.functional as F
    assert torch.cuda.is_available(),"No real CUDA device; no CPU fallback disguised as a GPU run"
    torch.set_num_threads(2)
    if torch.get_num_interop_threads()!=1:
        try: torch.set_num_interop_threads(1)
        except RuntimeError: pass
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic=True
    torch.backends.cudnn.benchmark=False
    if hasattr(torch.backends.cuda.matmul,"fp32_precision"):
        torch.backends.cuda.matmul.fp32_precision="ieee"
    else:
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False
    hw={"python":sys.version,"numpy":np.__version__,"torch":torch.__version__,"cuda":torch.version.cuda,
        "gpu_name":torch.cuda.get_device_name(0),"gpu_total_memory":torch.cuda.get_device_properties(0).total_memory,
        "platform":platform.platform(),"threads":torch.get_num_threads(),"deterministic":torch.are_deterministic_algorithms_enabled()}
    assert "T4" in hw["gpu_name"],f"Frozen accelerator T4 requested; observed {hw['gpu_name']}"
    hw["nvidia_smi"]=subprocess.run(["nvidia-smi","--query-gpu=name,uuid,driver_version,memory.total","--format=csv,noheader"],capture_output=True,text=True,timeout=20).stdout.strip()
    save(OUT/f"hardware_job{JOB_INDEX}.json",hw)
    log("Actual hardware "+json.dumps(hw))
    REPO=ROOT/"WeightCode"
    if not (REPO/".git").exists():
        subprocess.run(["git","clone","--quiet","--filter=blob:none","https://github.com/Gen-Verse/WeightCode",str(REPO)],check=True,timeout=120)
    subprocess.run(["git","checkout","--quiet",PROTOCOL["upstream_commit"]],cwd=REPO,check=True,timeout=60)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip()
    assert commit==PROTOCOL["upstream_commit"]
    sys.path.insert(0,str(REPO))
    from weightcode.baselines.instance_io import load_instance
    from weightcode.baselines.fit.runner import load_scan_evidence
    from weightcode.baselines.fit import scanrefs as R, seqgrad as SG
    from weightcode.common.identity import params_sha256, save_params, load_params, count_changed
    from weightcode.data import scan as S
    from weightcode.evalkit.patch_check import predict
    from weightcode.evalkit.scanskill import part_summary
    from weightcode.examples.fetch import hf_files, checked_files
    from weightcode.examples.scan import SCAN_RAW_URL
    from weightcode.models import transformer as T
    download=ROOT/"downloads"
    hf_files([f"weights/instances/{PROTOCOL['instance']}/"],download/"hf")
    checked_files({p:SCAN_RAW_URL.format(commit=S.SCAN_COMMIT,path=p) for p in S.RAW_SHA256},S.RAW_SHA256,download/"scan")
    inst=load_instance(download/"hf"/"weights"/"instances"/PROTOCOL["instance"])
    BASE=inst.params
    assert inst.params_sha256==PROTOCOL["base_sha256"]
    evidence=load_scan_evidence(inst)
    COUNTS["numpy_rows"]+=len(evidence.x)
    fit=R.rulegen_fit_set("addprim_jump","mixed")
    assert fit["record"]["commands_sha256"]==PROTOCOL["data"]["grammar_fit_commands_sha256"]
    checked=R.check_rows_against_official(download/"scan"/S.ALL_FILE,fit["commands"],fit["y"])
    x_np=np.concatenate((fit["x"],evidence.x))
    y_np=np.concatenate((fit["y"],evidence.y))
    assert len(x_np)==4065
    xt=torch.from_numpy(np.ascontiguousarray(x_np,dtype=np.int64)).to("cuda")
    yt=torch.from_numpy(np.ascontiguousarray(y_np,dtype=np.int64)).to("cuda")
    denominator=int((yt!=S.IGNORE).sum())
    built=S.build_condition_splits(download/"scan","addprim_jump")
    S.check_disjoint(built)
    assert params_sha256(built.sealed)==PROTOCOL["data"]["final_sha256"]
    parts={"check_new":built.private["V_check"],"check_old":built.private["old_check"],
           "final_new":{k:v[built.sealed["part"]==S.PART_NEW] for k,v in built.sealed.items()},
           "final_old":{k:v[built.sealed["part"]==S.PART_OLD] for k,v in built.sealed.items()}}
    with np.load(io.BytesIO(base64.b64decode(WSP_DELTA_B64)),allow_pickle=False) as z:
        delta={k:z[k] for k in z.files}
    wsp={k:((v.astype(np.float64)+delta[k]).astype(np.float32) if k in delta else v.copy()) for k,v in BASE.items()}
    for k in delta:
        np.copyto(wsp[k],BASE[k],where=wsp[k]==BASE[k])
    expected_wsp="6c9bc3bdaf347dfb6c868a71f17506bea58ab51f82707f236692604dc34198a0"
    assert params_sha256(wsp)==expected_wsp
    # Exactly the public program's grammar enumeration order, used only to audit
    # which final inputs were already queried without labels by that program.
    vs=[]
    for d in ["walk","look","run","jump","turn"]:
        for direction in ["left","right"]:
            vs += [d+" opposite "+direction,d+" around "+direction,d+" "+direction]
    vs += ["walk","look","run","jump"]
    ss=[c for v in vs for c in (v,v+" twice",v+" thrice")]
    grammar=list(ss)
    for a in ss:
        for b in ss: grammar += [a+" and "+b,a+" after "+b]
    jprobe=[c for c in grammar if "jump" in c.split() and c!="jump"][::8]
    probed=set(jprobe+[c for c in grammar if "jump" not in c.split()])
    fit_inputs=set(S.decode(x_np))
    unfitted={n:np.array([c not in fit_inputs for c in S.decode(p["x"])]) for n,p in parts.items()}
    common=np.array([c not in fit_inputs and c not in probed for c in S.decode(parts["final_new"]["x"])])
    save(OUT/"data_audit.json",{"fit_record":fit["record"],"label_check":checked,"fit_rows":4065,
         "valid_tokens":denominator,"fit_sha256":params_sha256({"x":x_np,"y":y_np}),
         "overlap":{n:{"total":len(p["x"]),"fit_overlap":int((~unfitted[n]).sum())} for n,p in parts.items()},
         "final_new_neither_fitted_nor_wsp_probed":int(common.sum()),"common_mask_sha256":sha_bytes(common.tobytes())})

    def accum(model,x,y,micro=128):
        model.zero_grad(set_to_none=True)
        denom=int((y!=S.IGNORE).sum())
        loss_sum=0.
        for start in range(0,len(x),micro):
            budget_check(25)
            logits=model(x[start:start+micro])
            loss=F.cross_entropy(logits.reshape(-1,logits.shape[-1]),y[start:start+micro].reshape(-1),ignore_index=S.IGNORE,reduction="sum")/denom
            loss.backward()
            loss_sum+=float(loss.detach())
            COUNTS["torch_gradient_rows"]+=min(micro,len(x)-start)
            COUNTS["gradient_microbatches"]+=1
        return loss_sum

    if not (OUT/"parity_before_fit.json").exists():
        model=SG.rebuild(BASE)
        parity=R.device_parity(model,BASE,inst.forward,evidence.x,"cuda")
        COUNTS["numpy_rows"]+=65
        COUNTS["torch_inference_rows"]+=130
        model=model.to("cuda")
        px=torch.from_numpy(evidence.x).to("cuda")
        py=torch.from_numpy(evidence.y).to("cuda")
        model.zero_grad(set_to_none=True)
        dense=SG.token_loss(model,px,py)
        dense.backward()
        COUNTS["torch_gradient_rows"]+=65
        dense_grad={k:p.grad.detach().clone() for k,p in model.named_parameters()}
        value=accum(model,px,py,17)
        absmax=relmax=0.
        for k,p in model.named_parameters():
            diff=(p.grad-dense_grad[k]).abs()
            absmax=max(absmax,float(diff.max()))
            mask=dense_grad[k].abs()>1e-3
            if mask.any(): relmax=max(relmax,float((diff[mask]/dense_grad[k].abs()[mask]).max()))
        assert absmax<=1e-4 and relmax<=1e-3 and abs(value-float(dense.detach()))<=1e-4
        save(OUT/"parity_before_fit.json",{**parity,"dense_loss":float(dense.detach()),"accum_loss":value,"grad_absmax":absmax,"grad_relmax":relmax,"before_any_training":True})
        del model,dense_grad
        torch.cuda.empty_cache()

    def checkpoint(directory,model,optimizer,step,mask,curve,prior_hash):
        state={"model":model.state_dict(),"optimizer":optimizer.state_dict(),"step":step,
               "mask":mask,"curve":curve,"base_sha256":inst.params_sha256,"prior_checkpoint_sha256":prior_hash}
        target=directory/"optimizer_checkpoint.pt"
        temp=directory/"optimizer_checkpoint.tmp.pt"
        torch.save(state,temp)
        temp.replace(target)
        current=sha_file(target)
        save(directory/"checkpoint_receipt.json",{"completed_steps":step,"sha256":current,"prior_sha256":prior_hash,"job_index":JOB_INDEX})
        return current

    def preds(params,name):
        path=OUT/(params_sha256(params)+"_"+name+".npz")
        if path.exists():
            with np.load(path,allow_pickle=False) as z:return z["pred"]
        budget_check(30)
        pred=predict(inst.forward,params,parts[name]["x"],256)
        COUNTS["numpy_rows"]+=len(parts[name]["x"])
        np.savez_compressed(path,pred=pred)
        return pred
    def readout(params,name):
        y=parts[name]["y"]
        bp,cp=preds(BASE,name),preds(params,name)
        result=part_summary(y,bp,cp)
        m=unfitted[name]
        result["not_in_generated_fit"]=part_summary(y[m],bp[m],cp[m]) if m.any() else {"n":0}
        if name=="final_new":
            result["neither_fitted_nor_wsp_probed"]=part_summary(y[common],bp[common],cp[common]) if common.any() else {"n":0}
        return result

    did_work=False
    for arm in PROTOCOL["arms"]:
        d=OUT/arm["name"]
        d.mkdir(exist_ok=True)
        if (d/"result.json").exists():continue
        did_work=True
        torch.manual_seed(0)
        model=SG.rebuild(BASE).to("cuda")
        optimizer=torch.optim.Adam(list(model.parameters()),lr=arm["lr"],betas=(.9,.999),eps=1e-8,weight_decay=0.,foreach=False)
        target=d/"optimizer_checkpoint.pt"
        step=0;mask=None;curve=[];chain_hash=None
        if target.exists():
            receipt=json.loads((d/"checkpoint_receipt.json").read_text())
            assert sha_file(target)==receipt["sha256"]
            state=torch.load(target,map_location="cuda",weights_only=True)
            assert state["base_sha256"]==inst.params_sha256
            model.load_state_dict(state["model"],strict=True)
            optimizer.load_state_dict(state["optimizer"])
            step=state["step"];mask=state["mask"];curve=state["curve"];chain_hash=receipt["sha256"]
            assert step==receipt["completed_steps"]
            del state
        log(f"Fixed arm {arm['name']}, resume step {step}/{arm['steps']}")
        if arm["method"]=="sparse19_sal" and mask is None:
            accum(model,xt,yt)
            raw=R.top_fraction({k:p.grad.detach().cpu().numpy() for k,p in model.named_parameters()},sorted(BASE))
            mask={k:torch.from_numpy(m.astype(np.float32)).to("cuda") for k,m in raw.items()}
            save(d/"mask.json",{"mask_sha256":params_sha256(raw),"n_entries":sum(int(v.sum()) for v in raw.values())})
            chain_hash=checkpoint(d,model,optimizer,step,mask,curve,chain_hash)
        fit_start=time.monotonic()
        try:
            while step<arm["steps"]:
                budget_check(55)
                loss=accum(model,xt,yt)
                if mask is not None:
                    for k,p in model.named_parameters():p.grad.mul_(mask[k])
                optimizer.step();step+=1;COUNTS["optimizer_steps"]+=1
                if step%10==0 or step==arm["steps"]:
                    torch.cuda.synchronize()
                    curve.append({"step":step,"loss_before_update":loss,"job_index":JOB_INDEX,"job_elapsed":time.monotonic()-JOB_START})
                    chain_hash=checkpoint(d,model,optimizer,step,mask,curve,chain_hash)
                    log(f"step {step}/{arm['steps']}, tokenCE {loss:.6f}, job {time.monotonic()-JOB_START:.1f}s")
        except BudgetYield:
            chain_hash=checkpoint(d,model,optimizer,step,mask,curve,chain_hash)
            raise
        child=T.export_seq_params(model)
        if mask is not None:
            for k,m in mask.items():
                fixed=~m.detach().cpu().numpy().astype(bool)
                assert np.array_equal(child[k][fixed],BASE[k][fixed])
        child_sha=save_params(d/"fixed_candidate.npz",child)
        seal={"arm":arm,"params_sha256":child_sha,"n_changed":count_changed(BASE,child),
              "checkpoint_sha256":chain_hash,"training_complete":True,"readouts_used_for_selection":False}
        save(d/"candidate_sealed_before_readouts.json",seal)
        # Any partial readout is cached by full model hash; no candidate is retuned.
        budget_check(120)
        readings={name:readout(child,name) for name in ("check_new","check_old","final_new","final_old")}
        result={**seal,"readout":readings,"exact_published_reference_hash":child_sha==arm.get("fixed_reference_child_sha256"),
                "execution_scope":"Author-fixed configuration with float32 microbatch accumulation; original GPU bit equality only if observed."}
        save(d/"result.json",result)
        log(f"Completed fixed {arm['name']}: final new {readings['final_new']['em_child']}, old {readings['final_old']['em_child']}")
        del model,optimizer,child
        torch.cuda.empty_cache()
        break # At most one fixed reference completed per bounded native job.
    completed=[OUT/a["name"]/"result.json" for a in PROTOCOL["arms"]]
    if all(p.exists() for p in completed):
        wsp_readings={n:readout(wsp,n) for n in ("final_new","final_old")}
        save(OUT/"summary.json",{"protocol":PROTOCOL,"amendment":AMENDMENT,"results":[json.loads(p.read_text()) for p in completed],
             "wsp_same_subsets":wsp_readings,"source_commit":commit,"wsp_sha256":expected_wsp,
             "grammar_data_audit":json.loads((OUT/"data_audit.json").read_text()),
             "scope":"Published author-selected rule-to-data reproduction; no new private model or new external holdout."})
        package("complete")
    else:
        package("partial","Remaining fixed arm or fixed steps continue immediately within eight-job total cap")
except BudgetYield as error:
    package("partial",str(error))
except Exception as error:
    package("failed",{"type":type(error).__name__,"message":str(error)})
    raise
