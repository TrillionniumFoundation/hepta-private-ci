"""Frozen integrity analyzer for the separate three-seed LIF SNN supplement."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from experiments.hcsn_free_boundary_v1 import training
from . import content_analysis
from .lif_supplement import ROOT, PACKAGE, digest, factory, read_json, verify, write_json


def completion(study, protocol):
    record=read_json(study/'COMPLETE.json')
    assert record['status']=='completed' and not record.get('unstarted'), 'complete study required'
    assert record['protocol_sha256']==protocol['_sha256'], 'completion identity'
    expected={(j['task'],j['model'],j['seed']) for j in protocol['jobs']}
    actual=[(r['job']['task'],r['job']['model'],r['job']['seed']) for r in record['records']]
    assert len(actual)==len(expected) and set(actual)==expected, 'complete unique job coverage'
    assert record['expected']==record['completed']==len(expected), 'complete counts'
    assert record['complete_child_cpu_seconds']==sum(r['child_total_cpu_seconds'] for r in record['records']), 'worker sum'
    for row in record['records']:
        job=row['job'];key=f"{job['task']}__{job['model']}__{job['seed']}"
        assert row==read_json(study/'runs'/key/'EXECUTION.json'), 'completion/worker receipt identity'
        assert row['child_total_cpu_seconds']==row['child_user_cpu_seconds']+row['child_system_cpu_seconds'], 'CPU components'
        assert row['returncode']==0, 'worker succeeded'
    return record


def lif_learning(study, job):
    folder=study/'runs'/f"{job['task']}__{job['model']}__{job['seed']}"
    summary=read_json(folder/'summary.json');rows=[]
    for candidate in summary['candidates']:
        directory=folder/candidate['directory']
        initial=content_analysis.arrays(directory/'initial.npz')
        selected=content_analysis.arrays(directory/candidate['best']['weights'])
        final=content_analysis.arrays(directory/candidate['checkpoints'][-1]['weights'])
        names=[name for name in initial if name.endswith(('.log_rate','.raw_threshold'))]
        assert len(names)==2, 'one LIF leak/threshold parameter pair'
        changes={name:dict(selected_max_abs_change=float(np.max(np.abs(selected[name]-initial[name]))),
            final_max_abs_change=float(np.max(np.abs(final[name]-initial[name]))),
            selected_changed_elements=int(np.count_nonzero(selected[name]!=initial[name])),
            elements=int(initial[name].size)) for name in names}
        assert all(v['selected_max_abs_change']>0 and v['final_max_abs_change']>0 for v in changes.values()), 'actual LIF leak/threshold learning'
        rows.append(dict(learning_rate=candidate['learning_rate'],changes=changes))
    return rows


def analyze(protocol_path, study, output):
    protocol=verify(protocol_path);protocol['_sha256']=digest(protocol_path)
    study,output=Path(study),Path(output)
    parent_path=ROOT/protocol['parent']['protocol'];parent=read_json(parent_path)
    parent['_sha256']=protocol['parent']['protocol_sha256'];parent_study=ROOT/protocol['parent']['results']
    assert digest(parent_path)==parent['_sha256'], 'parent registration'
    own_complete=completion(study,protocol);parent_complete=completion(parent_study,parent)
    assert protocol['optimization']==parent['optimization'], 'same CPU/selection protocol'
    assert protocol['data']==parent['data'], 'same task archives'
    output.mkdir(parents=True,exist_ok=False)
    started=time.process_time();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    data={}
    for task,record in protocol['data'].items():
        with np.load(ROOT/record['path'],allow_pickle=False) as archive:
            data[task]=dict(train_count=archive['train_y'].shape[0],input_dim=archive['train_x'].shape[-1],
                classes=record['output_dim'],labels={split:np.array(archive[f'{split}_y'],copy=True)
                    for split in ('test','ood') if f'{split}_y' in archive},
                replay_x=torch.as_tensor(np.array(archive['test_x'][:4],copy=True),dtype=torch.float32),
                replay_dt=torch.as_tensor(np.array(archive['test_dt'][:4],copy=True),dtype=torch.float32),
                lif_replay_x=torch.as_tensor(np.array(archive['test_x'][:128],copy=True),dtype=torch.float32),
                lif_replay_dt=torch.as_tensor(np.array(archive['test_dt'][:128],copy=True),dtype=torch.float32))
    old_factory=content_analysis.build_model;audits=[];pairs=[]
    try:
        content_analysis.build_model=factory
        for job in protocol['jobs']:
            reference=dict(task=job['task'],model=protocol['parent']['reused_model'],seed=job['seed'])
            assert reference in parent['jobs'], 'registered parent pair'
            record=dict(task=job['task'],seed=job['seed'],valid=True)
            for name,where,p,j in [('lif',study,protocol,job),('distribution',parent_study,parent,reference)]:
                try:
                    evidence=dict(data[j['task']])
                    if name=='lif':
                        # Match the original evaluation batch shape. Hard
                        # spikes can amplify different GEMM roundoff near zero;
                        # this audits128 samples without relaxing the tolerance.
                        evidence['replay_x']=evidence['lif_replay_x']
                        evidence['replay_dt']=evidence['lif_replay_dt']
                    audit=content_analysis.audit_run(where,p,j,evidence)
                    if name=='lif':audit['lif_physical_learning']=lif_learning(where,j)
                except Exception as error:
                    audit=dict(job=j,valid=False,error=f'{type(error).__name__}: {error}')
                audits.append(audit);record[name]=audit
                record['valid']=record['valid'] and audit['valid']
            if record['valid']:
                if record['lif']['shared_initialization_sha256']!=record['distribution']['shared_initialization_sha256']:
                    record['valid']=False;record['error']='Paired common frontend/readout initialization differs'
                else:
                    record['accuracy_differences']={split:
                        record['distribution']['predictions'][split]['accuracy']-record['lif']['predictions'][split]['accuracy']
                        for split in ('test','ood') if split in record['lif']['predictions'] and split in record['distribution']['predictions']}
            pairs.append(record)
    finally:
        content_analysis.build_model=old_factory
    table=[]
    for task in protocol['statistics']['tasks']:
        ordered=sorted((r for r in pairs if r['task']==task),key=lambda r:r['seed'])
        for split in ('test','ood'):
            available=split in data[task]['labels']
            valid=available and len(ordered)==3 and all(r['valid'] and split in r.get('accuracy_differences',{}) for r in ordered)
            row=dict(task=task,split=split,available=available,complete=valid,seeds=[r['seed'] for r in ordered])
            if valid:
                delta=[r['accuracy_differences'][split] for r in ordered]
                a=[r['distribution']['predictions'][split]['accuracy'] for r in ordered]
                b=[r['lif']['predictions'][split]['accuracy'] for r in ordered]
                row.update(distribution_accuracies=a,lif_accuracies=b,paired_accuracy_differences=delta,
                    distribution_mean=float(np.mean(a)),lif_mean=float(np.mean(b)),difference_mean=float(np.mean(delta)),
                    difference_sd=float(np.std(delta,ddof=1)),difference_range=[min(delta),max(delta)])
            table.append(row)
    selected_receipts={}
    for r in pairs:
        for name,where in [('lif',study),('distribution',parent_study)]:
            job=r[name]['job'];key=f"{job['task']}__{job['model']}__{job['seed']}"
            for artifact in ('EXECUTION.json','IDENTITY.json','summary.json','selection.json','selected.npz'):
                path=where/'runs'/key/artifact
                selected_receipts[str(path.relative_to(ROOT))]=digest(path) if path.is_file() else None
    result=dict(schema='hcsn-lif-supplement-analysis.v1',protocol_sha256=protocol['_sha256'],
        parent_protocol_sha256=parent['_sha256'],analysis_source_sha256=digest(__file__),
        status='passed' if all(r['valid'] for r in pairs) else 'integrity_failures',
        expected_pairs=18,valid_pairs=sum(r['valid'] for r in pairs),pair_audits=pairs,table=table,
        extra_lif_search_worker_cpu_seconds=own_complete['complete_child_cpu_seconds'],
        reused_distribution_search_worker_cpu_seconds=sum(r['distribution'].get('complete_child_cpu_seconds',0.) for r in pairs),
        reused_distribution_cost_additive=False,
        full_parent_study_worker_cpu_seconds_context=parent_complete['complete_child_cpu_seconds'],
        raw_artifact_sha256=selected_receipts,
        statistics_scope='Three paired training seeds per fixed task, descriptive raw differences/mean/SD/range. No new superiority gate, p-value or Holm family.',
        outcomes_previously_observed=True,fresh_test_confirmation=False,
        main_content002_registration_modified=False,
        selected_replay=dict(lif_samples=128,lif_batch_shape='same128 as original evaluator',
                            distribution_samples=4,max_absolute_logit_tolerance=5e-5),
        analysis_body_cpu_seconds=time.process_time()-started)
    verify(protocol_path)
    write_json(output/'ANALYSIS.json',result)
    lines=['# Traditional LIF SNN: separate matched supplement','',
        f"Integrity: {result['valid_pairs']}/18 pairs valid. The original176-search content002 study and its four-contrast Holm family are unchanged.",'',
        'This is a supplementary post-v1/content001/content002 comparison on the same previously observed datasets. It is not fresh-test confirmation. Each pair shares task archive, seed, frontend/readout initialization, nominal width32/depth1, matched active backbone parameters (within3%), both LR candidates and15/30/60 trainingCPU selection gates. Different CPU throughput permits different update counts; the actual paired minibatch prefix is audited.','',
        'The SNN uses the existing current-based recurrent LIF cell: hard0/1 forward spikes, slope5 fast-sigmoid surrogate backward, learned positive leak and threshold, and subtractive reset using a detached spike. The surrogate is not a derivative of the hard step. It has no explicit refractory phase, and its dense PyTorch implementation does not establish a neuromorphic energy advantage.','',
        '| Task | Split | Distribution mean | LIF mean | Paired difference pp | SD of paired differences pp |','|---|---|---:|---:|---:|---:|']
    for row in table:
        if not row['available']:continue
        if row['complete']:
            lines.append(f"| {row['task']} | {row['split']} | {100*row['distribution_mean']:.3f}% | {100*row['lif_mean']:.3f}% | {100*row['difference_mean']:.3f} | {100*row['difference_sd']:.3f} |")
        else:lines.append(f"| {row['task']} | {row['split']} | incomplete | | | |")
    lines+=['',f"New complete LIF search-worker CPU: {own_complete['complete_child_cpu_seconds']:.6f}s. The reused18 distribution searches cost {result['reused_distribution_search_worker_cpu_seconds']:.6f}s within content002; this is context, not an additional research charge. Training CPU, validation and candidate details are nested within worker receipts. The enclosing scheduler, preflight and analysis receipts are separate records, with containment stated in each.",'',
        'Every candidate/checkpoint hash, selection order, recorded prediction coordinate/label/CE, complete minibatch prefix and paired initialization is checked using the frozen audit_run with a process-local LIF factory. Selected LIF inference replays the first128test samples using the original evaluation batch shape, since hard spikes can amplify batch-shape-dependent floating-point roundoff near threshold; the tolerance remains5e-5. The reused distribution checkpoint retains its original first4sample replay. LIF leak/threshold changes are additionally checked at each LR-selected and final checkpoint. Raw three-seed differences are in ANALYSIS.json. No SNN result is inserted into the original Holm family or used to alter the original gates.']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    write_json(output/'EXECUTION.json',dict(analysis_self_cpu_seconds_to_receipt=time.process_time(),
        body_self_cpu_seconds=time.process_time()-started,analysis_sha256=digest(output/'ANALYSIS.json'),
        report_sha256=digest(output/'REPORT.md'),scope='Analyzer self-CPU through receipt; separate from all training/search processes'))
    print(json.dumps({k:result[k] for k in ('status','expected_pairs','valid_pairs','extra_lif_search_worker_cpu_seconds')}))
    if result['status']!='passed':raise SystemExit(1)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',type=Path,default=PACKAGE/'LIF_SUPPLEMENT001_PROTOCOL.json')
    parser.add_argument('--study',type=Path,default=PACKAGE/'results/lif_supplement001')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();analyze(args.protocol,args.study,args.output)
