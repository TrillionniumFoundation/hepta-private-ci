"""Independent fitted-head, runtime-binding and paid-feedback review.

Reads all retained training/development states; no confirmation samples or
training updates are created. Eigenvalue powers independently reproduce the
600 finite gradient steps, including every development selection candidate.
"""

import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import tarfile

import numpy as np
from scipy.integrate import quad

from experiments.analytic_event_neuron.round3 import feedback


ROOT = Path(__file__).resolve().parent.parent
RUN = Path(sys.argv[1]) if len(sys.argv)>1 else Path("/tmp/aen-round3-20261028")
SEEDS = (607,701,809,907,1009)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    with np.load(path,allow_pickle=False) as arrays:
        return {k:arrays[k].item() if arrays[k].ndim==0 else arrays[k] for k in arrays.files}


def review():
    checks, failures = 0, []
    maxima = {"quadrature_error":0.,"quadrature_omitted_tail_bound":0.,"posterior_error":0.,"native_cdf_error":0.,"finite_step_weight_error":0.}
    states, heads, candidates, owner_files, witness_states = 0,0,0,0,0
    def check(value,message):
        nonlocal checks
        checks += 1
        if not value:
            failures.append(message)
    rng=np.random.default_rng(91281028)
    for index in range(96):
        mean=float(rng.uniform(-5,5)); variance=float(np.exp(rng.uniform(-6,2))); cost=float(rng.choice([.03,.12,.48]))
        sigma=math.sqrt(variance); cutoff=math.sqrt(cost)
        lower,upper=(-cutoff-mean)/sigma,(cutoff-mean)/sigma
        def integrand(z):
            return ((mean+sigma*z)**2-cost)*math.exp(-z*z/2)/math.sqrt(2*math.pi)
        ref=quad(integrand,-16,min(lower,16),epsabs=2e-11,epsrel=2e-11)[0] if lower>-16 else 0.
        ref+=quad(integrand,max(upper,-16),16,epsabs=2e-11,epsrel=2e-11)[0] if upper<16 else 0.
        # Avoid infinite-interval quadrature missing a narrow central peak.
        # Outside |Z|<=16, (m+sZ)^2 <= 2m^2+2vZ^2 bounds omitted positive gain.
        tail=math.erfc(16/math.sqrt(2)); phi=math.exp(-128)/math.sqrt(2*math.pi)
        omitted=2*mean*mean*tail+2*variance*(32*phi+tail)
        maxima["quadrature_omitted_tail_bound"]=max(maxima["quadrature_omitted_tail_bound"],omitted)
        check(omitted<1e-50,"central quadrature tail bound")
        gap=abs(feedback.positive_square_expectation(mean,variance,cost)-ref)
        maxima["quadrature_error"]=max(maxima["quadrature_error"],gap)
        check(gap<2e-9,f"independent tail quadrature {index}")
    for seed in SEEDS:
        directory=RUN/f"feedback_prepared/seed_{seed}"
        model=json.loads((directory/"MODELS.json").read_text())
        receipt=json.loads((directory/"TRAINING_RECEIPT.json").read_text())
        check(receipt["model_sha256"]==sha(directory/"MODELS.json") and receipt["model_document_sha256"]==digest(model),"model receipt binding")
        data={split:load(directory/("TRAIN.npz" if split=="train" else "DEVELOPMENT.npz")) for split in ("train","development")}
        check(data["train"]["seed"]==80000000+100*seed+1 and data["development"]["seed"]==80000000+100*seed+2,"training/development seed identity")
        check(not set(data["train"]["ids"])&set(data["development"]["ids"]),"overlapping supervised cases")
        alpha=float(np.mean((data["train"]["target"]-data["train"]["initial_output"])**2))
        residual=data["train"]["self_evaluation"]-data["train"]["target"]
        residual2=data["train"]["wait_evaluation"]-data["train"]["target"]
        scale=float(np.mean(np.r_[residual**2/data["train"]["sensor_variance"],residual2**2/data["train"]["wait_variance"]]))
        calibration=model["calibration"]
        check(alpha==calibration["error_variance"] and scale==calibration["noise_scale"],"training-only MLE differs")
        with gzip.open(directory/"TRAINING_ROWS.json.gz","rt") as stream:
            rows=json.load(stream)
        for split in ("train","development"):
            check(len(rows[split])==len(data[split]["ids"]),"retained training rows missing")
            for i,row in enumerate(rows[split]):
                check(row["case"]==str(data[split]["ids"][i]),"retained case identity")
                levels=[0,0]; previous="0"*64
                for stage_index,stage in enumerate(row["stages"]):
                    states+=1
                    public,law,run=stage["public"],stage["law"],stage["runtime"]
                    check(set(public)=={"initial","residuals","variances","repair_cost","wait_cost","wait_variance"},"private public-schema field")
                    variance_noise=np.asarray(public["variances"])*scale
                    covariance=np.full((len(variance_noise),len(variance_noise)),alpha)+np.diag(variance_noise)
                    coefficient=np.linalg.solve(covariance,np.full(len(variance_noise),alpha))
                    expected_m=float(coefficient@public["residuals"]); expected_v=float(alpha-alpha*coefficient.sum())
                    gap=max(abs(expected_m-run["source_forecast"][0]),abs(expected_v-run["source_forecast"][1]))
                    maxima["posterior_error"]=max(maxima["posterior_error"],gap)
                    check(gap<2e-13,"independent posterior conditioning")
                    target_levels=[math.floor(run["source_forecast"][0]*4096+.5),math.floor(math.log(run["source_forecast"][1])*4096+.5)]
                    check(run["packet"]["counts"]==[target_levels[j]-levels[j] for j in range(2)],"independent error-feedback counts")
                    levels=target_levels
                    request={k:run[k] for k in ("schema","subject","model_sha256","public_sha256","source_sha256","sequence","time")}
                    check(run["public_sha256"]==digest(public) and run["source_sha256"]==digest(run["source_forecast"]),"public/source binding")
                    check(run["request_sha256"]==digest(request),"request digest")
                    check(run["checkpoint_before"]==previous,"adapter ancestry")
                    check(run["checkpoint_after"]==digest([previous,run["request_sha256"],run["decoder"],run["native"]["checkpoint_after"],law]),"effect and law checkpoint binding")
                    previous=run["checkpoint_after"]
                    q=run["native"]["head"]["parameters_q24_decoded"]
                    check(law["mean"]==q[0] and law["variance"]==q[1] and law==run["law"],"policy law bypasses actual native head")
                    masses=run["native"]["head"]["probabilities_q24"]
                    check(sum(masses)==2**24 and all(type(x) is int and x>=0 for x in masses),"native categorical integer simplex")
                    check(law["probabilities"]==[x/2**24 for x in masses],"delivered categorical law differs")
                    sd=math.sqrt(q[1]); put=.5*math.erfc((q[0]-q[2])/(sd*math.sqrt(2))); call=.5*math.erfc((q[3]-q[0])/(sd*math.sqrt(2)))
                    ref=[put,1-put-call,call]
                    gap=max(abs(a-b) for a,b in zip(ref,run["native"]["head"]["probabilities"]))
                    maxima["native_cdf_error"]=max(maxima["native_cdf_error"],gap)
                    check(gap<2e-15,"actual Q24 thresholds CDF reference")
                    amount=round(law["mean"]*2**24)/2**24
                    check(stage["values"]["repair_amount"]==amount,"shared native Q24 repair amount")
                    target=float(data[split]["target"][i]); initial=public["initial"]
                    gain=(initial-target)**2-(initial+amount-target)**2-public["repair_cost"]
                    check(gain==stage["realized_gain"],"realized training action gain differs")
                    for arm in feedback.LEARNED:
                        if arm=="history":
                            precision=sum(1/v for v in public["variances"])
                            residual=sum(x/v for x,v in zip(public["residuals"],public["variances"]))/precision
                            z=(np.array([residual,math.log(1/precision),math.log(public["repair_cost"])])-calibration["public_center"])/calibration["public_scale"]
                            powers=[p for p in itertools.product(range(4),repeat=3) if sum(p)<=3]
                            vector=[float(np.prod(z**p)) for p in powers]
                            vector+=np.exp(-.5*np.sum((np.asarray(calibration["history_centers"])-z)**2,axis=1)).tolist()
                        else:
                            vector=[]
                            for native_row in stage["native"][arm]:
                                tick=native_row["ticks"][1]
                                check(tick["drive_q24"]==[0]*10 and native_row["original_sparse_tick_calls"]==2,"second native tick had fresh drive")
                                check(tick["checkpoint_before"]==("0"*64 if arm=="reset" else native_row["ticks"][0]["checkpoint_after"]),"memory/reset checkpoint effect")
                                check(tick["authority"]=="DENY_ALL" and tick["requires_calibration"],"runtime authority changed")
                                if arm=="zero":check(native_row["drive_q24"]==0,"zero control had drive")
                                vector.extend([1.]+[x/2**24 for key in ("activation_q24","eligibility_q24") for x in tick[key]])
                        check(np.array_equal(vector,stage["vectors"][arm]),"native/history feature reconstruction")
        train_gain=np.asarray([s["realized_gain"] for row in rows["train"] for s in row["stages"]])
        dev_gain=np.asarray([[r["stages"][0]["realized_gain"],r["stages"][1]["realized_gain"],r["stages"][0]["public"]["wait_cost"]] for r in rows["development"]])
        dev_wait=np.asarray([r["stages"][0]["values"]["wait_gain"] for r in rows["development"]])
        dev_stop=np.asarray([r["stages"][0]["stop_utility"] for r in rows["development"]])
        for arm in feedback.LEARNED:
            heads+=1
            train_x=np.asarray([s["vectors"][arm] for r in rows["train"] for s in r["stages"]])
            dev_x=np.asarray([s["vectors"][arm] for r in rows["development"] for s in r["stages"]])
            center,spread=train_x.mean(0),train_x.std(0);center[0],spread[0]=0.,1.;spread=np.where(spread>1e-8,spread,1.)
            x=(train_x-center)/spread
            fitted={}
            for strength in (.001,.01,.1):
                penalty=np.eye(x.shape[1])*strength;penalty[0,0]=0.
                hessian=x.T@x/len(x)+penalty; rhs=x.T@train_gain/len(x)
                eigenvalues,basis=np.linalg.eigh(hessian);rate=.9/max(eigenvalues[-1],1e-8)
                factors=-np.expm1(600*np.log1p(-rate*eigenvalues))/eigenvalues
                weights=basis@(factors*(basis.T@rhs))
                raw=weights/spread;raw[0]-=float(raw@center);fitted[strength]=raw
            scores=[]
            for candidate in receipt["heads"][arm]["candidates"]:
                candidates+=1;raw=fitted[candidate["l2"]]
                gap=float(np.max(abs(raw-np.asarray(candidate["weights"]))))
                maxima["finite_step_weight_error"]=max(maxima["finite_step_weight_error"],gap)
                check(gap<2e-11,"finite 600-step eigensystem reference weights")
                predicted=(dev_x@raw).reshape(-1,2)+candidate["offset"]
                first=np.argmax(np.column_stack([np.zeros(len(predicted)),predicted[:,0],dev_wait]),axis=1)
                utility=dev_stop+np.where(first==1,dev_gain[:,0],np.where(first==2,-dev_gain[:,2]+(predicted[:,1]>0)*dev_gain[:,1],0))
                check(float(utility.mean())==candidate["development_utility"],"full two-stage candidate utility")
                scores.append((float(utility.mean()),candidate["l2"],-abs(candidate["offset"])))
            selected=max(range(len(scores)),key=lambda i:scores[i])
            chosen=receipt["heads"][arm]["candidates"][selected]
            check(model["heads"][arm]=={k:chosen[k] for k in ("weights","offset","l2")},"selected learned head differs")
            check(receipt["heads"][arm]["parameter_l2_change"]>0,"head weights did not train")
        del rows
        for split in ("train","development"):
            metadata=receipt[split+"_archive"]["owners"]
            path=directory/metadata["path"]
            check(sha(path)==metadata["sha256"] and path.stat().st_size==metadata["bytes"],"owner archive binding")
            state_hashes,witnesses,hashes={},{},{}
            with tarfile.open(path,"r:gz") as archive:
                for member in archive:
                    if not member.isfile():continue
                    content=archive.extractfile(member).read();rel=str(Path(member.name).relative_to(path.name[:-7]))
                    hashes[rel]={"sha256":hashlib.sha256(content).hexdigest(),"bytes":len(content)};owner_files+=1
                    if rel=="MANIFEST.json":manifest=json.loads(content)["files"];continue
                    if rel.endswith("/state.json") or rel.endswith("/delivery.witness.json"):
                        envelope=json.loads(content);document=envelope["document"]
                        check(envelope["sha256"]==digest(document),"owner/witness envelope hash")
                        subject=rel.split("/")[0]
                        if rel.endswith("/state.json"):
                            state_hashes[subject]=(digest(document),document["checkpoint"],document["sequence"])
                        else:witnesses[subject]=document["records"]
            check({k:v for k,v in hashes.items() if k!="MANIFEST.json"}==manifest,"all owner archive members")
            for subject,(state_hash,checkpoint,sequence) in state_hashes.items():
                witness_states+=1; chain=witnesses[subject]
                check(len(chain)==sequence==2 and chain[-1]["state_sha256"]==state_hash and chain[-1]["checkpoint"]==checkpoint,"independent witness final state binding")
                predecessor="0"*64
                for index,item in enumerate(chain,1):
                    check(item["sequence"]==index and item["predecessor"]==predecessor,"witness complete ancestry")
                    predecessor=item["checkpoint"]
    qualification=RUN/"feedback_runtime_independent_development/QUALIFICATION.json"
    runtime=json.loads(qualification.read_text())
    check(runtime["passed"] and runtime["development_only"] and runtime["unique_histories"]==4,"independent actual runtime qualification")
    check(runtime["fresh_processes"]==2 and runtime["recovery_native_ticks"]==1,"fresh process recovery accounting")
    check(runtime["cross_owner_atomicity"] is False and runtime["source_or_density_retention_certificate"] is None,"false atomicity/retention claim")
    sources={p.name:sha(p) for p in [Path(__file__),*[ROOT/name for name in ("feedback.py","runtime_feedback.py","feedback_study.py","runtime_feedback_study.py","feedback_audit.py","FEEDBACK_RUNTIME.md")]]}
    report={"schema":"hepta.paid-feedback.prefreeze-review.v1","passed":not failures,"checks":checks,"failures":failures,
        "maxima":maxima,"source_sha256":sources,"prepared_training_seeds":list(SEEDS),"retained_stage_states":states,
        "trained_heads_recomputed":heads,"development_candidates_recomputed":candidates,"owner_archive_files_verified":owner_files,
        "durable_owner_witness_pairs":witness_states,"independent_runtime_qualification_sha256":sha(qualification),
        "independent_runtime_unique_development_histories":4,"independent_runtime_fresh_processes":2,"confirmation_generated":False,
        "reference_correction":"Initial unsegmented half-infinite quad missed normal mass for four narrow-variance cases. Attempt and script retained under run/review_attempts; finite interval plus certified omitted-tail bound fixes the independent reference, with scientific source/models/data/gates unchanged.",
        "scope_limits":["No confirmation data and no training refits.","Native tick values read/reconstructed; qualification executes actual native, but training ticks were not rerun.",
          "Terminal error tails at native Q24 thresholds are not probability of gain for the chosen repair amplitude.",
          "Continuous future optimal amplitude is a wait-value plug-in; Q24 loss bound1/(4*2^48) and learned follow-up mismatch remain explicit.",
          "Zero/reset isolate sparse feature pathways; feedback remains available for shared amplitudes and wait values.",
          "Separate target-free policy process is not a hostile filesystem-access control boundary.","Two-owner partial commits fail closed; no cross-owner atomicity or retention certificate."]}
    path=ROOT/"evidence/FEEDBACK_RUNTIME_PREFREEZE_REVIEW.json";path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:report[k] for k in ("passed","checks","failures","maxima","retained_stage_states","development_candidates_recomputed")}))
    if failures:raise SystemExit(1)


if __name__=="__main__":review()
