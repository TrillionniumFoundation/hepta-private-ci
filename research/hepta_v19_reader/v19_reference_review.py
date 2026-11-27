"""Separately implemented original source→Qwen token→answer postseal reviewer.

Checks genuine SHA-pinned publisher source. Target answers are opened ONLY after
physical private model responses have sealed. Literal matches are weak proxies;
syntactic citation addresses never imply semantic entailment or sufficiency.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import stat

SOURCE_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
ARCHIVE_SHA='07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
BASE='hepta.v17.original-locomo-reader.shadow.v1'
SCHEMA='hepta.v19.original-locomo-native-qwen3-reference.shadow.v1'
REPO='Qwen/Qwen3-0.6B'
REVISION='16706fc57485378d4ffaf54139b29ccc66ae08fa'
ROOTS=('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44','conv-47','conv-48','conv-49','conv-50')
ARMS=('none','retrieved','annotated','lesion')
STOP=set('a an the of in on by to for from and or is are was were as that which what where when who how whose with at did does do have has had it its this those these their he she his her they but about after before been being than more most'.split())
WORDS=re.compile(r"[\w]+(?:['’][\w]+)?",re.UNICODE)
CITE=re.compile(r'\[E(\d+)\]')
SYSTEM=('Answer concisely from provided evidence only. If not supported, say unknown. '
        'Cite the evidence [E1], [E2], etc.')

EXPECTED_REFERENCE_PLAN_FIELDS={
    'schema','v17_plan_sha256','v17_requests_sha256','public_sha256','owner_sha256',
    'annotation_packet_sha256','model_repo','model_revision','source_roots','cases',
    'arms','output_cap','max_input_tokens','entries','entry_sha256',
    'publisher_answer_labels_not_exposed','model_specific_tokenization_not_matched',
    'source_time_prospective','independent_human_sufficiency','authority',
    'production_authorized','decision','plan_sha256',
}
EXPECTED_PRIVATE_FIELDS={
    'schema','plan_sha256','source_roots','model_repo','model_revision',
    'model_spec_sha256','model_weights_sha256','requests_by_id',
    'requests_by_id_sha256','physical_outputs','physical_outputs_sha256',
    'original_archive_sha256','journal_sha256','actual_unique_qwen_requests',
    'logical_arm_requests','measured_root_forward_calls','wall_ms','cpu_ms',
    'original_pretrained_qwen3_executed','physical_model_host_independently_signed',
    'current_135m_model_executed_by_this_runner',
    'task_semantic_correctness_independently_verified',
    'publisher_witness_sufficiency_human_certified',
    'model_token_budget_matched_to_135m','ndu_fbsde_solves',
    'authority','production_authorized','decision',
}
EXPECTED_MODEL_OUTPUT_FIELDS={
    'representative_id','logical_ids','generated_token_ids','answer','answer_sha256',
    'input_sha256','input_tokens','output_tokens','observed_root_model_forwards',
    'cpu_ms','wall_ms',
}
EXPECTED_START_FIELDS={
    'token_ids_sha256','model_spec_sha256','plan_sha256','representative_id',
    'logical_ids','input_tokens','physical_model_generation_started','authority',
}


def cbytes(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')

def digest(value):return sha256(cbytes(value)).hexdigest()

def txtsha(value):return sha256(value.encode('utf8')).hexdigest()

def secure_read(path,cap=22_000_000):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or not 0<p.stat().st_size<cap:
        raise ValueError('missing or unbounded data')
    def pairs(items):
        row={}
        for k,v in items:
            if k in row:raise ValueError('duplicate JSON property')
            row[k]=v
        return row
    def invalid(v):raise ValueError('nonfinite JSON '+v)
    return json.loads(p.read_bytes(),object_pairs_hook=pairs,parse_constant=invalid)


def independent_rank(question,docs):
    def words(s):return [x.casefold() for x in WORDS.findall(s) if len(x)>1 and x.casefold() not in STOP]
    query=Counter(words(question)); bags=[Counter(words(d['text'])) for d in docs]
    df=Counter(term for bag in bags for term in bag)
    n=len(docs);avg=sum(sum(b.values()) for b in bags)/n or 1.
    def score(b):
        size=sum(b.values())
        return sum(min(2,occ)*math.log1p((n-df[t]+.5)/(df[t]+.5))*(b[t]*2.2/(b[t]+1.2*(.25+.75*size/avg)))
                   for t,occ in query.items() if b.get(t))
    scored=[score(b) for b in bags]
    return [docs[i]['id'] for i in sorted(range(n),key=lambda i:(-scored[i],docs[i]['id']))]


def messages(question,ids,docs):
    if any(t in question or any(t in docs[i]['text'] for i in ids)
           for t in ('<|im_start|>','<|im_end|>','<|fim_prefix|>')):
        raise ValueError('role delimiter in publisher material')
    lines=['[E'+str(i)+'] '+ref+' '+docs[ref]['speaker']+': '+docs[ref]['text'][:240]
           for i,ref in enumerate(ids,1)]
    body='\n'.join(lines) if lines else '(no evidence provided)'
    return [{'role':'system','content':SYSTEM},
            {'role':'user','content':'Question: '+question+'\nEvidence:\n'+body}]



def original_chatml(question,ids,docs):
    """Independently reconstruct exact frozen V17 135M input, not producer import."""
    lines=['<|im_start|>system',SYSTEM,'<|im_end|>','<|im_start|>user',
           'Question: '+question,'Evidence:']
    if ids:
        lines.extend('[E'+str(i)+'] '+ref+' '+docs[ref]['speaker']+': '+docs[ref]['text'][:240]
                     for i,ref in enumerate(ids,1))
    else:
        lines.append('(no evidence provided)')
    lines.extend(['<|im_end|>','<|im_start|>assistant',''])
    return '\n'.join(lines)

def sourceaudit(original,public,owner,hidden,old_plan,annotation,old_requests,proposal):
    if (type(original) is not list or len(original)!=10 or type(public) is not list or len(public)!=10
        or {f.get('sample_id') for f in original}!=set(ROOTS)
        or {f.get('id') for f in public}!=set(ROOTS)
        or type(hidden) is not dict or set(hidden)!=set(ROOTS)
        or owner.get('schema')!=BASE+'.owner' or owner.get('source_sha256')!=SOURCE_SHA
        or owner.get('archive_sha256')!=ARCHIVE_SHA or owner.get('public_sha256')!=digest(public)
        or owner.get('hidden_sha256')!=digest(hidden) or owner.get('production_accepted') is not False
        or old_plan.get('schema')!=BASE+'.plan' or old_plan.get('public_sha256')!=digest(public)
        or old_plan.get('owner_sha256')!=digest(owner) or old_plan.get('case_selection')!='sha256_lowest_three_per_original_root_NO_answer_filter'
        or old_plan.get('plan_sha256')!=digest({k:v for k,v in old_plan.items() if k!='plan_sha256'})
        or annotation.get('schema')!=BASE+'.annotation-only' or annotation.get('plan_sha256')!=old_plan['plan_sha256']
        or annotation.get('original_hidden_sha256')!=digest(hidden) or annotation.get('answer_fields_exposed') is not False
        or annotation.get('packet_sha256')!=digest({k:v for k,v in annotation.items() if k!='packet_sha256'})
        or old_requests.get('schema')!=BASE+'.model-requests' or old_requests.get('requests_sha256')!=digest(old_requests.get('requests'))
        or old_requests.get('publisher_answer_text_never_supplied') is not True
        or type(proposal) is not dict or set(proposal)!=EXPECTED_REFERENCE_PLAN_FIELDS
        or proposal.get('schema')!=SCHEMA+'.source-plan' or proposal.get('v17_plan_sha256')!=old_plan['plan_sha256']
        or proposal.get('v17_requests_sha256')!=old_requests['requests_sha256']
        or proposal.get('annotation_packet_sha256')!=annotation['packet_sha256']
        or proposal.get('public_sha256')!=digest(public) or proposal.get('owner_sha256')!=digest(owner)
        or proposal.get('source_roots')!=list(ROOTS) or proposal.get('arms')!=list(ARMS)
        or proposal.get('model_repo')!=REPO or proposal.get('model_revision')!=REVISION
        or proposal.get('output_cap')!=24 or proposal.get('max_input_tokens')!=2048
        or proposal.get('publisher_answer_labels_not_exposed') is not True
        or proposal.get('independent_human_sufficiency') is not False
        or proposal.get('source_time_prospective') is not False
        or proposal.get('model_specific_tokenization_not_matched') is not True
        or proposal.get('production_authorized') is not False or proposal.get('authority')!='DENY_ALL'
        or proposal.get('decision')!='HOLD_NO_GO'
        or proposal.get('plan_sha256')!=digest({k:v for k,v in proposal.items() if k!='plan_sha256'})
        or proposal.get('entry_sha256')!=digest(proposal.get('entries'))):
        raise ValueError('original/strong-reference identity or scientific gate invalid')
    by_orig={f['sample_id']:f for f in original}
    by_pub={f['id']:f for f in public}
    question_info={};expected={};selected=[]
    for root in ROOTS:
        orig=by_orig[root];pub=by_pub[root]
        all_docs=[dict(id=x['dia_id'],speaker=x['speaker'],text=x['text'])
                  for name,rows in orig['conversation'].items()
                  if name.startswith('session_') and type(rows) is list for x in rows]
        if all_docs!=pub['utterances'] or len(pub['questions'])!=len(orig['qa']):
            raise ValueError('publisher source changed postseal')
        docs={x['id']:x for x in all_docs}
        old_gold={}
        for k,q in enumerate(orig['qa']):
            cid=root+'/q'+str(k)
            if pub['questions'][k]!={'id':cid,'question':q['question']}:
                raise ValueError('original publisher question tampered')
            old_gold[cid]={'answer':q.get('answer'),'support_ids':q.get('evidence'),
                           'category':q.get('category')}
        if hidden[root]!=old_gold:raise ValueError('publisher target owner tampered')
        ids=sorted(old_gold,key=lambda c:(txtsha(c),c))[:3]
        selected+=ids
        for cid in ids:
            i=int(cid.split('/q')[1]);q=orig['qa'][i]
            witnesses=list(dict.fromkeys(q.get('evidence',[])))[:3]
            if not witnesses or any(x not in docs for x in witnesses):
                raise ValueError('not an existing historical witness')
            if annotation['source_ids'].get(cid)!=witnesses:
                raise ValueError('publisher witness addresses changed')
            selected_refs={'none':[],'retrieved':independent_rank(q['question'],all_docs)[:3],
                           'annotated':witnesses,'lesion':witnesses[1:]}
            for arm,source_ids in selected_refs.items():
                name=cid+'|'+arm
                row=old_requests['requests'].get(name)
                if (type(row) is not dict or row.get('case_id')!=cid or row.get('source_ids')!=source_ids
                    or row.get('question_sha256')!=txtsha(q['question']) or
                    row.get('source_sha256')!=digest(pub)):
                    raise ValueError('original 135M evidence graph changed')
                msg=messages(q['question'],source_ids,docs)
                expected[name]={'case_id':cid,'arm':arm,'source_ids':source_ids,
                                'source_sha256':digest(pub),
                                'question_sha256':txtsha(q['question']),
                                'v17_request_sha256':row['request_sha256'],
                                'message_sha256':digest(msg),'messages':msg}
            question_info[cid]=dict(root=root,original=q,witness_ids=witnesses)
    if (sorted(selected)!=old_plan.get('case_ids') or sorted(selected)!=proposal.get('cases')
        or set(expected)!=set(old_requests['requests']) or expected!=proposal.get('entries')
        or len(expected)!=120):
        raise ValueError('source-first roster or Qwen messages drifted')
    return question_info


def score_after_seal(info,plan,physical):
    per={arm:dict(total=0,labeled=0,missing_answer=0,literal_hits=0,strict_equals=0,
                  valid_syntactic_citations=0,foreign_citation_cases=0,
                  no_evidence_cited=0,abstain_literal_unknown=0,
                  response_tokens=0,input_tokens=0,model_cpu_ms=0)
         for arm in ARMS}
    aliases=physical['requests_by_id'];outputs=physical['physical_outputs']
    for ident,entry in plan['entries'].items():
        cid=entry['case_id'];arm=entry['arm'];g=info[cid]['original']
        row=outputs[aliases[ident]];ans=row['answer'];metrics=per[arm]
        metrics['total']+=1
        target=g.get('answer')
        valid=target is not None and bool(str(target).strip())
        if valid:
            metrics['labeled']+=1
            gold=str(target).strip().casefold();pred=ans.strip().casefold()
            metrics['literal_hits']+=int(gold in pred)
            metrics['strict_equals']+=int(ans==str(target))
        else:metrics['missing_answer']+=1
        mentions=[int(x) for x in CITE.findall(ans)]
        metrics['foreign_citation_cases']+=int(any(m>len(entry['source_ids']) or m<=0 for m in mentions))
        metrics['valid_syntactic_citations']+=int(bool(mentions) and all(0<m<=len(entry['source_ids']) for m in mentions))
        metrics['no_evidence_cited']+=int(not entry['source_ids'] and bool(mentions))
        metrics['abstain_literal_unknown']+=int(ans.strip().casefold()=='unknown')
        metrics['response_tokens']+=row['output_tokens']
        metrics['input_tokens']+=row['input_tokens']
        # Single physical token stream may serve several logical actions.
        # Charge shared compute ONCE to the canonical first alias.
        metrics['model_cpu_ms']+=row['cpu_ms'] if ident==row['logical_ids'][0] else 0
    return per


def audit(original_path,public_path,owner_path,hidden_path,old_plan_path,annotation_path,
          old_requests_path,qwen_plan_path,private_path,journal_path,model_dir,spec_path,out_path):
    original=secure_read(original_path)
    if sha256(Path(original_path).read_bytes()).hexdigest()!=SOURCE_SHA:
        raise ValueError('not the genuine complete original LoCoMo corpus')
    p=list(map(secure_read,(public_path,owner_path,hidden_path,old_plan_path,annotation_path,old_requests_path,qwen_plan_path)))
    info=sourceaudit(original,*p)
    from v19_qwen_material import verify_snapshot
    spec=secure_read(spec_path);model_digest=verify_snapshot(model_dir,spec)
    private=secure_read(private_path,22_000_000)
    if (type(private) is not dict or set(private)!=EXPECTED_PRIVATE_FIELDS
        or private.get('schema')!=SCHEMA+'.physical-private' or
        private.get('plan_sha256')!=p[-1]['plan_sha256'] or
        private.get('model_spec_sha256')!=model_digest or
        private.get('model_weights_sha256')!=spec['files_sha256']['model.safetensors'] or
        private.get('original_archive_sha256')!=ARCHIVE_SHA or
        private.get('source_roots')!=list(ROOTS) or
        private.get('model_repo')!=REPO or private.get('model_revision')!=REVISION or
        private.get('original_pretrained_qwen3_executed') is not True or
        private.get('physical_model_host_independently_signed') is not False or
        private.get('task_semantic_correctness_independently_verified') is not False or
        private.get('publisher_witness_sufficiency_human_certified') is not False or
        private.get('model_token_budget_matched_to_135m') is not False or
        private.get('current_135m_model_executed_by_this_runner') is not False or
        private.get('ndu_fbsde_solves')!=0 or private.get('authority')!='DENY_ALL' or
        private.get('production_authorized') is not False or private.get('decision')!='HOLD_NO_GO'):
        raise ValueError('Qwen physical/authority status unsupported')
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(model_dir,local_files_only=True,
                                             trust_remote_code=False,use_fast=True)
    expected_token_map={}
    for ident,entry in sorted(p[-1]['entries'].items()):
        ids=tokenizer.apply_chat_template(entry['messages'],tokenize=True,
                                           add_generation_prompt=True,enable_thinking=False)
        if not isinstance(ids,list) or not 1<=len(ids)<=2048 or any(type(x) is not int or x<0 for x in ids):
            raise ValueError('Qwen original reference tokenization changed')
        key=digest(ids)
        expected_token_map[ident]=key
    if (expected_token_map!=private.get('requests_by_id') or
        private.get('requests_by_id_sha256')!=digest(expected_token_map) or
        private.get('logical_arm_requests')!=120 or
        private.get('actual_unique_qwen_requests')!=96 or
        set(private.get('physical_outputs',{}))!=set(expected_token_map.values()) or
        private.get('physical_outputs_sha256')!=digest(private['physical_outputs'])):
        raise ValueError('original Qwen raw answer roster incomplete')
    path=Path(journal_path)
    if (path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode)&0o077 or
        sha256(path.read_bytes()).hexdigest()!=private.get('journal_sha256')):
        raise ValueError('unverifiable fsynced journal file')
    def pairs(parts):
        obj={}
        for k,v in parts:
            if k in obj:raise ValueError('duplicate private start event')
            obj[k]=v
        return obj
    starts=[json.loads(line,object_pairs_hook=pairs) for line in path.read_text().splitlines()]
    if len(starts)!=96 or [row['token_ids_sha256'] for row in starts]!=sorted(private['physical_outputs']):
        raise ValueError('missing/reordered source-first physical call')
    forward_count=0
    for start in starts:
        key=start['token_ids_sha256'];row=private['physical_outputs'][key]
        ids=[x for x in expected_token_map if expected_token_map[x]==key]
        if (type(start) is not dict or set(start)!=EXPECTED_START_FIELDS or
            type(row) is not dict or set(row)!=EXPECTED_MODEL_OUTPUT_FIELDS or
            start.get('model_spec_sha256')!=model_digest or
            start.get('plan_sha256')!=p[-1]['plan_sha256'] or
            start.get('logical_ids')!=ids or
            start.get('representative_id')!=ids[0] or
            start.get('physical_model_generation_started') is not True or
            start.get('authority')!='DENY_ALL' or
            row.get('logical_ids')!=ids or row.get('representative_id')!=ids[0] or
            row.get('input_sha256')!=key or row.get('input_tokens')!=start['input_tokens'] or
            type(row.get('generated_token_ids')) is not list or
            not 1<=len(row['generated_token_ids'])<=24 or
            any(type(t) is not int or t<0 for t in row['generated_token_ids']) or
            row.get('output_tokens')!=len(row['generated_token_ids']) or
            row.get('answer')!=tokenizer.decode(row['generated_token_ids'],skip_special_tokens=True) or
            row.get('answer_sha256')!=txtsha(row['answer']) or
            type(row.get('observed_root_model_forwards')) is not int or
            not 1<=row['observed_root_model_forwards']<=len(row['generated_token_ids'])+1 or
            type(row.get('cpu_ms')) is not int or row['cpu_ms']<0 or
            type(row.get('wall_ms')) is not int or row['wall_ms']<0):
            raise ValueError('unbound model token generation, forward or physical output')
        forward_count+=row['observed_root_model_forwards']
    if forward_count!=private.get('measured_root_forward_calls'):
        raise ValueError('wrong physical reference forward count')
    metrics=score_after_seal(info,p[-1],private)
    if any(row['total']!=30 or row['labeled']+row['missing_answer']!=30 for row in metrics.values()):
        raise ValueError('incorrect original fixed reviewer denominators')
    report={'schema':SCHEMA+'.independent-postseal-summary',
            'original_publisher_sha256':SOURCE_SHA,'original_source_roots':10,
            'original_source_first_questions':30,'original_reference_logical_requests':120,
            'original_reference_physical_requests':96,
            'reference_material_sha256':model_digest,
            'reference_output_sha256':private['physical_outputs_sha256'],
            'reference_forward_count':forward_count,'source_plan_sha256':p[-1]['plan_sha256'],
            'scores':metrics,'strict_equal_is_only_literal_text':True,
            'answer_substring_not_semantic_accuracy':True,
            'citation_addresses_not_entailment':True,'human_evidence_sufficiency_verified':False,
            'independent_semantic_review_verified':False,
            'model_token_budget_matched_to_135m':False,
            'source_time_prospective':False,'no_cell_learning_or_NDU_gain':True,
            'independent_host_signature':False,
            'authority':'DENY_ALL','production_authorized':False,'decision':'HOLD_NO_GO'}
    import source_first as v17
    v17.write_once(out_path,report)
    return {'questions':30,'physical_requests':96,'model_forwards':forward_count,
            'summary_sha256':digest(metrics),'decision':'HOLD_NO_GO'}


def cli():
    pa=argparse.ArgumentParser()
    for k in ('original','public','owner','hidden','v17-plan','annotation','v17-requests',
              'reference-plan','physical','starts','model-dir','model-spec','output'):
        pa.add_argument('--'+k,required=True)
    args=pa.parse_args()
    print(json.dumps(audit(*(getattr(args,x.replace('-','_')) for x in
        ('original','public','owner','hidden','v17-plan','annotation','v17-requests',
         'reference-plan','physical','starts','model-dir','model-spec','output'))),sort_keys=True))

if __name__=='__main__':cli()
