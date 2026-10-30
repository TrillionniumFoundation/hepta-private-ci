"""Five-priority report extraction after actual primary and supplement closure.

No fitting, model execution, endpoint scoring, bootstrap, new metric or threshold.
The original gates are reported unchanged; completion does not imply benefit.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import math
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(SOURCE))
from operational.parameter_field_recovery06.postseal import prepare_plan as layout
from operational.parameter_field_recovery06.postseal import prepare_pins
from operational.parameter_field_recovery06.producer_adapter import ProducerAdapter
from operational.parameter_field_recovery06.postseal.prepare_plan import RAW, OPS, WORK, EPISODE, need, descriptor, verify, read, bound, write

OBSERVERS=('reward','audit')
B_EFFECTS=('ordinary-frozen task','field-ordinary task','field-history task','full-state-field task',
    'ordinary-frozen clean','field-frozen clean','full-state-frozen clean','history-frozen clean',
    'fixed-taper-field task (secondary)','fixed-taper-frozen clean (secondary)')
C_EFFECTS=('interaction task','dual field increment task','ordinary field increment task',
    'dual-field minus ordinary-field task','ordinary-baseline minus warmstart clean',
    'ordinary-field minus warmstart clean','dual-baseline minus warmstart clean','dual-field minus warmstart clean')
OUTPUTS={'GATE.json','BANK_SUMMARY.json','EQUAL_DYNAMICS_GROUPS.jsonl','SUCCESSOR_DIFFERENCES.jsonl',
    'GATED_CALIBRATION.json','GATED_CALIBRATION_ROWS.jsonl','W_SHARED_ACTION_REGRET.json','INTEGRITY_ISSUES.json','INPUTS.json'}
MODES=('field12','full_current_state','history6')
SEEDS=(17,29,43)


def _without_time(value,key):
    return {k:v for k,v in value.items() if k!=key}


def _arguments(argv):
    need(argv[:3]==[layout.PYTHON,'-B',str(layout.OWN/'run_supplement.py')],'Wrong registered supplement entrypoint')
    result,index={},3
    while index<len(argv):
        flag=argv[index]
        need(flag.startswith('--') and flag not in result,'Malformed or duplicated supplement flag')
        if flag=='--execute-post-seal':
            result[flag]=True
            index+=1
        else:
            need(index+1<len(argv),'Incomplete supplement flag')
            result[flag]=argv[index+1]
            index+=2
    return SimpleNamespace(**{k[2:].replace('-','_'):v for k,v in result.items()})


def open_gate(pins_item,wait4_item):
    """Metadata only until the original 30/26-seal producer-aware gate admits."""
    pins=bound(pins_item)
    need(pins.get('schema')=='hepta.execution06.root-postseal-arguments.1'
         and pins_item['path']==str(WORK/'control/POSTSEAL_ARGUMENTS.json'),'Wrong postseal argument receipt')
    verify(pins['preparation_code'])
    audit,expected=prepare_pins.collect_primary(pins['pipeline_config'],pins['plan'])
    need(_without_time({k:v for k,v in pins.items() if k!='metadata_audit'},'at_utc')==_without_time(expected,'at_utc'),
         'Prepared arguments differ from actual primary/producer evidence')
    stored_audit=bound(pins['metadata_audit'])
    need(_without_time(stored_audit,'at_utc')==_without_time(audit,'at_utc'),'Primary/17-ACK audit differs')
    supplement=Path(pins['output'])
    need(supplement==WORK/'supplement' and not (supplement/'FAILED.json').exists(),'Supplement failure or wrong directory')
    completion_item=descriptor(supplement/'COMPLETE.json')
    completion=bound(completion_item)
    need(completion.get('schema')=='hepta.fullstudy.postseal-supplement.2' and completion.get('complete') is True
         and completion.get('execution_episode')==EPISODE and completion.get('plan')==pins['plan']
         and completion.get('scientific_admission_criteria_changed') is False
         and completion.get('new_independent_samples')==0,'No complete unchanged registered supplement')
    outputs={}
    for row in completion['outputs']:
        need(set(row)=={'path','bytes','sha256'} and row['path'] in OUTPUTS and row['path'] not in outputs,'Unexpected or duplicate supplement output')
        outputs[row['path']]=verify({**row,'path':str(supplement/row['path'])})
    need(set(outputs)==OUTPUTS,'Incomplete supplement output population')
    producer=bound(pins['producer_config'])
    factory=ProducerAdapter(producer['producer_map'],producer['import_receipt'],producer['fresh_registration']).for_postseal(
        importlib.import_module('supplements.parameter_field_fullstudy_20261030.postseal_supplement'))
    inputs=factory.Inputs()
    plan,store,protocol,current_gate=factory.gate(_arguments(pins['argv']),inputs,WORK/'review')
    # All scientific seal bytes, original sources and producer identities passed.
    saved_gate=bound(outputs['GATE.json'])
    need(saved_gate==completion['gate'] and _without_time(saved_gate,'admitted_at')==_without_time(current_gate,'admitted_at'),
         'Supplement gate differs from current exact gate')
    stability=bound(outputs['INPUTS.json'])
    need(stability.get('all_consumed_bytes_sha_verified') is True and stability.get('metadata_stable_at_end') is True
         and stability.get('raw_inputs_modified') is False,'Supplement input stability missing')
    for item in stability['inputs']:
        verify({k:item[k] for k in ('path','bytes','sha256')})
    issues=bound(outputs['INTEGRITY_ISSUES.json'])
    issue_count=issues['issue_count']
    need(type(issue_count) is int and issue_count>=0 and issue_count==len(issues['issues'])==completion['integrity_issue_count']
         and issues.get('any_issue_precludes_unqualified_interpretation') is True,'Supplement integrity disposition differs')
    expected_exit=3 if issue_count else 0
    need(completion['status']==('COMPLETE_WITH_INTEGRITY_ISSUES' if issue_count else 'COMPLETE_DESCRIPTIVE_SUPPLEMENT'),
         'Supplement completion status contradicts issues')
    measured=bound(wait4_item)
    need(wait4_item['path']==str(OPS/'root_steps/postseal_supplement_01/WAIT4.json')
         and not Path(wait4_item['path']).with_name('FAILED.json').exists()
         and measured.get('schema')=='hepta.execution04.root-engineering-wait4.1'
         and measured.get('complete') is True and measured['child']['exit_code']==expected_exit
         and measured['command_success'] is (expected_exit==0),'Actual measured supplement exit differs')
    intent=bound(measured['intent'])
    need(intent.get('schema')=='hepta.execution04.root-engineering-intent.1'
         and intent.get('argv')==pins['argv'] and intent.get('stdin') is None
         and intent.get('cwd')==str(OPS/'empty_cwd') and intent.get('automatic_retry') is False,
         'Measured supplement command or cwd differs')
    verify(measured['stdout'])
    verify(measured['stderr'])
    return {'pins':pins,'plan':plan,'store':store,'inputs':inputs,'outputs':outputs,'issues':issues,
        'completion':completion,'completion_item':completion_item,'wait4_item':wait4_item,'measured':measured,
        'pins_item':pins_item,'gate':saved_gate}


def global_inactive(result,spec,manifest,read_paths):
    """The original exact 12-field-path/72-decision predicate, no efficacy claim."""
    need(result['status']=='COMPLETE' and result['efficacy_artifacts_opened'] is True,'Aggregate is incomplete')
    candidates=[row for row in result['five_priority_findings'] if row['priority']==1]
    need(len(candidates)==1,'Missing/duplicate priority1')
    mechanisms=candidates[0]['paths']['A']
    need(len(mechanisms)==48,'A aggregate population differs')
    field=[row for row in mechanisms if row['method']=='field12']
    expected={(seed,schedule) for seed in SEEDS for schedule in range(6000,6004)}
    need(len(field)==12 and {(r['seed'],r['schedule_id']) for r in field}==expected,'Incomplete A field denominator')
    counterparts={(r['seed'],r['schedule_id']):r for r in field}
    need(spec['stages']['A']['status']=='COMPLETE','A report-input stage is incomplete')
    runs=spec['stages']['A']['runs']
    need(len(runs)==3 and {r['seed'] for r in runs}==set(SEEDS),'A run population differs')
    actual,sources=[],[]
    for run in runs:
        seed,item=run['seed'],run['paths']
        target=RAW/f'stage_A/seed-{seed}/paths/PATHS.json'
        need(item['path']==str(target),'Wrong A PATHS location')
        entry=manifest['logical_paths'][target.relative_to(RAW).as_posix()]
        need(all(item[k]==entry[k] for k in ('bytes','sha256')),'A PATHS is outside the final manifest')
        paths=read_paths(item)
        need(paths.get('complete') is True and paths.get('training_complete') is True
             and paths.get('phase')=='A' and paths.get('seed')==seed,'A PATHS seal differs')
        population={(schedule,mode) for schedule in range(6000,6004) for mode in ('ordinary',*MODES)}
        need(len(paths['paths'])==16 and {(r['schedule_id'],r['method']) for r in paths['paths']}==population
             and all(r['seed']==seed for r in paths['paths']),'A actual paths population differs')
        sources.append(item)
        for row in paths['paths']:
            if row['method']!='field12':
                continue
            trace=row['trace']
            need(len(trace)==6 and [t['decision'] for t in trace]==list(range(6))
                 and all(type(t['choice']['override']) is bool for t in trace),'A decision trace incomplete')
            overrides=sum(t['choice']['override'] for t in trace)
            accepted=sum(bool(t['choice']['override'] and t['transaction']['accepted']) for t in trace)
            equal=row['terminal_reference_tail_state_equal']
            other=counterparts[(seed,row['schedule_id'])]
            need(type(equal) is bool and overrides==row['overrides']==other['overrides']
                 and accepted==row['accepted_overrides']==other['accepted_overrides']
                 and equal==other['same_baseline_terminal_complete_state'],'A trace and aggregate mechanism conflict')
            actual.append({'seed':seed,'schedule_id':row['schedule_id'],'decisions':6,'overrides':overrides,
                'accepted_overrides':accepted,'same_baseline_terminal_complete_state':equal})
    need(len(actual)==12 and sum(r['decisions'] for r in actual)==72
         and {(r['seed'],r['schedule_id']) for r in actual}==expected,'Incomplete global denominator')
    overrides=sum(r['overrides'] for r in actual)
    equal=sum(r['same_baseline_terminal_complete_state'] for r in actual)
    return {'schema':'hepta.execution06.A-inactive-global.1','complete':True,'field_paths':12,'decisions':72,
        'overrides':overrides,'accepted_overrides':sum(r['accepted_overrides'] for r in actual),
        'same_baseline_terminal_complete_state_count':equal,'A_registered_inactive_predicate':overrides==0 and equal==12,
        'registered_rule':'All12field paths,72decisions,zero field overrides,and12same-guard baseline terminal identities',
        'predicate_false_does_not_establish_activity_or_efficacy':True,'rows':sorted(actual,key=lambda r:(r['seed'],r['schedule_id'])),
        'raw_path_inputs':sources,'new_training_scoring_refitting':False}


def _effects(analysis,names,seeds):
    need(analysis['formal_family']==list(names) and set(analysis['effects'])==set(names)
         and analysis['seeds']==list(seeds) and analysis['observers']==list(OBSERVERS),'Formal effect population differs')
    stats=analysis['statistics']
    tail=.05/(2*len(names))
    need(stats['draws']==8000 and stats['family_size_per_observer']==len(names)
         and stats['quantiles']==[tail,1-tail],'Registered inference family differs')
    for effect in analysis['effects'].values():
        need(set(effect['point'])==set(effect['ci'])==set(OBSERVERS)
             and set(effect['per_seed'])=={str(s) for s in seeds},'Missing observer or paired seed effect')
        values=[*effect['point'].values(),*[v for row in effect['ci'].values() for v in row],
                *[v for row in effect['per_seed'].values() for v in row.values()]]
        need(all(type(v) in (float,int) and math.isfinite(v) for v in values)
             and all(len(effect['ci'][o])==2 and effect['ci'][o][0]<=effect['ci'][o][1] for o in OBSERVERS)
             and all(set(row)==set(OBSERVERS) for row in effect['per_seed'].values()),'Malformed effect interval or value')


def _jsonl(item):
    verify(item)
    rows=[]
    with Path(item['path']).open() as stream:
        for line in stream:
            need(len(line)<=2*1024**2 and line.strip(),'Invalid bounded supplement JSONL row')
            rows.append(json.loads(line))
    return rows


def compile_review(result,supplement,inactive,issues,contracts):
    """Select existing results and fixed scope statements; never revise a gate."""
    need(result['status']=='COMPLETE' and result['efficacy_artifacts_opened'] is True,'Incomplete aggregate')
    rows=result['five_priority_findings']
    need(len(rows)==5 and {r['priority'] for r in rows}==set(range(1,6)),'Five-priority result population differs')
    findings={row['priority']:row for row in rows}
    for phase,count in (('A',48),('B',240),('C',32)):
        need(len(findings[1]['paths'][phase])==count,'Path population differs: '+phase)
    need(all(r['parameter_optimizer_trace_available'] is False and r['first_parameter_optimizer_divergence_clock'] is None
             for r in findings[1]['paths']['C']),'Frozen C component-resolution contract changed')
    b,c=result['formal_analyses']['B'],result['formal_analyses']['C']
    _effects(b,B_EFFECTS,SEEDS)
    _effects(c,C_EFFECTS,tuple(range(801,809)))
    need(findings[3]['B_effects']==b['effects'] and findings[4]['B_thresholds']==b['statistical_thresholds']
         and findings[5]['C_effects']==c['effects'] and findings[5]['C_thresholds']==c['statistical_thresholds'],
         'Priority findings disagree with the original formal analyses')
    cal=supplement['GATED_CALIBRATION.json']
    cal_rows=supplement['GATED_CALIBRATION_ROWS.jsonl']
    expected_parents={f'schedule-6003-{prefix}-step-{step}' for prefix in ('baseline','balanced') for step in range(0,288,48)}
    need(cal['registered_parent_slots']==36 and cal['head_mode_rows']==108 and cal['new_independent_samples']==0
         and len(cal_rows)==108 and {(r['seed'],r['mode'],r['parent']) for r in cal_rows}==
             {(seed,mode,parent) for seed in SEEDS for mode in MODES for parent in expected_parents},
         '108 dependent calibration rows /36 parent slots differ')
    summaries=cal['models_and_modes']
    need(len(summaries)==9 and {(r['seed'],r['mode']) for r in summaries}=={(s,m) for s in SEEDS for m in MODES}
         and all(r['calibration_rows']==12 and r['calibration_rows_dependent_and_used_to_choose_tau'] is True
                 and r['new_independent_samples']==0 and r['certificate'] is False for r in summaries),
         'Calibration dependence or no-certificate disclosure differs')
    all_parents={f'schedule-{schedule}-{prefix}-step-{step}' for schedule in range(6000,6004)
                 for prefix in ('baseline','balanced') for step in range(0,288,48)}
    equal=supplement['EQUAL_DYNAMICS_GROUPS.jsonl']
    successor=supplement['SUCCESSOR_DIFFERENCES.jsonl']
    need(len(equal)==144 and {(r['seed'],r['parent']) for r in equal}=={(s,p) for s in SEEDS for p in all_parents}
         and len(successor)==576 and {(r['seed'],r['parent'],r['action']) for r in successor}==
             {(s,p,a) for s in SEEDS for p in all_parents for a in range(4)},'Supplement parent/action population differs')
    witness=supplement['W_SHARED_ACTION_REGRET.json']['records']
    need(len(witness)==3 and {r['seed'] for r in witness}==set(SEEDS)
         and all(r['constructed_off_policy'] is True and r['reachable_state_guarantee'] is False for r in witness),
         'Witness scope differs')
    costs=result['actual_costs']
    prior=result['prior_attempt_costs']
    need(prior['pre_execution04_gradient_microsteps_lower_bound']==182096
         and prior['gradient_microsteps_known_lower_bound']==214160
         and costs['all_attempts_gradient_microsteps_known_lower_bound']==557968
         and prior['historical_evidence_tiers']['execution04_A29_literal_failure_lower_bound']==14784
         and prior['historical_evidence_tiers']['execution05_A29_literal_failure_lower_bound']==17280
         and prior['execution05_cost_plan']['a29_failure']['costs']['optimizer_steps']==15984
         and prior['execution05_cost_plan']['actual_outer_wait4_missing'] is True
         and prior['execution05_cost_plan']['whole_execution05_cpu_total_or_upper_bound_known'] is False
         and costs['nonoverlapping_cost_ledger']['execution05_measured_disjoint_cpu_seconds_lower_bound']==1555.961190367
         and costs['nonoverlapping_cost_ledger']['execution05_imported_A17_new_scientific_work']==0
         and costs['nonoverlapping_cost_ledger']['whole_campaign_cpu_total_or_upper_bound_known'] is False
         and costs['nonoverlapping_cost_ledger']['a17_current_scientific_rows']==1
         and costs['nonoverlapping_cost_ledger']['a17_failed_increment_rows']==0,'Execution06 one-time imported/historical cost accounting missing')
    need(result['original_1GiB_2GiB_reserve_contract_passed'] is False
         and result['historical_exact_regression_gate'].startswith('FAIL'),'Original resource/history limitations were rewritten')
    extra={1:{'successor_summary':supplement['BANK_SUMMARY.json'],'A_global':inactive},
           2:{'gated_calibration':cal,'gated_calibration_rows':cal_rows,'A_head_scope_only':True,'C_gated_calibration_not_recomputed':True},
           3:{'B_effects':{name:b['effects'][name] for name in ('field-history task','full-state-field task')},'constructed_witness':result['constructed_witness'],'W_shared_action_regret':witness},
           4:{'formal_B':b,'actual_costs':costs,'prior_attempt_costs':prior,'original_gate_does_not_include_taper_or_total_cost':True},
           5:{'formal_C':c,'positive_interaction_can_mean_less_harm':True,'original_gate_does_not_require_positive_dual_simple_effect':True}}
    scopes={row['priority']:row for row in contracts['FIELD_MAP.json']['priorities']}
    return {'schema':'hepta.execution06.five-priority-review.1','execution_episode':EPISODE,'complete':True,
        'status':'REVIEW_COMPLETE_WITH_INTEGRITY_ISSUES' if issues['issue_count'] else 'REVIEW_COMPLETE',
        'scientific_positive_conclusion_automatically_assigned':False,'original_statistical_gates_redefined':False,
        'new_experiments_metrics_thresholds_or_analysis_family':False,'new_independent_samples':0,
        'integrity_issues':issues,'unqualified_interpretation_blocked':bool(issues['issue_count']),
        'priorities':[{'priority':i,'question':scopes[i]['question'],'existing_finding':findings[i],
                       'existing_supplement_or_formal_outputs':extra[i],'scope_and_interpretation':scopes[i]} for i in range(1,6)],
        'C_resolution_scope':contracts['C_SCOPE.json'],'original_resource_contract_passed':False,
        'historical_exact_regression_gate':result['historical_exact_regression_gate'],
        'terminal_persistence_and_publication_not_inferred':True,'review_own_future_wait4_not_yet_available':True}


def _effects_table(analysis):
    lines=['| 原登记差值方向 | Observer | Point | 原 CI | 每个配对 seed/model |','| --- | --- | ---: | --- | --- |']
    for name in analysis['formal_family']:
        row=analysis['effects'][name]
        for observer in OBSERVERS:
            per=', '.join(str(seed)+': '+repr(row['per_seed'][str(seed)][observer]) for seed in analysis['seeds'])
            lines.append('| '+name+' | '+observer+' | '+repr(row['point'][observer])+' | '+repr(row['ci'][observer])+' | '+per+' |')
    return '\n'.join(lines)


def render(review):
    by={row['priority']:row for row in review['priorities']}
    b=by[4]['existing_supplement_or_formal_outputs']['formal_B']
    c=by[5]['existing_supplement_or_formal_outputs']['formal_C']
    lines=['# Execution06：五项问题的实际结果审查','',
        '审查状态：**'+review['status']+'**。完整执行、证据完整性、原统计门、活动和成本分别报告；本审查不自动赋予正向科学结论。','',
        'A17 为 execution04 原字节导入，在当前逻辑研究中计一次；A29 的 execution04、execution05 两次失败分别计成本，本轮是整个 job 重做。',
        '', '完整性问题数：'+str(review['integrity_issues']['issue_count'])+'。存在任何问题时，禁止无条件科学解释。','']
    titles={1:'合法后继与实际活动',2:'Baseline 对齐标签与误差尺度',3:'Field 遗漏的决策信息',4:'Ordinary、轻量控制及净收益',5:'Hepta 的额外适配与交互'}
    for number in range(1,6):
        row=by[number]
        lines += ['## P'+str(number)+'：'+titles[number],'',row['scope_and_interpretation']['interpretation'] if 'interpretation' in row['scope_and_interpretation'] else row['scope_and_interpretation']['disposition_template'],'']
        if number==1:
            inactive=row['existing_supplement_or_formal_outputs']['A_global']
            lines += ['完整 A field 分母：12 条路径、72 次决策；overrides='+str(inactive['overrides'])+'，accepted overrides='+str(inactive['accepted_overrides'])+'，相同 baseline 物理终态='+str(inactive['same_baseline_terminal_complete_state_count'])+'；原 inactive 谓词='+str(inactive['A_registered_inactive_predicate'])+'。',
                '', 'C 的整体状态首次分歧只在 macro16 边界可定位；单独参数/优化器分量与内部微步首次分歧不可辨识。C 的 component null 表示未提供该诊断，不能改写为“没有分歧”。A/B 分辨率为 macro48。','']
        elif number==2:
            lines += ['108 行来自9个A heads和36个依赖parent slots，且同一校准数据选择tau；新增独立样本为0。这不是expected Q或uniform certificate，不包括C两个head的gated校准。增益为0的比值保留null/无定义。','']
        elif number==3:
            lines += ['相同四动作、guard和拟合约束下比较具体head；full-state ridge不是oracle。History仍支付H12观测成本。近场momentum反射不保证同一field输入或reachable状态；有共同最优动作时，排序变化不证明必然决策损失。','']
        elif number==4:
            lines += [_effects_table(b),'','原 B 布尔门：','', '```json',json.dumps(b['statistical_thresholds'],indent=2,ensure_ascii=False),'```','',
                '十个原差值全部保留，轻控制是fixed taper，history6不属于廉价控制。taper−field保持原方向；原field布尔门不包含taper或总成本Pareto门。完整成本和未知范围见 REVIEW.json，不能事后拟合兑换率宣称无条件净收益。','']
        else:
            lines += [_effects_table(c),'','原 C 布尔门：','', '```json',json.dumps(c['statistical_thresholds'],indent=2,ensure_ascii=False),'```','',
                '同时报告Δdual、Δordinary和interaction=Δdual−Δordinary，并保留四臂own-warmstart retention。正交互可能只是较少伤害；原gate没有要求Δdual下界为正，本审查不改写原gate。该受控FPT事件律比较不推出完整Hepta/NDU、更多模态或LLM规模优势。','']
        # The JSON keeps every mapped field, not merely the headline thresholds.
        details={'existing_finding':row['existing_finding'],'existing_supplement_or_formal_outputs':row['existing_supplement_or_formal_outputs']}
        lines += ['<details>','<summary>已封存字段与原始方向（完整）</summary>','', '```json',json.dumps(details,indent=2,ensure_ascii=False,allow_nan=False),'```','', '</details>','']
    lines += ['## 成本与结论范围','',
        '原历史梯度下界182,096，加execution04失败A29的14,784与execution05失败A29的17,280，历史下界为214,160。完整计划343,808已含唯一A17，因此全尝试梯度下界为557,968，不再另加A17。05失败optimizer计数15,984；不完整trace仅作子集核验。原04 outer CPU含A17，作为不可再加的包络观察。05实际outer wait4缺失；controller的1,548.712305秒加supervisor自计区间7.248885367秒，仅得1,555.961190367秒下界。worker的1,512.719833秒和phase区间已嵌套，禁止再加。新06 outer不含历史A17执行。完整历史CPU未知，归档和恢复工程成本在独立root总账保留，墙钟和峰值RSS不相加。',
        '', '原1 GiB/2 GiB资源合同未过与历史V5 FAIL保持原记录。阴性结果可以完成比较；不以扩样、换baseline或扩模态来补出正向结果。终端归档、真实远端回读和公开发布需其各自实际凭据，本审查完成不代替它们。','']
    if 'provenance' in review:
        lines += ['## 可核验输入与执行凭据', '', '以下是本报告所用实际文件的完整路径、大小和 SHA256；数值来自其中绑定的 aggregate 和 supplement。', '', '```json', json.dumps(review['provenance'],indent=2,ensure_ascii=False), '```', '']
    return '\n'.join(lines)


def main():
    wall,cpu=time.monotonic(),time.process_time()
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('arguments','expected-arguments-sha256','wait4','expected-wait4-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--execute-review',action='store_true')
    args=parser.parse_args()
    need(args.execute_review,'Explicit postseal review required')
    destination=WORK/'review'
    need(not destination.exists(),'Review output exists; preserve partial evidence, do not automatically retry')
    pins_item,wait4_item=descriptor(Path(args.arguments).absolute()),descriptor(Path(args.wait4).absolute())
    need(pins_item['sha256']==args.expected_arguments_sha256 and wait4_item['sha256']==args.expected_wait4_sha256,
         'External review input pin differs')
    context=open_gate(pins_item,wait4_item)
    pins,store=context['pins'],context['store']
    def raw_item(item):
        name=Path(item['path']).relative_to(RAW).as_posix()
        need(store.descriptor(name)==item,'Selected scientific input differs from sealed manifest')
        return store.read_json(name)
    result=raw_item(pins['artifacts']['aggregate_results'])
    spec=bound(pins['report_inputs'])
    inactive=global_inactive(result,spec,bound(pins['artifacts']['manifest']),raw_item)
    supplement={name:(_jsonl(item) if name.endswith('.jsonl') else bound(item)) for name,item in context['outputs'].items()
                if name not in ('GATE.json','INPUTS.json','INTEGRITY_ISSUES.json')}
    contracts={name:bound(item) for name,item in context['plan']['review_contracts'].items() if name.endswith('.json')}
    report=compile_review(result,supplement,inactive,context['issues'],contracts)
    report['provenance']={'arguments':pins_item,'primary':pins['primary'],'aggregate_results':pins['artifacts']['aggregate_results'],
        'report_inputs':pins['report_inputs'],'producer_map':pins['producer_map'],'import_receipt':pins['import_receipt'],
        'supplement_complete':context['completion_item'],'supplement_wait4':wait4_item,'implementation':descriptor(Path(__file__).resolve()),
        'plan':pins['plan'],'review_contracts':context['plan']['review_contracts']}
    report['operational_cost_observations']={'execution06_outer_wait4':bound(pins['outer_wait4']),
        'supplement_wait4':context['measured'],'supplement_interval':context['completion']['costs'],
        'supplement_interval_nested_in_wait4_do_not_add_again':True,'unknown_campaign_upper_bound':True}
    context['inputs'].unchanged()
    for item in (*context['plan']['postseal_sources'].values(), *context['plan']['review_contracts'].values()):
        verify(item)
    for item in context['outputs'].values():
        verify(item)
    destination.mkdir(parents=True,exist_ok=False)
    written=[write(destination/'A_INACTIVE_GLOBAL.json',{**inactive,'provenance':report['provenance']}),
             write(destination/'REVIEW.json',report)]
    with (destination/'COMMENTS.zh-CN.md').open('x') as stream:
        stream.write(render(report))
    written.append(descriptor(destination/'COMMENTS.zh-CN.md'))
    complete=write(destination/'COMPLETE.json',{'schema':'hepta.execution06.postseal-review-completion.1',
        'at_utc':datetime.now(timezone.utc).isoformat(),'complete':True,'status':report['status'],
        'outputs':written,'provenance':report['provenance'],'integrity_issue_count':context['issues']['issue_count'],
        'new_training_scoring_fitting_samples':0,'raw_inputs_modified':False,
        'scientific_positive_conclusion_automatically_assigned':False,'terminal_remote_persistence_verified_here':False,
        'own_wall_seconds_until_receipt':time.monotonic()-wall,'own_cpu_seconds_until_receipt':time.process_time()-cpu,
        'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'cost_scope':'This review interval; excludes final receipt write and its future external wait4 parent; do not add to that inclusive measurement.'})
    print(json.dumps({'review_complete':complete,'status':report['status'],'scientific_positive_conclusion_automatically_assigned':False}))
    return 3 if context['issues']['issue_count'] else 0


if __name__=='__main__':
    raise SystemExit(main())
