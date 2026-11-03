"""Read-only verification of two preexisting, completed source-write model archives.

Never changes original answers. Exact ZIP pins are independent of inside manifests.
This creates only a diagnostic, not model generation or independent citation review.
"""
from pathlib import Path
import hashlib
import json
import re
import zipfile
from collections import Counter

ROOT = Path('/mnt/data')
ARCHIVES = {
    'full': ('memory-source-write-original-full.zip', 'bb90d42cc20b1e0a4088904e3c464f10a1c2624f662440044f4d1d28638d14e5'),
    'supervised_positions': ('memory-source-write-optimized-full.zip', '4dab11e3ceb297e8160fa342982ff68d93d86c98537b83925db857c4f0e8958c'),
}
ARMS = ('hybrid','organized','knowledge','parameter_only','empty','policy_initial','policy')
PAIRS = (('hybrid','organized'),('organized','knowledge'),('empty','parameter_only'),('policy_initial','policy'),('organized','policy'))
MARKER = re.compile(r'\[E[1-9]\d*\]')

def load(pin):
    filename, expected = pin
    b = (ROOT / filename).read_bytes()
    assert hashlib.sha256(b).hexdigest() == expected, 'outer ZIP mismatch'
    with zipfile.ZipFile(ROOT/filename) as z:
        names = z.namelist()
        assert len(names) == len(set(names)) and 'SHA256SUMS' in names
        claimed = {}
        for line in z.read('SHA256SUMS').decode('utf-8').splitlines():
            h, name = line.split('  ./', 1)
            assert re.fullmatch(r'[0-9a-f]{64}', h) and name not in claimed
            claimed[name] = h
        assert set(names) - {'SHA256SUMS'} == set(claimed), 'incomplete internal manifest'
        for name, h in claimed.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == h, 'internal file drift'
        raw = [json.loads(x) for x in z.read('tasks/raw-answers.jsonl').splitlines()]
        scored = json.loads(z.read('tasks/scored-answers.json'))
        prior = json.loads(z.read('tasks/source-effects.json'))
        ready = json.loads(z.read('snapshot/READY.json'))
        summary = json.loads(z.read('tasks/report.json'))
        assert len(raw)==len(scored)==56 and ready['production_accepted'] is False
        assert {(x['question_id'],x['arm']) for x in raw} == {(x['question_id'],x['arm']) for x in scored}
        assert len({x['question_id'] for x in raw})==8
        assert prior['original_answer_executions']==56 and prior['semantic_citation_precision'] is None
        for a,b in zip(raw,scored,strict=True):
            assert a['question_id']==b['question_id'] and a['arm']==b['arm']
            assert all(b[k]==v for k,v in a.items())
            assert set(b)-set(a) == ({'parsed_identifier','strict_task_success'} | ({'procedure_verification'} if a['kind']=='procedure' else set()))
        by={(x['question_id'],x['arm']):x for x in scored}
        result={}
        for arm in ARMS:
            rows=[x for x in scored if x['arm']==arm]
            assert len(rows)==8
            unbound=valid=all_marks=0;refused=0
            for x in rows:
                assert x['status']=='succeeded'
                evidence=x['receipt']['delivered_evidence']
                allow={f"[{y['label']}]" for y in evidence}
                marks=MARKER.findall(x['answer'])
                all_marks+=len(marks)
                valid+=sum(m in allow for m in marks)
                unbound+=sum(m not in allow for m in marks)
                refused+=int(x['answer'].strip() in ('I do not have enough evidence.','I do not have enough evidence','I do not know.'))
                if arm in ('parameter_only','empty'):
                    assert evidence==[], 'no-evidence arm received citations'
            result[arm]={'planned':8,'completed':8,'strict_task_successes':sum(x['strict_task_success'] is True for x in rows), 'raw_emitted_markers':all_marks,'markers_with_delivered_label':valid,'undelivered_marker_occurrences':unbound,'literal_protocol_refusals':refused}
        pairs={}
        for baseline,candidate in PAIRS:
            x=[(by[q,baseline],by[q,candidate]) for q in sorted({r['question_id'] for r in scored})]
            pairs[f'{candidate}_vs_{baseline}']={'wins':sum(not a['strict_task_success'] and b['strict_task_success'] for a,b in x),'losses':sum(a['strict_task_success'] and not b['strict_task_success'] for a,b in x),'changed_raw_answers':sum(a['answer']!=b['answer'] for a,b in x),'matched_input_digests':sum(a['receipt']['input_ids_digest']==b['receipt']['input_ids_digest'] for a,b in x),'same_selected':sum(a['selected']==b['selected'] for a,b in x)}
        t=ready['training']
        tr={k:t.get(k) for k in ('steps','input_tokens','supervised_tokens','loss_backend','actual_projection_positions','adapter_delta_squared_norm','training_seconds','trainable_parameters')}
        return dict(artifact=filename,artifact_sha256=expected, internal_members=len(claimed),source_commit=ready['writer_source'],base_identity=ready['base_identity'], source_sha=ready['source_sha'],training=tr,write_seconds=ready['write_seconds'],per_arm=result,pairs=pairs,semantic_citation_precision=None,independent_source_families=None,production_accepted=False,original_task_success_recomputed=True)

report={label:load(pin) for label,pin in ARCHIVES.items()}
a,b=report.values()
assert a['source_sha']==b['source_sha'] and a['base_identity']==b['base_identity']
assert a['training']['steps']==b['training']['steps']==128
assert a['training']['input_tokens']==b['training']['input_tokens'] and a['training']['supervised_tokens']==b['training']['supervised_tokens']
assert all(x['planned']==8 for row in report.values() for x in row['per_arm'].values())
report={'schema':'hepta.local-crossrun-real-answers-audit.v1','historical_comparisons':report,'same_base_and_original_source':True,'observed_speed_change_seconds':a['write_seconds']-b['write_seconds'],'one_model_run_is_not_an_independent_family':True,'new_model_calls':0,'independent_semantic_citation_precision':None,'production_accepted':False}
p=ROOT/'memory_source_pairwise_real_answers_20261014.json';p.write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+'\n')
print('created',p,'sha256',hashlib.sha256(p.read_bytes()).hexdigest())
for name,run in report['historical_comparisons'].items():
 print(name,'steps',run['training']['steps'],'write seconds',run['write_seconds'],'training tokens',run['training']['input_tokens'],'valid tasks',[f'{k}:{v["strict_task_successes"]}' for k,v in run['per_arm'].items()]);print('no-evidence bad markers',run['per_arm']['parameter_only']['undelivered_marker_occurrences']);print('adapter effect',run['pairs']['knowledge_vs_organized']);print('param only',run['pairs']['parameter_only_vs_empty'])
