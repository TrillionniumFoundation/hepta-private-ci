"""Reproduce original reader score/citation/cost Pareto accounting; no inference."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import zipfile

MODELS={
 'qwen-3b':('event-reader-actual-48.zip','831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98'),
 'smol-1.7b':('event-reader-smol-48.zip','67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae'),
}
ARMS=('empty','hybrid','entity_time','organized','program_support','without_prerequisite')
FAIR_ARMS=('empty','hybrid','entity_time','organized')
SRC='59f9eadd5cc919359079e04442f7343838a60057'
PLAN='9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897'


def sha(raw):
 return hashlib.sha256(raw).hexdigest()


def read_archive(path, expected):
 content=path.read_bytes()
 if sha(content)!=expected:
  raise ValueError('outer archived model bytes differ')
 files={}
 with zipfile.ZipFile(path) as z:
  for item in z.infolist():
   if (item.is_dir() or item.filename in files or item.file_size>30_000_000
       or '..' in Path(item.filename).parts or item.filename.startswith('/') or '\\' in item.filename):
    raise ValueError('invalid archived member')
   files[item.filename]=z.read(item)
 pins={}
 for line in files['SHA256SUMS'].decode().splitlines():
  m=re.fullmatch(r'([0-9a-f]{64})  (?:\./)?(.+)',line)
  if m is None or m.group(2) in pins:raise ValueError('invalid manifest')
  pins[m.group(2)]=m.group(1)
 if set(pins)!=set(files)-{'SHA256SUMS'}:raise ValueError('manifest census changed')
 for n,d in pins.items():
  if sha(files[n])!=d: raise ValueError('manifest checksum mismatch: '+n)
 if files['tested-commit.txt'].decode().strip()!=SRC:raise ValueError('generating source changed')
 return files


def extract(path, expected):
 files=read_archive(path,expected)
 report=json.loads(files['run/report.json'])
 scored=json.loads(files['run/scored-answers.json'])
 raw=[json.loads(ln) for ln in files['run/raw-answers.jsonl'].decode().splitlines()]
 if len(raw)!=48 or len(scored)!=48:raise ValueError('incomplete 8x6 records')
 attempts=[(x['question_id'],x['arm']) for x in raw]
 if len(set(attempts))!=48 or set(x['arm'] for x in raw)!=set(ARMS):raise ValueError('duplicate/unknown arms')
 if len(set(x['question_id'] for x in raw))!=8:raise ValueError('wrong question count')
 for a,b in zip(raw,scored):
  if any(b.get(k)!=v for k,v in a.items()):raise ValueError('replaced original model answer/receipt')
 for arm in ARMS:
  rs=[r for r in scored if r['arm']==arm]
  aggregate=report['arms'][arm]
  if len(rs)!=8 or any(r['status']!='succeeded' for r in rs):raise ValueError('incomplete actual inference')
  assert sum(bool(r['strict_task_success']) for r in rs)==aggregate['strict_task_successes']
  assert sum(r['receipt']['input_tokens'] for r in rs)==aggregate['input_tokens']
  assert sum(r['receipt']['generated_tokens'] for r in rs)==aggregate['generated_tokens']
  assert abs(sum(r['receipt']['seconds'] for r in rs)-aggregate['measured_read_seconds']) <1e-7
 return report,scored,files


def pareto(rows):
 frontier=[]
 for a in rows:
  dominated=[]
  for b in rows:
   if b['arm']==a['arm']:continue
   better=(b['strict_correct']>=a['strict_correct'] and b['correct_with_full_chain']>=a['correct_with_full_chain'] and b['input_tokens']<=a['input_tokens'] and b['measured_reader_seconds']<=a['measured_reader_seconds'])
   strict=(b['strict_correct']>a['strict_correct'] or b['correct_with_full_chain']>a['correct_with_full_chain'] or b['input_tokens']<a['input_tokens'] or b['measured_reader_seconds']<a['measured_reader_seconds'])
   if better and strict: dominated.append(b['arm'])
  frontier.append((a['arm'],dominated))
 return dict(non_dominated=[a for a,d in frontier if not d],dominated={a:d for a,d in frontier if d})


def build(root):
 formal=json.loads((root/'memorycell_citation_delivery/historical-event-citation-chain-20261011.json').read_text())
 assert formal['generating_commit']==SRC and formal['pinned_plan_sha256']==PLAN and formal['real_model_generations']==96
 out=dict(schema='hepta.memory-frozen-reader.multimetric-pareto.v1', generating_commit=SRC,pinned_original_plan_sha256=PLAN,
  metrics=['8-case strict task success','8-case correctly answered with connected cited public event path','complete prompt input tokens','sum of reader seconds'],
  reader_only=True,human_semantic_adjudication=False,independent_source_families=0,production_accepted=False,
  test_window='eight previously exposed authored development cases',model_pairs={})
 for name,(file,digest) in MODELS.items():
  report,scored,files=extract(root/file,digest)
  formal_model=formal['models'][name]
  assert formal_model['archive_sha256']==digest and formal_model['attempted']==48
  arms=[]
  for arm in ARMS:
   original=report['arms'][arm];cit=formal_model['by_arm'][arm]
   assert cit['strict_task_success']==original['strict_task_successes']
   arms.append(dict(arm=arm,eligible_annotation_blind=arm in FAIR_ARMS,attempts=8,
    strict_correct=original['strict_task_successes'],correct_with_full_chain=cit['correct_with_public_event_chain_connected'],
    correct_with_program_declared_support_citations=cit['correct_with_full_program_declared_citations'],
    correct_without_any_citation=cit['correct_without_citation_marker'],
    input_tokens=original['input_tokens'],generated_tokens=original['generated_tokens'],
    measured_reader_seconds=round(original['measured_read_seconds'],6),
    raw_model_generation_sha256=sha(files['run/raw-answers.jsonl']),scored_model_answer_sha256=sha(files['run/scored-answers.json'])))
  fair=[x for x in arms if x['eligible_annotation_blind']]
  out['model_pairs'][name]=dict(archive_zip_sha256=digest,manifest_items=len(files)-1,model_answer_count=len(scored),arms=arms,
   descriptive_pareto=pareto(fair))
 return out


if __name__=='__main__':
 p=argparse.ArgumentParser()
 p.add_argument('--root',type=Path,default=Path('/mnt/data'))
 p.add_argument('--out',type=Path,default=Path('/mnt/data/memorycell_frozen_reader_multimetric_pareto_20261011.json'))
 a=p.parse_args()
 result=build(a.root)
 a.out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
 print(json.dumps({m:{'frontier':v['descriptive_pareto']['non_dominated'],'dominated':v['descriptive_pareto']['dominated'],'counts':[(a['arm'],a['strict_correct'],a['correct_with_full_chain'],a['input_tokens']) for a in v['arms']]} for m,v in result['model_pairs'].items()},indent=2))
