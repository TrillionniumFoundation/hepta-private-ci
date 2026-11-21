"""Fixed-law causal rescues and constructive two-unit/readout weight program."""
from pathlib import Path
from fractions import Fraction
from types import SimpleNamespace
import copy
import gc
import os
import sys
import time
import numpy as np

BASE = Path(os.environ.get("HEPTA_WSP_INPUT_ROOT","/workspace/scratch/4b91365ace88")).resolve()
OLD = BASE/"neuron_margin_experiment"
FT = BASE/"neuron_full_mlp_experiment"
sys.path.insert(0,str(OLD))
sys.path.insert(0,str(FT))
from artifact_io import read,save,sha,canonical,identity,json_bytes
from vendor import planning as planning
from vendor import quadratic
from task_graph import backward_values,forward_occupancy,state_weights
import mlp_math as mlp
from run_full_mlp_experiment import exact_full_radius,save_model,save_npz

TERMINAL = (0,4,5)
ARMS = ("C","S","B","Q","SB","SQ","BQ","SBQ","J_own","D","R","P","RP","K")


def subset(full):
    return SimpleNamespace(**{key:getattr(full,key) for key in (
        "checked_mm","NumpyPolicy","Oracle","initial","legal","due_request","successor",
        "predicted","outcomes","policy_value","head","deploy")})


def enumerate_graph(ctx,public,oracle,cap,budget):
    """Complete original state identity, including accrued charges."""
    mapping=planning.enumerate_states(ctx,public,True,cap)
    keys,states=list(mapping),list(mapping.values())
    indices={key:i for i,key in enumerate(keys)}
    order=sorted(range(len(states)),key=lambda i:states[i]["tick"])
    masks=np.array([ctx.legal(public,s) for s in states])
    probabilities=np.array([oracle.posterior(s) for s in states])
    if not np.isfinite(probabilities).all() or np.any(probabilities<0) or np.any(probabilities>1):
        raise ArithmeticError("nonfinite or invalid declared-law posterior")
    terminal=np.c_[np.zeros((len(states),4)),1-2*probabilities,2*probabilities-1]
    edges=[];max_error=0.
    for index,state in enumerate(states):
        if index%128==0:budget()
        row=[]
        for action in (1,2,3):
            outgoing=[]
            if masks[index,action]:
                for probability,completion in ctx.outcomes(public,state,action,oracle):
                    after=ctx.successor(public,state,action,completion)
                    fee=float(after["charges"]-state["charges"])
                    if after["tick"]!=state["tick"]+1 or not np.isfinite(probability) or probability<0 or not np.isfinite(fee) or fee<0:
                        raise ArithmeticError("invalid finite-law DAG edge")
                    outgoing.append((float(probability),indices[canonical(after)],
                                     fee))
                max_error=max(max_error,abs(sum(p for p,_,_ in outgoing)-1))
            row.append(outgoing)
        edges.append(row)
    if max_error>2e-11:
        raise ArithmeticError("declared-law graph probability normalization")
    qstar=terminal.copy(); values=np.zeros(len(states))
    for index in reversed(order):
        for a,outgoing in enumerate(edges[index]):
            if masks[index,a+1]:
                total=0.
                for probability,after,fee in outgoing:
                    if probability:total+=probability*(float(values[after])-fee)
                qstar[index,a+1]=total
        values[index]=float(np.where(masks[index],qstar[index],-np.inf).max())
    return dict(keys=keys,states=states,indices=indices,order=order,masks=masks,
                posterior=probabilities,terminal=terminal,edges=edges,qstar=qstar,
                optimal_values=values,initial=indices[canonical(ctx.initial(public))],
                probability_error=max_error)


def value(graph,scores):
    actions=np.where(graph["masks"],scores,-np.inf).argmax(1)
    result=backward_values(graph["order"],actions,graph["terminal"],graph["edges"])
    occupancy,terminal_mass=forward_occupancy(graph["order"],graph["initial"],actions,graph["edges"])
    if abs(terminal_mass-1)>2e-10:
        raise ArithmeticError("policy terminal probability mismatch")
    return float(result[graph["initial"]]),actions,occupancy


def forward_X(ctx,public,model,graph):
    """Memoize only unchanged renewal mass/bank; public features stay full-state."""
    if model.family!="renewal":
        raise ValueError("physical-feature memoization is only qualified for renewal checkpoints")
    rows=[]; physical={}
    for state in graph["states"]:
        key=(state["tick"],tuple((r["observation_tick"],r["observation"],r["reliability"])
                                for r in state["history"]))
        if key not in physical:
            mass,bank,_=model.represent(public,state)
            physical[key]=(mass,bank)
        mass,bank=physical[key]
        pub=ctx.ns["public_features"](public,state)
        rows.append(np.r_[pub,mass,bank])
    return np.asarray(rows)


