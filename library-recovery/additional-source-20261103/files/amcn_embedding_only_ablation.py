"""Actual pretrained MiniLM word-embedding-only + linear Semantic Head pilot.

NON-AUTHORIZING. This does not execute the 6-layer BERT contextual Encoder,
HF Tokenizer, full Reader, official benchmark, or independent human reviewer.
It is an explicit, low-resource representation-ablation control over existing
publisher weak support, not a model superiority or production proof.

Stages: prepare (weak TRAIN supervision, label-blind heldout shortlists),
train (TRAIN labels only; freeze predictions and actual Safetensors weights),
score (read withheld weak support after model outputs are fixed).
"""
from __future__ import annotations
import argparse,collections,hashlib,json,os,pathlib,re,time
import numpy as np
import torch
from safetensors import safe_open
from safetensors.torch import save_file
import sys
sys.path.insert(0,'/mnt/data/amcn-local')
from amcn_core import Evidence,digest,require
from amcn_source_first import lexical_shortlist

SRC=pathlib.Path('/mnt/data/amcn_verified_locomo_public.json')
MODEL=pathlib.Path('/mnt/data/amcn-encoder-checkpoint/model.safetensors')
VOCAB=pathlib.Path('/mnt/data/amcn-encoder-checkpoint/vocab.txt')
DATA_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
WEIGHT_SHA='53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
VOCAB_SHA='07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3'
GEN='locomo-archive-'+DATA_SHA[:12]
SCOPE='amcn.historical.locomo.shadow'
SCHEMA='hepta.amcn.pretrained-embedding-table-only-shadow.v1'
SEED=17;STEPS=64;BATCH=4;LR=0.005


def file_sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()

def write_new(path,data):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as f:
  raw=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'
  f.write(raw);f.flush();os.fsync(f.fileno())
 return file_sha(path)

def read(path):
 return json.loads(pathlib.Path(path).read_bytes())

def history(sample):
 fam='locomo:'+sample['sample_id'];docs=[]
 for sess in sorted((k for k in sample['conversation'] if k.startswith('session_') and k[8:].isdigit()),key=lambda v:int(v[8:])):
  for turn in sample['conversation'][sess]:
   text=f"{turn['speaker']}: {turn['text']}"
   if turn.get('blip_caption'):text+='\n[provided image caption; not observed pixels] '+turn['blip_caption']
   raw=text.encode()
   if not 1<=len(raw)<=1200:continue
   docs.append(Evidence(fam+'/'+turn['dia_id'],fam,SCOPE,1,text,hashlib.sha256(raw).hexdigest(),GEN))
 return docs

