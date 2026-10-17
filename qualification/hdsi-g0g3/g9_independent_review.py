"""Independent G9 original-source answer reviewer, without model, Torch or producer imports.

Reopens original LoCoMo only after all four sealed root prediction artifacts exist.
Scores literal-answer appearance and exact match, NOT human semantic correctness.
"""
from __future__ import annotations
import argparse,collections,hashlib,json,math,re,unicodedata
from pathlib import Path

ORIG='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
WEIGHT='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
ROOTS=('conv-47','conv-48','conv-49','conv-50')
ARMS=('none','bm25','oracle','lesion')
SCHEMA='hepta.hdsi.g9.independent-original-answer-review.v1'
DOM=b'hepta.hdsi.g9.reader-capacity-v1\0'
T=re.compile(r'(?u)\b\w+\b')


def need(v,why):
    if v is not True:raise ValueError(why)


def sha(b):return hashlib.sha256(b).hexdigest()


def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()


def seal(obj):return sha(DOM+canonical(obj))


def norm(s):
    return [s for s in T.findall(unicodedata.normalize('NFKC',s).casefold()) if s]


def exact(out,ans):return norm(out)==norm(ans)


def literal_contains(out,ans):
    a=norm(ans);b=norm(out)
    if not a or not b or len(a)>len(b):return False
    return any(b[i:i+len(a)]==a for i in range(len(b)-len(a)+1))


def f1(out,ans):
    a=collections.Counter(norm(ans));b=collections.Counter(norm(out))
    ov=sum((a&b).values())
    if not a or not b:return 0.
    p=ov/sum(b.values());r=ov/sum(a.values())
    return 2*p*r/(p+r) if p+r else 0.


def original_bm25(docs,q):
    lines=[T.findall(d['text'].casefold()) for d in docs]
    n=len(lines);avg=sum(len(x) for x in lines)/n
    counts=[collections.Counter(tokens) for tokens in lines]
    df=collections.Counter(t for line in lines for t in set(line))
    qt=sorted(set(T.findall(q.casefold())))
    data=[]
    for idx,(tokens,count) in enumerate(zip(lines,counts)):
        val=0.;scale=.25+.75*len(tokens)/max(avg,1)
        for token in qt:
            f=count.get(token,0)
            if f:
                idf=math.log1p((n-df[token]+.5)/(df[token]+.5))
                val+=idf*f*2.2/(f+1.2*scale)
        data.append((-val,docs[idx]['id'],idx))
    return [r[2] for r in sorted(data)]


def original_docs(root):
    docs={}
    for key,turns in root['conversation'].items():
        if not key.startswith('session_') or type(turns) is not list:continue
        for d in turns:
            if type(d) is not dict:continue
            name,txt,who=d.get('dia_id'),d.get('text'),d.get('speaker')
            if type(name) is not str or re.fullmatch(r'D\d+:\d+',name) is None or type(txt) is not str or not txt.strip() or len(txt.encode())>8192 or type(who) is not str or not who or len(who)>80:continue
            need(name not in docs,'duplicate original dialogue')
            docs[name]={'id':name,'text':who+': '+txt,'text_sha':sha((who+': '+txt).encode())}
    return sorted(docs.values(),key=lambda d:d['id'])


