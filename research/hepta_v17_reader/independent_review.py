"""Source-independent authoring of a private original Reader trace reviewer.

Consumes real frozen answer text only after the physical producer has sealed.
Never reports weak publisher substring as semantic correctness, grounding, or
independently human-certified witness sufficiency. No model run in this module.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import stat
import time

from original_135m import BPE, verify, WEIGHTS, TOKENIZER, CONFIG, file_sha

CORPUS_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
ARCHIVE_SHA='07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
SCHEMA='hepta.v17.original-locomo-reader.shadow.v1'
ROOTS=('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44','conv-47','conv-48','conv-49','conv-50')
ARMS=('none','retrieved','annotated','lesion')
LEX=re.compile(r"[\w]+(?:['’][\w]+)?",re.UNICODE)
STOP=set('a an the of in on by to for from and or is are was were as that which what where when who how whose with at did does do have has had it its this those these their he she his her they but about after before been being than more most'.split())
CITATIONS=re.compile(r'\[E(\d+)\]')


def canon(o):return json.dumps(o,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()


def digest(o):return sha256(canon(o)).hexdigest()


def string_sha(s):return sha256(s.encode()).hexdigest()


def read(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or not 0<p.stat().st_size<16_000_000:
        raise ValueError('independent reviewer unsafe source')
    def no_duplicate(pairs):
        obj={}
        for k,v in pairs:
            if k in obj:raise ValueError('duplicate field')
            obj[k]=v
        return obj
    return json.loads(p.read_bytes(),object_pairs_hook=no_duplicate,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite field')))


def rank(question,rows):
    q=Counter(w.lower() for w in LEX.findall(question) if len(w)>1 and w.casefold() not in STOP)
    docs=[Counter(w.casefold() for w in LEX.findall(r['text']) if len(w)>1 and w.casefold() not in STOP) for r in rows]
    n=len(docs);freq=Counter(x for d in docs for x in d)
    avg=sum(map(lambda d:sum(d.values()),docs))/n or 1
    def score(d):
        l=sum(d.values());s=0.0
        for x,c in q.items():
            if x in d:
                s+=min(2,c)*math.log1p((n-freq[x]+.5)/(freq[x]+.5))*d[x]*2.2/(d[x]+1.2*(.25+.75*l/avg))
        return s
    scores=[score(d) for d in docs]
    return [rows[i]['id'] for i in sorted(range(n),key=lambda i:(-scores[i],rows[i]['id']))]


def prompt(question,ids,docs):
    s=['<|im_start|>system','Answer concisely from provided evidence only. If not supported, say unknown. Cite the evidence [E1], [E2], etc.',
       '<|im_end|>','<|im_start|>user','Question: '+question,'Evidence:']
    if ids:
        s.extend('[E'+str(i)+'] '+ref+' '+docs[ref]['speaker']+': '+docs[ref]['text'][:240]
                 for i,ref in enumerate(ids,1))
    else:s.append('(no evidence provided)')
    s.extend(['<|im_end|>','<|im_start|>assistant',''])
    # Distinct authored prompt builder, identical UTF-8 user-facing bytes.
    return '\n'.join(s)


def audit(original_path,public_path,owner_path,hidden_path,plan_path,annotation_path,
          request_path,physical_path,starts_path,model_root,output_path):
    start=time.process_time()
    original=read(original_path)
    if sha256(Path(original_path).read_bytes()).hexdigest()!=CORPUS_SHA:
        raise ValueError('original publisher source tampered')
    public,owner,hidden,plan,annot,requests,physical=map(read,(
        public_path,owner_path,hidden_path,plan_path,annotation_path,request_path,physical_path))
    if (type(original) is not list or len(original)!=10 or type(public) is not list or
        owner.get('schema')!=SCHEMA+'.owner' or owner.get('source_sha256')!=CORPUS_SHA or
        owner.get('archive_sha256')!=ARCHIVE_SHA or owner.get('public_sha256')!=digest(public) or
        owner.get('hidden_sha256')!=digest(hidden) or owner.get('roots')!=list(ROOTS) or
        plan.get('schema')!=SCHEMA+'.plan' or plan.get('plan_sha256')!=digest({k:v for k,v in plan.items() if k!='plan_sha256'}) or
        plan.get('owner_sha256')!=digest(owner) or plan.get('public_sha256')!=digest(public) or
        plan.get('arms')!=list(ARMS) or plan.get('model_weight_sha256')!=WEIGHTS or
        plan.get('n_cases')!=30 or plan.get('max_tokens')!=24 or
        annot.get('schema')!=SCHEMA+'.annotation-only' or annot.get('packet_sha256')!=digest({k:v for k,v in annot.items() if k!='packet_sha256'}) or
        annot.get('original_hidden_sha256')!=digest(hidden) or annot.get('plan_sha256')!=plan['plan_sha256'] or
        annot.get('answer_fields_exposed') is not False or
        requests.get('schema')!=SCHEMA+'.model-requests' or requests.get('requests_sha256')!=digest(requests.get('requests')) or
        requests.get('annotation_packet_sha256')!=annot['packet_sha256'] or requests.get('plan_sha256')!=plan['plan_sha256'] or
        requests.get('publisher_answer_text_never_supplied') is not True or
        physical.get('schema')!=SCHEMA+'.original-135m-physical' or physical.get('plan_sha256')!=plan['plan_sha256'] or
        physical.get('requests_sha256')!=requests['requests_sha256'] or
        physical.get('model_sha256')!=WEIGHTS or physical.get('tokenizer_sha256')!=TOKENIZER or physical.get('model_config_sha256')!=CONFIG or
        physical.get('original_archive_sha256')!=ARCHIVE_SHA or physical.get('source_from_original_archive') is not True or
        physical.get('reader_original_weights_executed') is not True or physical.get('original_torch_fp32_research_path') is not True or
        physical.get('official_hf_parity_verified') is not False or physical.get('stronger_reference_reader_executed') is not False or
        physical.get('independent_host_attestation_verified') is not False or
        physical.get('decision')!='HOLD_NO_GO' or physical.get('production_authorized') is not False or
        owner.get('authority')!='DENY_ALL' or plan.get('authority')!='DENY_ALL' or requests.get('authority')!='DENY_ALL'):
        raise ValueError('unverified original source, model, or research boundary')
    # Fresh source extraction independently crosses the original public/gold split.
    if {s['sample_id'] for s in original}!=set(ROOTS):raise ValueError('original roots missing')
    corpus={s['sample_id']:s for s in original}
    pub_by={s['id']:s for s in public}
    if set(pub_by)!=set(ROOTS) or set(hidden)!=set(ROOTS):raise ValueError('incorrect original-root population')
    expected_cases=[]
    expected_requests={}
    for root in ROOTS:
        orig=corpus[root];record=pub_by[root]
        docs=[dict(id=x['dia_id'],speaker=x['speaker'],text=x['text'])
              for key,segment in orig['conversation'].items() if key.startswith('session_') and type(segment) is list
              for x in segment]
        if docs!=record['utterances'] or len(orig['qa'])!=len(record['questions']):
            raise ValueError('unbound original question/utterance bytes')
        gold_group={}
        for i,q in enumerate(orig['qa']):
            qid=f'{root}/q{i}'
            if record['questions'][i]!=dict(id=qid,question=q['question']):raise ValueError('publisher question injection')
            gold_group[qid]=dict(answer=q.get('answer'),support_ids=q.get('evidence'),category=q.get('category'))
        if hidden[root]!=gold_group:raise ValueError('altered publisher restricted answers')
        cases=sorted((f'{root}/q{i}' for i in range(len(orig['qa']))),
                     key=lambda cid:(string_sha(cid),cid))[:3]
        expected_cases.extend(cases)
        for cid in cases:
            index=int(cid.split('/q')[1]);q=orig['qa'][index];question=q['question']
            references={d['id']:d for d in docs}
            witness=list(dict.fromkeys(q['evidence']))[:3]
            if not witness or any(k not in references for k in witness):
                raise ValueError('incorrect original publisher witness')
            if annot['source_ids'].get(cid)!=witness:raise ValueError('annotation-only source edit')
            selected=dict(none=[],retrieved=rank(question,docs)[:3],annotated=witness,lesion=witness[1:])
            for arm,source_ids in selected.items():
                name=cid+'|'+arm
                text=prompt(question,source_ids,references)
                expected_requests[name]=dict(case_id=cid,arm=arm,source_ids=source_ids,
                    question_sha256=string_sha(question),source_sha256=digest(record),
                    request_sha256=string_sha(text),prompt=text)
    if (sorted(expected_cases)!=plan['case_ids'] or
            set(expected_requests)!=set(requests['requests']) or
            set(annot['source_ids'])!=set(expected_cases)):
        raise ValueError('source-first selection changed or missing arms')
    # Corpus provenance and exact prompt identity, not simply trusted hash labels.
    if expected_requests!=requests['requests']:
        raise ValueError('incorrect Reader input bytes or source citations')
    verify(model_root)
    tokenizer=BPE(model_root)
    unique={}
    for rid,r in expected_requests.items():
        idx=tokenizer.encode(r['prompt'])
        if len(idx)>1000 or len(idx)+24>1024:raise ValueError('tokenizer context clipped')
        key=r['request_sha256']
        if key in unique and unique[key]['tokens']!=idx:
            raise ValueError('identical prompt has different tokenizer inputs')
        unique.setdefault(key,dict(tokens=idx,ids=[]))['ids'].append(rid)
    original_outputs=physical.get('physical_outputs')
    if (type(original_outputs) is not dict or set(original_outputs)!=set(unique) or
            physical.get('physical_unique_requests')!=len(unique) or
            physical.get('logical_arm_requests')!=len(expected_requests) or
            physical.get('outputs_sha256')!=digest(original_outputs)):
        raise ValueError('false actual original model execution census')
    starts=Path(starts_path)
    if (not starts.is_file() or starts.is_symlink() or starts.stat().st_size>100_000 or
        stat.S_IMODE(starts.stat().st_mode)&0o077!=0 or
        physical.get('journal_sha256')!=file_sha(starts)):
        raise ValueError('missing or exposed original forward start journal')
    attempts=[]
    for row in starts.read_text().splitlines():
        x=json.loads(row)
        if x.get('model_sha256')!=WEIGHTS or x.get('started_real_forward') is not True or x.get('production_authorized') is not False:
            raise ValueError('untrusted original model start record')
        attempts.append(x)
    if len(attempts)!=len(unique) or [x['prompt_sha256'] for x in attempts]!=sorted(unique):
        raise ValueError('missing interrupted original physical forward')
    total_forwards=0
    for attempt in attempts:
        key=attempt['prompt_sha256'];token_ids=unique[key]['tokens'];out=original_outputs[key]
        generated=out.get('output_ids')
        if (out.get('representative_id')!=sorted(unique[key]['ids'])[0] or
            attempt.get('representative_id')!=out['representative_id'] or
            attempt.get('input_tokens')!=len(token_ids) or attempt.get('token_ids_sha256')!=digest(token_ids) or
            out.get('token_ids_sha256')!=digest(token_ids) or out.get('input_tokens')!=len(token_ids) or
            type(generated) is not list or not 1<=len(generated)<=24 or
            any(type(t) is not int or not 0<=t<49152 for t in generated) or
            out.get('output_tokens')!=len(generated) or
            tokenizer.decode(generated)!=out.get('original_answer') or
            out.get('answer_sha256')!=string_sha(out['original_answer']) or
            type(out.get('cpu_ms')) is not int or out['cpu_ms']<0 or
            type(out.get('wall_ms')) is not int or out['wall_ms']<0):
            raise ValueError('tampered original token/original model answer or cost')
        total_forwards+=len(generated)+(1 if generated[-1]!=2 else 0)
    if physical.get('model_forward_calls')!=total_forwards:
        raise ValueError('original model forward count inconsistent')
    summaries={arm:dict(count=0,substring=0,exact=0,citations=0,invalid_citations=0,
                        publisher_support_cited=0,source_annotations=0,input_tokens=0,
                        output_tokens=0,model_prompts_unique=set(),abstentions=0,
                        answer_output_changed_vs_none=0) for arm in ARMS}
    weak={}
    for cid in sorted(expected_cases):
        root=cid.split('/')[0]
        qgold=hidden[root][cid]
        ans=str(qgold['answer']) if qgold['answer'] is not None else 'None'
        baseline=None
        for arm in ARMS:
            req=expected_requests[cid+'|'+arm]
            out=original_outputs[req['request_sha256']]
            answer=out['original_answer']
            if arm=='none':baseline=answer
            cited=[int(t) for t in CITATIONS.findall(answer)]
            valid=[c for c in cited if 1<=c<=len(req['source_ids'])]
            support=set(qgold['support_ids'])
            cited_s=set(req['source_ids'][i-1] for i in valid)
            stats=summaries[arm]
            stats['count']+=1
            # These are weak publisher-target text proxies, not human answer evaluation.
            hit=bool(ans.strip()) and ans.casefold() in answer.casefold()
            exact=ans.strip().casefold()==answer.strip().casefold()
            stats['substring']+=int(hit);stats['exact']+=int(exact)
            stats['citations']+=len(valid);stats['invalid_citations']+=len(cited)-len(valid)
            stats['publisher_support_cited']+=len(cited_s&support)
            stats['source_annotations']+=len(support)
            stats['input_tokens']+=out['input_tokens'];stats['output_tokens']+=out['output_tokens']
            stats['model_prompts_unique'].add(req['request_sha256'])
            stats['abstentions']+=int(answer.strip().lower() in ('unknown','none','not enough information'))
            stats['answer_output_changed_vs_none']+=int(arm!='none' and answer!=baseline)
        weak[cid]=digest({arm:original_outputs[expected_requests[cid+'|'+arm]['request_sha256']]['answer_sha256'] for arm in ARMS})
    report=[]
    for arm in ARMS:
        x=summaries[arm]
        report.append(dict(arm=arm,cases=x['count'],weak_literal_answer_substrings=x['substring'],
             strict_full_answer_equality=x['exact'],observed_citations=x['citations'],
             out_of_evidence_citations=x['invalid_citations'],publisher_support_address_citations=x['publisher_support_cited'],
             publisher_support_addresses=x['source_annotations'],input_tokens=x['input_tokens'],
             output_tokens=x['output_tokens'],unique_prompt_sha=len(x['model_prompts_unique']),
             literal_abstentions=x['abstentions'],changed_vs_no_evidence=x['answer_output_changed_vs_none']))
    result=dict(schema=SCHEMA+'.independent-postseal-source-score',original_corpus_sha256=CORPUS_SHA,
         original_archive_sha256=ARCHIVE_SHA,plan_sha256=plan['plan_sha256'],
         physical_outputs_sha256=physical['outputs_sha256'],
         exact_ten_historical_original_roots=True,source_first_cases=len(expected_cases),
         untrained_model_pretrained_weights_used=True,
         physical_unique_model_requests=len(unique),logical_arm_requests=len(expected_requests),
         original_model_forward_calls=total_forwards,reader_wall_ms=physical['model_wall_ms'],
         reader_cpu_ms=physical['model_cpu_ms'],summary=report,summary_sha256=digest(report),
         private_original_answer_receipt_sha256=digest(weak),
         selected_question_population_small=True,source_independent_future_windows=0,
         original_dataset_existing_publisher_answers_only=True,
         publisher_support_is_not_independent_sufficiency=True,
         absolute_weak_literal_scores_not_semantic_accuracy=True,
         original_reader_not_hf_operator_parity_verified=True,
         stronger_reference_reader_executed=False,
         independently_signed_model_host_and_semantic_review=False,
         true_NDU_FBSDE=False,full_lifecycle_comparison=False,
         learned_cell_improvement=False,production_authorized=False,
         model_selected=False,authority='DENY_ALL',decision='HOLD_NO_GO',
         review_cpu_ms=round(1000*(time.process_time()-start)))
    output=Path(output_path)
    if output.exists() or output.is_symlink():raise FileExistsError('review output already exists')
    with output.open('x',encoding='utf-8') as f:
        json.dump(result,f,sort_keys=True,ensure_ascii=False,allow_nan=False);f.write('\n')
    return result


def main():
    ap=argparse.ArgumentParser()
    for arg in ('original','public','owner','hidden','plan','annotation','requests','physical','starts','reader-dir','output'):
        ap.add_argument('--'+arg,required=True)
    a=ap.parse_args()
    result=audit(a.original,a.public,a.owner,a.hidden,a.plan,a.annotation,
        a.requests,a.physical,a.starts,a.reader_dir,a.output)
    print(json.dumps({k:result[k] for k in ('schema','source_first_cases','physical_unique_model_requests',
        'logical_arm_requests','original_model_forward_calls','summary','decision')},sort_keys=True))

if __name__=='__main__':main()
