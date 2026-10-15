"""Physical archived Reader capacity probe on two original CPython fault witnesses.

Read-only research, no learning, no real bug repair, no HF parity certification.
Same exact original frozen weights/tokenizer, prompt and tool permissions across arms.
"""
from __future__ import annotations
import argparse,ast,hashlib,json,math,os,re,time
from pathlib import Path
from collections import Counter
from physical_original_reader import ReaderTokenizer,ReaderModel,chat,WEIGHT_SHA,TOKENIZER_SHA,ORIGINAL_LOGITS_SHA,digest,filehash,require
import torch

MODULE_SHA='8486d3c54d5ab5a8468703239287e60127d7f2159f5ae6652b33a456a3716444'
TEST_SHA='347061ba9071babdcabcc74d4d1c2581a567f9d788864e3c4d958c2c3c009907'
SCHEMA='hepta.memory.original-cpython-frozen-reader-physical-diagnostic.v1'
CONDS=('no_source','lexical_top2','original_crossfile_oracle','declaration_lesion')
TASKS=(
 ('header-fault','An original CPython HTTP test expected an outgoing Content-length header of 42 but observed 41. Which HTTPConnection method handles this faulty operation?', 'putheader','HeaderTests','test_putheader'),
 ('send-fault','An original CPython HTTP test expected socket bytes to remain intact but observed corrupted transmitted bytes. Which HTTPConnection method performs this faulty operation?', 'send','BasicTest','test_send'),
)
CANON=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'

def build_plan(module_path:Path,test_path:Path):
 raw=module_path.read_bytes();test=test_path.read_bytes()
 require(digest(raw)==MODULE_SHA and digest(test)==TEST_SHA,'original SHA-pinned Git evidence required')
 src=raw.decode(); code=src.splitlines();t=ast.parse(src)
 cls=next(c for c in t.body if isinstance(c,ast.ClassDef) and c.name=='HTTPConnection')
 names=('send','putheader','putrequest','request','_send_request','endheaders')
 modules={c.name:c for c in cls.body if isinstance(c,ast.FunctionDef) and c.name in names}
 require(set(modules)==set(names),'source candidate census drift')
 docs=[]
 for name in names:
  fn=modules[name]
  # Original unmodified declaration plus subsequent source. Never synthesize summaries.
  excerpt='\n'.join(code[fn.lineno-1:min(fn.end_lineno,fn.lineno+9)])
  excerpt=excerpt[:420]
  docs.append(dict(kind='original_implementation',symbol=name,source_line=fn.lineno,source_sha256=digest(excerpt.encode()),text=excerpt))
 tst=ast.parse(test);testlines=test.decode().splitlines()
 testclasses={c.name:c for c in tst.body if isinstance(c,ast.ClassDef) and c.name in ('HeaderTests','BasicTest')}
 require(len(testclasses)==2,'test classes drift')
 # No execution/test target identity is written to individual reader requests.
 corpus_tokens=[set(re.findall(r'[A-Za-z0-9_]+',d['text'].lower())) for d in docs]
 df=Counter(w for s in corpus_tokens for w in s)
 def selected(question):
  query=set(re.findall(r'[A-Za-z0-9_]+',question.lower()))
  scores=[]
  for d,toks in zip(docs,corpus_tokens):
   score=sum(math.log((len(docs)+1)/(df[w]+0.5)) for w in query&toks)
   scores.append((score,d))
  return [d for _,d in sorted(scores,key=lambda x:(-x[0],x[1]['source_sha256']))[:2]]
 cases=[]
 for task,question,target,cn,tm in TASKS:
  testfn=next(x for x in testclasses[cn].body if isinstance(x,ast.FunctionDef) and x.name==tm)
  test_excerpt='\n'.join(testlines[testfn.lineno-1:min(testfn.end_lineno,testfn.lineno+7)])[:420]
  oracle=[dict(kind='original_upstream_test',source_line=testfn.lineno,source_sha256=digest(test_excerpt.encode()),text=test_excerpt),next(d for d in docs if d['symbol']==target)]
  # All markers and doc order retained, but querying a declaration can no
  # longer establish actual premise support once its declaration is removed.
  lesion=[]
  for d in oracle:
   lines=d['text'].splitlines()
   mutated='\n'.join(s for s in lines if target not in s and not (d['kind']=='original_implementation' and re.match(r'\s*def ',s)))
   mutated=mutated or '[REDACTED SOURCE EXCERPT]'
   lesion.append(dict(d,source_sha256=digest(mutated.encode()),text=mutated))
  conds={
   'no_source':[dict(kind='missing',text='[NO SOURCE EVIDENCE]',source_sha256=digest(b'[NO SOURCE EVIDENCE]'))],
   'lexical_top2':selected(question),
   'original_crossfile_oracle':oracle,
   'declaration_lesion':lesion,
  }
  require(len(conds['lexical_top2'])==2 and len(oracle)==2 and len(lesion)==2,'bounded pair only')
  # Keep gold out of the public model plan. Original mechanical program-task
  # labels are independently derived after answers have already been sealed.
  cases.append(dict(task=task,root='python/cpython',question=question,conditions=conds,
                    original_code_sha256=MODULE_SHA, original_test_sha256=TEST_SHA))
 return dict(schema=SCHEMA,cases=cases,conditions=list(CONDS),reader_weights_sha256=WEIGHT_SHA,
             reader_tokenizer_sha256=TOKENIZER_SHA,original_source_sha256=MODULE_SHA,
             original_tests_sha256=TEST_SHA,source_count=6,
             model_context_limit=1024,max_new_tokens=32,max_evidence_sources=2,
             frozen_reader_untrained=True,training_steps=0,
             identical_reader_weights_and_prompt=True,tools_allowed=False,
             independent_source_roots=1,independent_human_semantic_review=False,
             complete_lifecycle_tco=None,real_program_repair_success=None,production_qualified=False)

