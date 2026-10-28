"""Train-only pretrained observers, development selection, untouched calibration.

This preserves the original 60% empirical adequacy requirement and reports source
uncertainty, unseen classes and majority controls separately. A point gate is not
a distribution-free future guarantee. Qualification data are never loaded here.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .data_sources import digest, save
from .data_v3_contract import validate_receipt
from .profile_contract import cpu_seconds
from .semantic_backbones import PINS
from .semantic_tsm import TSM_FILE, TSM_SHA

SPEC = {
    "schema":"hepta.closure.semantic-observer-protocol.v1",
    "features":{"action":"two preregistered candidates: S3D 1424 features and Something-Something V2 TSM 2222 features, actual video only",
                "sound":"frozen PANN MobileNetV2 1024 embedding + 527 probabilities, actual audio only"},
    "training_role":"observer_train","development_role":"development",
    "execution_recovery":{"checkpoint_every":64,"state":"model, AdamW, sampler RNG, global dropout RNG, past candidate states and source/protocol guard"},
    "calibration_role":"observer_calibration","qualification_access":False,
    "normalization":"source-uniform train mean/std, std floor 0.01, feature clamp [-8,8]",
    "ridge_lambdas":[0.1,1.0,10.0,100.0],
    "mlp":{"hidden":128,"dropout":0.15,"adamw_lr":0.001,"weight_decay":0.01,
           "steps":1024,"batch":64,"checkpoint_steps":[256,1024],"seed":6317},
    "selection":"maximum source-uniform development top-1 accuracy; first registered candidate wins ties",
    "classes":"all published frozen ontology IDs including training-unseen IDs; never filter by held-out performance",
    "adequacy":{"action_accuracy":0.6,"sound_accuracy":0.6,
                "both_modalities_must_exceed_own_training_majority_accuracy":True},
    "uncertainty":"exact binomial interval when one event per independent video; source-bootstrap paired contrasts; no participant-independence claim",
    "no_output_reference_shortcut":"generated output features must be recomputed from its actual physical media, never copied from this target feature cache",
    "weights":{**PINS,TSM_FILE:TSM_SHA},
}


def load_role(root, role):
    plan=json.loads((root/"SOURCE_PROTOCOL.json").read_text())
    plan_copy=dict(plan);protocol_sha=plan_copy.pop("protocol_sha256")
    if digest(plan_copy)!=protocol_sha:
        raise ValueError("Source manifest identity changed")
    feature_protocol=json.loads((root/"FEATURE_PROTOCOL.json").read_text())
    if feature_protocol["source_protocol_sha256"]!=protocol_sha:
        raise ValueError("Feature/source allocation identity mismatch")
    for name,pin in feature_protocol["source_hashes"].items():
        if digest((Path(__file__).parent/name).read_bytes())!=pin:
            raise ValueError("Frozen feature implementation changed")
    if feature_protocol["weights"]!={**PINS,TSM_FILE:TSM_SHA}:
        raise ValueError("Pretrained feature pins changed")
    expected={r["source_id"]:r for r in plan["selected"] if r["role"]==role}
    path=root/"prepared"/role
    directories={p.name:p for p in path.iterdir() if p.is_dir()}
    if set(directories)!=set(expected):
        raise ValueError("Prepared source IDs differ from the exact frozen role")
    records=[];features={"action_s3d":[],"action_tsm":[],"sound":[]};source_hashes=set()
    for source_id,directory in sorted(directories.items()):
        receipt=json.loads((directory/"RECEIPT.json").read_text())
        source=expected[source_id]
        if plan["schema"]=="hepta.closure.natural-sources.v3":
            # Original execution hashes remain in the original receipt. Only
            # the allocation binding changed; never relabel old extraction.
            validate_receipt(root,plan,source,receipt)
        elif (receipt["role"]!=role or receipt["source_id"]!=source_id or
                receipt["source_protocol_sha256"]!=protocol_sha or
                receipt["feature_protocol_sha256"]!=digest(feature_protocol) or
                receipt["source_hashes"]!=feature_protocol["source_hashes"] or
                receipt["original_source_bytes"]!=source["source_bytes"] or
                receipt["original_member"]!=source["member"]):
            raise ValueError("Prepared source provenance mismatch")
        if receipt["original_source_sha256"] in source_hashes:
            raise ValueError("Duplicated original source bytes cannot count as independent sources")
        source_hashes.add(receipt["original_source_sha256"])
        for name,pin in receipt["retained_files"].items():
            if digest((directory/name).read_bytes())!=pin:
                raise ValueError("Retained source/feature bytes changed")
        events=source["events"][:source["retained_event_count"]]
        if len(receipt["events"])!=len(events):raise ValueError("Frozen event count changed")
        for i,(row,event) in enumerate(zip(receipt["events"],events)):
            if (row["source_id"]!=source_id or row["role"]!=role or
                    row["source_sha256"]!=receipt["original_source_sha256"] or
                    row["event_id"]!=f"{source_id}-closure-{i}" or
                    any(row[key]!=value for key,value in event.items())):
                raise ValueError("Event labels/windows differ from frozen annotation identities")
        data=np.load(directory/"FEATURES.npz")
        for key,array in (("action_s3d","video"),("action_tsm","video_tsm"),("sound","audio")):
            if len(data[array])!=len(events) or not np.isfinite(data[array]).all():
                raise ValueError("Invalid actual-media feature arrays")
            features[key].extend(data[array])
        records.extend(receipt["events"])
    return records,{key:np.asarray(value,np.float64) for key,value in features.items()}


def source_weights(rows):
    counts=Counter(row["source_id"] for row in rows)
    return np.asarray([1/(len(counts)*counts[row["source_id"]]) for row in rows])


def accuracy(prediction, rows, kind):
    correct=np.asarray(prediction)==np.asarray([row[kind+"_id"] for row in rows])
    weights=source_weights(rows)
    counts=Counter(row[kind+"_id"] for row in rows)
    recalls={str(label):float(correct[[r[kind+"_id"]==label for r in rows]].mean()) for label in counts}
    return {"source_uniform_accuracy":float(correct@weights),"event_accuracy":float(correct.mean()),
            "sources":len({r["source_id"] for r in rows}),"events":len(rows),
            "class_recalls":recalls,"macro_recall_present_classes":float(np.mean(list(recalls.values()))),
            "present_class_count":len(counts),"correct_by_event":correct.tolist()}


def mlp(state):
    model=nn.Sequential(nn.Linear(state["feature_count"],128),nn.SiLU(),nn.Dropout(.15),
                        nn.Linear(128,len(state["classes"])))
    if "state_dict" in state:
        model.load_state_dict(state["state_dict"],strict=True)
    return model


def predict(state, x):
    features=np.clip((x-state["mean"])/state["scale"],-8,8)
    if state["kind"]=="ridge":
        scores=np.c_[features,np.ones(len(x))]@state["weights"]
    else:
        model=mlp(state).eval()
        with torch.no_grad():scores=model(torch.tensor(features,dtype=torch.float32)).numpy()
    return np.asarray(state["classes"])[scores.argmax(1)]


def train(root, output):
    if list((root/"prepared/observer_calibration").glob("*")):
        raise ValueError("Observer calibration sources were already accessed; preserve the existing frozen study")
    output.mkdir(parents=True,exist_ok=True)
    source=json.loads((root/"SOURCE_PROTOCOL.json").read_text())
    protocol={**SPEC,"source_protocol_sha256":source["protocol_sha256"],
              "implementation_sha256":digest(Path(__file__).read_bytes()),
              "backbone_source_sha256":digest((Path(__file__).parent/"semantic_backbones.py").read_bytes())}
    if (output/"OBSERVER_FREEZE.json").exists():
        raise FileExistsError("A completed observer study must not be overwritten")
    if (output/"PROTOCOL.json").exists():
        if json.loads((output/"PROTOCOL.json").read_text())!=protocol:
            raise ValueError("Resumed observer protocol changed")
    else:
        save(output/"PROTOCOL.json",protocol)
    train_rows,train_x=load_role(root,"observer_train")
    dev_rows,dev_x=load_role(root,"development")
    if len({r['source_id'] for r in train_rows})!=source['roles']['observer_train'] or len(dev_rows)!=source['roles']['development']:
        raise ValueError("Incomplete preregistered observer training/development cohort")
    if ({r['source_id'] for r in train_rows}&{r['source_id'] for r in dev_rows} or
            {r['source_sha256'] for r in train_rows}&{r['source_sha256'] for r in dev_rows}):
        raise ValueError('Original source ID/byte leakage')
    torch.set_num_threads(2)
    weights=source_weights(train_rows)
    candidates={};selected={};recoveries={};start=time.monotonic()
    for kind in ("action","sound"):
        families=("action_s3d","action_tsm") if kind=="action" else ("sound",)
        classes=sorted(map(int,source['ontology'][kind]))
        lookup={label:i for i,label in enumerate(classes)}
        y=np.asarray([lookup[r[kind+'_id']] for r in train_rows])
        studies=[];states=[]
        for family in families:
            original_x=train_x[family]
            mean=weights@original_x
            scale=np.maximum(np.sqrt(weights@((original_x-mean)**2)),.01)
            x=np.clip((original_x-mean)/scale,-8,8)
            base={'mean':mean,'scale':scale,'classes':classes,'feature_count':x.shape[1],
                  'feature_family':family}
            X=np.c_[x,np.ones(len(x))]
            w=weights*len(weights);target=np.eye(len(classes))[y]
            gram=X.T@(X*w[:,None]);right=X.T@(target*w[:,None])
            for regularization in SPEC['ridge_lambdas']:
                penalty=np.eye(len(gram))*regularization;penalty[-1,-1]=1e-8
                state={**base,'kind':'ridge','weights':np.linalg.solve(gram+penalty,right)}
                score=accuracy(predict(state,dev_x[family]),dev_rows,kind)
                studies.append({'name':f'{family}_ridge_{regularization:g}','development':score});states.append(state)
            del gram,right
            torch.manual_seed(SPEC['mlp']['seed'])
            model=mlp(base)
            optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
            xx=torch.tensor(x,dtype=torch.float32);yy=torch.tensor(y,dtype=torch.long)
            probabilities=torch.tensor(weights,dtype=torch.float64)
            rng=torch.Generator().manual_seed(SPEC['mlp']['seed']+1)
            recovery_path=output/(family+"_RECOVERY.pt")
            recovery_guard=digest({'protocol':digest(protocol),'family':family,
                'normalized_train_features':digest(np.ascontiguousarray(x).tobytes()),
                'source_weights':weights.tolist(),'train_labels':y.tolist(),
                'development_event_ids':[row['event_id'] for row in dev_rows]})
            start_step=0;past_states=[];past_studies=[]
            if recovery_path.exists():
                recovered=torch.load(recovery_path,map_location='cpu',weights_only=True)
                if recovered['guard']!=recovery_guard:
                    raise ValueError('Observer recovery source/protocol identity changed')
                model.load_state_dict(recovered['model'],strict=True)
                optimizer.load_state_dict(recovered['optimizer'])
                rng.set_state(recovered['sampler_rng'])
                torch.set_rng_state(recovered['global_rng'])
                start_step=recovered['step'];past_studies=recovered['past_studies']
                past_states=[{key:(value.numpy() if key in ('mean','scale') else value)
                              for key,value in item.items()} for item in recovered['past_states']]
                studies.extend(past_studies);states.extend(past_states)
            recoveries[family]={'resumed_from_step':start_step,'recovery_guard':recovery_guard}
            for step in range(start_step+1,SPEC['mlp']['steps']+1):
                ids=torch.multinomial(probabilities,64,replacement=True,generator=rng)
                loss=F.cross_entropy(model(xx[ids]),yy[ids])
                optimizer.zero_grad();loss.backward();optimizer.step()
                if step in SPEC['mlp']['checkpoint_steps']:
                    state={**base,'kind':'mlp','state_dict':{k:v.detach().clone() for k,v in model.state_dict().items()}}
                    score=accuracy(predict(state,dev_x[family]),dev_rows,kind)
                    study={'name':f'{family}_mlp_{step}','development':score}
                    studies.append(study);states.append(state)
                    past_studies.append(study);past_states.append(state)
                if step%64==0:
                    recovered={'schema':'hepta.closure.observer-recovery.v1','guard':recovery_guard,
                        'step':step,'model':model.state_dict(),'optimizer':optimizer.state_dict(),
                        'sampler_rng':rng.get_state(),'global_rng':torch.get_rng_state(),
                        'past_studies':past_studies,
                        'past_states':[{key:(torch.from_numpy(value) if isinstance(value,np.ndarray) else value)
                                        for key,value in item.items()} for item in past_states]}
                    temporary=recovery_path.with_suffix('.pending')
                    torch.save(recovered,temporary);temporary.replace(recovery_path)
                    print(json.dumps({'observer_family':family,'step':step,'resumed_from_step':start_step}),flush=True)
        best=max(range(len(studies)),key=lambda i:studies[i]['development']['source_uniform_accuracy'])
        state=states[best]
        label_mass=np.zeros(len(classes))
        for index,label in enumerate(y):label_mass[label]+=weights[index]
        majority=classes[int(label_mass.argmax())]
        state['training_majority_label']=majority
        path=output/(kind+'_observer.pt')
        frozen={k:torch.from_numpy(v) if isinstance(v,np.ndarray) else v for k,v in state.items()}
        torch.save(frozen,path)
        selected[kind]={'selected_candidate':studies[best]['name'],'checkpoint_file':path.name,
                        'checkpoint_sha256':digest(path.read_bytes()),
                        'development':studies[best]['development'],
                        'training_majority_label':majority,
                        'development_majority':accuracy([majority]*len(dev_rows),dev_rows,kind),
                        'training_present_classes':sorted({r[kind+'_id'] for r in train_rows}),
                        'all_ontology_classes':classes}
        candidates[kind]=studies
        print(json.dumps({'observer':kind,'selected':studies[best]['name'],
                          'development_accuracy':studies[best]['development']['source_uniform_accuracy']}),flush=True)
    freeze={'schema':'hepta.closure.semantic-observer-freeze.v1',
            'source_protocol_sha256':source['protocol_sha256'],'protocol_sha256':digest(protocol),
            'selected':selected,'candidates':candidates,
            'consumed_training_development_source_sha256':sorted({r['source_sha256'] for r in train_rows+dev_rows}),
            'feature_protocol_sha256':digest(json.loads((root/'FEATURE_PROTOCOL.json').read_text())),
            'recoverable_execution':recoveries,
            'new_calibration_access':False,
            'new_qualification_access':False,'wall_seconds':time.monotonic()-start,
            'development_viable':all(selected[k]['development']['source_uniform_accuracy']>=.6 and selected[k]['development']['source_uniform_accuracy']>selected[k]['development_majority']['source_uniform_accuracy'] for k in selected),
            'implementation_sha256':digest(Path(__file__).read_bytes())}
    save(output/'OBSERVER_FREEZE.json',freeze)
    return freeze


def load_state(path):
    state=torch.load(path,map_location='cpu',weights_only=True)
    return {k:v.numpy() if isinstance(v,torch.Tensor) else v for k,v in state.items()}


def calibrate(root, output):
    from scipy.stats import beta
    freeze=json.loads((output/'OBSERVER_FREEZE.json').read_text())
    source=json.loads((root/'SOURCE_PROTOCOL.json').read_text())
    protocol=json.loads((output/'PROTOCOL.json').read_text())
    expected_protocol={**SPEC,'source_protocol_sha256':source['protocol_sha256'],
        'implementation_sha256':digest(Path(__file__).read_bytes()),
        'backbone_source_sha256':digest((Path(__file__).parent/'semantic_backbones.py').read_bytes())}
    if protocol!=expected_protocol or digest(protocol)!=freeze['protocol_sha256'] or freeze['implementation_sha256']!=expected_protocol['implementation_sha256']:
        raise ValueError('Frozen observer semantics, thresholds or implementation changed')
    if freeze['source_protocol_sha256']!=source['protocol_sha256']:
        raise ValueError('Observer/source binding changed')
    if digest(json.loads((root/'FEATURE_PROTOCOL.json').read_text()))!=freeze['feature_protocol_sha256']:
        raise ValueError('Observer feature protocol changed')
    freeze_file_sha=digest((output/'OBSERVER_FREEZE.json').read_bytes())
    for path in (root/'prepared/observer_calibration').glob('*/RECEIPT.json'):
        if json.loads(path.read_text())['heldout_freeze_sha256']!=freeze_file_sha:
            raise ValueError('Observer calibration source was opened under another observer freeze')
    rows,x=load_role(root,'observer_calibration')
    if {r['source_sha256'] for r in rows}&set(freeze['consumed_training_development_source_sha256']):
        raise ValueError('Calibration original bytes overlap prior fitting/selection sources')
    if len(rows)!=64 or len({r['source_id'] for r in rows})!=64:
        raise ValueError('Complete independent observer calibration source cohort required')
    result={'schema':'hepta.closure.semantic-calibration.v1','observer_freeze_sha256':digest(freeze),
            'source_protocol_sha256':source['protocol_sha256'],'qualification_access':False,
            'thresholds_unchanged':SPEC['adequacy'],'observers':{}}
    for kind in ('action','sound'):
        path=output/freeze['selected'][kind]['checkpoint_file']
        if digest(path.read_bytes())!=freeze['selected'][kind]['checkpoint_sha256']:
            raise ValueError('Selected observer checkpoint changed')
        state=load_state(path)
        prediction=predict(state,x[state['feature_family']]);report=accuracy(prediction,rows,kind)
        success=sum(report['correct_by_event']);n=len(rows)
        report['source_binomial_interval_95']=[float(beta.ppf(.025,success,n-success+1)) if success else 0.,
            float(beta.ppf(.975,success+1,n-success)) if success<n else 1.]
        majority=accuracy([state['training_majority_label']]*n,rows,kind)
        report['majority_control']=majority
        report['passed_empirical_adequacy']=(report['source_uniform_accuracy']>=.6 and
             report['source_uniform_accuracy']>majority['source_uniform_accuracy'])
        report['unseen_training_class_fraction']=float(np.mean([r[kind+'_id'] not in
            freeze['selected'][kind]['training_present_classes'] for r in rows]))
        report['predictions']=prediction.tolist()
        result['observers'][kind]=report
    result['adequate']=all(r['passed_empirical_adequacy'] for r in result['observers'].values())
    result['future_population_accuracy_certified']=False
    result['policy_or_model_changed_after_calibration']=False
    save(output/'OBSERVER_CALIBRATION.json',result)
    print(json.dumps({'adequate':result['adequate'],'accuracy':{k:v['source_uniform_accuracy'] for k,v in result['observers'].items()}}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--calibrate',action='store_true')
    args=parser.parse_args()
    started=time.monotonic();entry_cpu=cpu_seconds()
    (calibrate if args.calibrate else train)(args.assets,args.output)
    save(args.output/f"RESOURCE_{'calibration' if args.calibrate else 'fit'}_{time.time_ns()}.json",
         {'total_process_self_children_CPU_seconds':cpu_seconds(),
          'module_import_CPU_seconds_before_dispatch':entry_cpu,
          'wall_seconds_after_imports':time.monotonic()-started,
          'includes_feature_validation_training_selection_and_reporting_before_this_receipt':True})
