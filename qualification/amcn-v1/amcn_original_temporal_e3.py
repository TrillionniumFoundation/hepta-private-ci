"""Original LoCoMo temporal-graph mechanism probe (TRAIN-only / SHADOW / DENY_ALL).

Real historical source text; edges encode *adjacency*, never human-validated
causality. Reuses original AMCN train_relation_router. No natural-language
Reader/strong-RAG/equal-compute gain is asserted. Separate processes:
prepare (owner source), train (TRAIN weak labels only), rank (no labels),
score (withheld retrospective publisher weak supports after original seal).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from hashlib import sha256
import json
from math import exp, isfinite, log
import os
from pathlib import Path
import re

from amcn_core import Edge, Evidence, FrozenGraph, RELATIONS, digest as owner_digest
from amcn_learning import train_relation_router

CORPUS_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
PROFILE = 'hepta.amcn.original-locomo-temporal-graph-mechanism.shadow.v1'
SPLITS = {x:'train' for x in ('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44')}
SPLITS.update({'conv-47':'select','conv-48':'select',
               'conv-49':'retrospective_heldout_a','conv-50':'retrospective_heldout_b'})
HELDOUT = ('conv-49','conv-50')
ARMS = ('bm25','temporal_fixed','temporal_learned','temporal_edge_lesion')
WORDS = re.compile(r'\w+', re.UNICODE)
SUPPORT = re.compile(r'D(\d+):0*(\d+)', re.I)
MAX_PUBLIC_BYTES = 12_000_000
READER_CALLS = 0


def sha_bytes(b):return sha256(b).hexdigest()

def canonical(d):return (json.dumps(d,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')

def put_new(p,d):
    p=Path(p)
    if p.exists() or p.is_symlink():raise ValueError('refuse overwrite original evidence')
    p.parent.mkdir(parents=True,exist_ok=True)
    raw=canonical(d)
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    fd=os.open(str(p.parent),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return sha_bytes(raw)


def pairs_unique(rows):
    out={}
    for k,v in rows:
        if k in out:raise ValueError('duplicate JSON identity')
        out[k]=v
    return out


def read_pinned(path,expected_sha,max_bytes=MAX_PUBLIC_BYTES):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or not (0<path.stat().st_size<=max_bytes):
        raise ValueError('missing unsafe or too-large original source')
    raw=path.read_bytes()
    if sha_bytes(raw)!=expected_sha:raise ValueError('external original source SHA changed')
    return json.loads(raw,object_pairs_hook=pairs_unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite input')))


def require(condition,msg):
    if not condition:raise ValueError(msg)


def sources_from_conversation(sample):
    conv=sample['conversation'];family=sample['sample_id'];out=[];sessions={}
    for key,speech in conv.items():
        m=re.fullmatch(r'session_(\d+)',key)
        if not m:continue
        session=int(m.group(1))
        require(type(speech) is list and speech,'missing original chronological session')
        session_ids=[]
        for item in speech:
            sid=item['dia_id'];text=item['text'];speaker=item['speaker']
            normal=SUPPORT.fullmatch(sid)
            require(normal is not None and int(normal[1])==session and
                    type(text) is str and text and isinstance(speaker,str),
                    'invalid original real session/source identity')
            norm=f'D{session}:{int(normal[2])}'
            # Every arm uses the identical original dialogue text + speaker field.
            rendered=speaker+': '+text
            require(len(rendered.encode())<=32768,'source bound')
            out.append({'id':norm,'root':family,'text':rendered,'session':session,
                        'index':int(normal[2]),'revision':1,'revoked':False,
                        'content_sha256':sha_bytes(rendered.encode())})
            session_ids.append(norm)
        sessions[session]=session_ids
    require(len(out)==len(set(row['id'] for row in out)),'duplicate conversation source')
    return out,sessions


def source_edge(source_id,target_id,relation,by_id):
    a,b=by_id[source_id],by_id[target_id]
    require(a['root']==b['root'] and source_id!=target_id,'unrelated source edge')
    return {'source_id':source_id,'target_id':target_id,'relation':relation,
            'support_sha256':owner_digest({'source':source_id,'target':target_id,
                'relation':relation,'source_sha':a['content_sha256'],
                'target_sha':b['content_sha256'],'source_root':a['root']})}


def make_edges(sources,sessions):
    by_id={x['id']:x for x in sources};out=[]
    for session,ids in sorted(sessions.items()):
        for prior,nxt in zip(ids,ids[1:]):
            out.append(source_edge(prior,nxt,'temporal',by_id))
            out.append(source_edge(nxt,prior,'associative',by_id))
    return sorted(out,key=lambda x:(x['source_id'],x['target_id'],x['relation']))


def parse_support(raw):
    require(isinstance(raw,list) and len(raw)<=128,'invalid publisher support')
    valid=set();unresolved=[]
    for field in raw:
        require(isinstance(field,str) and len(field)<=2048,'invalid publisher reference')
        matches=list(SUPPORT.finditer(field))
        for m in matches:valid.add(f'D{int(m[1])}:{int(m[2])}')
        if not matches or SUPPORT.sub('',field).strip(' ,;\t\n'):
            unresolved.append(field)
    return sorted(valid),unresolved


def prepare(corpus,out_public,out_train,out_heldout):
    require(sha_bytes(Path(corpus).read_bytes())==CORPUS_SHA,'original LoCoMo corpus byte identity changed')
    original=json.loads(Path(corpus).read_bytes())
    require(isinstance(original,list) and len(original)==10,'complete original source family missing')
    source_roots={};edges={};cases=[];train=[];heldout=[];seen=set()
    for sample in original:
        family=sample['sample_id']
        require(family in SPLITS and family not in seen,'unknown/duplicate source family')
        seen.add(family)
        src,sessions=sources_from_conversation(sample)
        source_roots[family]=src;edges[family]=make_edges(src,sessions)
        for i,q in enumerate(sample['qa']):
            question=q['question'];case_id=f'{family}:{i}'
            require(isinstance(question,str) and question and len(question)<=1024,'unbounded question')
            cases.append({'case_id':case_id,'family':family,'split':SPLITS[family],
                          'question':question,'question_sha256':sha_bytes(question.encode())})
            support,unresolved=parse_support(q.get('evidence',[]))
            target={'case_id':case_id,'family':family,'publisher_support':support,
                    'unresolved_original_annotations':unresolved}
            (train if SPLITS[family]=='train' else heldout).append(target)
    require(set(source_roots)==set(SPLITS) and len(cases)==1986 and len(train)==1157
            and len(heldout)==829 and sum(map(len,source_roots.values()))==5882,
            'original complete source/QA census changed')
    public={'profile':PROFILE+'.source-only.v1','original_corpus_sha256':CORPUS_SHA,
            'sources':source_roots,'edges':edges,'cases':cases,'splits':SPLITS,
            'gold_included':False,'calendar_future_windows':0,'production_accepted':False}
    public_sha=put_new(out_public,public)
    train_sha=put_new(out_train,{'profile':PROFILE+'.train-labels.v1',
                'public_sha256':public_sha,'targets':train,'split':'train',
                'heldout_gold_included':False,'production_accepted':False})
    held_sha=put_new(out_heldout,{'profile':PROFILE+'.withheld-publisher-weak.v1',
                'public_sha256':public_sha,'targets':heldout,
                'heldout_source_families':4,'production_accepted':False})
    return {'source_sha256':public_sha,'train_sha256':train_sha,'heldout_sha256':held_sha,
            'source_count':5882,'question_count':1986}


class BM25:
    def __init__(self,sources):
        self.ids=[s['id'] for s in sources]
        require(len(set(self.ids))==len(self.ids),'duplicate eligible source')
        self.counts=[Counter(WORDS.findall(s['text'].casefold())) for s in sources]
        self.lengths=[sum(c.values()) for c in self.counts]
        self.average=max(1.0,sum(self.lengths)/len(self.lengths))
        self.df=Counter()
        for row in self.counts:self.df.update(set(row))
    def score(self,q):
        terms=set(WORDS.findall(q.casefold()));n=len(self.ids)
        scores={}
        for i,(sid,bag,length) in enumerate(zip(self.ids,self.counts,self.lengths)):
            total=0.
            for w in terms:
                tf=bag.get(w,0)
                if tf:
                    df=self.df[w]
                    total+=log(1+(n-df+.5)/(df+.5))*(tf*2.2/(tf+1.2*(.25+.75*length/self.average)))
            scores[sid]=total
        return scores


def closure(lexical,edges):
    adj=defaultdict(list)
    for e in edges:adj[e['source_id']].append(e)
    touched=set(lexical);frontier=list(lexical)
    for _ in range(2):
        nxt=[]
        for sid in frontier:
            for e in adj[sid]:
                dest=e['target_id']
                if dest not in touched:
                    touched.add(dest);nxt.append(dest)
        frontier=nxt
    require(len(touched)<=512,'physical graph owner bounded MAX_SOURCES exceeded')
    return touched


def fixed_weights():
    return {r:(-.5 if r=='contradicts' else .5) for r in RELATIONS}


def graph_rank(candidates,base,edges,weights,top,seed_ids):
    """Bounded original two-hop signed propagation; no causal-truth claims."""
    require(set(seed_ids)<=set(candidates) and len(seed_ids)==len(set(seed_ids)) and
            0<len(seed_ids)<=16,'unknown original lexical seeds')
    adj=defaultdict(list)
    for e in edges:
        if e['source_id'] in base and e['target_id'] in base:
            adj[e['source_id']].append((e['target_id'],e['relation']))
    for v in adj.values():v.sort()
    boost=defaultdict(float)
    for seed in seed_ids:
        seen={seed};queue=deque([(seed,0,1.)])
        while queue:
            node,hop,strength=queue.popleft()
            if hop==2:continue
            for dst,relation in adj[node]:
                if dst in seen:continue
                seen.add(dst)
                w=weights[relation]
                require(isfinite(w) and -8<=w<=8,'unbounded learned edge')
                signed=strength*max(-1.,min(1.,w))
                boost[dst]+=base[seed]*signed/(hop+1)
                if signed>0:queue.append((dst,hop+1,signed))
    return sorted(candidates,key=lambda sid:(-(base[sid]+boost[sid]/len(seed_ids)),sid))[:top]


def owner_train_graph(public,training,*,source_family='conv-26',steps=96,seed=17):
    original=public['sources'][source_family]
    require(len(original)<=512,'graph owner cannot load unbounded source corpus')
    src=[Evidence(evidence_id=s['id'],source_root=s['root'],scope='original-locomo',
         generation='g1',revision=1,content_sha256=s['content_sha256'],
         text=s['text'],revoked=False) for s in original]
    es=[Edge(source=e['source_id'],target=e['target_id'],relation=e['relation'],
             support_sha256=e['support_sha256']) for e in public['edges'][source_family]]
    graph=FrozenGraph(src,es,scope='original-locomo',generation='g1')
    weights,receipt=train_relation_router(graph,training,steps=steps,seed=seed)
    require(receipt['production_accepted'] is False and
            receipt['metrics']['graph_sha256']==graph.snapshot_digest and
            receipt['metrics']['optimizer_steps']==steps,'original owner failed physical training')
    # Independent scalar double precision reproduction of original Torch SGD.
    check={r:0. for r in RELATIONS}
    for step in range(steps):
        grad=Counter()
        for x in training:
            name=x['relation'];grad[name]+=(1/(1+exp(-check[name]))-x['label'])/len(training)
        for name in check:check[name]=max(-8.,min(8.,check[name]-.1*grad[name]))
    require(all(abs(weights[r]-check[r])<2e-5 for r in RELATIONS),'physical owner SGD not reproducible')
    return weights,receipt,graph.snapshot_digest


def train(public_file,source_sha,train_labels,labels_sha,out_path,*,steps=96):
    public=read_pinned(public_file,source_sha)
    labels=read_pinned(train_labels,labels_sha)
    require(public['profile']==PROFILE+'.source-only.v1' and public['gold_included'] is False
            and public['production_accepted'] is False and
            labels['profile']==PROFILE+'.train-labels.v1' and
            labels['public_sha256']==source_sha and
            labels['heldout_gold_included'] is False and
            len(labels['targets'])==1157,'TRAIN-only evidence source must be isolated')
    by={z['case_id']:z for z in labels['targets']}
    count=Counter();rows=[]; positives=[];negatives=[]
    indexes={family:BM25(src) for family,src in public['sources'].items() if SPLITS[family]=='train'}
    for c in public['cases']:
        if c['split']!='train':continue
        target=by.get(c['case_id']);require(target is not None and target['family']==c['family'],
                                       'missing original TRAIN weak label')
        support=set(target['publisher_support'])
        family=c['family'];sources=public['sources'][family];edges=public['edges'][family]
        ranked=indexes[family].score(c['question'])
        seeds=sorted(ranked,key=lambda sid:(-ranked[sid],sid))[:16]
        adj=defaultdict(list)
        for e in edges:adj[e['source_id']].append(e)
        for src in seeds:
            for e in adj[src]:
                row={'relation':e['relation'],'label':int(e['target_id'] in support),
                     'family':family,'split':'train'}
                (positives if row['label'] else negatives).append((
                   sha_bytes((c['case_id']+'/'+src+'/'+e['target_id']).encode()),row))
    require(positives and negatives,'no real TRAIN weak examples')
    # Retain every positive and a deterministic capped negative witness, all TRAIN.
    positives.sort(key=lambda x:x[0]);negatives.sort(key=lambda x:x[0])
    require(len(positives)<=2048,'too many true weak positives for fixed pilot')
    picked=positives+negatives[:min(4096-len(positives),len(positives)*4)]
    rows=[r for _,r in picked]
    require(4<=len(rows)<=4096 and {r['label'] for r in rows}=={0,1} and
            len({r['family'] for r in rows})>=2,
            'TRAIN graph classes or roots insufficient')
    weights,receipt,graph_sha=owner_train_graph(public,rows,steps=steps)
    output={'profile':PROFILE+'.learned-relation-weights.v1',
            'source_sha256':source_sha,'train_label_sha256':labels_sha,
            'physical_owner_graph_sha256':graph_sha,
            'training_examples':len(rows),'train_positive':len(positives),
            'train_negative':len(rows)-len(positives),
            'training_families':sorted(set(r['family'] for r in rows)),
            'steps':steps,'parameters':len(weights),'weights':weights,
            'owner_receipt_sha256':owner_digest(receipt),
            'calibrated_against_independent_scalar_sgd':True,
            'relation_truth_independently_authenticated':False,
            'new_encoder_training':False,'reader_calls':0,
            'production_accepted':False}
    return put_new(out_path,output)


def rank(public_file,source_sha,weight_file,weight_sha,out_path,*,top=3):
    public=read_pinned(public_file,source_sha);weights=read_pinned(weight_file,weight_sha)
    require(public['profile']==PROFILE+'.source-only.v1' and public['gold_included'] is False
            and weights['source_sha256']==source_sha and
            weights['profile']==PROFILE+'.learned-relation-weights.v1' and
            weights['calibrated_against_independent_scalar_sgd'] is True and
            weights['relation_truth_independently_authenticated'] is False and
            weights['production_accepted'] is False,
            'source identity or real physical graph TRAIN owner missing')
    require(set(weights['weights'])==set(RELATIONS) and all(isfinite(v) for v in weights['weights'].values()),
            'malformed physical relation parameters')
    require(top==3,'matched Reader final evidence-slot pilot')
    ranked=[];total_edges=0
    groups=defaultdict(list)
    for c in public['cases']:groups[c['family']].append(c)
    for family in sorted(groups):
        src=public['sources'][family];edges=public['edges'][family]
        idx=BM25(src);total_edges+=len(edges)
        for c in groups[family]:
            raw=idx.score(c['question'])
            bm=sorted(raw,key=lambda sid:(-raw[sid],sid))
            seeds=bm[:16]
            frontier=closure(seeds,edges)
            visible=seeds+sorted(frontier-set(seeds))
            max_score=max(raw.values()) if raw else 0.
            base={sid:(raw[sid]/max_score if max_score>0 else 0.) for sid in visible}
            e=[x for x in edges if x['source_id'] in frontier and x['target_id'] in frontier]
            lesion=next((x for x in e if x['source_id']==seeds[0]),None)
            require(lesion is not None,'missing predeclared source-adjacent edge lesion')
            remaining=[x for x in e if x is not lesion]
            fixed=graph_rank(visible,base,e,fixed_weights(),top,seeds)
            trained=graph_rank(visible,base,e,weights['weights'],top,seeds)
            altered=graph_rank(visible,base,remaining,weights['weights'],top,seeds)
            ranked.append({'case_id':c['case_id'],'family':family,'split':c['split'],
                           'question_sha256':c['question_sha256'],'original_candidates':len(visible),
                           'lexical_seeds_sha256':owner_digest(seeds),
                           'lesion_edge_sha256':owner_digest(lesion),
                           'selected':{'bm25':bm[:3],
                                       'temporal_fixed':fixed,
                                       'temporal_learned':trained,
                                       'temporal_edge_lesion':altered}})
    require(len(ranked)==1986 and len({r['case_id'] for r in ranked})==1986,
            'dropped original historical question')
    return put_new(out_path,{'profile':PROFILE+'.sealed-source-ranks.v1',
            'source_sha256':source_sha,'physical_weights_sha256':weight_sha,
            'original_question_count':1986,'registered_source_count':5882,
            'registered_adjacent_edges':total_edges,
            'ranking_publisher_gold_opened':False,
            'max_final_evidence_count':3,'reader_calls':0,
            'semantic_entailment_independently_verified':False,
            'calendar_future_windows':0,'production_accepted':False,
            'predictions':ranked})


def score(public_file,source_sha,rank_file,rank_sha,held_file,held_sha,out_path):
    p=read_pinned(public_file,source_sha)
    ranks=read_pinned(rank_file,rank_sha)
    withheld=read_pinned(held_file,held_sha)
    require(ranks['profile']==PROFILE+'.sealed-source-ranks.v1' and
            ranks['source_sha256']==source_sha and
            ranks['ranking_publisher_gold_opened'] is False and
            ranks['original_question_count']==1986 and
            ranks['max_final_evidence_count']==3 and
            ranks['reader_calls']==0 and ranks['production_accepted'] is False and
            withheld['public_sha256']==source_sha and
            withheld['profile']==PROFILE+'.withheld-publisher-weak.v1',
            'original source ranking not sealed before gold scoring')
    labels={r['case_id']:r for r in withheld['targets']}
    require(len(labels)==829,'original heldout+select publisher question census')
    counts=defaultdict(lambda: defaultdict(Counter));flips=Counter();changed=Counter()
    assessed=0
    for r in ranks['predictions']:
        if r['family'] not in HELDOUT:continue
        target=labels.get(r['case_id'])
        require(target is not None and target['family']==r['family'],'missing publisher weak source')
        support=set(target['publisher_support'])
        b=set(r['selected']['bm25'])
        for arm in ARMS:
            chosen=r['selected'][arm]
            require(len(chosen)==3 and len(set(chosen))==3,'final evidence budget drift')
            count=counts[r['family']][arm]
            count['questions']+=1
            count['hit3']+=int(bool(support.intersection(chosen)))
            count['all3']+=int(bool(support) and support<=set(chosen))
            changed[arm]+=int(chosen!=r['selected']['bm25'])
        assessed+=1
    require(assessed==400 and set(counts)==set(HELDOUT),'original heldout denominators omitted')
    roll={arm:{key:sum(counts[f][arm][key] for f in HELDOUT)
               for key in ('questions','hit3','all3')} for arm in ARMS}
    return put_new(out_path,{'profile':PROFILE+'.postseal-weak-score.v1',
            'original_rank_sha256':rank_sha,'publisher_weak_sha256':held_sha,
            'per_family':{f:{arm:dict(counts[f][arm]) for arm in ARMS} for f in HELDOUT},
            'heldout_total':400,'independent_historical_source_roots':2,
            'totals':roll,'changed_top3_vs_bm25':dict(changed),
            'independent_semantic_score':None,'whole_reader_tasks_executed':0,
            'strong_rag_equal_compute_verified':False,'true_future_windows':0,
            'temporal_relation_not_causal_truth':True,'production_accepted':False})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='phase',required=True)
    a=sub.add_parser('prepare')
    a.add_argument('--original',required=True);a.add_argument('--public',required=True)
    a.add_argument('--train',required=True);a.add_argument('--withheld',required=True)
    for name in ('train','rank','score'):
        a=sub.add_parser(name)
        a.add_argument('--public',required=True);a.add_argument('--public-sha',required=True)
        a.add_argument('--output',required=True)
        if name=='train':
            a.add_argument('--train-labels',required=True);a.add_argument('--train-sha',required=True)
            a.add_argument('--steps',type=int,default=96)
        if name=='rank':
            a.add_argument('--weights',required=True);a.add_argument('--weight-sha',required=True)
        if name=='score':
            a.add_argument('--rank',required=True);a.add_argument('--rank-sha',required=True)
            a.add_argument('--heldout',required=True);a.add_argument('--heldout-sha',required=True)
    args=p.parse_args(argv)
    if args.phase=='prepare':r=prepare(args.original,args.public,args.train,args.withheld)
    elif args.phase=='train':r=train(args.public,args.public_sha,args.train_labels,args.train_sha,args.output,steps=args.steps)
    elif args.phase=='rank':r=rank(args.public,args.public_sha,args.weights,args.weight_sha,args.output)
    else:r=score(args.public,args.public_sha,args.rank,args.rank_sha,args.heldout,args.heldout_sha,args.output)
    print(json.dumps({'sha256':r} if isinstance(r,str) else r,sort_keys=True))

if __name__=='__main__':main()
