"""Independent read-only verification of two exact GitHub Actions Qwen runs.

No model inference, target editing, evidence selection, credential minting,
or production approval. Never treat repeated public queries as independent.
"""
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ARCHIVES = {
    'earlier_reader': ('rag-reader-38224780900.zip', '7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8'),
    'earlier_replay': ('rag-replay-38224780900.zip', '2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071'),
    'later_reader': ('rag-reader-38389920977.zip', 'de7087dbd3ee367475ef279d01dbeeeea46ee991b11399324289300df10c40bf'),
    'later_replay': ('rag-independent-replay-38389920977.zip', '442c7171cb2c522988e6e6c52b12201d1b59104702229dc256ca91b7bf6559c1'),
}


def strict_json(s):
    def unique(pairs):
        out = {}
        for k,v in pairs:
            if k in out: raise ValueError('Duplicate JSON key: '+k)
            out[k] = v
        return out
    return json.loads(s, object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite '+x)))


def load_archive(base, key):
    filename, pin = ARCHIVES[key]
    f = base / filename
    assert hashlib.sha256(f.read_bytes()).hexdigest() == pin, 'outer SHA mismatch: '+filename
    with zipfile.ZipFile(f) as z:
        names = z.namelist()
        assert len(names) == len(set(names)), 'duplicate zip member'
        assert all(n and not n.startswith('/') and '..' not in Path(n).parts and not n.endswith('/') for n in names), 'zip traversal'
        contents={n:z.read(n) for n in names}
    assert 'SHA256SUMS' in contents
    manifest={}
    for line in contents['SHA256SUMS'].decode('utf-8').splitlines():
        h,name=line.split('  ',1)
        name=name.removeprefix('./')
        assert name not in manifest
        manifest[name]=h
    assert set(manifest)==set(contents)-{'SHA256SUMS'}
    for name,sha in manifest.items():
        assert hashlib.sha256(contents[name]).hexdigest()==sha, 'inner SHA mismatch: '+name
    return contents, len(manifest)


def raw_rows(contents, stage, count):
    rows=[strict_json(line) for line in contents[f'{stage}/raw-answers.jsonl'].decode().splitlines()]
    assert len(rows)==count and len({(r['question_id'],r['arm']) for r in rows})==count
    assert all(r['status']=='succeeded' for r in rows)
    return {(r['question_id'],r['arm']):r for r in rows}


def verify(base):
    archives={key:load_archive(base,key) for key in ARCHIVES}
    first,later=archives['earlier_reader'][0],archives['later_reader'][0]
    parts={}
    receipt_fields=('reader_identity','reader_profile','input_ids_digest','generated_ids_digest',
                    'input_tokens','generated_tokens','delivered_evidence')
    for phase,count in [('calibration',40),('evaluation',72)]:
        x,y=raw_rows(first,phase,count),raw_rows(later,phase,count)
        assert x.keys()==y.keys()
        for key in x:
            a,b=x[key],y[key]
            for field in ('question_id','arm','kind','candidate_digest','selected','answer','status'):
                assert a.get(field)==b.get(field),f'drift at {phase}/{key}/{field}'
            for field in receipt_fields:
                assert a['receipt'].get(field)==b['receipt'].get(field),f'drift at {phase}/{key}/receipt.{field}'
        parts[phase]={'planned':count,'actual':len(x),'paired_input_answer_digest_matches':len(x),
                      'distinct_question_ids':len({q for q,_ in x})}
    earlier= strict_json(first['evaluation/report.json'])
    new=strict_json(later['evaluation/report.json'])
    before=strict_json(first['calibration/report.json'])
    after=strict_json(later['calibration/report.json'])
    assert before['frozen_k']==after['frozen_k']==1
    assert set(earlier['success_by_arm'])==set(new['success_by_arm'])
    arms={}
    for arm in earlier['success_by_arm']:
        a,b=earlier['success_by_arm'][arm],new['success_by_arm'][arm]
        for field in ('strict_success','input_tokens','generated_tokens','support_covered'):
            if field in a: assert a[field]==b[field],f'report mismatch {arm} {field}'
        assert a['planned']==b['planned']==8
        citation_old=earlier['formal_citation_chain']['by_arm'][arm]
        citation_new=new['formal_citation_chain']['by_arm'][arm]
        assert citation_old==citation_new
        arms[arm]={'strict_correct':a['strict_success'],'out_of':8,
                   'cited_full_declared_source_chain':citation_new['correct_with_full_program_declared_citations'],
                   'prompt_input_tokens':a['input_tokens'],
                   'earlier_reader_seconds':round(a['inference_seconds'],3),
                   'later_reader_seconds':round(b['inference_seconds'],3)}
    receipt={}
    for prefix in ('earlier','later'):
        rr=strict_json(archives[f'{prefix}_replay'][0]['receipt.json'])
        assert rr['calibration']['attempts']==40 and rr['evaluation']['attempts']==72
        assert rr['calibration']['all_model_calls_succeeded'] and rr['evaluation']['all_model_calls_succeeded']
        assert rr['production_accepted'] is False
        receipt[prefix]={'original_sha':rr['generating_commit'], 'replay_schema':rr['schema'], 'output_sha256':hashlib.sha256(archives[f'{prefix}_replay'][0]['receipt.json']).hexdigest()}
    return {
        'schema':'local.readonly.strong-rag.two-run-independent-check.v1',
        'finding':'historical exact-answer reproducibility; no independent validation or production admission',
        'archives_sha256':{k:sha for k,(_,sha) in ARCHIVES.items()},
        'internal_manifest_members_verified':{k:n for k,(_,n) in archives.items()},
        'model_inventory_identity':'f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225',
        'compared_pairs':parts, 'calibrated_k':before['frozen_k'],
        'calibration_leave_one_out_stable':after['calibration_sensitivity']['stable_to_one_calibration_case_removal'],
        'evaluation':arms, 'separate_independent_replays':receipt,
        'full_path_minus_single_hop_correct_delta':arms['entity_time']['strict_correct']-arms['single_hop']['strict_correct'],
        'organizer_minus_full_path_correct_delta':arms['organized']['strict_correct']-arms['entity_time']['strict_correct'],
        'organizer_minus_full_path_full_chain_citation_delta':arms['organized']['cited_full_declared_source_chain']-arms['entity_time']['cited_full_declared_source_chain'],
        'organizer_prompt_tokens_saved':arms['entity_time']['prompt_input_tokens']-arms['organized']['prompt_input_tokens'],
        'independent_new_source_families':0,
        'human_semantic_citation_review_complete':False,
        'parametric_memory_training_qualified':False,
        'production_accepted':False,
    }

if __name__=='__main__':
    base=Path(sys.argv[1] if len(sys.argv)>1 else '/mnt/data')
    result=verify(base)
    out=base/'memorycell_oct14_two_run_verified.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('VERIFIED',result['compared_pairs'], 'zip_members',sum(result['internal_manifest_members_verified'].values()))
    print('Wrote',out)
