"""Independent, offline, source-byte audit of the 2026-10-13 real Qwen experiment.

Uses only already downloaded GitHub Actions artifacts. No model load, internet,
implicit model responses, source selection or mutable answer rewriting.
"""
from __future__ import annotations
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import zipfile

ROOT=Path('/mnt/data')
READER=ROOT/'memorycell-real-reader-38389920977.zip'
REPLAY=ROOT/'memorycell-replay-38389920977.zip'
CALIBRATION=ROOT/'memorycell-calibration-38389920977.zip'
ORIGINAL=ROOT/'event-inputs-20261010.zip'
COMMIT='3b03ea7dee4b270bdf328251f7a404571c9d1013'
EXPECTED={
    READER.name:'de7087dbd3ee367475ef279d01dbeeeea46ee991b11399324289300df10c40bf',
    REPLAY.name:'442c7171cb2c522988e6e6c52b12201d1b59104702229dc256ca91b7bf6559c1',
    CALIBRATION.name:'26ff349eef1e78367577be7dc59308166bb73ea13d5f63070ecdfd6fbc093f24',
    ORIGINAL.name:'23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b',
}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def check_zip(path):
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==EXPECTED[path.name],path.name
    with zipfile.ZipFile(path) as z:
        files={i.filename:i for i in z.infolist()}
        assert len(files)==len(z.infolist()) and 'SHA256SUMS' in files
        for n,i in files.items():
            assert not n.startswith('/') and '..' not in Path(n).parts and not stat.S_ISLNK(i.external_attr>>16),n
        listed={}
        for row in z.read('SHA256SUMS').decode().splitlines():
            h,n=row.split('  ',1);n=n.removeprefix('./')
            assert re.fullmatch('[a-f0-9]{64}',h) and n not in listed and n in files,n
            assert hashlib.sha256(z.read(n)).hexdigest()==h,n
            listed[n]=h
        assert set(listed)==set(files)-{'SHA256SUMS'}
        return len(listed)


def load_json(z,name): return json.loads(z.read(name))


def parse_answer(answer):
    m=re.fullmatch(r'\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*',answer)
    return m.group(1) if m else None


def check_score(row,truth):
    answer=parse_answer(row['answer'])
    if truth['kind']=='procedure':
        recipe=truth['procedure'];mode=recipe['modes'].get(answer)
        result=sorted(recipe['values']) if mode=='sort' else list(reversed(recipe['values'])) if mode=='reverse' else None
        success=result is not None and result==recipe['target']
    else: success=answer==truth['expected']
    assert success==row['strict_task_success'],(row['question_id'],row['arm'],'task')
    assert answer==row['parsed_identifier'],(row['question_id'],row['arm'],'parse')
    assert (set(truth['support']).issubset(set(row['selected'])))==row['required_sources_covered']
    if truth['kind']=='procedure':
        record=row['procedure_verification']
        assert record['request']['supplied']==(answer or 'invalid_response')
        assert record['request']['recipe']==recipe
        assert (record['exit_code']==0)==success
        assert json.loads(record['stdout'])==dict(succeeded=success,supplied=(answer or 'invalid_response'),actual_output=result)
    return success


