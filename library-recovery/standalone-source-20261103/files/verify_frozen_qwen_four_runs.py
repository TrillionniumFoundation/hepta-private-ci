"""Source-byte and paired-outcome verification of four previously generated Qwen runs.

Research-only; no model inference or independent human entailment judgement.
"""
import hashlib
import json
import re
import stat
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path('/mnt/data')
PINS = {
 'A': ('8250698244417eb14994518af05fa6f79e783066', '7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f', '7e390bddfb1c59e0bb82999b01747a180eb1ec1f84d9f863a536dd036ec483f1',267),
 'B': ('eba9af092cca1c2875552ffaea2219678143a73c', 'b4cf1346ce4c5b1625cdc57845bcca33fcf82f84340433b602d76258c10c1138', '4c64e9c01bef56d0f311e633af53c7a246102e7083a272122286fb7ff66085a3',267),
 'C': ('c24fad24b65984a6255a8854c6714c141911ff79', '2d71f40e553e7d28cad9d8e16803f52b7a99e771b5bf54f55c89bc9468702107', 'fe710be3f987e34ec3cda48be37509e20a01b48db090907c98ce33cfff198225',38),
 'D': ('e0e413d670be8982b9986a119696c6ca164ca518', 'd59560882e217d8772e4044ec33b8cdb10f5297f19b0a6e03e53266407c839a0', '9a4dfb20f0ab5bb6de6ed577e7787d3faa8c02f5a842198a5b1b1eafced2ea53',300),
}
PLAN='9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897'
MODEL='f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225'
CAL={'k1','k2','k3','k4','k6'}
EVAL={'selected_k','hybrid_k4','hybrid_k6','hybrid_k4_reversed','single_hop','entity_time','organized','program_support','empty'}
SCORE_FIELDS={'parsed_identifier','strict_task_success','required_sources_covered','procedure_verification'}

def sha(raw): return hashlib.sha256(raw).hexdigest()

def loads(raw):
 def unique(pairs):
  result={}
  for k,v in pairs:
   if k in result: raise ValueError('duplicate json key')
   result[k]=v
  return result
 def bad(x): raise ValueError('nonfinite JSON')
 return json.loads(raw,object_pairs_hook=unique,parse_constant=bad)

def validate_zip(path,expected_sha,expected_members=None):
 raw=path.read_bytes()
 assert sha(raw)==expected_sha,(path,'outer hash mismatch')
 z=zipfile.ZipFile(path)
 names=z.namelist()
 assert len(set(names))==len(names)
 for item in z.infolist():
  p=PurePosixPath(item.filename)
  assert item.filename and not item.filename.startswith('/') and '..' not in p.parts
  assert not item.is_dir() and not stat.S_ISLNK(item.external_attr>>16)
 if expected_members is not None:
  assert len(names)==expected_members+1,(path,len(names))
  content=z.read('SHA256SUMS').decode().splitlines()
  listed={}
  for line in content:
   match=re.fullmatch(r'([0-9a-f]{64})  (?:\./)?(.+)',line)
   assert match,line
   digest,name=match.groups()
   assert name not in listed
   listed[name]=digest
  assert set(listed)==set(names)-{'SHA256SUMS'}
  for name,digest in listed.items(): assert sha(z.read(name))==digest,(path,name)
 return z

