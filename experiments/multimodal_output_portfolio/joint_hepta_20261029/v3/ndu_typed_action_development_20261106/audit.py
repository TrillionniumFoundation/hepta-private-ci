"""Receipt and correctness audit; performs no model forward or task tool call."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads((args.results/'result.json').read_text())
    cfg=json.loads((ROOT/'protocol.json').read_text())
    frozen=json.loads((ROOT/'freeze.json').read_text())
    checks=[]
    def require(condition,description):
        checks.append({'name':description,'passed':bool(condition)})
        if not condition:raise AssertionError(description)
    require(report['source_unchanged'] is True,'execution source boundary unchanged')
    require(report['protocol_sha256']==sha(ROOT/'protocol.json'),'protocol digest')
    require(all(sha(ROOT/path)==digest for path,digest in frozen['source_sha256'].items()),'source and input freeze exact')
    require(all(sha(args.results/path)==digest for path,digest in report['artifacts_sha256'].items()),'all raw artifacts exact')
    events=[json.loads(line) for line in (args.results/'events.jsonl').read_text().splitlines()]
    ids=sorted(set(x['request_id'] for x in events))
    require(len(ids)==24 and len(events)==48,'24 unique requests and 48 intent/terminal entries')
    for rid in ids:
        rows=[x for x in events if x['request_id']==rid]
        require(len(rows)==2 and [x['phase'] for x in rows]==['intent','terminal'],'intent precedes one terminal: '+rid)
        require(rows[0]['payload']==rows[1]['payload'] and rows[1]['status']=='ok','matching successful receipt: '+rid)
        raw=json.loads((args.results/(rid+'.json')).read_text())
        require(sha_bytes(raw['stdout'].encode())==rows[1]['stdout_sha256'],'exact stdout: '+rid)
    fingerprints=set()
    decision_rows=[]
    task_map={x['task_id']:x for x in cfg['tasks']}
    for event in events:
        if event['phase']=='terminal' and event['context']['stage']=='model':
            raw=json.loads((args.results/(event['request_id']+'.json')).read_text())['response']
            logits=raw['legal_label_logits']
            label=max(logits,key=logits.get)
            require(label==raw['selected_label'],'selected legal argmax: '+event['request_id'])
            require(raw['parameter_sha256_before']==raw['parameter_sha256_after'],'parameters frozen: '+event['request_id'])
            require(raw['model_id']==cfg['model_id'] and raw['revision']==cfg['revision'],'exact public model: '+event['request_id'])
            require(event['payload']=={'question':task_map[event['context']['task_id']]['question']},'public question only: '+event['request_id'])
            require(len(raw['input_token_ids'])==raw['input_tokens'] and raw['forward_calls']==1,'one declared model forward: '+event['request_id'])
            fingerprints.add(raw['parameter_sha256_before'])
            decision_rows.append(raw)
    require(fingerprints=={'815634c0b4c921ad07b4a32437ff872342e745b15a386f6ca8f5a2d4974e0c13'},'same parameters as prior Qwen development')
    # Reconstruct evaluation with independently expressed source readers.
    sql=gzip.decompress((ROOT/'inputs/sources/chinook.sql.gz').read_bytes()).decode('utf-8-sig')
    db=sqlite3.connect(':memory:')
    db.executescript(sql)
    source=(ROOT/'inputs/sources/statistics.py').read_text()
    targets={}
    for task in cfg['tasks']:
        name=task['question'].split('the ')[-1].split(' table')[0] if task['family']=='sqlite_count' else task['question'].split('for the ')[1].split(' function')[0]
        if task['family']=='sqlite_count':
            targets[task['task_id']]=sum(1 for _ in db.execute('SELECT * FROM "'+name+'"'))
        else:
            matches=[line.strip() for line in source.splitlines() if line.startswith('def '+name+'(')]
            require(len(matches)==1,'unique reference source declaration: '+name)
            targets[task['task_id']]=matches[0]
    db.close()
    require(len(report['episodes'])==24,'complete three-arm eight-task schedule')
    cells=Counter((x['task_id'],x['arm']) for x in report['episodes'])
    require(set(cells)=={(t['task_id'],a) for t in cfg['tasks'] for a in cfg['arms']} and set(cells.values())=={1},'each prespecified task-arm once')
    compatible={a:0 for a in cfg['arms']}
    comparisons=[]
    for row in report['episodes']:
        expected=targets[row['task_id']]
        correct=row['delivered'] and type(row['answer']) is type(expected) and row['answer']==expected
        require(correct==row['correct'],'independent answer reconciliation: '+row['task_id']+'/'+row['arm'])
        compatible[row['arm']]+=int(row['delivered'] and type(row['answer']) is type(expected))
        require(row['elapsed_seconds']<=cfg['episode_deadline_seconds'],'recorded episode completed within deadline: '+row['task_id']+'/'+row['arm'])
    for task in cfg['tasks']:
        full=next(x for x in report['episodes'] if x['task_id']==task['task_id'] and x['arm']=='frozen_lm_selector')
        base=next(x for x in report['episodes'] if x['task_id']==task['task_id'] and x['arm']=='literal_router')
        comparisons.append({'task_id':task['task_id'],'quality_difference':int(full['correct'])-int(base['correct']),
             'extra_elapsed_seconds':full['elapsed_seconds']-base['elapsed_seconds'],
             'same_task_tool_count':full['tool_calls']==base['tool_calls']==1})
    require(all(x['quality_difference']<=0 and x['extra_elapsed_seconds']>0 and x['same_task_tool_count'] for x in comparisons),'literal router weakly dominates quality and strictly dominates measured elapsed time on every task')
    result={'schema':'ndu.typed-action-receipt-audit.v1','audit_kind':'separate reconstruction by same implementation author; not external or independent review',
        'checks':checks,'all_checks_pass':all(x['passed'] for x in checks),'model_forwards_during_audit':0,'task_tool_calls_during_audit':0,
        'evaluation_database_reads_during_audit':True,'task_schema_compatible_deliveries':compatible,'paired_descriptive_comparisons':comparisons,
        'total_input_tokens':sum(x['input_tokens'] for x in decision_rows),'decision_output_tokens':8,
        'model_forward_seconds':sum(x['forward_seconds'] for x in decision_rows),
        'same_fixed_model_parameter_sha256':list(fingerprints)[0],
        'independent_confirmation':False,'actual_host_currency_cost':None,'scale_decision':'HOLD'}
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps({'all_checks_pass':result['all_checks_pass'],'checks':len(checks),'task_schema_compatible_deliveries':compatible,'paired_descriptive_comparisons':comparisons,'total_input_tokens':result['total_input_tokens'],'model_forward_seconds':result['model_forward_seconds']},indent=2))


def sha_bytes(value):return hashlib.sha256(value).hexdigest()

if __name__=='__main__':main()
