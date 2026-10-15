"""Forward-only v2 fixed-prompt control: format adherence, not new memory gain.

The v1 frozen source/evidence plan is unchanged. This separately frozen profile
MUST NOT be pooled with v1 results, and its labels remain in independent scorer.
"""
from __future__ import annotations
import argparse,json,os,re,time
from pathlib import Path
import torch
import study_program_capacity as core
from physical_original_reader import ReaderModel,ReaderTokenizer,WEIGHT_SHA,TOKENIZER_SHA,digest,filehash,require

PROFILE='hepta.memory.original-cpython-reader-format-intervention.v2'
SYSTEM=('You are inspecting original source snippets for one failing HTTP test. '
        'Return EXACTLY one answer in the form HTTPConnection.method [E1] or '
        'HTTPConnection.method [E2], with the citation number that contains '
        'the original method definition. If you cannot find the declaration '
        'in the snippets, return the single word unknown. '
        'Do not add explanations, quotes, or extra words.')

def chat_v2(question,evidence):
 require(len(evidence) in (1,2) and all(len(e.encode())<=640 for e in evidence),'evidence bounds')
 context='\n'.join(f'[E{i}] {value}' for i,value in enumerate(evidence,1))
 return f'<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{context}\nQuestion: {question}<|im_end|>\n<|im_start|>assistant\n'

def protocol(plan_sha):
 return dict(schema=PROFILE, original_plan_sha256=plan_sha,
             original_reader_weights_sha256=WEIGHT_SHA, original_tokenizer_sha256=TOKENIZER_SHA,
             frozen_system_prompt=SYSTEM, candidate_answer_shape='HTTPConnection.method [E#] or unknown',
             all_arms_same_reader_prompt_and_output_ceiling=True,
             output_ceiling=32,reader_tools_allowed=False,task_count=2,conditions=list(core.CONDS),
             original_answers_not_repaired=True,official_HF_operator_parity_certified=False,
             production_qualified=False)

def generate(plan,proto,stage,out):
 require(proto==protocol(digest(core.CANON(plan))),'changed frozen v2 prompt profile')
 require(not out.exists(),'no original model journal overwrite')
 torch.set_num_threads(3)
 tok=ReaderTokenizer(stage/'tokenizer.json');model=ReaderModel(stage)
 assert filehash(stage/'model.safetensors')==WEIGHT_SHA
 out.mkdir(parents=True)
 rows=[]
 with (out/'original-generation.jsonl').open('x') as f:
  for c in plan['cases']:
   for cond in core.CONDS:
    docs=c['conditions'][cond]; q=chat_v2(c['question'],[d['text'] for d in docs]); ids=tok.encode(q)
    require(len(ids)+32<=1024,'no prompt truncation')
    row=dict(protocol_sha256=digest(core.CANON(proto)),task=c['task'],condition=cond,
             model_sha256=WEIGHT_SHA,tokenizer_sha256=TOKENIZER_SHA,
             question_sha256=digest(c['question'].encode()),
             evidence_sha256=digest(core.CANON(docs)),
             input_token_digest=digest(json.dumps(ids,separators=(',',':')).encode()),
             input_tokens=len(ids),max_output_tokens=32)
    t0=time.perf_counter()
    try:
     output_ids=model.generate(ids,max_new_tokens=32)
     ans=tok.decode(output_ids)
     row.update(status='succeeded',output_token_ids=output_ids,output_tokens=len(output_ids),answer=ans,answer_sha256=digest(ans.encode()))
    except Exception as e:row.update(status='failed',output_tokens=0,answer=None,error_type=type(e).__name__)
    row['inference_seconds']=round(time.perf_counter()-t0,6)
    f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n');f.flush();os.fsync(f.fileno());rows.append(row)
 return dict(schema=PROFILE+'.physical-generation',plan_sha256=proto['original_plan_sha256'],
             protocol_sha256=digest(core.CANON(proto)),original_journal_sha256=filehash(out/'original-generation.jsonl'),
             attempted=len(rows),completed=sum(r['status']=='succeeded' for r in rows),
             genuine_original_frozen_weight_model_calls=sum(r['status']=='succeeded' for r in rows),
             prompt_intervention_not_memory_learning=True,production_qualified=False)