def prepare(output):
 assert file_sha(SRC)==DATA_SHA
 data=json.loads(SRC.read_bytes())
 families=sorted(['locomo:'+s['sample_id'] for s in data],key=digest)
 n=len(families);tr=max(4,n*6//10);sel=min(n-2,max(tr+1,n*8//10))
 splits={f:('train' if i<tr else 'select' if i<sel else 'future_a' if i==sel else 'future_b') for i,f in enumerate(families)}
 public=[];train={};withheld={};support={};shortlists={}
 for sample in data:
  fam='locomo:'+sample['sample_id'];docs=history(sample);by_id={d.evidence_id:d for d in docs}
  qs=sorted([(fam+'/q'+str(i),q['question'],{fam+'/'+v for v in q.get('evidence',[])}) for i,q in enumerate(sample['qa'])],key=lambda x:digest(x[0]))
  eligible=[(qid,q,refs) for qid,q,refs in qs if len(q.encode())<=512 and docs]
  role=splits[fam]
  if role=='train':
   selected=next(((qid,q,refs) for qid,q,refs in eligible if any(d.evidence_id in refs for d in docs) and any(d.evidence_id not in refs for d in docs)),None)
   if selected is None:continue
   qid,q,refs=selected
   for label,item in ((1,next(d for d in docs if d.evidence_id in refs)),
                      (0,next(d for d in docs if d.evidence_id not in refs))):
    rid=digest([qid,item.evidence_id,'train'])
    public.append({'row_id':rid,'qid':qid,'family':fam,'split':'train','question':q,'doc_id':item.evidence_id,'doc':item.text,'doc_sha256':item.content_sha256})
    train[rid]=label
   other=next(((qid,q,refs) for qid,q,refs in eligible if qid!=selected[0]),None)
   if other is None:continue
   qid,q,refs=other;role='retention'
  else:
   qid,q,refs=eligible[0]
  plan=lexical_shortlist(q,docs,scope=SCOPE,generation=GEN,top_k=16)
  shortlists[qid]=plan
  support[qid]=sorted(refs)
  for sid in plan['ranked_source_ids']:
   item=by_id[sid];rid=digest([qid,sid,role])
   public.append({'row_id':rid,'qid':qid,'family':fam,'split':role,'question':q,'doc_id':sid,'doc':item.text,'doc_sha256':item.content_sha256})
   withheld[rid]=int(sid in refs)
 output=pathlib.Path(output);output.mkdir(parents=True,exist_ok=False)
 pub={'schema':SCHEMA+'.public','data_sha256':DATA_SHA,'rows':public,'shortlists':shortlists,'generation':GEN}
 gold={'schema':SCHEMA+'.withheld','public_digest':digest(pub),'row_labels':withheld,'publisher_support':support}
 write_new(output/'public.json',pub);write_new(output/'train.json',train);write_new(output/'sealed-gold.json',gold)
 stats={'rows':len(public),'train_rows':len(train),'nontrain_rows':len(withheld),'queries':len(shortlists),'source_family_count':len(families)}
 write_new(output/'preparation-metadata.json',{'schema':SCHEMA,'metadata':stats,'source_labels_are_publisher_weak':True,'production_accepted':False})
 return stats

TOKEN_PATTERN=re.compile(r'[A-Za-z0-9]+|[^\w\s]',re.UNICODE)
def tokenizer(vocab):
 ids={word:i for i,word in enumerate(vocab)};unk=ids.get('[UNK]',100)
 def encode(text):
  out=[]
  for tok in TOKEN_PATTERN.findall(text.lower()):
   if tok in ids:out.append(ids[tok]);continue
   if len(tok)>100:out.append(unk);continue
   i=0;parts=[];ok=True
   while i<len(tok):
    found=None;end=len(tok)
    while end>i:
     sub=tok[i:end] if i==0 else '##'+tok[i:end]
     if sub in ids:found=ids[sub];break
     end-=1
    if found is None:ok=False;break
    parts.append(found);i=end
   out.extend(parts if ok else [unk])
  return out or [unk]
 return encode

def train(public_path,labels_path,out):
 assert file_sha(MODEL)==WEIGHT_SHA and file_sha(VOCAB)==VOCAB_SHA
 pub=read(public_path);labels=read(labels_path)
 assert pub['schema']==SCHEMA+'.public'
 assert set(labels)=={r['row_id'] for r in pub['rows'] if r['split']=='train'}
 assert set(labels.values())=={0,1}
 vocab=VOCAB.read_text().splitlines();tokenize=tokenizer(vocab)
 with safe_open(str(MODEL),framework='pt',device='cpu') as s:
  embedding=s.get_tensor('embeddings.word_embeddings.weight').detach().float()
 assert embedding.shape==(30522,384)
 def pool(text):
  indices=torch.tensor(tokenize(text),dtype=torch.long)
  return embedding[indices].mean(0)
 cache={};features=[]
 start=time.perf_counter()
 with torch.no_grad():
  for row in pub['rows']:
   q=row['question'];d=row['doc']
   qv=cache.setdefault(('q',q),pool(q));dv=cache.setdefault(('d',row['doc_sha256']),pool(d))
   features.append(torch.cat((qv,dv,(qv-dv).abs(),qv*dv)))
 x=torch.stack(features).contiguous();idx=[i for i,r in enumerate(pub['rows']) if r['split']=='train']
 y=torch.tensor([labels[pub['rows'][i]['row_id']] for i in idx],dtype=torch.long)
 with torch.random.fork_rng(devices=[]):
  torch.manual_seed(SEED)
  frozen=torch.nn.Linear(x.shape[1],2).eval()
 learned=torch.nn.Linear(x.shape[1],2)
 learned.load_state_dict(frozen.state_dict())
 optim=torch.optim.AdamW(learned.parameters(),lr=LR,weight_decay=0)
 generator=torch.Generator().manual_seed(SEED)
 initial={k:v.clone() for k,v in frozen.state_dict().items()}
 train_start=time.perf_counter()
 for i in range(STEPS):
  ix=torch.randint(len(idx),(BATCH,),generator=generator)
  logits=learned(x[idx][ix]);loss=torch.nn.functional.cross_entropy(logits,y[ix])
  optim.zero_grad(set_to_none=True);loss.backward()
  torch.nn.utils.clip_grad_norm_(learned.parameters(),1.)
  optim.step()
 learned.eval()
 assert all(torch.equal(v,frozen.state_dict()[k]) for k,v in initial.items())
 with torch.no_grad():
  a=frozen(x).softmax(-1)[:,1].tolist();b=learned(x).softmax(-1)[:,1].tolist()
 out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=False)
 save_file({k:v.detach().contiguous() for k,v in learned.state_dict().items()},str(out/'trained-head.safetensors'))
 pred=[{'row_id':r['row_id'],'split':r['split'],'family':r['family'],'qid':r['qid'],'doc_id':r['doc_id'],
        'frozen_relevance':a[i],'trained_relevance':b[i]} for i,r in enumerate(pub['rows'])]
 write_new(out/'predictions.json',pred)
 receipt={'schema':SCHEMA+'.candidate','source_public_sha256':file_sha(pathlib.Path(public_path)),
          'train_only_labels_sha256':file_sha(pathlib.Path(labels_path)),
          'model_embedding_tensor_source_sha256':WEIGHT_SHA,'vocab_sha256':VOCAB_SHA,
          'head_sha256':file_sha(out/'trained-head.safetensors'),
          'predictions_sha256':file_sha(out/'predictions.json'),
          'actual_trainable_parameters':sum(p.numel() for p in learned.parameters()),
          'optimizer_steps':STEPS,'batch':BATCH,'seed':SEED,
          'representation':'original-bert-embedding-table-mean-pool-custom-tokenizer-no-transformer-layers',
          'training_seconds':time.perf_counter()-train_start,
          'features_and_train_seconds':time.perf_counter()-start,
          'torch_version':torch.__version__,
          'independent_task_capability_proven':False,'production_accepted':False}
 write_new(out/'receipt.json',receipt)
 return receipt