def verify_plan(plan,source,test):
 require(CANON(plan)==CANON(build_plan(source,test)),'frozen plan content is not source derived')
 require(list(plan['conditions'])==list(CONDS) and len(plan['cases'])==2,'plan census drift')
 for c in plan['cases']:
  require(set(c['conditions'])==set(CONDS),'condition drift')
  for a,docs in c['conditions'].items():
   require(len(docs)<=2 and all(d['source_sha256']==digest(d['text'].encode()) for d in docs),'evidence hash drift')
 return True

def run(plan,stage,out):
 require(not out.exists(),'original model journal overwrite prohibited')
 require(filehash(stage/'model.safetensors')==WEIGHT_SHA and filehash(stage/'tokenizer.json')==TOKENIZER_SHA,'weight mismatch')
 torch.set_num_threads(3)
 reader=ReaderModel(stage);tok=ReaderTokenizer(stage/'tokenizer.json')
 # Actual original model material: reference fingerprint is not asserted equal
 # without independent official operator/tokenizer parity proof.
 logits=reader.forward([1,420,35,177],reset=True)
 fingerprint=digest(logits.contiguous().numpy().tobytes())
 require(torch.topk(logits,5).indices.tolist()==[122,123,237,113,133],'original model numerical top-5 differs from archived reference')
 out.mkdir(parents=True,exist_ok=False)
 rows=[]
 with (out/'original-generation.jsonl').open('x',encoding='utf8') as f:
  for case in plan['cases']:
   for condition in CONDS:
    evidence=[d['text'] for d in case['conditions'][condition]]
    prompt=chat(case['question'],evidence)
    ids=tok.encode(prompt)
    require(0<len(ids)+32<=1024,'original model context ceiling exceeded, no truncation')
    item=dict(task=case['task'],condition=condition,question_sha256=digest(case['question'].encode()),
              evidence_sha256=digest(CANON(case['conditions'][condition])),
              input_token_digest=digest(json.dumps(ids,separators=(',',':')).encode()),
              input_tokens=len(ids),max_output_tokens=32,model_sha256=WEIGHT_SHA,
              tokenizer_sha256=TOKENIZER_SHA,model_reference_top5_fingerprint_matched=True,
              model_exact_reference_logits_sha256_match=(fingerprint==ORIGINAL_LOGITS_SHA))
    start=time.perf_counter()
    try:
     tokens=reader.generate(ids,max_new_tokens=32)
     item.update(status='succeeded',output_token_ids=tokens,output_tokens=len(tokens),answer=tok.decode(tokens),
                 answer_sha256=digest(tok.decode(tokens).encode()))
    except Exception as exc:
     item.update(status='failed',output_tokens=0,answer=None,error_type=type(exc).__name__)
    item['inference_seconds']=round(time.perf_counter()-start,6)
    rows.append(item)
    f.write(json.dumps(item,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n');f.flush();os.fsync(f.fileno())
 return dict(journal_sha256=filehash(out/'original-generation.jsonl'),attempts=len(rows),
             completed=sum(x['status']=='succeeded' for x in rows),
             original_weights_verified=True,original_tokenizer_verified=True,
             original_numerical_top5_verified=True,logit_sha256=fingerprint,
             exact_historical_fp32_logits_parity=(fingerprint==ORIGINAL_LOGITS_SHA),
             genuine_physical_frozen_reader_calls=sum(x['status']=='succeeded' for x in rows),
             unverified_official_hf_parity=True,
             learned_memory_gain=None,production_qualified=False)

def parse_ans(s):
 # Primary strict canonical output, no forgiving repair of raw model text.
 if not isinstance(s,str):return None
 m=re.fullmatch(r'\s*(?:HTTPConnection\.)?([a-z_]+)(?:\s+\[E([12])\])?\s*\.?\s*',s)
 return (m.group(1),int(m.group(2)) if m.group(2) else None) if m else None

def score(plan,journal,source,test,sha,stage):
 require(verify_plan(plan,source,test),'plan invalid')
 require(filehash(journal)==sha,'original raw inference journal independently pinned SHA differs')
 data=journal.read_bytes()
 require(data.endswith(b'\n') and len(data.splitlines())==len(plan['cases'])*len(CONDS),'complete original model journal required')
 def unique(pairs):
  out={}
  for k,v in pairs:
   require(k not in out,'duplicate JSON key');out[k]=v
  return out
 def no_constant(value):
  raise ValueError('nonfinite original JSON value: '+value)
 rows=[json.loads(x,object_pairs_hook=unique,parse_constant=no_constant)
       for x in data.splitlines()]
 tokenizer=ReaderTokenizer(stage/'tokenizer.json')
 census=set();results=[]
 # An independent source-backed fixed task label; not returned to model before scoring.
 originals={x[0]:x[2] for x in TASKS}
 for row in rows:
  key=(row['task'],row['condition'])
  require(key not in census,'duplicate original inference')
  census.add(key)
  c=next((c for c in plan['cases'] if c['task']==row['task']),None)
  require(c is not None and row['condition'] in CONDS,'unregistered model request')
  cond=row['condition'];ev=c['conditions'][cond]
  request_ids=tokenizer.encode(chat(c['question'],[d['text'] for d in ev]))
  require(row.get('input_token_digest')==digest(json.dumps(request_ids,separators=(',',':')).encode())
          and row.get('input_tokens')==len(request_ids),
          'original v1 Reader input token/prompt mismatch')
  require(row['question_sha256']==digest(c['question'].encode()) and row['evidence_sha256']==digest(CANON(ev)), 'altered original model request')
  require(row.get('status') in ('succeeded','failed') and row.get('model_sha256')==WEIGHT_SHA and row.get('tokenizer_sha256')==TOKENIZER_SHA,'unbound model status')
  require(type(row.get('input_tokens')) is int and 0<row['input_tokens']<=1024 and row.get('max_output_tokens')==32 and type(row.get('output_tokens')) is int and 0<=row['output_tokens']<=32,'token budget drift')
  require(type(row.get('inference_seconds')) in (float,int)
          and 0 <= row['inference_seconds'] < 7200,
          'invalid original model inference time')
  if row['status']=='succeeded':
   output_ids=row.get('output_token_ids')
   require(isinstance(output_ids,list) and 0<len(output_ids)==row['output_tokens']
           and all(type(i) is int and 0<=i<49152 for i in output_ids),
           'original output token IDs inconsistent')
   decoded=tokenizer.decode(output_ids)
   require(type(row.get('answer')) is str and row['answer']==decoded
           and digest(decoded.encode())==row.get('answer_sha256'),
           'original output material inconsistent')
  else:require(row.get('answer') is None and row['output_tokens']==0,'failed model generation credited')
  parsed=parse_ans(row.get('answer'))
  tgt=originals[row['task']]
  match=bool(parsed and parsed[0]==tgt)
  cited=bool(parsed and parsed[1] and 1<=parsed[1]<=len(ev))
  declaration=bool(cited and ev[parsed[1]-1].get('symbol')==tgt and re.search(r'\bdef\s+'+re.escape(tgt)+r'\b',ev[parsed[1]-1]['text']))
  results.append(dict(task=row['task'],condition=cond,strict_correct=match,original_source_premise_supported=declaration,strict_correct_cited=match and declaration,
                      response_sha256=row.get('answer_sha256'),status=row['status'],input_tokens=row['input_tokens'],output_tokens=row['output_tokens'],inference_seconds=row['inference_seconds']))
 require(census=={(c['task'],a) for c in plan['cases'] for a in CONDS},'incomplete attempt census')
 by={a:[r for r in results if r['condition']==a] for a in CONDS}
 return dict(schema=SCHEMA+'.independent-score.v1',source_sha256=MODULE_SHA,test_sha256=TEST_SHA,
             source_and_test_from_original_git=True,original_journal_sha256=sha,
             original_reader_sha256=WEIGHT_SHA,original_tokenizer_sha256=TOKENIZER_SHA,
             by_condition={a:dict(attempts=len(rs),strict_correct=sum(r['strict_correct'] for r in rs),strict_supported=sum(r['strict_correct_cited'] for r in rs),model_calls=sum(r['status']=='succeeded' for r in rs),input_tokens=sum(r['input_tokens'] for r in rs),output_tokens=sum(r['output_tokens'] for r in rs)) for a,rs in by.items()},
             original_rows=results,roots=['python/cpython'],independent_roots=1,
             official_HF_parity_certified=False,independent_human_semantic_review=False,
             real_program_repair_success=None,learned_memory_incremental_gain=None,
             full_lifecycle_cost=None,production_qualified=False)

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
 q=s.add_parser('prepare');q.add_argument('--source',required=True,type=Path);q.add_argument('--tests',required=True,type=Path);q.add_argument('--out',required=True,type=Path)
 q=s.add_parser('generate');q.add_argument('--plan',required=True,type=Path);q.add_argument('--source',required=True,type=Path);q.add_argument('--tests',required=True,type=Path);q.add_argument('--stage',required=True,type=Path);q.add_argument('--out',required=True,type=Path)
 q=s.add_parser('score');q.add_argument('--plan',required=True,type=Path);q.add_argument('--source',required=True,type=Path);q.add_argument('--tests',required=True,type=Path);q.add_argument('--stage',required=True,type=Path);q.add_argument('--journal',required=True,type=Path);q.add_argument('--journal-sha256',required=True);q.add_argument('--out',required=True,type=Path)
 a=p.parse_args()
 if a.cmd=='prepare':
  require(not a.out.exists(),'no plan overwrite');a.out.write_bytes(CANON(build_plan(a.source,a.tests)))
  print(json.dumps(dict(plan_sha256=filehash(a.out),cases=2,conditions=4)))
 elif a.cmd=='generate':
  plan=json.loads(a.plan.read_bytes());verify_plan(plan,a.source,a.tests)
  receipt=run(plan,a.stage,a.out)
  (a.out/'generation-report.json').write_bytes(CANON(receipt));print(json.dumps(receipt,sort_keys=True))
 else:
  require(not a.out.exists(),'no scorer overwrite');report=score(json.loads(a.plan.read_bytes()),a.journal,a.source,a.tests,a.journal_sha256,a.stage);a.out.write_bytes(CANON(report));print(json.dumps(report['by_condition'],sort_keys=True))
if __name__=='__main__':main()
