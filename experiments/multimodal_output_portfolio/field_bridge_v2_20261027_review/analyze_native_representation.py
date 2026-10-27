"""Read-only, preregistered train/dev diagnosis; never open test/retention data."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..field_bridge_20261027.controls import choose, history_features
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge, Q24, prepare_request

HERE = Path(__file__).resolve().parent
PROTOCOL = HERE / "DEVELOPMENT_NORMALIZATION_PROTOCOL.json"
CHANNELS = ["left_text_confidence", "right_text_confidence", "left_image_confidence", "right_image_confidence",
            "left_disagreement", "right_disagreement", "missing_fraction", "pixel_entropy"]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rank_report(train, values):
    mean, scale = train.mean(0), np.maximum(train.std(0), 1e-6)
    result = {}
    for name, x in (("centered", values-values.mean(0)), ("train_standardized", (values-mean)/scale)):
        x = x-x.mean(0)
        s = np.linalg.svd(x, compute_uv=False)
        tolerance = max(x.shape)*np.finfo(float).eps*s[0]
        result[name] = dict(rank=int(np.sum(s>tolerance)), tolerance=float(tolerance), singular_values=s.tolist(),
                            participation_rank=float(np.sum(s*s)**2/max(np.sum(s**4), 1e-300)))
    result["exact_constant_columns"] = np.flatnonzero(np.ptp(values, axis=0)==0).tolist()
    return result


def collision_report(features, original, returns):
    groups = {}
    for index, row in enumerate(features):
        groups.setdefault(row.astype("<f8").tobytes(), []).append(index)
    duplicates = [indices for indices in groups.values() if len(indices)>1]
    differing_inputs = differing_best_actions = 0
    for indices in duplicates:
        differing_inputs += len({original[i].astype("<f8").tobytes() for i in indices})>1
        differing_best_actions += len(set(np.argmax(returns[indices], axis=1).tolist()))>1
    oracle = float(returns.max(1).sum())
    state_oracle = sum(float(returns[indices].sum(0).max()) for indices in groups.values())
    return dict(unique_states=len(groups), duplicated_state_groups=len(duplicates),
                rows_in_duplicated_groups=sum(map(len, duplicates)), groups_with_distinct_original_histories=differing_inputs,
                groups_with_distinct_best_actions=differing_best_actions,
                empirical_state_conditioned_oracle_regret=max((oracle-state_oracle)/len(returns), 0.))


def native(bridge, first, second, prefix):
    matrix = np.empty((len(first), 40))
    first_active, second_active, eligible = [], [], []
    native_ns = 0
    for index, (a, b) in enumerate(zip(first, second, strict=True)):
        request = prepare_request(case=f"{prefix}:{index}",
            readback_digest=hashlib.sha256(np.stack((a,b)).astype("<f8").tobytes()).hexdigest(),
            features_q24=np.rint((2*a-1)*Q24).astype(np.int64).tolist(),
            next_features_q24=np.rint((2*b-1)*Q24).astype(np.int64).tolist(), reset_before_readout=False)
        output, _ = bridge.execute(request)
        first_active.append(np.asarray(output.ticks[0].activation)>0)
        second_active.append(np.asarray(output.ticks[1].activation)>0)
        eligible.append(np.asarray(output.ticks[1].eligibility)!=0)
        matrix[index] = np.r_[np.asarray(output.ticks[1].activation), np.asarray(output.ticks[1].eligibility)]/Q24
        native_ns += sum(t.native_ns for t in output.ticks)
    return matrix, dict(first_activation_fraction=np.mean(first_active,axis=0).tolist(),
                         second_activation_fraction=np.mean(second_active,axis=0).tolist(),
                         eligibility_nonzero_fraction=np.mean(eligible,axis=0).tolist(), native_ns=native_ns)


def heads(train_x, train_return, dev_x, dev_return, conditions):
    mean, scale = train_x.mean(0), np.maximum(train_x.std(0),1e-6)
    z = np.column_stack(((train_x-mean)/scale,np.ones(len(train_x))))
    gram, cross = z.T@z,z.T@train_return
    penalty = np.diag(np.r_[np.ones(40),0.])
    records=[]
    for alpha in (.0001,.01,1.):
        coefficient=np.linalg.solve(gram+alpha*penalty,cross)
        model=dict(schema="hepta.field-bridge.ridge-readout.v1", coefficient=coefficient.tolist(),
                   normalizer=dict(mean=mean.tolist(),scale=scale.tolist()),chosen_alpha=alpha)
        train_actions,dev_actions=choose(model,train_x),choose(model,dev_x)
        train_values=train_return[np.arange(len(train_x)),train_actions]
        dev_values=dev_return[np.arange(len(dev_x)),dev_actions]
        record=dict(alpha=alpha,model=model,train_value=float(train_values.mean()),dev_value=float(dev_values.mean()),
                    train_oracle_regret=float(train_return.max(1).mean()-train_values.mean()),
                    dev_oracle_regret=float(dev_return.max(1).mean()-dev_values.mean()),
                    train_actions=np.bincount(train_actions,minlength=5).tolist(),
                    dev_actions=np.bincount(dev_actions,minlength=5).tolist(),
                    development_by_condition={name:float(values.mean()) for name,values in
                        zip(conditions,np.split(dev_values,len(conditions)),strict=True)})
        records.append(record)
    return records


def input_statistics(x):
    return dict(mean=x.mean(0).tolist(),std=x.std(0).tolist(),minimum=x.min(0).tolist(),maximum=x.max(0).tolist(),
                fraction_signed_drive_abs_ge_point99=(np.abs(2*x-1)>=.99).mean(0).tolist())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs",type=Path,required=True)
    parser.add_argument("--ffi",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists(): raise ValueError("Refusing to overwrite exploratory diagnosis")
    protocol=json.loads(PROTOCOL.read_text())
    source_hash=sha(__file__)
    allowed=json.loads((args.inputs/'INPUTS.json').read_text())
    conditions=json.loads((HERE.parent/'field_bridge_20261027/PROTOCOL.json').read_text())["training_conditions"]
    bridge=NativeFastBridge(args.ffi,"bfad6ca9d91d958296fa47c7f8ace4414b7ddf659e079ae5394c37bd104ceac3")
    results={}
    for seed in (17,29,43):
        path=args.inputs/f"{seed}-frozen-banks.npz"
        expected=next(r for r in allowed["extracted_only"] if r["member"]==f"run/runtime/{seed}-frozen/banks.npz")
        if sha(path)!=expected["sha256"]: raise ValueError("Archived bank changed")
        with np.load(path,allow_pickle=False) as data:
            if set(data.files)!=set(protocol["input_keys"]): raise ValueError("Unexpected bank keys")
            bank={key:data[key].copy() for key in data.files}
        train_joint=np.concatenate((bank['train_x0'],bank['train_x1']))
        mean,scale=train_joint.mean(0),np.maximum(train_joint.std(0),1e-6)
        train_return,dev_return=bank['train_returns'],bank['dev_returns']
        fixed=int(train_return.mean(0).argmax())
        baseline=dict(training_best_fixed_action=fixed,development_best_fixed_action=int(dev_return.mean(0).argmax()))
        for split,returns in (("train",train_return),("development",dev_return)):
            baseline[split]=dict(stop=float(returns[:,0].mean()),training_selected_fixed=float(returns[:,fixed].mean()),
                                 best_fixed_on_this_split=float(returns.mean(0).max()),row_oracle=float(returns.max(1).mean()),
                                 all_fixed_values=returns.mean(0).tolist())
        transforms=[]
        for grid in protocol['grid']:
            transformed={}
            for split in ('train','dev'):
                for event in ('x0','x1'):
                    raw=bank[f'{split}_{event}']
                    transformed[f'{split}_{event}']=raw if grid['k'] is None else (np.clip((raw-mean)/(scale*grid['k']),-1,1)+1)/2
            row=dict(transform=grid,representations={},normalizer=dict(mean=mean.tolist(),scale=scale.tolist()),
                     normalized_input_train=input_statistics(np.concatenate((transformed['train_x0'],transformed['train_x1']))))
            for representation in ('native','history'):
                started=time.perf_counter_ns()
                stats={}
                matrices={}
                for split in ('train','dev'):
                    a,b=transformed[f'{split}_x0'],transformed[f'{split}_x1']
                    if representation=='native':
                        matrices[split],stats[split]=native(bridge,a,b,f'diagnostic-{seed}-{grid["name"]}-{split}')
                    else:
                        matrices[split]=history_features(a,b)
                features_elapsed=time.perf_counter_ns()-started
                started=time.perf_counter_ns()
                candidates=heads(matrices['train'],train_return,matrices['dev'],dev_return,conditions)
                fit_elapsed=time.perf_counter_ns()-started
                row['representations'][representation]=dict(candidates=candidates,native_activity=stats,
                    train_rank=rank_report(matrices['train'],matrices['train']),
                    dev_rank=rank_report(matrices['train'],matrices['dev']),
                    train_collisions=collision_report(matrices['train'],np.c_[bank['train_x0'],bank['train_x1']],train_return),
                    dev_collisions=collision_report(matrices['dev'],np.c_[bank['dev_x0'],bank['dev_x1']],dev_return),
                    feature_wall_ns=features_elapsed,three_head_fit_wall_ns=fit_elapsed,
                    train_feature_sha256=hashlib.sha256(matrices['train'].astype('<f8').tobytes()).hexdigest(),
                    dev_feature_sha256=hashlib.sha256(matrices['dev'].astype('<f8').tobytes()).hexdigest())
            transforms.append(row)
        selected={}
        for representation in ('native','history'):
            all_candidates=[dict(transform=t['transform']['name'],**c) for t in transforms for c in t['representations'][representation]['candidates']]
            selected[representation]=max(all_candidates,key=lambda r:r['dev_value'])
        results[str(seed)]=dict(input_sha256=sha(path),baselines=baseline,transforms=transforms,selected=selected,
            raw_input_train=input_statistics(train_joint),raw_input_dev=input_statistics(np.concatenate((bank['dev_x0'],bank['dev_x1']))))
        print(json.dumps({'seed':seed,'selected':{k:{n:r[n] for n in ('transform','alpha','dev_value','dev_oracle_regret')} for k,r in selected.items()},'baseline':baseline}),flush=True)
    a=np.asarray([[1.,.9,.6,.7,0.,0.,0.,.4]])
    b=a.copy();b[0,2]=.75
    x,_=native(bridge,a,a,'structural-collision-a');y,_=native(bridge,b,b,'structural-collision-b')
    assert np.array_equal(x,y) and not np.array_equal(history_features(a,a),history_features(b,b))
    witness=dict(first_history=[a[0].tolist(),a[0].tolist()],second_history=[b[0].tolist(),b[0].tolist()],
                  identical_native_state=x[0].tolist(),native_state_equal=True,raw_history_equal=False,
                  different_channel='left_image_confidence, .60 versus .75 at both events',
                  interpretation='readout noninjectivity witness only; no fabricated task outcomes or utility gap')
    report=dict(schema='hepta.field-bridge-v2.native-representation-diagnostic.v1',protocol_sha256=sha(PROTOCOL),
                source_sha256=source_hash,inputs=allowed,library_sha256=bridge.binary_sha256,conditions=conditions,
                public_channel_order=CHANNELS,results=results,structural_collision=witness,
                test_retention_accessed=False,new_model_outputs_generated=False,formal_efficacy_claim=False)
    if sha(__file__)!=source_hash: raise RuntimeError('Analysis source changed during execution')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')


if __name__=='__main__': main()