def rescore(plan,proto,raw_journal,original_source,original_tests,stage,expected_sha):
 core.verify_plan(plan,original_source,original_tests)
 require(proto==protocol(digest(core.CANON(plan))),'wrong v2 prompt profile')
 require(filehash(raw_journal)==expected_sha,'post-hoc raw answer alteration')
 tok=ReaderTokenizer(stage/'tokenizer.json')
 def unique_pairs(pairs):
  item={}
  for key,value in pairs:
   require(key not in item,'duplicate original JSON field')
   item[key]=value
  return item
 def reject_constant(value):
  raise ValueError('nonfinite original JSON value: '+value)
 rows=[json.loads(line,object_pairs_hook=unique_pairs,parse_constant=reject_constant)
       for line in raw_journal.read_bytes().splitlines()]
 require(len(rows)==8,'incomplete original model census')
 protocol_sha=digest(core.CANON(proto)); seen=set(); output=[]
 labels={x[0]:x[2] for x in core.TASKS}
 for row in rows:
  key=row.get('task'),row.get('condition')
  require(key not in seen,'duplicate Reader journal');seen.add(key)
  c=next((x for x in plan['cases'] if x['task']==key[0]),None)
  require(c is not None and key[1] in core.CONDS,'extra original model attempt')
  docs=c['conditions'][key[1]];question=c['question']
  ids=tok.encode(chat_v2(question,[d['text'] for d in docs]))
  require(row.get('protocol_sha256')==protocol_sha and row.get('input_token_digest')==digest(json.dumps(ids,separators=(',',':')).encode())
          and row.get('input_tokens')==len(ids) and row.get('max_output_tokens')==32
          and row.get('question_sha256')==digest(question.encode()) and row.get('evidence_sha256')==digest(core.CANON(docs))
          and row.get('model_sha256')==WEIGHT_SHA and row.get('tokenizer_sha256')==TOKENIZER_SHA,'unbound original request or model')
  require(row.get('status')=='succeeded' and type(row.get('output_tokens')) is int and 0<row['output_tokens']<=32,'missing actual generation')
  require(type(row.get('inference_seconds')) in (int,float) and 0<=row['inference_seconds']<7200,'invalid model execution timing')
  out_ids=row.get('output_token_ids')
  require(isinstance(out_ids,list) and len(out_ids)==row['output_tokens'] and all(type(i)==int and 0<=i<49152 for i in out_ids),'wrong raw token ids')
  decoded=tok.decode(out_ids)
  require(row.get('answer')==decoded and digest(decoded.encode())==row.get('answer_sha256'),'changed original answer bytes')
  parsed=core.parse_ans(decoded)
  target=labels[key[0]]
  correct=bool(parsed and parsed[0]==target)
  required=bool(parsed and parsed[1] and 1<=parsed[1]<=len(docs) and docs[parsed[1]-1].get('symbol')==target and re.search(r'\bdef\s+'+re.escape(target)+r'\b',docs[parsed[1]-1]['text']))
  abstained=decoded.strip()=='unknown'
  output.append(dict(task=key[0],condition=key[1],strict_method_correct=correct,cited_necessary_declaration=required,
                     correct_and_supported=correct and required,abstained=abstained,answer_sha256=row['answer_sha256'],
                     input_tokens=row['input_tokens'],output_tokens=row['output_tokens']))
 require(seen=={(c['task'],a) for c in plan['cases'] for a in core.CONDS},'incomplete fixed source/model census')
 return dict(schema=PROFILE+'.independent-score',raw_journal_sha256=expected_sha,
             protocol_sha256=protocol_sha,by_condition={a:dict(calls=2,strict_correct=sum(v['strict_method_correct'] for v in output if v['condition']==a),
             correct_and_supported=sum(v['correct_and_supported'] for v in output if v['condition']==a),
             unknown_abstentions=sum(v['abstained'] for v in output if v['condition']==a)) for a in core.CONDS},
             original_rows=output,source_roots=1,actual_model_calls=8,
             exact_pretrained_reference_parity_unverified=True,
             not_independent_future_cohort=True,learner_parameters_trained=False,real_program_repair_success=None,
             complete_lifecycle_tco=None,production_qualified=False)

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('freeze');a.add_argument('--plan',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
 a=sub.add_parser('run');a.add_argument('--plan',type=Path,required=True);a.add_argument('--protocol',type=Path,required=True);a.add_argument('--stage',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
 a=sub.add_parser('score');a.add_argument('--plan',type=Path,required=True);a.add_argument('--protocol',type=Path,required=True);a.add_argument('--journal',type=Path,required=True);a.add_argument('--journal-sha256',required=True);a.add_argument('--source',type=Path,required=True);a.add_argument('--tests',type=Path,required=True);a.add_argument('--stage',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
 args=p.parse_args();plan=json.loads(args.plan.read_bytes())
 if args.command=='freeze':
  require(not args.out.exists(),'no existing v2 protocol overwrite');args.out.write_bytes(core.CANON(protocol(digest(core.CANON(plan)))))
  print(json.dumps(dict(protocol_sha256=filehash(args.out))))
 else:
  proto=json.loads(args.protocol.read_bytes())
  if args.command=='run':print(json.dumps(generate(plan,proto,args.stage,args.out)))
  else:
   require(not args.out.exists(),'no score rewrite')
   report=rescore(plan,proto,args.journal,args.source,args.tests,args.stage,args.journal_sha256)
   args.out.write_bytes(core.CANON(report));print(json.dumps(report['by_condition']))
if __name__=='__main__':main()
