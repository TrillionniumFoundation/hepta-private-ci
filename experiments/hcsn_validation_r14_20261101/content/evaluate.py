"""Fresh heldout content factorial with actual causal READ/STOP execution."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_validation_r12_20261031.content.models import FAMILIES, Model
from .data import TASKS, DOMAINS, dataset
from .engine import ValueController, all_logits, policy_values, replay, online_rollout, READ_FEE, TIME_FEE, model_hash
from .study import MODES, SEEDS, configure, sha, write, tensors, verified


def one(output, task, seed, mode):
    protocol = verified(output)
    freeze = json.loads((output/'CANDIDATE_FREEZE.json').read_text())
    if freeze['protocol_sha256']!=sha(output/'PROTOCOL.json'):
        raise ValueError('Candidate freeze does not belong to this protocol')
    name = f'{task}_s{seed}_{mode}'
    fit = output/'fits'/name
    entry = freeze['candidates']['fits/'+name]
    if sha(fit/'selected.pt') != entry['sha256']:
        raise ValueError('Selected group changed')
    payload = torch.load(fit/'selected.pt', map_location='cpu', weights_only=False)
    if payload['protocol_sha256']!=sha(output/'PROTOCOL.json'):
        raise ValueError('Selected payload does not belong to this protocol')
    dest = output/'heldout'/name
    dest.mkdir(parents=True, exist_ok=False)
    controller = ValueController()
    controller.load_state_dict(payload['controller']); controller.eval()
    common_controller_hash = model_hash(controller)
    results = []
    with torch.no_grad():
        for family in FAMILIES:
            saved = payload['models'][family]
            model = Model(**saved['config'])
            model.load_state_dict(saved['state']); model.eval()
            for domain in DOMAINS[task]:
                data = dataset(task, 'test', domain)
                x, dt, y = tensors(data)
                # Actual value actor: future frames are passed only after READ.
                cpu, wall = time.process_time(), time.perf_counter()
                actual = online_rollout(model, controller, x, dt, y)
                value_cpu, value_wall = time.process_time()-cpu, time.perf_counter()-wall
                # Ordinary light execution can legally read all then run once.
                cpu, wall = time.process_time(), time.perf_counter()
                full = model(x, dt)
                light_cpu, light_wall = time.process_time()-cpu, time.perf_counter()-wall
                light_accuracy = (full.argmax(-1) == y).float()
                light_fee = READ_FEE*dt.shape[1] + TIME_FEE*dt.sum(1)
                logits = all_logits(model, x, dt)
                q = policy_values(controller, logits, dt)
                diagnostic = replay(logits, q, dt, y)
                path_mismatch = int((actual['reads'] != diagnostic['read_count']).sum())
                prediction_mismatch = int((actual['prediction'] != diagnostic['terminal_prediction']).sum())
                raw_name = f'{family}__{domain}.npz'
                np.savez_compressed(dest/raw_name, ids=data['ids'], labels=data['y'],
                    group=data['group'], input_sha256=data['sha256'],
                    value_utility=actual['utility'].numpy(), light_utility=(light_accuracy-light_fee).numpy(),
                    value_accuracy=actual['accuracy'].numpy(), light_accuracy=light_accuracy.numpy(),
                    reads=actual['reads'].numpy(), fees=actual['fee'].numpy(),
                    initial_stop=diagnostic['initial_stop'].numpy(),
                    score_margin=diagnostic['score_margin'].numpy(),
                    realized_margin=diagnostic['realized_margin'].numpy(), occupied=diagnostic['occupied'].numpy())
                results.append(dict(task=task,seed=seed,mode=mode,family=family,domain=domain,
                    value_utility=float(actual['utility'].mean()), light_utility=float((light_accuracy-light_fee).mean()),
                    value_accuracy=float(actual['accuracy'].mean()),light_accuracy=float(light_accuracy.mean()),
                    initial_stop=float(diagnostic['initial_stop'].mean()),
                    initial_selected=float((actual['reads']==0).float().mean()),read_count=float(actual['reads'].float().mean()),
                    actual_fee=float(actual['fee'].mean()), value_cpu_seconds=value_cpu,value_wall_seconds=value_wall,
                    light_cpu_seconds=light_cpu,light_wall_seconds=light_wall,
                    process_cost_note='Online phases are nested in the enclosing scientific worker receipt; no addition of nested times.',
                    actor_model_calls=actual['model_calls'],processed_prefix_tokens=actual['processed_prefix_tokens'],
                    root_value_target_mse=float(diagnostic['root_mse']),occupied_value_target_mse=float(diagnostic['occupied_mse']),
                    occupied_sample_hindsight_gap=float(diagnostic['occupied_hindsight_gap']),
                    conditional_expected_regret=None,
                    regret_note='One realized future per prefix: hindsight gap is not conditional expected regret. True conditional audit is the separate value study.',
                    offline_online_read_mismatches=path_mismatch,offline_online_prediction_mismatches=prediction_mismatch,
                    data_sha256=data['sha256'],raw=raw_name,raw_sha256=sha(dest/raw_name),
                    controller_sha256=common_controller_hash,backend_sha256=model_hash(model),
                    energy_joules=None,energy_status='unavailable',parameters=sum(p.numel() for p in model.parameters())))
    write(dest/'SUMMARY.json',dict(rows=results, selected=entry, controller_sha256=common_controller_hash,
         source_freeze_sha256=sha(output/'SOURCE_FREEZE.json'),candidate_freeze_sha256=sha(output/'CANDIDATE_FREEZE.json')))
    if any(r['offline_online_read_mismatches'] or r['offline_online_prediction_mismatches'] for r in results):
        write(dest/'FAILED.json',dict(reason='Offline Q-pi policy differs from actual online actor; raw results retained'))
        raise AssertionError('Causal actor alignment gate failed')
    return dict(group=name,rows=len(results),path_mismatches=sum(r['offline_online_read_mismatches'] for r in results))


def summarize(output):
    protocol = verified(output)
    groups = []
    allrows = []
    for task in TASKS:
        for mode in MODES:
            for seed in SEEDS:
                name=f'{task}_s{seed}_{mode}'
                folder=output/'heldout'/name
                if (folder/'FAILED.json').exists():
                    raise ValueError('Heldout attempt contains a retained failure: '+name)
                result=json.loads((folder/'SUMMARY.json').read_text())
                if result['source_freeze_sha256']!=sha(output/'SOURCE_FREEZE.json') or result['candidate_freeze_sha256']!=sha(output/'CANDIDATE_FREEZE.json'):
                    raise ValueError('Heldout source/candidate identity changed: '+name)
                receipt=json.loads((output/'receipts'/('evaluate_'+name+'.json')).read_text())
                if receipt['exit_code']!=0:
                    raise ValueError('Heldout scientific worker did not complete: '+name)
                for row in result['rows']:
                    if row['offline_online_read_mismatches'] or row['offline_online_prediction_mismatches']:
                        raise ValueError('Heldout causal actor alignment failed: '+name)
                    if sha(folder/row['raw']) != row['raw_sha256']:
                        raise ValueError('Raw outcome changed')
                allrows.extend(result['rows'])
                by={(r['family'],r['domain']):r for r in result['rows']}
                for domain in DOMAINS[task]:
                    d=by['analytic',domain]
                    for comparison,ordinary in [('matched','ordinary_dual'),('strong_selected',result['selected']['ordinary'])]:
                        b=by[ordinary,domain]
                        a,B,c,D=b['light_utility'],b['value_utility'],d['light_utility'],d['value_utility']
                        groups.append(dict(task=task,mode=mode,seed=seed,domain=domain,comparison=comparison,ordinary=ordinary,
                            A=a,B=B,C=c,D=D,B_A=B-a,D_C=D-c,C_A=c-a,D_B=D-B,interaction=(D-c)-(B-a),
                            D_B_quality=d['value_accuracy']-b['value_accuracy'],
                            online_cpu_ratio=d['value_cpu_seconds']/b['value_cpu_seconds']))
    averages=[]
    keys=sorted(set((r['task'],r['mode'],r['domain'],r['comparison']) for r in groups))
    for task,mode,domain,comparison in keys:
        subset=[r for r in groups if (r['task'],r['mode'],r['domain'],r['comparison'])==(task,mode,domain,comparison)]
        averages.append(dict(task=task,mode=mode,domain=domain,comparison=comparison,
            ordinary=[r['ordinary'] for r in subset],
            **{k:float(np.mean([r[k] for r in subset])) for k in ['A','B','C','D','B_A','D_C','C_A','D_B','interaction','D_B_quality','online_cpu_ratio']},
            paired_seed_D_B=[r['D_B'] for r in subset],n_fit_seeds=len(subset)))
    write(output/'RESULTS.json', dict(rows=allrows,contrasts=groups,means=averages,
        scientific_acceptance='descriptive_only_three_inherited_fit_seeds',
        integrated_full_distribution=False,production_activation=False,
        source_freeze_sha256=sha(output/'SOURCE_FREEZE.json'),candidate_freeze_sha256=sha(output/'CANDIDATE_FREEZE.json')))
    lines=['# R14：完整内容后端冻结／共同训练与控制四格','',
        '所有结果来自新固定数据种子。每个 task/seed/mode 的八个核心使用完全相同的一组价值控制器权重；轻量与价值两臂共享同一份内容权重。',
        '冻结模式将 encoder、core、readout 全部冻结；共同训练模式继续更新这些部件和控制器。原始48份内容模型在两模式配对复用，三种拟合种子不被样本数或域数扩增。','',
        '解析模型仍为继承的固定 renewal 活动门，本轮没有把数值线的完整条件分布偷偷算作该模型状态。各域均执行真正的 READ/STOP，初始 STOP 开放。','',
        '|任务|模式|对照|A|B|C|D|D−B|D−B各种子|','|---|---|---|---:|---:|---:|---:|---:|---|']
    for r in averages:
        if r['domain']=='iid':
            lines.append(f"|{r['task']}|{r['mode']}|{r['comparison']}|{r['A']:.6f}|{r['B']:.6f}|{r['C']:.6f}|{r['D']:.6f}|{r['D_B']:+.6f}|{r['paired_seed_D_B']}|")
    lines += ['', '完整域和五种效应见 RESULTS.json，所有逐样本结果保留为 NPZ。',
        '在线成本为实际执行的前缀重算方案；light 读取全部后只需一次合法完整 forward。该实现没有增量缓存，不能据此推断最优部署开销。',
        '内容线的 realized hindsight gap 不是条件期望 regret；没有把单条未来当作条件期望。独立 value 实验负责完整条件后续枚举。',
        '三种旧拟合种子上的继续训练和新数据评估提供描述性结果，不构成八次全新训练或通用基础核心准入。物理能耗未测。']
    (output/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    return dict(rows=len(allrows),contrasts=len(groups),means=len(averages),iid=[r for r in averages if r['domain']=='iid'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['one','summarize'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--task',choices=list(TASKS))
    parser.add_argument('--mode',choices=list(MODES))
    parser.add_argument('--seed',type=int)
    args=parser.parse_args();configure()
    result=one(args.output,args.task,args.seed,args.mode) if args.command=='one' else summarize(args.output)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__': main()