def world_context(full,public,base,protocol,budget):
    started=time.process_time()
    model=full.NumpyPolicy(base)
    truth=full.Oracle(public,full.law,model.confusion)
    graph=enumerate_graph(full,public,truth,protocol["state_cap"],budget)
    X=forward_X(full,public,model,graph)
    hidden,logits,p_C,scores_C=mlp.strict_chunks(mlp.pack(base),X)
    C_value,C_actions,C_occupancy=value(graph,scores_C)
    # Independent original recursive scalar executor, with the original
    # representation and affine reduction, validates every world's baseline.
    reference_policy=planning.WorldPolicy(full,public,model,None)
    reference,_=full.policy_value(public,full.head(base),
                                 lambda _p,s:reference_policy.feature(s)[0],truth)
    if float(reference)!=C_value:
        raise ArithmeticError("full-DAG C utility differs from original recursive executor")
    omega=.9*C_occupancy/C_occupancy.sum()+.1/len(X)
    if abs(float(omega.sum())-1)>2e-12:
        raise ArithmeticError("common calibration weights not normalized")
    return dict(public=public,base=base,model=model,truth=truth,graph=graph,X=X,
                C_hidden=hidden,C_logits=logits,C_belief=p_C,C_scores=scores_C,
                C_value=C_value,C_actions=C_actions,C_occupancy=C_occupancy,omega=omega,
                preparation_CPU_seconds=time.process_time()-started,
                original_recursive_exact=True)


def measure(world,scores,belief):
    utility,actions,occupancy=value(world["graph"],scores)
    error=float(np.sum(world["omega"]*(belief-world["graph"]["posterior"])**2))
    q=world["graph"]["qstar"]
    regret=np.where(world["graph"]["masks"],q,-np.inf).max(1)-q[np.arange(len(q)),actions]
    return dict(utility=utility,excess_Brier=error,
                teacher_regret=float(np.sum(occupancy*regret)),
                decision_mass=float(occupancy.sum()),
                action_difference_C=float(np.sum(world["omega"]*(actions!=world["C_actions"]))),
                action_sha256=sha(actions.tobytes()),
                belief_sha256=sha(belief.tobytes()),actions=actions)


def evaluate_weight(world,artifact):
    _,_,belief,scores=mlp.strict_chunks(mlp.pack(artifact),world["X"])
    return measure(world,scores,belief),belief,scores


def evaluate_all(full,world,artifacts,protocol,budget):
    started=time.process_time()
    graph=world["graph"];truth=world["truth"]
    X_S=[]
    for s,x in zip(graph["states"],world["X"]):
        X_S.append(np.r_[x[:43],truth.belief(s),truth.bank(s)])
    _,_,p_S,scores_S=mlp.strict_chunks(mlp.pack(world["base"]),np.asarray(X_S))
    records={}; beliefs={}
    score_arrays={}
    for name in ("C","S","B","Q","SB","SQ","BQ","SBQ"):
        scores=(scores_S if "S" in name else world["C_scores"]).copy()
        belief=(p_S if "S" in name else world["C_belief"]).copy()
        if "B" in name:
            scores[:,4:6]=graph["terminal"][:,4:6]
            belief=graph["posterior"].copy()
        if "Q" in name:scores[:,1:4]=graph["qstar"][:,1:4]
        records[name]=measure(world,scores,belief)
        beliefs[name]=belief;score_arrays[name]=scores
    if not np.array_equal(score_arrays["BQ"],score_arrays["SBQ"]):
        raise ArithmeticError("BQ/SBQ score identity failed")
    own=full.Oracle(world["public"],planning.OwnTableLaw(world["model"],full),world["model"].confusion)
    own_graph=enumerate_graph(full,world["public"],own,protocol["state_cap"],budget)
    if own_graph["keys"]!=graph["keys"]:
        raise ArithmeticError("own/truth graph state identity differs")
    records["J_own"]=measure(world,own_graph["qstar"],own_graph["posterior"])
    for name in ("D","R","P","RP","K"):
        records[name],beliefs[name],_=evaluate_weight(world,artifacts[name])
    optimum=float(graph["optimal_values"][graph["initial"]])
    tolerance=protocol["oracle_tolerance"]*(1+abs(optimum))
    if abs(records["BQ"]["utility"]-optimum)>tolerance:
        raise ArithmeticError("oracle Bellman policy fails optimum equality")
    if records["BQ"]["utility"]!=records["SBQ"]["utility"]:
        raise ArithmeticError("BQ/SBQ expected utility differs")
    if any(r["utility"]>optimum+tolerance for r in records.values()):
        raise ArithmeticError("a policy exceeds same-law optimal expected utility")
    diagnostic=dict(states=len(graph["states"]),original_recursive_exact=True,
        qstar_initial=optimum,oracle_tolerance=tolerance,
        probability_error=graph["probability_error"],
        common_support_sha256=sha(canonical(graph["keys"]).encode()),
        common_weights_sha256=sha(world["omega"].tobytes()),
        calibration_scope="complete lawful states; fixed .9 C occupancy normalized plus .1 uniform",
        CPU_seconds=time.process_time()-started)
    return records,diagnostic,beliefs["K"]