def verify():
    files={path.name:check_zip(path) for path in (ORIGINAL,CALIBRATION,READER,REPLAY)}
    with zipfile.ZipFile(ORIGINAL) as origin,zipfile.ZipFile(READER) as source,zipfile.ZipFile(REPLAY) as independent,zipfile.ZipFile(CALIBRATION) as calibration:
        plan=load_json(origin,'plan/plan.json');labels=load_json(origin,'observations/labels.json');sources=load_json(origin,'plan/source-view.json');originals={s['identity']:s for s in sources};truths={l['id']:l for l in labels}
        assert hashlib.sha256(origin.read('plan/plan.json')).hexdigest()=='9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897'
        assert len(plan['cases'])==8 and len(originals)==108 and len(truths)==16
        assert source.read('tested-commit.txt').decode().strip()==COMMIT
        assert independent.read('auditor-source-commit.txt').decode().strip()==COMMIT
        for name in calibration.namelist():
            if name=='SHA256SUMS':continue
            assert calibration.read(name)==source.read(name),'calibration checkpoint drift: '+name
        policy=load_json(source,'calibration/frozen-policy.json');report=load_json(source,'evaluation/report.json');cal_report=load_json(source,'calibration/report.json');ind=load_json(independent,'receipt.json')
        assert ind['generating_commit']==COMMIT and ind['verified_artifact_files']==43
        assert policy['selected_k']==1 and report['selected_k']==1
        assert policy['raw_answers_sha256']==hashlib.sha256(source.read('calibration/raw-answers.jsonl')).hexdigest()
        assert report['raw_answers_sha256']==hashlib.sha256(source.read('evaluation/raw-answers.jsonl')).hexdigest()
        assert policy['frozen_before_evaluation'] is True and policy['candidate_accepted'] is False and policy['production_accepted'] is False
        assert all(x['scope'].startswith('controlled_') for x in sources)
        test_ids={c['query']['identity'] for c in plan['cases']}
        cal_plan=load_json(source,'prep/calibration-plan.json')
        assert set(c['query']['identity'] for c in cal_plan['cases']).isdisjoint(test_ids)
        assert set(x['scope'] for x in load_json(source,'prep/calibration-sources.json')).isdisjoint(test_ids)
        assert len(cal_plan['cases'])==8 and len(test_ids)==8
        all_aggs={};base_model_id=None
        for stage,expected in (('calibration',40),('evaluation',72)):
            raw=[json.loads(x) for x in source.read(stage+'/raw-answers.jsonl').decode().splitlines()]
            scored=load_json(source,stage+'/scored-answers.json')
            assert len(raw)==len(scored)==expected
            assert len({(x['question_id'],x['arm']) for x in raw})==expected
            aggregate=defaultdict(lambda:dict(attempts=0,success=0,coverage=0,full_cited=0,input_tokens=0,output_tokens=0,reader_seconds=0.0,by_kind=defaultdict(lambda:dict(attempts=0,success=0,full_cited=0))))
            for source_row,row in zip(raw,scored,strict=True):
                assert {k:v for k,v in row.items() if k not in ('parsed_identifier','strict_task_success','required_sources_covered','procedure_verification')}==source_row
                assert source_row['status']=='succeeded'
                assert row['question_id'] in truths
                assert (row['question_id'] in test_ids)==(stage=='evaluation')
                answer_ok=check_score(row,truths[row['question_id']]);rec=row['receipt']
                assert isinstance(rec['trainable_parameters'],int) and rec['trainable_parameters']==0
                assert rec['answer_postprocessed'] is False and rec['production_accepted'] is False
                assert 0<rec['input_tokens']<=2048 and 0<rec['generated_tokens']<=64
                if base_model_id is None:base_model_id=(rec['reader_identity'],rec['reader_profile'])
                assert (rec['reader_identity'],rec['reader_profile'])==base_model_id
                delivery=rec['delivered_evidence']
                assert [r['original_id'] for r in delivery]==row['selected']
                quoted=set()
                for i,e in enumerate(delivery,1):
                    source_doc=originals[e['original_id']]
                    assert e['label']==f'E{i}' and e['excerpt']==source_doc['content']
                    assert e['root']==source_doc['root'] and e['scope']==source_doc['scope']
                    assert e['source_digest']==digest(source_doc['content'])
                    if f'[E{i}]' in row['answer']:quoted.add(e['original_id'])
                assert row['citation_audit']['request']['answer']==row['answer']
                assert row['citation_audit']['request']['prompt_digest']==rec['input_ids_digest']
                d=aggregate[row['arm']];d['attempts']+=1;d['success']+=int(answer_ok);d['coverage']+=int(row['required_sources_covered']);d['input_tokens']+=rec['input_tokens'];d['output_tokens']+=rec['generated_tokens'];d['reader_seconds']+=rec['seconds'];full=answer_ok and set(truths[row['question_id']]['support']).issubset(quoted);d['full_cited']+=int(full)
                kind=d['by_kind'][row['kind']];kind['attempts']+=1;kind['success']+=int(answer_ok);kind['full_cited']+=int(full)
            for arm,d in aggregate.items():
                assert d['attempts']==8,arm
                d['reader_seconds']=round(d['reader_seconds'],3)
                d['by_kind']=dict(d['by_kind'])
                published=(cal_report['arms'] if stage=='calibration' else report['success_by_arm'])[arm]
                assert d['success']==published['strict_success'] and d['input_tokens']==published['input_tokens'] and d['output_tokens']==published['output_tokens']
                assert d['coverage']==published['support_covered']
                if stage=='evaluation':
                    reported=ind['formal_citation_chain']['by_arm'][arm]
                    assert d['full_cited']==reported['correct_with_full_program_declared_citations'],(arm,d['full_cited'],reported)
            all_aggs[stage]=dict(sorted(aggregate.items()))
        assert len(all_aggs['calibration'])==5 and len(all_aggs['evaluation'])==9
        assert ind['calibration']['attempts']==40 and ind['evaluation']['attempts']==72
        assert ind['calibration']['all_model_calls_succeeded'] is True and ind['evaluation']['all_model_calls_succeeded'] is True
        assert not ind['production_accepted'] and not ind['independent_semantic_judge'] and not ind['statistical_superiority']
        # Parenthesized gate: descriptive paired differences only; no statistical inference.
        return {
            'schema':'hepta.memory-cell.real-qwen-independent-raw-audit.v1',
            'generating_commit':COMMIT,
            'workflow_run_id':38389920977,
            'archive_sha256':dict((k,EXPECTED[k]) for k in sorted(EXPECTED)),
            'verified_inner_sha256_members':files,
            'original_source_plan_sha256':'9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897',
            'reader_identity':base_model_id[0],
            'reader_profile':base_model_id[1],
            'frozen_calibrated_k':1,
            'calibration':all_aggs['calibration'],
            'evaluation':all_aggs['evaluation'],
            'replay_independent_success':True,
            'same_prompt_pairs':ind['same_prompt_consistency']['observed_identical_prompt_pairs'],
            'same_prompt_divergence_count':len(ind['same_prompt_consistency']['answer_disagreements'])+len(ind['same_prompt_consistency']['output_token_disagreements'])+len(ind['same_prompt_consistency']['task_result_disagreements']),
            'source_family_count':0,
            'independent_semantic_judge':False,
            'independent_future_benchmark':False,
            'production_accepted':False,
        }

if __name__=='__main__':
    data=verify()
    path=ROOT/'memorycell_verified_40_72_real_qwen_20261013.json'
    path.write_text(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({
      'report_file':str(path),
      'calibration':{k:(v['success'],v['input_tokens']) for k,v in data['calibration'].items()},
      'evaluation':{k:(v['success'],v['full_cited'],v['input_tokens'],v['reader_seconds']) for k,v in data['evaluation'].items()},
      'archive_pins_verified':data['verified_inner_sha256_members'],
      'same_prompt_pairs':data['same_prompt_pairs'],
    },ensure_ascii=False,indent=2))