def review(original:bytes,panel:dict,receipts:list[dict])->dict:
    need(sha(original)==ORIG,'original source SHA mismatch')
    need(type(panel) is dict and panel.get('original_sha')==ORIG
         and panel.get('reader_weight_sha')==WEIGHT
         and panel.get('original_answers_in_packet') is False
         and panel.get('production_authorized') is False
         and panel.get('disposition')=='HOLD_NO_GO','false evidence claim')
    need(panel.get('digest')==seal({k:v for k,v in panel.items() if k!='digest'}),'changed input panel')
    need(type(panel.get('cases')) is list and len(panel['cases'])==16,'wrong case roster')
    need(type(receipts) is list and len(receipts)==4,'missing original model roots')
    raw={x['sample_id']:x for x in json.loads(original)}
    need(set(raw)>={*ROOTS},'original conversation roots absent')
    # Independently reconstruct G5/G8 question selection. Re-reading an
    # arbitrary valid publisher question by index is NOT enough: it would allow
    # posthoc selection of the 16 easiest historical test cases.
    fixed_roster={}
    for root in ROOTS:
        ranked=[]
        for ix,rec in enumerate(raw[root]['qa']):
            q=rec.get('question') if type(rec) is dict else None
            if type(q) is not str or not 4<=len(q.strip())<=350 or len(q.encode())>800:
                continue
            h=sha(('hdsi.g5.question.v1\0'+root+'\0'+str(ix)+'\0'+q).encode())
            ranked.append((h,'q'+str(ix)))
        fixed_roster[root]=[qid for _,qid in sorted(ranked)[:4]]
    expected=[];original_gold={}
    for i,c in enumerate(panel['cases']):
        root=ROOTS[i//4]
        need(c['root']==root and c['id']==root+'/'+fixed_roster[root][i%4],
             'posthoc source-first question selection')
        qidx=int(c['id'].split('/q')[1]);publisher=raw[root]['qa'][qidx]
        need(publisher['question']==c['question'] and c['question_sha']==sha(c['question'].encode()),'publisher original question drift')
        docs=original_docs(raw[root]);by_id={d['id']:d for d in docs}
        ids=sorted(set(publisher['evidence']))
        need(bool(ids) and all(d in by_id for d in ids),'unsupported original publisher evidence')
        expected_arms={'none':[], 'oracle':[by_id[x] for x in ids], 'lesion':[by_id[x] for x in ids[1:]],
                       'bm25':[docs[j] for j in original_bm25(docs,c['question'])[:5]]}
        need(type(c['arms']) is dict and set(c['arms'])==set(ARMS),'missing evidence arm')
        for name in ARMS:
            need(c['arms'][name]==expected_arms[name],'original evidence substitution: '+name)
        answer=publisher.get('answer')
        original_gold[c['id']]=str(answer) if isinstance(answer,(str,int,float)) and answer is not None else None
        expected.append(c['id'])
    expected_keys={(case,arm) for case in expected for arm in ARMS}
    got={};measures={'calls':0,'prefills':0,'input_tokens':0,'generated_tokens':0,
                    'wall_seconds_self_reported':0.,'cpu_seconds_self_reported':0.}
    for ri,r in enumerate(receipts):
        need(type(r) is dict and set(r)=={'schema','source_digest','model_sha','tokenizer_sha','reader',
             'original_answer_labels_received','model_tokenizer_upstream_parity_verified','root',
             'case_count','arms','records','physical_work','full_human_semantic_score_verified',
             'future_sources_verified','production_authorized','disposition','digest'},'model output schema')
        need(r['schema']=='hepta.hdsi.g9.original-native-reader.no-answer-oracle.v1'
             and r['source_digest']==panel['digest'] and r['model_sha']==WEIGHT
             and r['tokenizer_sha']=='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
             and r['root']==ROOTS[ri] and r['case_count']==4
             and r['arms']==list(ARMS) and r['original_answer_labels_received'] is False
             and r['model_tokenizer_upstream_parity_verified'] is False
             and r['full_human_semantic_score_verified'] is False
             and r['future_sources_verified'] is False and r['production_authorized'] is False
             and r['disposition']=='HOLD_NO_GO','incorrect original model identity or authority')
        need(r['digest']==seal({k:v for k,v in r.items() if k!='digest'}),'prediction seal changed')
        work=r['physical_work']
        need(type(work) is dict and set(work)=={'calls','prefills','input_tokens','generated_tokens',
              'elapsed_cpu_seconds_self_reported','elapsed_wall_seconds_self_reported',
              'peak_rss_bytes_self_reported','gpu_energy_joules','target_host_p99_ms'},'missing physical meter')
        need(work['prefills']==16 and work['calls']>16 and work['input_tokens']>16
             and work['generated_tokens']>0 and type(work['peak_rss_bytes_self_reported']) is int
             and work['peak_rss_bytes_self_reported']>0
             and work['gpu_energy_joules'] is None and work['target_host_p99_ms'] is None,
             'contradictory physical profile')
        need(type(r['records']) is list and len(r['records'])==16,'unpaid/missing original calls')
        for record in r['records']:
            need(type(record) is dict and set(record)=={'case_id','question_sha','arm','text',
                 'input_tokens','generated_tokens','forward_calls'},'record schema')
            k=(record['case_id'],record['arm'])
            need(k in expected_keys and k not in got and record['case_id'].startswith(r['root']+'/'),
                 'duplicate/unknown source case or arm')
            question=panel['cases'][expected.index(record['case_id'])]
            need(record['question_sha']==question['question_sha']
                 and type(record['text']) is str and len(record['text'].encode())<4096
                 and type(record['input_tokens']) is int and 0<record['input_tokens']<=1024
                 and type(record['generated_tokens']) is int and 0<=record['generated_tokens']<=24
                 and type(record['forward_calls']) is int
                 and max(1,record['generated_tokens'])<=record['forward_calls']<=max(1,record['generated_tokens'])+1,
                 'fake reader output or uncounted EOS')
            got[k]=record
        for stat,field in [('calls','forward_calls'),('input_tokens','input_tokens'),('generated_tokens','generated_tokens')]:
            need(work[stat]==sum(x[field] for x in r['records']),'model cost count mismatch')
        for stat in ['calls','prefills','input_tokens','generated_tokens']:
            measures[stat]+=work[stat]
        for dst,src in [('wall_seconds_self_reported','elapsed_wall_seconds_self_reported'),
                        ('cpu_seconds_self_reported','elapsed_cpu_seconds_self_reported')]:
            v=work[src];need(type(v) in (float,int) and math.isfinite(v) and 0<=v<10000,'invalid reported cost')
            measures[dst]+=v
    need(set(got)==expected_keys,'missing original predictions')
    aggregate={a:{'evaluated':0,'literal_answer':0,'exact_output':0,'token_f1_sum':0.,'unknown':0} for a in ARMS}
    paired={a:{'rescue_vs_none':0,'harm_vs_none':0} for a in ARMS if a!='none'}
    scores={}
    for cid in expected:
        gold=original_gold[cid]
        if gold is None:continue
        for a in ARMS:
            output=got[(cid,a)]['text'];y=literal_contains(output,gold)
            agg=aggregate[a]
            agg['evaluated']+=1;agg['literal_answer']+=int(y)
            agg['exact_output']+=int(exact(output,gold))
            agg['token_f1_sum']+=f1(output,gold)
            agg['unknown']+=int(norm(output)==['unknown'])
            scores[(cid,a)]=y
        base=scores[(cid,'none')]
        for a in paired:
            current=scores[(cid,a)]
            paired[a]['rescue_vs_none']+=int(current and not base)
            paired[a]['harm_vs_none']+=int(base and not current)
    need(all(v['evaluated']==15 for v in aggregate.values()),'original answer eligibility changed')
    for v in aggregate.values():
        v['mean_token_f1']=round(v.pop('token_f1_sum')/v['evaluated'],6)
    out={'schema':SCHEMA,'source_packet_digest':panel['digest'],
         'original_source_sha':ORIG,'original_model_sha':WEIGHT,
         'original_roots':list(ROOTS),'total_source_first_cases':16,
         'answer_scored_cases':15,'unscored_original_missing_answer':1,
         'four_evidence_arms':list(ARMS),'per_arm':aggregate,'paired':paired,
         'paid_original_model':measures,
         'interpretation':'literal gold phrase proxy, not adjudicated semantic answer quality',
         'historically_public_source':True,'future_independent_verified':False,
         'upstream_tokenizer_numeric_parity_verified':False,
         'control_is_not_ndu_lift':True,'production_authorized':False,'disposition':'HOLD_NO_GO'}
    out['digest']=seal(out)
    return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True)
    p.add_argument('--panel',type=Path,required=True);p.add_argument('--run',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=review(a.original.read_bytes(),json.loads(a.panel.read_bytes()),
                  [json.loads(k.read_bytes()) for k in a.run])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('xb') as f:
        f.write(canonical(result)+b'\n');f.flush()
        import os;os.fsync(f.fileno())
    print(json.dumps({'source_cases':16,'score_denominator':15,
         'score':{k:v['literal_answer'] for k,v in result['per_arm'].items()},
         'paid_model_forwards':result['paid_original_model']['calls'],
         'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
