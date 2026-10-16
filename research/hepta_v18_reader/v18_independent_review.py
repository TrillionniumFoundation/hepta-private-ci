"""Separately authored original V18 Reader evidence/format and weak-label reviewer.

Does NOT import the V18 proposer/runner. Parent V17 original source, all token
IDs, and generated raw answer bytes are independently reopened postseal.
Never confuses publisher literal text with independent semantic correctness.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import time

import source_first as v17
# Keep the source-only test surface independent of Torch/regex/safetensors.
WEIGHTS='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKENIZER='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
CONFIG='8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'

def file_sha(p):
    h=sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

SCHEMA='hepta.v18.original-reader-prompt-serialization.shadow.v1'
REGISTERED=('plain_none','plain_annotated','role_annotated')
PLAN_FIELDS = frozenset(('schema','parent_plan_sha256','parent_requests_sha256',
    'public_sha256','owner_sha256','annotation_packet_sha256','original_corpus_sha256',
    'model_sha256','max_output_tokens','original_roots','cases','arms','proposed',
    'request_sha256','answer_text_never_read','original_publisher_answer_fields_not_used',
    'source_time_prospective','retrospective_historical_cohort',
    'human_witness_sufficiency_unverified','model_selected','nd_u_utility_not_evaluated',
    'production_authorized','authority','decision','proposal_sha256'))
PHYSICAL_FIELDS = frozenset(('schema','proposal_sha256','model_sha256',
    'tokenizer_sha256','config_sha256','model_source_digest','responses',
    'responses_sha256','journal_sha256','physical_unique_requests',
    'model_forward_calls','cpu_ms','wall_ms','real_original_model_forward',
    'model_not_HF_operator_parity','real_reference_qwen_forwards',
    'answer_quality_independently_reviewed','human_sufficiency_not_certified',
    'production_authorized','decision','authority'))
OUTPUT_FIELDS = frozenset(('representative_id','generated_token_ids','answer',
    'answer_sha256','input_sha256','input_tokens','output_tokens','cpu_ms','wall_ms'))
BASELINES=('none','annotated')
CITE=re.compile(r'\[E(\d+)\]')


def reconstructed_prompt(question,source_ids,docs,mode):
    lines=[]
    for index,address in enumerate(source_ids):
        item=docs[address]
        lines.append('[E%d] %s %s: %s' %(index+1,address,item['speaker'],item['text'][:240]))
    block='\n'.join(lines) if lines else '(no evidence provided)'
    if mode in ('plain_none','plain_annotated'):
        return ''.join(('You are given a question and evidence. Answer using only the evidence. '
                        'If the evidence is insufficient, answer unknown.\nEvidence:\n',block,
                        '\nQuestion: ',question,'\nAnswer:'))
    if mode=='role_annotated':
        return ''.join(('<|im_start|>system\nGive only the shortest answer supported by evidence. '
                        'If unknown, respond unknown. Cite an evidence marker only when available.\n',
                        '<|im_end|>\n<|im_start|>user\nEvidence:\n',block,
                        '\nQuestion: ',question,'\n<|im_end|>\n<|im_start|>assistant\n'))
    raise ValueError('unknown original frozen output arm')


def safe_read(path,cap=20_000_000):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or not 0<p.stat().st_size<cap:
        raise ValueError('unsafe/missing/large evidence')
    def unique(pairs):
        obj={}
        for k,v in pairs:
            if k in obj:raise ValueError('duplicate JSON key')
            obj[k]=v
        return obj
    return json.loads(p.read_bytes(),object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite original JSON')))


def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,allow_nan=False,
        separators=(',',':')).encode()).hexdigest()


def textsha(obj):return sha256(obj.encode()).hexdigest()


def group_scores():
    return dict(cases=0,labeled=0,missing_publisher_answer=0,literal_substring=0,
        literal_full_equal=0,citation_tokens=0,
        out_of_evidence_citation_tokens=0,support_address_citation_tokens=0,
        input_tokens=0,output_tokens=0,physical_requests=0,source_echo_prefix=0,
        answer_abstained_literal=0,strict_equal_to_old_annotated=0)


def run(public_path,owner_path,original_path,hidden_path,plan_path,annotation_path,
        prev_req_path,prev_output_path,prev_journal_path,proposal_path,physical_path,
        journal_path,reader_dir,output_path):
    # Parent original audit verifies real 135M source/Gold/selection/token/citations.
    # It does not certify an independent model host or human semantic grading.
    from original_135m import BPE, verify
    import independent_review as v17audit
    baseline_report=Path(output_path).with_name(Path(output_path).stem+'.v17-parent-audit.json')
    if baseline_report.exists():raise FileExistsError('parent audit already exists')
    validated=v17audit.audit(original_path,public_path,owner_path,hidden_path,
        plan_path,annotation_path,prev_req_path,prev_output_path,prev_journal_path,
        reader_dir,baseline_report)
    start=time.process_time()
    pub,owner,hidden,plan,annot,prev,proposal,physical=map(safe_read,(
        public_path,owner_path,hidden_path,plan_path,annotation_path,prev_req_path,
        proposal_path,physical_path))
    old=safe_read(prev_output_path)
    if (plan.get('schema')!=v17.SCHEMA+'.plan' or
        plan.get('plan_sha256')!=digest({k:v for k,v in plan.items() if k!='plan_sha256'}) or
        plan.get('source_roots')!=list(v17.ROOTS) or len(plan.get('case_ids',[]))!=30 or
        owner.get('hidden_sha256')!=digest(hidden) or
        type(proposal) is not dict or set(proposal)!=PLAN_FIELDS or
        type(physical) is not dict or set(physical)!=PHYSICAL_FIELDS or
        proposal.get('schema')!=SCHEMA+'.proposal' or
        proposal.get('proposal_sha256')!=digest({k:v for k,v in proposal.items() if k!='proposal_sha256'}) or
        proposal.get('parent_plan_sha256')!=plan['plan_sha256'] or
        proposal.get('parent_requests_sha256')!=prev.get('requests_sha256') or
        proposal.get('annotation_packet_sha256')!=annot.get('packet_sha256') or
        proposal.get('public_sha256')!=digest(pub) or
        proposal.get('owner_sha256')!=digest(owner) or
        proposal.get('original_corpus_sha256')!=v17.CORPUS_SHA or
        proposal.get('request_sha256')!=digest(proposal.get('proposed')) or
        proposal.get('arms')!=list(REGISTERED) or
        proposal.get('cases')!=plan['case_ids'] or
        proposal.get('model_sha256')!=WEIGHTS or
        proposal.get('model_selected') is not False or
        proposal.get('source_time_prospective') is not False or
        proposal.get('retrospective_historical_cohort') is not True or
        proposal.get('human_witness_sufficiency_unverified') is not True or
        proposal.get('nd_u_utility_not_evaluated') is not True or
        proposal.get('answer_text_never_read') is not True or
        proposal.get('original_publisher_answer_fields_not_used') is not True or
        proposal.get('authority')!='DENY_ALL' or
        physical.get('schema')!=SCHEMA+'.real-135m-private-output' or
        physical.get('proposal_sha256')!=proposal['proposal_sha256'] or
        physical.get('model_sha256')!=WEIGHTS or
        physical.get('tokenizer_sha256')!=TOKENIZER or
        physical.get('config_sha256')!=CONFIG or
        physical.get('model_source_digest')!=file_sha(__import__('original_135m').__file__) or
        physical.get('real_original_model_forward') is not True or
        physical.get('model_not_HF_operator_parity') is not True or
        physical.get('real_reference_qwen_forwards')!=0 or
        physical.get('answer_quality_independently_reviewed') is not False or
        physical.get('human_sufficiency_not_certified') is not True or
        physical.get('production_authorized') is not False or
        physical.get('decision')!='HOLD_NO_GO' or
        physical.get('authority')!='DENY_ALL' or
        physical.get('responses_sha256')!=digest(physical.get('responses'))):
        raise ValueError('unverifiable V17/V18 real model lineage or no-go flags')
    model_root=verify(reader_dir)
    tokenizer=BPE(model_root)
    groups={g['id']:g for g in pub};joined={}
    for cid in plan['case_ids']:
        family=groups[cid.split('/')[0]]
        docs={x['id']:x for x in family['utterances']}
        question=next((q['question'] for q in family['questions'] if q['id']==cid),None)
        if question is None:raise ValueError('publisher question missing')
        support=annot['source_ids'][cid]
        for arm in REGISTERED:
            key=cid+'|'+arm
            row=proposal['proposed'].get(key)
            ids=[] if arm=='plain_none' else support
            expected=reconstructed_prompt(question,ids,docs,arm)
            if (type(row) is not dict or set(row)!={'case_id','arm','source_ids','question_sha256',
                'source_sha256','prompt_sha256','prompt'} or
                row['case_id']!=cid or row['arm']!=arm or row['source_ids']!=ids or
                row['question_sha256']!=textsha(question) or row['source_sha256']!=digest(family) or
                row['prompt_sha256']!=textsha(expected) or row['prompt']!=expected):
                raise ValueError('original prompt source/geometry mismatch')
            toks=tokenizer.encode(expected)
            if not 1<=len(toks)<=1000 or len(toks)+24>1024:
                raise ValueError('token ids length invalid')
            if row['prompt_sha256'] in joined and joined[row['prompt_sha256']]['tokens']!=toks:
                raise ValueError('same SHA different tokenization')
            joined[row['prompt_sha256']]=dict(key=key,tokens=toks)
    if (set(proposal['proposed'])!={cid+'|'+arm for cid in plan['case_ids'] for arm in REGISTERED}
        or len(joined)!=90):raise ValueError('missing/aliased original output universe')
    new_outputs=physical['responses']
    if set(joined)!=set(new_outputs) or physical.get('physical_unique_requests')!=90:
        raise ValueError('cannot count incomplete model inferences')
    path=Path(journal_path)
    if (not path.is_file() or path.is_symlink() or path.stat().st_size>200_000 or
        stat.S_IMODE(path.stat().st_mode)&0o077 or physical.get('journal_sha256')!=file_sha(path)):
        raise ValueError('missing or insecure original start journal')
    attempts=[json.loads(z) for z in path.read_text().splitlines()]
    if len(attempts)!=90 or [a.get('prompt_sha256') for a in attempts]!=sorted(joined):
        raise ValueError('nonmonotonic/missing model start')
    forwards=0
    for event in attempts:
        key=event['prompt_sha256'];entry=joined[key];output=new_outputs[key]
        tokens=output.get('generated_token_ids')
        if (type(output) is not dict or set(output)!=OUTPUT_FIELDS or
            event.get('representative_id')!=entry['key'] or
            event.get('token_ids_sha256')!=digest(entry['tokens']) or
            event.get('model_sha256')!=WEIGHTS or event.get('actual_start') is not True or
            event.get('authority')!='DENY_ALL' or
            output.get('representative_id')!=entry['key'] or
            type(tokens) is not list or not 1<=len(tokens)<=24 or
            any(type(t) is not int or not 0<=t<49152 for t in tokens) or
            output.get('input_tokens')!=len(entry['tokens']) or
            output.get('input_sha256')!=digest(entry['tokens']) or
            output.get('output_tokens')!=len(tokens) or
            output.get('answer')!=tokenizer.decode(tokens) or
            output.get('answer_sha256')!=textsha(output['answer']) or
            type(output.get('cpu_ms')) is not int or output['cpu_ms']<0 or
            type(output.get('wall_ms')) is not int or output['wall_ms']<0):
            raise ValueError('forged pretrained model output/forward or token hash')
        forwards+=len(tokens)+(1 if tokens[-1]!=2 else 0)
    if physical.get('model_forward_calls')!=forwards:
        raise ValueError('model forward count does not match physical generated tokens')
    score={arm:group_scores() for arm in (*BASELINES,*REGISTERED)}
    pairs=defaultdict(int)
    for cid in plan['case_ids']:
        root=cid.split('/')[0];gold=hidden[root][cid]
        original_answer=gold.get('answer')
        has_gold=(original_answer is not None and str(original_answer).strip()!='')
        target=str(original_answer).strip() if has_gold else ''
        group=groups[root]
        docs={x['id']:x for x in group['utterances']}
        witness=annot['source_ids'][cid]
        old_annot_req=prev['requests'][cid+'|annotated']
        old_annot=old['physical_outputs'][old_annot_req['request_sha256']]['original_answer']
        for arm in (*BASELINES,*REGISTERED):
            if arm in BASELINES:
                req=prev['requests'][cid+'|'+arm]
                output=old['physical_outputs'][req['request_sha256']]
                answer=output['original_answer'];ids=req['source_ids']
            else:
                req=proposal['proposed'][cid+'|'+arm]
                output=new_outputs[req['prompt_sha256']]
                answer=output['answer'];ids=req['source_ids']
            s=score[arm];s['cases']+=1
            if has_gold:
                s['labeled']+=1
                s['literal_substring']+=int(target.casefold() in answer.casefold())
                s['literal_full_equal']+=int(target.casefold()==answer.strip().casefold())
            else:s['missing_publisher_answer']+=1
            s['input_tokens']+=output['input_tokens'];s['output_tokens']+=output['output_tokens']
            s['physical_requests']+=1
            citations=[int(t) for t in CITE.findall(answer)]
            s['citation_tokens']+=len(citations)
            s['out_of_evidence_citation_tokens']+=sum(c<1 or c>len(ids) for c in citations)
            s['support_address_citation_tokens']+=sum(1<=c<=len(ids) and ids[c-1] in gold['support_ids'] for c in citations)
            s['answer_abstained_literal']+=int(answer.strip().casefold() in ('unknown','no information','not enough information'))
            raw_excerpts=[docs[i]['text'][:240] for i in ids]
            s['source_echo_prefix']+=int(len(answer.strip())>=16 and any(answer.strip()[:16].casefold() in t.casefold() for t in raw_excerpts))
            s['strict_equal_to_old_annotated']+=int(answer==old_annot)
        for arm in REGISTERED:
            a=new_outputs[proposal['proposed'][cid+'|'+arm]['prompt_sha256']]['answer']
            pairs[f'{arm}/changed_vs_old_annotated']+=int(a!=old_annot)
            pairs[f'{arm}/source_root_count']+=1
    report=dict(schema=SCHEMA+'.independent-original-postseal-review',
        inherited_v17_original_report_sha256=digest(validated),
        inherited_v17_original_physical_sha256=file_sha(prev_output_path),
        previous_original_source_read_sha256=file_sha(original_path),
        new_original_physically_generated_sha256=file_sha(physical_path),
        new_original_generated_token_sha256=digest(new_outputs),
        full_original_reader_byte_and_journal_replay=True,
        proposal_sha256=proposal['proposal_sha256'],
        independent_review_cpu_ms=round(1000*(time.process_time()-start)),
        source_roots=len(v17.ROOTS),original_cases=len(plan['case_ids']),
        baseline_model_forward_calls=old['model_forward_calls'],
        genuinely_new_original_model_forward_calls=forwards,
        genuinely_new_original_unique_requests=90,
        arms=[dict(arm=arm,**score[arm]) for arm in (*BASELINES,*REGISTERED)],
        paired_changes=dict(pairs),
        model_weight_sha256=WEIGHTS,original_archive_sha256=v17.ARCHIVE_SHA,
        reported_strict_matches_not_independent_semantic_correctness=True,
        missing_answer_cases_are_unknown_not_wrong=True,
        publisher_annotation_not_independent_sufficiency=True,
        objective_and_source_time_not_prospective=True,
        no_stronger_Qwen_reference_executed=True,
        no_earned_cell_or_NDU_gain=True,
        no_operator_parity_or_model_host_signature=True,
        production_authorized=False,decision='HOLD_NO_GO',authority='DENY_ALL')
    report['summary_sha256']=digest(report['arms'])
    # Plain JSON output: do not expose source text, gold, original model answers.
    v17.write_once(output_path,report)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('public','owner','original','hidden','plan','annotation','previous',
              'previous-physical','previous-journal','proposal','physical','journal','reader-dir','out'):
        ap.add_argument('--'+k,required=True)
    a=ap.parse_args()
    result=run(a.public,a.owner,a.original,a.hidden,a.plan,a.annotation,a.previous,
        a.previous_physical,a.previous_journal,a.proposal,a.physical,a.journal,a.reader_dir,a.out)
    print(json.dumps({k:result[k] for k in ('schema','original_cases','genuinely_new_original_model_forward_calls','summary_sha256','decision')},sort_keys=True))

if __name__=='__main__':main()
