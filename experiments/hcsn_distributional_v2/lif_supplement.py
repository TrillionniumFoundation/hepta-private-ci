"""Separate matched LIF SNN supplement; never changes the content002 matrix.

The existing hard-forward LIF implementation and frozen optimizer/search are
used through process-local factory bindings. The registered single-worker
scheduler preserves all failed/completed work and drains on a stop request.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1 import training
from . import content_training
from .content_study import TASKS, evaluate
from .model import MatchedClassifier, build_model as original_factory


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
PARENT_PROTOCOL = PACKAGE / 'CONTENT002_PROTOCOL.json'
NEW_SOURCES = ('lif_supplement.py', 'lif_supplement_analysis.py')


def read_json(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path=Path(path)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
    temporary.replace(path)


def factory(name, input_dim, output_dim, width=32, depth=1, seed=0):
    if name=='lif_snn':
        return MatchedClassifier(name,input_dim,output_dim,width,depth,seed)
    return original_factory(name,input_dim,output_dim,width,depth,seed)


def source_map(parent):
    files=dict(parent['source_files_sha256'])
    for name in NEW_SOURCES:
        path=PACKAGE/name
        files[str(path.relative_to(ROOT))]=digest(path)
    return files


def verify_files(files):
    for relative,expected in files.items():
        if digest(ROOT/relative)!=expected:raise RuntimeError('Frozen source changed: '+relative)


def verify(protocol_path):
    protocol=read_json(protocol_path)
    verify_files(protocol['source_files_sha256'])
    if digest(ROOT/protocol['parent']['protocol'])!=protocol['parent']['protocol_sha256']:
        raise RuntimeError('Parent registration changed')
    if digest(ROOT/protocol['preflight']['path'])!=protocol['preflight']['sha256']:
        raise RuntimeError('Preflight identity changed')
    for record in protocol['data'].values():
        if digest(ROOT/record['path'])!=record['sha256']:raise RuntimeError('Registered data changed')
    return protocol


def lif_parameter_names(model):
    return [name for name,_ in model.named_parameters()
            if name.endswith(('.log_rate','.raw_threshold'))]


def preflight(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    parent=read_json(PARENT_PROTOCOL);files=source_map(parent);verify_files(files)
    started=time.process_time();rows=[]
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    for task in TASKS:
        record=parent['data'][task];path=ROOT/record['path']
        if digest(path)!=record['sha256']:raise RuntimeError('Training archive identity changed')
        access=[];train=training.load_split(path,'train',access)
        if train['x'].shape[-1]!=64:raise AssertionError('Registered common input dimension64 required')
        for seed in (9201,9202,9203):
            model=factory('lif_snn',64,record['output_dim'],seed=seed)
            reference=factory('distribution_free_dual',64,record['output_dim'],seed=seed)
            common={name:value.detach().clone() for name,value in model.state_dict().items()
                    if name.startswith(('frontend.','readout.'))}
            if not all(torch.equal(value,reference.state_dict()[name]) for name,value in common.items()):
                raise AssertionError('Common initialization differs')
            counts=model.counts();target=reference.counts()
            gap=abs(counts['backbone']-target['backbone'])/target['backbone']
            if gap>.03:raise AssertionError('Active backbone parameter gap exceeds3%')
            del reference
            names=lif_parameter_names(model)
            if len(names)!=2:raise AssertionError('One learned leak/threshold pair expected')
            parameters=dict(model.named_parameters())
            initial={name:parameters[name].detach().clone() for name in names}
            maximum={name:0. for name in names}
            spikes=[]
            handles=[block.register_forward_hook(lambda module,args,out:spikes.append(out.detach().clone()))
                     for block in model.backbone.blocks]
            optimizer=torch.optim.Adam(model.parameters(),lr=.001)
            generator=torch.Generator().manual_seed(seed+200003)
            updates=[]
            for update in range(2):
                ids=torch.randint(len(train['x']),(32,),generator=generator)
                optimizer.zero_grad(set_to_none=True)
                logits,aux=model(train['x'][ids],train['dt'][ids],return_sequence=True)
                loss=F.cross_entropy(logits.flatten(0,1),train['y'][ids].flatten(),ignore_index=-100)
                if not bool(torch.isfinite(loss)):raise AssertionError('Nonfinite preflight loss')
                loss.backward()
                gradients={}
                for name in names:
                    gradient=parameters[name].grad
                    if gradient is None or not bool(torch.isfinite(gradient).all()):
                        raise AssertionError('Missing/nonfinite LIF physical gradient')
                    gradients[name]=float(gradient.abs().max())
                    maximum[name]=max(maximum[name],gradients[name])
                torch.nn.utils.clip_grad_norm_(model.parameters(),2.)
                optimizer.step()
                updates.append(dict(step=update+1,loss=float(loss.detach()),physical_gradient_max=gradients,
                                    forward_spike_count=float(aux['event_count'])))
            for handle in handles:handle.remove()
            observed=torch.cat([p.flatten() for p in spikes])
            if not bool(((observed==0)|(observed==1)).all()) or not bool((observed==1).any()):
                raise AssertionError('LIF did not produce actual nonempty hard0/1 spikes')
            changes={name:float((parameters[name].detach()-initial[name]).abs().max()) for name in names}
            if not all(value>0 for value in maximum.values()) or not all(value>0 for value in changes.values()):
                raise AssertionError('LIF threshold/leak were not effectively learned')
            rows.append(dict(task=task,seed=seed,counts=counts,reference_counts=target,
                relative_backbone_gap=gap,common_initialization_equal=True,updates=updates,
                physical_parameter_max_changes=changes,physical_gradient_max=maximum,
                unique_forward_spike_values=observed.unique().tolist(),spike_count=float(observed.sum()),
                maximum_train_dt=float(train['dt'].max()),input_shape=list(train['x'].shape),
                access_log=access))
        del train
    # Exercise the new scheduler with a real failing child. Its process is
    # reaped by wait4; later jobs must remain unstarted. No model data is used.
    from unittest.mock import patch
    fixture=dict(source_files_sha256={},data={},jobs=[dict(task='probe',model='lif_snn',seed=i) for i in range(3)],
                 execution=dict(workers=1))
    dispatch=output/'dispatch_failure_probe';dispatch.mkdir()
    fixture_path=output/'dispatch_fixture.json';write_json(fixture_path,fixture)
    write_json(dispatch/'REGISTRATION.json',dict(protocol_sha256=digest(fixture_path)))
    original_popen=subprocess.Popen
    def child(command,**kwargs):
        return original_popen([sys.executable,'-c','raise SystemExit(7)'],**kwargs)
    with patch(__name__+'.verify',return_value=fixture),patch('subprocess.Popen',side_effect=child):
        aborted=batch(fixture_path,dispatch)
    if (aborted['status']!='aborted' or aborted['completed']!=1 or len(aborted['unstarted'])!=2
            or aborted['records'][0]['returncode']!=7 or aborted['complete_child_cpu_seconds']<=0):
        raise AssertionError('Single-worker abort/drain receipt contract failed')
    verify_files(files)
    result=dict(schema='hcsn-lif-supplement-preflight.v1',passed=True,train_only=True,
        source_files_sha256=files,parent_protocol_sha256=digest(PARENT_PROTOCOL),records=rows,
        scheduler_real_child_probe=dict(status=aborted['status'],started=aborted['completed'],
            unstarted=len(aborted['unstarted']),child_cpu_seconds=aborted['complete_child_cpu_seconds'],
            nested_in_enclosing_preflight_wait4=True),
        lif_contract=dict(forward='hard0/1 at membrane>=threshold',backward='fast-sigmoid surrogate slope5',
            leak='exp(-softplus(log_rate)*dt)',threshold='softplus(raw_threshold)+1e-4',
            reset='subtract spike.detach()*threshold',refractory='none in this traditional LIF comparator',
            cost='Dense PyTorch recurrent implementation; no neuromorphic or energy claim'),
        process_self_cpu_to_receipt=time.process_time(),body_self_cpu_seconds=time.process_time()-started)
    write_json(output/'RESULTS.json',result)
    print(json.dumps(dict(passed=True,task_seed_cases=len(rows),counts=rows[0]['counts'])),flush=True)
    return result


def register(protocol_path, output, preflight_path):
    protocol_path,output,preflight_path=Path(protocol_path),Path(output),Path(preflight_path)
    if protocol_path.exists() or output.exists():raise FileExistsError('New registration/output required')
    parent=read_json(PARENT_PROTOCOL);files=source_map(parent);verify_files(files)
    pre=read_json(preflight_path)
    if (not pre['passed'] or not pre['train_only'] or pre['source_files_sha256']!=files
            or pre['parent_protocol_sha256']!=digest(PARENT_PROTOCOL)):
        raise RuntimeError('A matching successful train-only preflight is required')
    jobs=[dict(task=task,model='lif_snn',seed=seed) for task in TASKS for seed in (9201,9202,9203)]
    random.Random(2026103001).shuffle(jobs)
    protocol=dict(schema='hcsn-lif-supplement-study.v1',study_id='lif_supplement001',
        registered_utc=datetime.now(timezone.utc).isoformat(),status_at_registration='No supplementary full search started',
        scope='Supplementary post-v1/content001/content002 registration on previously observed datasets; not fresh-test confirmation',
        parent=dict(protocol=str(PARENT_PROTOCOL.relative_to(ROOT)),protocol_sha256=digest(PARENT_PROTOCOL),
            results='experiments/hcsn_distributional_v2/results/content002',
            reused_model='distribution_free_dual',reused_searches=18,read_only_reuse=True,
            original_176_jobs_and_holm4_unchanged=True),
        preflight=dict(path=str(preflight_path.relative_to(ROOT)),sha256=digest(preflight_path)),
        source_files_sha256=files,data=parent['data'],jobs=jobs,
        optimization=parent['optimization'],parameter_matching=parent['parameter_matching'],
        lif_contract=pre['lif_contract'],statistics=dict(seeds=[9201,9202,9203],tasks=list(TASKS),
            unit='Within-task paired training seed; accuracy difference distribution_free_dual minus lif_snn',
            summary='Per-task raw three-seed pairs, mean/SD/range; descriptive only',
            new_significance_gate=False,new_holm_family=False,changes_to_original_gates=False),
        selection='Both LR complete, then minimum validation CE over15/30/60CPU checkpoints; heldout afterwards',
        cost=dict(full_worker='wait4 full child import/setup/twoLR/validation/checkpoint/heldout/identity',
            training_nested=True,reused_parent_searches='Report read-only parent search costs separately; never add them a second time to overall research cost',
            failures='Preserve and charge all started searches; affected contrast incomplete',energy_measured=False),
        execution=dict(workers=1,expected_searches=18,expected_lr_candidates=36,
            nominal_training_cpu_seconds=2160.,
            stop_policy='First failed worker or STOP_REQUESTED.json halts new dispatch; every active worker finishes and is reaped by wait4'))
    if protocol['optimization']['primary_cpu_checkpoints']!=[15.,30.,60.]:raise AssertionError('CPU gates changed')
    if protocol['optimization']['training_cpu_seconds_per_lr']!=60.:raise AssertionError('CPU budget changed')
    write_json(protocol_path,protocol);output.mkdir(parents=True,exist_ok=False)
    write_json(output/'REGISTRATION.json',dict(protocol_sha256=digest(protocol_path),jobs=18,
        registered_utc=protocol['registered_utc'],status='before_supplementary_full_training'))
    snapshot=output/'source';snapshot.mkdir()
    for relative in files:
        path=snapshot/relative;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,path)
    shutil.copyfile(protocol_path,output/'PROTOCOL.json')
    return protocol


def worker(protocol_path, output, task, seed):
    protocol=verify(protocol_path);identity=digest(protocol_path)
    job=dict(task=task,model='lif_snn',seed=seed)
    if job not in protocol['jobs']:raise ValueError('Unregistered LIF search')
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    saved=(training.build_model,training.evaluate,training.train_candidate,content_training.build_model)
    try:
        training.build_model=factory;content_training.build_model=factory
        training.evaluate=evaluate;training.train_candidate=content_training.train_candidate
        o=protocol['optimization']
        summary=training.run_search(ROOT/protocol['data'][task]['path'],'lif_snn',seed,output,
            cpu_seconds=o['training_cpu_seconds_per_lr'],width=o['width'],depth=o['depth'],
            batch_size=o['batch_size'],max_updates=o['max_updates'],learning_rates=o['learning_rates'])
    finally:
        training.build_model,training.evaluate,training.train_candidate,content_training.build_model=saved
    verify(protocol_path)
    if digest(protocol_path)!=identity:raise RuntimeError('Supplementary protocol changed')
    write_json(Path(output)/'IDENTITY.json',dict(job=job,protocol_sha256=identity,
        source_files_sha256=protocol['source_files_sha256'],dataset_sha256=protocol['data'][task]['sha256'],
        status=summary['status']))
    print(json.dumps(dict(job=job,status=summary['status'])),flush=True)


def batch(protocol_path, output):
    protocol=verify(protocol_path);protocol_path=Path(protocol_path).resolve();output=Path(output).resolve()
    registration=read_json(output/'REGISTRATION.json')
    if registration['protocol_sha256']!=digest(protocol_path):raise RuntimeError('Registration mismatch')
    if (output/'PROGRESS.json').exists() or (output/'runs').exists():raise FileExistsError('Existing execution evidence')
    (output/'runs').mkdir();(output/'process_logs').mkdir()
    begin=time.process_time();wall=time.perf_counter();pending=list(protocol['jobs']);active={};records=[]
    stopped=None;unstarted=[];stop_path=output/'STOP_REQUESTED.json'
    environment=os.environ.copy()
    for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):environment[key]='1'
    environment['PYTHONDONTWRITEBYTECODE']='1'
    while pending or active:
        if stop_path.exists() and stopped is None:
            stopped=dict(reason='operator_stop',request=read_json(stop_path),request_sha256=digest(stop_path))
            unstarted,pending=pending,[]
            write_json(output/'DRAINING.json',dict(stop=stopped,unstarted=unstarted,
                active_jobs=[r['job'] for r in active.values()],protocol_sha256=registration['protocol_sha256']))
        while pending and len(active)<protocol['execution']['workers']:
            if stop_path.exists():break
            job=pending.pop(0);key=f"{job['task']}__{job['model']}__{job['seed']}"
            destination=output/'runs'/key;log_path=output/'process_logs'/(key+'.log')
            command=[sys.executable,'-m','experiments.hcsn_distributional_v2.lif_supplement','worker',
                '--protocol',str(protocol_path),'--output',str(destination),'--task',job['task'],'--seed',str(job['seed'])]
            stream=log_path.open('w')
            process=subprocess.Popen(command,cwd=ROOT,env=environment,stdout=stream,stderr=subprocess.STDOUT)
            active[process.pid]=dict(process=process,stream=stream,job=job,output=destination,
                                    log_path=log_path,command=command,wall=time.perf_counter())
        finished=[]
        for pid,item in list(active.items()):
            got,status,usage=os.wait4(pid,os.WNOHANG)
            if not got:continue
            code=os.waitstatus_to_exitcode(status);item['process'].returncode=code;item['stream'].close()
            item['output'].mkdir(parents=True,exist_ok=True)
            receipt=dict(job=item['job'],command=item['command'],returncode=code,
                child_user_cpu_seconds=usage.ru_utime,child_system_cpu_seconds=usage.ru_stime,
                child_total_cpu_seconds=usage.ru_utime+usage.ru_stime,child_peak_rss_kib_linux=usage.ru_maxrss,
                wall_seconds=time.perf_counter()-item['wall'],protocol_sha256=registration['protocol_sha256'],
                stdout_sha256=digest(item['log_path']),output=str(item['output'].relative_to(output)),
                measurement='Linux wait4 complete isolated worker; candidate/training values are nested')
            write_json(item['output']/'EXECUTION.json',receipt);records.append(receipt);finished.append(pid)
            if code!=0 and stopped is None:
                stopped=dict(reason='worker_failure',job=item['job'],returncode=code);unstarted,pending=pending,[]
                write_json(output/'DRAINING.json',dict(stop=stopped,unstarted=unstarted,
                    active_jobs=[r['job'] for other,r in active.items() if other!=pid],
                    protocol_sha256=registration['protocol_sha256']))
            print(json.dumps(dict(completed=len(records),expected=len(protocol['jobs']),job=item['job'],returncode=code)),flush=True)
        for pid in finished:del active[pid]
        if finished:write_json(output/'PROGRESS.json',dict(protocol_sha256=registration['protocol_sha256'],records=records))
        if active:time.sleep(.05)
    verify(protocol_path)
    if digest(protocol_path)!=registration['protocol_sha256']:raise RuntimeError('Protocol changed during batch')
    success=stopped is None and len(records)==len(protocol['jobs']) and all(r['returncode']==0 for r in records)
    result=dict(schema='hcsn-lif-supplement-completion.v1',status='completed' if success else 'aborted',
        protocol_sha256=registration['protocol_sha256'],expected=len(protocol['jobs']),completed=len(records),
        failures=sum(r['returncode']!=0 for r in records),stop=stopped,unstarted=unstarted,records=records,
        complete_child_cpu_seconds=sum(r['child_total_cpu_seconds'] for r in records),
        coordinator_self_cpu_seconds=time.process_time()-begin,wall_seconds=time.perf_counter()-wall,
        completed_utc=datetime.now(timezone.utc).isoformat())
    write_json(output/('COMPLETE.json' if success else 'ABORTED.json'),result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('preflight','register','run','worker'))
    parser.add_argument('--protocol',type=Path,default=PACKAGE/'LIF_SUPPLEMENT001_PROTOCOL.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preflight',type=Path)
    parser.add_argument('--task',choices=TASKS);parser.add_argument('--seed',type=int)
    args=parser.parse_args()
    if args.action=='preflight':preflight(args.output)
    elif args.action=='register':
        p=register(args.protocol,args.output,args.preflight);print(json.dumps(p['execution']))
    elif args.action=='worker':worker(args.protocol,args.output,args.task,args.seed)
    else:
        result=batch(args.protocol,args.output);print(json.dumps({k:result[k] for k in ('status','completed','failures','complete_child_cpu_seconds')}))
        if result['status']!='completed':raise SystemExit(1)
