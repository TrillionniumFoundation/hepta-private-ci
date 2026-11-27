import argparse, collections, datetime, hashlib, json, math, re, statistics, time
from pathlib import Path

parser=argparse.ArgumentParser(description='Development-only synthetic typo retrieval diagnostic')
parser.add_argument('--data-dir',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
ROOT=args.output_dir.resolve()
DATA=args.data_dir.resolve()
START=time.monotonic()
def sha(b): return hashlib.sha256(b).hexdigest()
def tokens(s): return re.findall(r'[a-z0-9]+',s.lower())
def grams(s):
    s=' '.join(tokens(s))
    return {s[i:i+3] for i in range(max(0,len(s)-2))}
def typo(q):
    words=sorted(re.finditer(r'[A-Za-z]{6,}',q),key=lambda m:(-len(m.group()),m.start()))
    for m in words:
        w=m.group(); mid=(len(w)-1)//2
        for i in [mid]+[i for i in range(len(w)-1) if i!=mid]:
            if w[i]!=w[i+1]:
                w=w[:i]+w[i+1]+w[i]+w[i+2:]
                return q[:m.start()]+w+q[m.end():]
    return q
class Index:
    def __init__(self,docs,chars):
        self.ids=sorted(docs); self.docs=docs
        self.tf={k:collections.Counter(tokens(docs[k])) for k in self.ids}
        self.length={k:sum(self.tf[k].values()) for k in self.ids}
        self.avg=sum(self.length.values())/len(self.ids) or 1
        self.df=collections.Counter(t for k in self.ids for t in self.tf[k])
        self.char={k:grams(docs[k]) for k in self.ids} if chars else None
    def rank(self,q,alpha):
        words=tokens(q);n=len(self.ids); scores={}
        for k in self.ids:
            scores[k]=sum(math.log(1+(n-self.df[t]+.5)/(self.df[t]+.5))*self.tf[k][t]*2.2/(self.tf[k][t]+1.2*(.25+.75*self.length[k]/self.avg)) for t in words if self.tf[k][t])
        rank=sorted(self.ids,key=lambda k:(-scores[k],k))
        if not alpha:return rank[0]
        g=grams(q); cs={k:len(g&self.char[k])/max(1,len(g|self.char[k])) for k in self.ids}
        cr=sorted(self.ids,key=lambda k:(-cs[k],k));b={k:i+1 for i,k in enumerate(rank)};c={k:i+1 for i,k in enumerate(cr)}
        return min(self.ids,key=lambda k:(-((1-alpha)/(60+b[k])+alpha/(60+c[k])),k))
def load(name,p):
    b=(DATA/name).read_bytes();assert sha(b)==p['inputs'][name]
    return [json.loads(x) for x in b.splitlines()]
def evaluate(rows,alpha):
    start=time.perf_counter();cache={};hits={'clean':collections.defaultdict(list),'typo':collections.defaultdict(list)};changed=0
    for r in rows:
        assert time.monotonic()-START<300
        docs={d['id']:d['text'] for d in r['candidates']}
        key=sha(json.dumps(docs,sort_keys=True).encode())
        if key not in cache:cache[key]=Index(docs,bool(alpha))
        tq=typo(r['query']);changed+=tq!=r['query']
        for mode,q in [('clean',r['query']),('typo',tq)]:
            hit=cache[key].rank(q,alpha) in r['positive_ids'];hits[mode][r['group_id']].append(int(hit))
    metrics={mode:{'macro_top1':statistics.mean(sum(v)/len(v) for v in groups.values()),'hits':sum(sum(v) for v in groups.values()),'queries':len(rows),'components':len(groups),'per_component':{k:[sum(v),len(v)] for k,v in groups.items()}} for mode,groups in hits.items()}
    return {'quality':metrics,'wall_seconds':time.perf_counter()-start,'perturbed_queries':changed}
def save(n,x):
    p=ROOT/n
    with p.open('x') as f:json.dump(x,f,indent=2);f.write('\n');f.flush()
    return sha(p.read_bytes())
def main():
    protocol=json.loads((ROOT/'protocol.json').read_bytes())
    assert typo('abcdef')=='abdcef';assert typo('abc')=='abc'
    assert Index({'a':'apple apple','b':'pear pear'},False).rank('apple',0)=='a'
    train=load('train.jsonl',protocol);base=evaluate(train,0);arms={str(a):evaluate(train,a) for a in protocol['alphas']}
    eligible=[a for a in protocol['alphas'] if arms[str(a)]['quality']['clean']['macro_top1']>=base['quality']['clean']['macro_top1']]
    alpha=min(eligible,key=lambda a:(-arms[str(a)]['quality']['typo']['macro_top1'],-arms[str(a)]['quality']['clean']['macro_top1'],a)) if eligible else None
    selection={'selected_alpha':alpha,'train_bm25':base,'train_candidates':arms,'protocol_sha256':sha((ROOT/'protocol.json').read_bytes()),'code_sha256':sha(Path(__file__).read_bytes()),'freeze_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    selsha=save('selection.json',selection)
    if alpha is None:save('result.json',{'status':'NO_TRAIN_ADMISSION','selection_sha256':selsha});return
    dev=load('dev.jsonl',protocol);runs={'baseline':[],'candidate':[]}
    for order in [('baseline','candidate'),('candidate','baseline'),('baseline','candidate')]:
        for arm in order:runs[arm].append(evaluate(dev,0 if arm=='baseline' else alpha))
    for arm in runs:
        assert all(x['quality']==runs[arm][0]['quality'] for x in runs[arm])
    b=runs['baseline'][0]['quality'];c=runs['candidate'][0]['quality'];ratio=statistics.median(x['wall_seconds'] for x in runs['candidate'])/statistics.median(x['wall_seconds'] for x in runs['baseline'])
    checks={'clean_no_loss':c['clean']['macro_top1']>=b['clean']['macro_top1'],'typo_gain_at_least_005':c['typo']['macro_top1']-b['typo']['macro_top1']>=.05-1e-12,'cold_wall_at_most_2x':ratio<=2}
    result={'status':'DIAGNOSTIC_CRITERIA_MET' if all(checks.values()) else 'DIAGNOSTIC_NO_GO','scope':'EXPOSED_DEVELOPMENT_SYNTHETIC_TYPO_ONLY','selection_sha256':selsha,'protocol_sha256':selection['protocol_sha256'],'code_sha256':selection['code_sha256'],'selected_alpha':alpha,'checks':checks,'dev_runs':runs,'median_wall_ratio':ratio,'model_forwards':0,'test72_reads':0,'generalization_claim':False,'whole_wall_seconds':time.monotonic()-START}
    save('result.json',result);print(json.dumps({k:v for k,v in result.items() if k!='dev_runs'},indent=2));print('BM25',b);print('CANDIDATE',c)
if __name__=='__main__':main()
