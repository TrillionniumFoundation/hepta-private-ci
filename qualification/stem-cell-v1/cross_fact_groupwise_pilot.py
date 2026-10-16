"""Fixed split experimental training: CE vs complete three-candidate question loss."""
import random,time,json,hashlib,argparse
import torch
from torch.nn import functional as F
from cross_fact_bridge import matched_reader_pair
from cross_fact_composition_transfer import source_panel,checked_panels
SEEDS=(41,47,53)
UPDATES=800

def quality(model,panel):
 with torch.no_grad():
  logits=model(*panel['features'],steps=2)
  s=logits[:,1]-logits[:,0]
  probs=s.sigmoid()
  pred=probs>.5
  labels=panel['labels'].bool()
  complete=pred.eq(labels).reshape(-1,3).all(-1).sum().item()
  top1=(s.reshape(-1,3).argmax(-1)==labels.reshape(-1,3).int().argmax(-1)).sum().item()
  correct=pred.eq(labels).sum().item()
 return {'correct':int(correct),'EM':int(complete),'top1':int(top1),'count':len(labels),'questions':len(labels)//3,'brier':float((probs-labels.float()).square().mean())}

def run(*, seeds=SEEDS, modes=('cross_fact','local'), loss_arms=('binary','binary_plus_group'), updates=UPDATES):
 torch.set_num_threads(1)
 train=source_panel('train',fact_order_seed=17)
 test=source_panel('heldout',fact_order_seed=71)
 checked_panels(train,test)
 obs=[]
 for seed in seeds:
  # Sampling entire registered question slates prevents missing alternatives.
  rng=random.Random(seed)
  groups=[rng.sample(range(90),20) for _ in range(updates)]
  streamsha=hashlib.sha256(json.dumps(groups,separators=(',',':')).encode()).hexdigest()
  for mode in modes:
   for loss_name in loss_arms:
    c,l=matched_reader_pair(input_dim=11,hidden_dim=24,seed=seed)
    model=(c if mode=='cross_fact' else l).train()
    opt=torch.optim.AdamW(model.parameters(),lr=.003,foreach=False)
    tick=time.process_time_ns()
    for group in groups:
     idx=torch.tensor([i for g in group for i in (g*3,g*3+1,g*3+2)])
     batch=tuple(t[idx] for t in train['features'])
     targets=train['labels'][idx]
     opt.zero_grad(set_to_none=True)
     logits=model(*batch,steps=2)
     binary=F.cross_entropy(logits,targets)
     scores=(logits[:,1]-logits[:,0]).reshape(-1,3)
     rank_targets=targets.reshape(-1,3).argmax(-1)
     groupwise=F.cross_entropy(scores,rank_targets)
     loss=(binary+groupwise if loss_name=='binary_plus_group' else binary)
     loss.backward();opt.step()
    model.eval().requires_grad_(False)
    row={'seed':seed,'mode':mode,'loss':loss_name,'streamsha':streamsha,'updates':updates,'examples':updates*60,'params':sum(p.numel() for p in model.parameters()),'cpu_ns':time.process_time_ns()-tick,'train':quality(model,train),'heldout':quality(model,test)}
    obs.append(row)
    print(seed,mode,loss_name,row['heldout'],flush=True)
 return obs
if __name__=='__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('--seed',type=int,choices=SEEDS)
 parser.add_argument('--mode',choices=('cross_fact','local'))
 parser.add_argument('--loss',choices=('binary','binary_plus_group'))
 parser.add_argument('--updates',type=int,default=UPDATES)
 args=parser.parse_args()
 if not 1<=args.updates<=UPDATES:parser.error('bounded updates')
 print(json.dumps(run(seeds=(args.seed,) if args.seed else SEEDS,
    modes=(args.mode,) if args.mode else ('cross_fact','local'),
    loss_arms=(args.loss,) if args.loss else ('binary','binary_plus_group'),
    updates=args.updates),sort_keys=True))