runs={};summaries={};member_checks=0
for name,(commit,full,replay,members) in PINS.items():
 z=validate_zip(ROOT/f'qwen-four-run-{name}-full.zip',full,members)
 y=validate_zip(ROOT/f'qwen-four-run-{name}-replay.zip',replay)
 member_checks+=members
 assert z.read('tested-commit.txt').decode().strip()==commit
 rp='shard-replay.json' if 'shard-replay.json' in y.namelist() else 'receipt.json'
 receipt=loads(y.read(rp))
 assert receipt['generating_commit']==commit and receipt['original_plan_sha256']==PLAN
 assert receipt['model_identity']==MODEL and receipt['production_accepted'] is False
 frozen=loads(z.read('calibration/frozen-policy.json'))
 assert frozen['selected_k']==1 and frozen['source_commit']==commit
 assert frozen['reader_identity']==MODEL and frozen['original_test_plan_sha256']==PLAN
 phase_data={};summary={}
 for phase,expected_arms in (('calibration',CAL),('evaluation',EVAL)):
  raw=[loads(line) for line in z.read(f'{phase}/raw-answers.jsonl').splitlines()]
  scored=loads(z.read(f'{phase}/scored-answers.json'))
  report=loads(z.read(f'{phase}/report.json'))
  expected=40 if phase=='calibration' else 72
  assert len(raw)==len(scored)==expected
  census={(r['question_id'],r['arm']) for r in raw}
  assert len(census)==expected
  assert {r['arm'] for r in raw}==expected_arms
  assert len({r['question_id'] for r in raw})==8
  assert all(r['status']=='succeeded' for r in raw)
  assert all('strict_task_success' not in r for r in raw)
  for actual,saved in zip(raw,scored):
   assert {k:v for k,v in saved.items() if k not in SCORE_FIELDS}==actual
  assert report['raw_answers_sha256']==sha(z.read(f'{phase}/raw-answers.jsonl'))
  rows={(phase,r['question_id'],r['arm']):(r,score) for r,score in zip(raw,scored)}
  phase_data.update(rows)
  if phase=='evaluation':
   stats=report['success_by_arm']
   chains=report['formal_citation_chain']['by_arm']
   for arm in sorted(expected_arms):
    good=sum(score['strict_task_success'] is True for (ph,q,a),(r,score) in rows.items() if a==arm)
    assert good==stats[arm]['strict_success']==chains[arm]['strict_task_success']
    tokens=sum(r['receipt']['input_tokens'] for (ph,q,a),(r,score) in rows.items() if a==arm)
    assert tokens==stats[arm]['input_tokens']
    summary[arm]={'correct':good,'input_tokens':tokens,'full_program_citations':chains[arm]['correct_with_full_program_declared_citations']}
 runs[name]=phase_data
 summaries[name]=summary
 assert receipt['evaluation']['attempts']==72 and receipt['calibration']['attempts']==40
keys=set(runs['A'])
assert len(keys)==112
for name,rows in runs.items(): assert set(rows)==keys
unstable=[];task_flips=[]
for key in sorted(keys):
 rows=[runs[n][key] for n in 'ABCD']
 originals=[r[0] for r in rows]
 assert len({tuple(r['selected']) for r in originals})==1,(key,'selected drift')
 assert len({r['candidate_digest'] for r in originals})==1
 assert len({r['receipt']['reader_identity'] for r in originals})==1
 assert len({r['receipt']['input_tokens'] for r in originals})==1
 assert len({r['receipt']['input_ids_digest'] for r in originals})==1
 assert all(r['receipt']['delivered_evidence']==originals[0]['receipt']['delivered_evidence'] for r in originals)
 out={(r['answer'],r['receipt']['generated_ids_digest']) for r in originals}
 tasks={scored['strict_task_success'] for _,scored in rows}
 if len(out)>1: unstable.append(key)
 if len(tasks)>1: task_flips.append(key)
assert len(unstable)==13,(len(unstable),unstable)
assert len(task_flips)==2,task_flips
for n in 'ABCD':
 assert summaries[n]['organized']['correct']==8
 assert summaries[n]['entity_time']['correct']==8
 assert summaries[n]['organized']['full_program_citations']==4
 assert summaries[n]['entity_time']['full_program_citations']==4
 assert summaries[n]['organized']['input_tokens']==5179
 assert summaries[n]['entity_time']['input_tokens']==5752
result={
 'schema':'memorycell.external-frozen-qwen-fourrun-secondary-check.v1',
 'generating_source_pins':{n:PINS[n][0] for n in 'ABCD'},
 'downloaded_archives':8,
 'outer_zip_sha256_verified':8,
 'inner_full_archive_files_verified':member_checks,
 'original_model_calls':sum(len(x) for x in runs.values()),
 'calibration_calls':160,
 'evaluation_calls':288,
 'identical_prompt_input_positions':112,
 'cross_host_output_variation_positions':len(unstable),
 'cross_host_task_success_flip_positions':len(task_flips),
 'different_task_success_positions':[{'stage':x[0],'question_id':x[1],'arm':x[2]} for x in task_flips],
 'per_run':summaries,
 'organization_incremental_success_over_full_path':{n:summaries[n]['organized']['correct']-summaries[n]['entity_time']['correct'] for n in 'ABCD'},
 'organization_incremental_full_chain_over_full_path':{n:summaries[n]['organized']['full_program_citations']-summaries[n]['entity_time']['full_program_citations'] for n in 'ABCD'},
 'development_only':True,
 'new_language_model_inference':0,
 'independent_semantic_entailment_judgement':False,
 'production_accepted':False,
}
out=ROOT/'frozen_qwen_four_run_secondary_verification.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('per_run','generating_source_pins')},indent=2))
print('JSON:',out)
