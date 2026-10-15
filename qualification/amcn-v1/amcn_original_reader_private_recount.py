"""Independent, read-only recount of 96 *previously recorded* archived Reader attempts.

No new model inference, no post-hoc substitutions, no publisher labels, no semantic
correctness or owner signatures. Count ungrounded/no-evidence responses and exact
citation syntax as diagnostic—not a memory-system win or HF operator parity.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

ORIGINAL_MODEL = '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
ORIGINAL_TOKENIZER = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
BASE_PROFILE = 'hepta.amcn.reader-evidence-sufficiency-physical.shadow.v1'
LONG_PROFILE = BASE_PROFILE + '.original-budget-ladder-64.shadow.v1'
ARMS = ('no_evidence','original_bm25_top3','publisher_annotated_witness','publisher_witness_lesion')
LONG_ARMS = ('publisher_annotated_witness','publisher_witness_lesion')
PINS = {
 'annotation': {
  'plan':'7b410e2e05b66767d8c5a67c97eee354f294b1ce8e4c8954e87cdb4ee7db4cb7',
  'seal':'8ba6e315dfcd70158c2d7b1c220411b2deee5cad062c0634c5dae66404f16692',
  'starts':'b5537988f9ea4a62e9f2efeb882154341e8f3b207c719f6d3dbc0372207f8642',
  'answers':'c3cb3cae2f8076389407b531ab58166dfd76f03fcf9fd369e71e7c6c19777993',
  'statuses':'f2394be985510658a13713a672cc09e2f2b4ec48073267ddeb7247d9e191bf41',
  'plan_name':'reader-plan.json','dir_name':'original-48-reader-attempts','cases':12,
 },
 'verbatim': {
  'plan':'8810ac2a88190fb27aded5f25920c8e0ea48ad08c1369ae67b5aed4723087b41',
  'seal':'6cdb9eb4ce4dd94eaf008f4fc85e7dc387bcec432105388ba6e2eea8c8842a89',
  'starts':'9caaf43d4219b052c27f620b6560b3d539a389d69911a2082da2fe2ee23738f2',
  'answers':'87b648412b9c41c6a926b3acd9142f98c416a53ae812e89c4de1407143e62a3f',
  'statuses':'42a29a4ff794a316d10048fa930b07000762e88c0e8d5b4925426f699a68d1e2',
  'plan_name':'verbatim-plan.json','dir_name':'original-verbatim-32-reader','cases':8,
 },
 'long': {
  'plan':'8810ac2a88190fb27aded5f25920c8e0ea48ad08c1369ae67b5aed4723087b41',
  'seal':'6c0519731a77702f44874dd01df7b724e7e1e09791dc24b677adc219ce92d069',
  'starts':'46be6cd1edf621f7589010c45f4c9eea6c934219c90bd4539e5417f8aaa4d84f',
  'answers':'d1e81d5f5d8749d5234a8de8841a45b2108e779cf6aab74328159ee2855480e2',
  'statuses':'bf0cd6cccba5d4538c74248640caaa4529ef940aa4f9af7800322be176ee988e',
  'plan_name':'verbatim-plan.json','dir_name':'original-verbatim-16-ladder64','cases':8,
 },
}
CITE = re.compile(r'\[E([0-9]+)\]')
# Conservative recognition of a *literal* abstention, not semantic quality.
ABSTAIN = re.compile(r'\b(?:unknown|insufficient (?:evidence|information)|not enough (?:evidence|information)|'
                     r'cannot (?:answer|determine)|can.t (?:answer|determine)|don.t know|'
                     r'unable to (?:answer|determine)|no (?:evidence|information)|not provided)\b',re.I)


def require(condition: bool, reason: str):
    if not condition:
        raise ValueError(reason)


def file_sha(p: Path) -> str:
    h=sha256()
    with p.open('rb') as inp:
        for b in iter(lambda:inp.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def canonical(x) -> bytes:
    return (json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()


def digest(x) -> str:
    return sha256(canonical(x)).hexdigest()


def strict_json(raw: bytes):
    def unique(pairs):
        obj={}
        for k,v in pairs:
            require(k not in obj,'duplicate JSON member')
            obj[k]=v
        return obj
    return json.loads(raw,object_pairs_hook=unique,
        parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def read_exact(path: Path, expected_sha: str, *, size_limit=20_000_000) -> bytes:
    require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=size_limit,
            'missing or unsafe externally pinned original file')
    raw=path.read_bytes()
    require(sha256(raw).hexdigest()==expected_sha, 'original external SHA pin mismatch')
    return raw


def jsonl(path: Path, expected_sha: str) -> list[dict]:
    raw=read_exact(path,expected_sha)
    require(raw.endswith(b'\n'),'torn JSONL row')
    rows=[strict_json(x) for x in raw.splitlines()]
    require(all(type(x) is dict for x in rows),'invalid journal JSONL shape')
    return rows


def validate_plan(plan, cfg, cohort):
    arms=LONG_ARMS if cohort=='long' else ARMS
    require(isinstance(plan,dict) and plan.get('profile')==BASE_PROFILE and
            plan.get('production_accepted') is False and
            plan.get('independent_future_windows')==0 and
            plan.get('publisher_support_not_independent_human_review') is True and
            plan.get('reader_sha256')==ORIGINAL_MODEL and
            plan.get('tokenizer_sha256')==ORIGINAL_TOKENIZER and
            plan.get('max_new_tokens')==24 and
            plan.get('arms')==list(ARMS), 'historical original research plan identity drift')
    cases=plan['cases']
    require(len(cases)==cfg['cases'] and len({c['case_id'] for c in cases})==len(cases),
            'incomplete or duplicated historical case cohort')
    require(len({c['family'] for c in cases})==4,'not four original retrospective families')
    if cohort != 'annotation':
        require(plan.get('publisher_answer_used_for_stress_cohort_selection') is True,
                'gold-selected eight-question cohort must stay explicitly labeled')
    else:
        require(plan.get('publisher_answer_text_ever_seen_during_prepare') is False,
                'annotation cohort had publisher answer selection')
    for case in cases:
        require(set(case['requests'])==set(ARMS),'missing original source regime')
        for arm in arms:
            req=case['requests'][arm]
            require(isinstance(req['prompt'],str) and
                    req['prompt_sha256']==sha256(req['prompt'].encode()).hexdigest() and
                    type(req['input_tokens']) is int and 0<req['input_tokens']<=1024 and
                    isinstance(req['sources'],list) and
                    len(req['sources'])==(0 if arm=='no_evidence' else 3) and
                    len(set(req['sources']))==len(req['sources']),
                    'original prompt/input/citation/source-frontier drift')
    return cases,arms


def recount(root: Path, cohort: str, tokenizer):
    cfg=PINS[cohort]
    plan=strict_json(read_exact(root/cfg['plan_name'],cfg['plan']))
    cases,arms=validate_plan(plan,cfg,cohort)
    directory=root/cfg['dir_name']
    seal=strict_json(read_exact(directory/'seal.json',cfg['seal']))
    if cohort=='long':
        fields={'starts':'starts_sha256','answers':'answers_sha256','statuses':'status_sha256'}
    else:
        fields={'starts':'starts_sha256','answers':'responses_sha256','statuses':'statuses_sha256'}
    for name,key in fields.items():
        require(seal.get(key)==cfg[name], 'original sealed journal SHA not equal external pin')
    files={name:jsonl(directory/filename,cfg[short]) for name,filename,short in (
        ('starts','starts.jsonl','starts'),('answers','raw_answers.jsonl','answers'),
        ('statuses','statuses.jsonl','statuses'))}
    n=cfg['cases']*len(arms)
    require(len(files['starts'])==len(files['statuses'])==n and
            seal.get('attempts')==(seal.get('completed') if cohort=='long' else seal.get('successes'))==n and
            seal.get('failures')==0 and len(files['answers'])==n and
            seal.get('plan_sha256')==cfg['plan'] and
            (seal.get('original_reader_sha256')==ORIGINAL_MODEL if cohort=='long'
             else seal.get('reader_sha256')==ORIGINAL_MODEL) and
            seal.get('tokenizer_sha256')==ORIGINAL_TOKENIZER and
            seal.get('production_accepted') is False, 'original attempt count/model identity drift')
    responses=[]
    metrics=Counter()
    starts=files['starts']; answers=files['answers']; statuses=files['statuses']
    for i,(case,arm) in enumerate((c,a) for c in cases for a in arms):
        req=case['requests'][arm]
        base={'index':i,'key':case['case_id']+'/'+arm,
              'request_sha256':digest(req)}
        if cohort=='long':
            base.update(model_sha256=ORIGINAL_MODEL,max_new_tokens=64)
        else:base.update(reader_sha256=ORIGINAL_MODEL)
        require(starts[i]==base and statuses[i]=={**base,'status':'success'},
                'missing/reordered/unexpected original starts or status')
        a=answers[i]
        if cohort=='long':
            tokens=a['token_ids']; text=a['text']
            require(set(a)==set(base)|{'token_ids','token_ids_sha256','text',
                   'text_sha256','input_tokens','output_tokens'} and
                   all(a[k]==v for k,v in base.items()) and
                   a['token_ids_sha256']==digest(tokens) and
                   a['text_sha256']==sha256(text.encode()).hexdigest(),
                   'tampered original long Reader answer')
        else:
            tokens=a['generated_ids']; text=a['raw_output']
            require(set(a)==set(base)|{'generated_ids','token_ids_sha256','raw_output',
                    'output_sha256','input_tokens','output_tokens'} and
                    all(a[k]==v for k,v in base.items()) and
                    a['token_ids_sha256']==digest(tokens) and
                    a['output_sha256']==sha256(text.encode()).hexdigest(),
                    'tampered original short Reader answer')
        require(isinstance(tokens,list) and 1<=len(tokens)<=(64 if cohort=='long' else 24)
                and all(type(t) is int and 0<=t<49152 for t in tokens) and
                tokenizer.decode(tokens)==text and
                a['input_tokens']==req['input_tokens'] and
                a['output_tokens']==len(tokens) and
                digest(tokenizer.encode(req['prompt']))==req['input_ids_sha256'],
                'Reader original tokenizer/answer/token budget drift')
        matches=[int(x) for x in CITE.findall(text)]
        metrics['calls']+=1;metrics['input_tokens']+=a['input_tokens'];metrics['output_tokens']+=len(tokens)
        metrics['citation_tag_count']+=len(matches)
        metrics['answers_with_citation_tag']+=int(bool(matches))
        metrics['citation_outside_delivered_evidence']+=int(any(x<1 or x>len(req['sources']) for x in matches))
        if arm=='no_evidence':
            metrics['zero_evidence_calls']+=1
            metrics['literal_abstention_observed']+=int(bool(ABSTAIN.search(text)))
            metrics['zero_evidence_nonabstentions']+=int(not ABSTAIN.search(text))
        responses.append({'case_id':case['case_id'],'arm':arm,'tokens':tokens,
                          'prompt_sha256':req['prompt_sha256']})
    return dict(metrics),responses


def audit(root: Path, tokenizer) -> dict:
    summaries={};replays={}
    for cohort in PINS:
        m,r=recount(root,cohort,tokenizer)
        summaries[cohort]=m;replays[cohort]=r
    shorts={(x['case_id'],x['arm']):x for x in replays['verbatim']}
    pref=0
    for row in replays['long']:
        before=shorts.get((row['case_id'],row['arm']))
        require(before is not None and before['prompt_sha256']==row['prompt_sha256']
                and before['tokens']==row['tokens'][:len(before['tokens'])],
                'different original Reader source, model or first 24 greedy tokens')
        pref+=1
    require(pref==16,'missing exact original 24-to-64 model pairs')
    zero=sum(s.get('zero_evidence_calls',0) for s in summaries.values())
    nonabs=sum(s.get('zero_evidence_nonabstentions',0) for s in summaries.values())
    return {'profile':'hepta.amcn.original-reader-96-private-byte-recount.no-go.v1',
            'original_model_sha256':ORIGINAL_MODEL,'original_tokenizer_sha256':ORIGINAL_TOKENIZER,
            'original_24_to_64_greedy_prefix_pairs_verified':pref,
            'original_attempts_recounted':sum(s['calls'] for s in summaries.values()),
            'all_success_status':True,'cohort_stats':summaries,
            'no_evidence_calls':zero,'no_evidence_nonabstaining_outputs':nonabs,
            'no_evidence_literal_abstention_outputs':zero-nonabs,
            'literal_abstention_is_not_semantic_certification':True,
            'tokenizer_official_HF_parity_verified':False,
            'independent_human_semantic_entailment':None,
            'model_host_independent_attestation':False,
            'publisher_answers_or_raw_dialogue_uploaded':False,
            'future_calendar_windows':0,'memorycell_learning_gain_proven':False,
            'production_accepted':False,'recommendation':'NO-GO: enforce evidence-empty abstention upstream of this Reader'}


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('--original-work',type=Path,required=True)
    cli.add_argument('--original-reader',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    x=cli.parse_args()
    require(not x.output.exists() and not x.output.is_symlink(),'create-only independent receipt')
    from amcn_original_text_reader import ArchivedByteLevelBPE
    reader=ArchivedByteLevelBPE(x.original_reader, expected_tokenizer_sha256=ORIGINAL_TOKENIZER)
    result=audit(x.original_work,reader)
    x.output.parent.mkdir(parents=True,exist_ok=True)
    with x.output.open('xb') as f:f.write(canonical(result))
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))


if __name__=='__main__':main()