def score(public_path,withheld_path,model_dir,output):
 pub=read(public_path);gold=read(withheld_path);mdl=pathlib.Path(model_dir)
 rec=read(mdl/'receipt.json');pred=read(mdl/'predictions.json')
 assert rec['source_public_sha256']==file_sha(pathlib.Path(public_path))
 assert gold['public_digest']==digest(pub)
 assert rec['predictions_sha256']==file_sha(mdl/'predictions.json')
 assert rec['head_sha256']==file_sha(mdl/'trained-head.safetensors')
 assert len(pred)==len(pub['rows']) and set(gold['row_labels'])=={r['row_id'] for r in pub['rows'] if r['split']!='train'}
 mapped={r['row_id']:r for r in pred};outcomes=[]
 for qid,plan in sorted(pub['shortlists'].items()):
  rows=[r for r in pub['rows'] if r['qid']==qid and r['split']!='train']
  assert [r['doc_id'] for r in rows]==plan['ranked_source_ids']
  support=set(gold['publisher_support'][qid])
  for r in rows:
   assert gold['row_labels'][r['row_id']]==int(r['doc_id'] in support)
  def winner(key):
   row=max(rows,key=lambda r:mapped[r['row_id']][key]);return row['doc_id'] in support
  outcomes.append({'qid_sha256':digest(qid),'split':rows[0]['split'],'family':rows[0]['family'],
   'lexical_top1':int(rows[0]['doc_id'] in support),
   'frozen_top1':int(winner('frozen_relevance')),
   'trained_top1':int(winner('trained_relevance')),
   'support_in_shortlist':sum(r['doc_id'] in support for r in rows),
   'publisher_weak_support_count':len(support)})
 summary={}
 for split in ('select','future_a','future_b','retention'):
  subset=[o for o in outcomes if o['split']==split]
  summary[split]={'queries':len(subset),'lexical_hits':sum(o['lexical_top1'] for o in subset),
    'frozen_hits':sum(o['frozen_top1'] for o in subset),'trained_hits':sum(o['trained_top1'] for o in subset),
    'source_first_any_hit':sum(o['support_in_shortlist']>0 for o in subset)}
 report={'schema':SCHEMA+'.weak-outcome','source_sha256':DATA_SHA,'read_only_publisher_support':True,
  'original_pretrained_embedding_tensor_is_real':True,'BERT_six_transformer_layers_executed':False,
  'Reader_model_calls':0,'human_sufficient_evidence_review':False,
  'trained_head_byte_sha256':rec['head_sha256'],
  'by_split':summary,'outcomes':outcomes,'no_independent_future_calendar_evidence':True,
  'effective_independent_samples_qualified':False,'production_accepted':False}
 write_new(output,report)
 return report

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
 a=s.add_parser('prepare');a.add_argument('out')
 a=s.add_parser('train');a.add_argument('public');a.add_argument('labels');a.add_argument('out')
 a=s.add_parser('score');a.add_argument('public');a.add_argument('gold');a.add_argument('model_dir');a.add_argument('out')
 args=p.parse_args();func={'prepare':prepare,'train':train,'score':score}[args.cmd]
 if args.cmd=='prepare':r=func(args.out)
 elif args.cmd=='train':r=func(args.public,args.labels,args.out)
 else:r=func(args.public,args.gold,args.model_dir,args.out)
 print(json.dumps(r,sort_keys=True,default=str))
if __name__=='__main__':main()