def construct_program(ctx,fit,base,protocol,budget):
    """Only own-law TRAIN targets. No evaluator law is accepted by this API."""
    started=time.process_time()
    if quadratic.LAMBDA!=protocol["head_ridge"]:
        raise ValueError("frozen head ridge differs from reused solver")
    previous=read(FT/f"attempt001/fit_{fit}_CANDIDATE.json.gz")
    with np.load(FT/"attempt001"/previous["dataset"]["path"],allow_pickle=False) as archive:
        data={k:archive[k] for k in archive.files}
    X=data["X"];original=mlp.pack(base);C=ctx.head(base)
    hidden,logits,p_C,C_scores=mlp.strict_chunks(original,X)
    if not np.array_equal(C_scores,data["C_scores"]):
        raise ArithmeticError("frozen original full TRAIN forward changed")
    H=np.c_[hidden,np.ones(len(X))]
    Y=np.zeros((len(X),4));weights=np.zeros_like(Y)
    teacher_p=np.zeros(len(X));rows=[];offset=0
    public=read(OLD/f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")
    policy=ctx.NumpyPolicy(base)
    for world,old in zip(public,previous["reconstructed_worlds"]):
        budget()
        oracle=ctx.Oracle(world,planning.OwnTableLaw(policy,ctx),policy.confusion)
        g=enumerate_graph(ctx,world,oracle,protocol["state_cap"],budget)
        n=len(g["states"]);sl=slice(offset,offset+n)
        if sha(canonical(g["keys"]).encode())!=old["state_order_sha256"]:
            raise ArithmeticError("original TRAIN state ordering changed")
        if not np.array_equal(g["masks"],data["legal_masks"][sl]):
            raise ArithmeticError("original TRAIN legality changed")
        Y[sl,:3]=g["qstar"][:,1:4]
        teacher_p[sl]=g["posterior"]
        clipped=np.clip(g["posterior"],protocol["posterior_clip"],1-protocol["posterior_clip"])
        Y[sl,3]=np.log(clipped/(1-clipped))
        _,_,original_occupancy=value(g,C_scores[sl])
        W,_,_=state_weights(g["masks"],original_occupancy,64,.9)
        if sha(W.tobytes())!=old["W_sha256"]:
            raise ArithmeticError("original continuation sample weights changed")
        weights[sl,:3]=W
        weights[sl,3]=8*(g["posterior"]*(1-g["posterior"]))**2*data["belief_weights"][sl]
        rows.append(dict(world_id=world["id"],rows=n,state_order_sha256=old["state_order_sha256"],
                         optimal_initial=float(g["optimal_values"][g["initial"]]),
                         teacher_sha256=sha(Y[sl].tobytes()),
                         sample_weight_sha256=sha(weights[sl].tobytes())))
        offset+=n
    if offset!=len(X) or len(rows)!=64:
        raise ArithmeticError("complete original TRAIN required")
    u=data["state_weights"].copy();u/=u.sum()
    mu=u@X;centered=X-mu
    std=np.sqrt(np.sum(u[:,None]*centered**2,axis=0))
    active=std>protocol["std_floor"]
    scale=np.where(active,std,1.)
    Z=np.where(active,centered/scale,0.)
    residual=(Y[:,:3]-C_scores[:,1:4])*data["legal_masks"][:,1:4]
    residual-=u@residual
    A=np.linalg.solve(Z.T@(u[:,None]*Z)+protocol["input_ridge"]*np.eye(85),
                      Z.T@(u[:,None]*residual))
    U,singular,Vt=np.linalg.svd(A,full_matrices=False)
    singular_scale=max(float(singular[0]),1e-12)
    valid=bool(singular[1]>protocol["std_floor"] and
               singular[0]-singular[1]>protocol["svd_gap"]*singular_scale and
               singular[1]-singular[2]>protocol["svd_gap"]*singular_scale)
    for j in range(3):
        at=int(np.abs(U[:,j]).argmax())
        if U[at,j]<0:U[:,j]*=-1;Vt[j]*=-1
    impact=[]
    for j in range(48):
        cont=np.sum((hidden[:,j,None]*C[:3,j][None,:])**2*data["legal_masks"][:,1:4],axis=1)
        removed=1/(1+np.exp(-np.clip(logits[:,3]-C[3,j]*hidden[:,j],-700,700)))
        impact.append(float(np.sum(data["belief_weights"]*(cont+8*(p_C-removed)**2))))
    units=sorted(range(48),key=lambda j:(impact[j],j))[:2]
    radius=.5*float(np.linalg.norm(C[:3]))*(1-1e-8)
    exact_full_radius(original,base,radius)
    report=dict(fit=fit,valid=valid,reason="READY" if valid else "SVD_RANK_OR_GAP_STOP",
        rows=len(X),TRAIN=rows,own_law_labels_only=True,input_mu=mu,input_std=std,
        active_input_columns=active,ridge_coefficients=A,singular_values=singular,
        U=U,Vt=Vt,unit_impact=impact,selected_units=units,
        intended_preactivation_std=.5,radius=radius)
    params={"R":original.copy(),"P":original.copy(),"RP":original.copy()}
    if valid:
        target=copy.deepcopy(base)
        for j,unit in enumerate(units):
            direction=np.where(active,U[:,j]/scale,0.)
            projected=centered@direction
            deviation=float(np.sqrt(np.sum(u*projected**2)))
            if deviation<=protocol["std_floor"]:
                report.update(valid=False,reason="ZERO_DIRECTION_STD_STOP");valid=False;break
            row=.5*direction/deviation
            target["network"]["w1"][unit]=row.tolist()
            target["network"]["b1"][unit]=-float(row@mu)
        if valid:
            dr=mlp.pack(target)-original
            length=float(np.linalg.norm(dr))
            scaling=min(1.,(radius/2)*(1-1e-8)/max(length,1e-300))
            representation_mask=np.zeros(len(original),dtype=bool)
            for unit in units:
                representation_mask[unit*85:(unit+1)*85]=True
                representation_mask[4080+unit]=True
            R=original.copy()
            R[representation_mask]=original[representation_mask]+scaling*dr[representation_mask]
            norm_R=exact_full_radius(R,base,radius)
            exact_delta=Fraction(int(norm_R["delta_squared"]["numerator"]),
                                 int(norm_R["delta_squared"]["denominator"]))
            remaining=(Fraction.from_float(radius)**2-exact_delta)
            readout_radius=float(np.sqrt(float(remaining)))*(1-1e-8)
            h_R=mlp.strict_chunks(R,X)[0]
            problem=quadratic.prepare(np.c_[h_R,np.ones(len(X))],Y,weights,C,ctx.checked_mm)
            problem["radius"]=readout_radius
            solved,solver=quadratic.direct(problem,ctx.checked_mm,budget)
            solver["internal_196_coordinate_norm_certificate"]=solver.pop("certificate")
            solver["norm_scope"]="internal readout certificate only; final full delta separately uses original C_Q147 bound"
            report.update(readout_solver=solver,representation_scaling=scaling,
                          attempted_representation_parameters=R,readout_radius=readout_radius)
            if not solver["converged"]:
                report.update(valid=False,reason="DIRECT_READOUT_CERTIFICATE_STOP")
            else:
                rp=mlp.child_model(base,R)
                rp["network"]["w2"]=solved[:,:48].tolist();rp["network"]["b2"]=solved[:,48].tolist()
                P=copy.deepcopy(base);P["network"]["w2"]=solved[:,:48].tolist();P["network"]["b2"]=solved[:,48].tolist()
                params={"R":R,"P":mlp.pack(P),"RP":mlp.pack(rp)}
                allowed=representation_mask.copy();allowed[4128:]=True
                changed_counts={}
                for name,v in params.items():
                    exact_full_radius(v,base,radius)
                    changed=v.view(np.uint64)!=original.view(np.uint64)
                    if np.any(changed & ~allowed) or np.count_nonzero(changed)>368:
                        raise ArithmeticError("constructive edit escaped its exact coordinate support")
                    changed_counts[name]=int(np.count_nonzero(changed))
                new=mlp.unpack(R);actual_std=[]
                for unit in units:
                    z=X@new["w1"][unit]+new["b1"][unit]
                    actual_std.append(float(np.sqrt(np.sum(u*(z-u@z)**2))))
                report.update(representation_scaling=scaling,actual_preactivation_std=actual_std,
                    readout_radius=readout_radius,readout_solver=solver,reason="CONSTRUCTED",
                    actual_changed_coordinates=changed_counts)
    report["CPU_seconds"]=time.process_time()-started
    return params,report,dict(own_optimal_targets=Y,sample_weights=weights,
                              own_posterior=teacher_p),radius
