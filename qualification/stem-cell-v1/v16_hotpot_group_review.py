"""Independent algorithmic replay + postseal *support retrieval* review.

Does not import v16_hotpot_group or v15_evidence_proposer. This is a
second authored scorer, not a separately signed observer or answer Reader.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import time

from v15_hotpot_source import SCHEMA as SOURCE_SCHEMA, digest, load, write_once
import v15_hotpot_source as source

POLICIES = ('bm25_2', 'bm25_5', 'graph_5', 'lesion_5', 'hash_5',
            'ndu_shadow', 'ordinary_same_profile', 'hash_budget')
TARIFF = 18
WORDS = re.compile(r"[\w]+(?:['’][\w]+)?", re.UNICODE)
STOP = set('a an the of in on by to for from and or is are was were as that which what where when who how whose with at did does do have has had it its this those these their he she his her they but about after before been being than more most'.split())


def words(text):
    return [w.casefold() for w in WORDS.findall(text) if len(w) > 1 and w.casefold() not in STOP]


def title_in(text, title):
    needle, hay = words(title), words(text)
    return bool(needle) and len(needle) <= 18 and any(
        hay[i:i+len(needle)] == needle for i in range(len(hay)-len(needle)+1))


def independent_rank(row):
    sentences = [(title, i, line) for title, para in row['context'] for i, line in enumerate(para)]
    if not 5 <= len(sentences) <= 8192 or len({(a,b) for a,b,_ in sentences}) != len(sentences):
        raise ValueError('bad original evidence geometry')
    bags = [Counter(words(title) + words(text)) for title, _, text in sentences]
    document_freq = Counter(term for bag in bags for term in bag)
    average = sum(sum(bag.values()) for bag in bags) / len(bags) or 1.
    question = Counter(words(row['question']))
    scores = []
    for bag in bags:
        length = sum(bag.values())
        score = 0.
        for term, occurrence in question.items():
            if not bag.get(term):
                continue
            score += (min(2, occurrence) * math.log1p(
                (len(bags) - document_freq.get(term,0) + .5) / (document_freq.get(term,0) + .5))
                * (bag[term] * 2.2 / (bag[term] + 1.2*(.25+.75*length/average))))
        scores.append(score)
    bm25 = sorted(range(len(sentences)), key=lambda i:(-scores[i],sentences[i][0].casefold(),sentences[i][1]))
    titles = [title for title, _ in row['context']]
    by_title = defaultdict(list)
    for i, (title, _, _) in enumerate(sentences):
        by_title[title].append(i)

    def graph(broken):
        best, best_weight = None, float('-inf')
        for anchor in bm25[:min(16,len(bm25))]:
            anchor_title, _, anchor_text = sentences[anchor]
            for pos, actual_title in enumerate(titles):
                if actual_title == anchor_title or not title_in(anchor_text, actual_title):
                    continue
                target_title = titles[(pos+1) % len(titles)] if broken else actual_title
                if target_title == anchor_title or target_title not in by_title:
                    continue
                target = min(by_title[target_title], key=lambda i:(-scores[i],sentences[i][1]))
                value = scores[anchor] + scores[target] + 2.5
                if value > best_weight:
                    best = (anchor,target)
                    best_weight = value
        if best is None:
            return bm25, False
        return list(dict.fromkeys((*best, *bm25))), True

    linked, has_edge = graph(False)
    lesion, _ = graph(True)
    random_rank = sorted(range(len(sentences)),key=lambda i:sha256(
        ('hepta-v15-hash-null/'+row['id']+'/'+sentences[i][0]+'/'+str(sentences[i][1])).encode()).digest())
    return sentences, bm25, linked, lesion, random_rank, has_edge


def independent_reward(row, picks, lookup):
    q = set(words(row['question']))
    covered = set()
    for t, i in picks:
        covered.update(words(t+' '+lookup[t,i]))
    return 60*min(3,len({t for t,_ in picks}))+40*len(q&covered)//max(1,len(q))


def replay_one(row):
    if type(row) is not dict or set(row) != {'id','question','context'}:
        raise ValueError('gold leaked into original public request')
    sentences,bm25,linked,lesion,random_rank,has_edge = independent_rank(row)
    lookup={(a,b):text for a,b,text in sentences}
    rankings = dict(bm25_2=bm25,bm25_5=bm25,graph_5=linked,
                    lesion_5=lesion,hash_5=random_rank,ndu_shadow=linked,
                    ordinary_same_profile=linked,hash_budget=linked)
    two=[(sentences[i][0],sentences[i][1]) for i in linked[:2]]
    five=[(sentences[i][0],sentences[i][1]) for i in linked[:5]]
    gain=independent_reward(row,five,lookup)-independent_reward(row,two,lookup)
    # Exhaustive finite reference; tie chooses STOP.
    u2=independent_reward(row,two,lookup)-2*TARIFF
    u5=independent_reward(row,five,lookup)-5*TARIFF
    selected_by_reference=5 if u5>u2 else 2
    if (5 if gain > 3*TARIFF else 2)!=selected_by_reference:
        raise ValueError('reference control inconsistency')
    out={}
    for policy in POLICIES:
        k=5 if policy in ('bm25_5','graph_5','lesion_5','hash_5') else 2
        if policy in ('ndu_shadow','ordinary_same_profile'):
            k=selected_by_reference
        if policy=='hash_budget':
            k=5 if sha256(('hepta-v16-budget-null/'+row['id']).encode()).digest()[0] < 128 else 2
        picks=[(sentences[i][0],sentences[i][1]) for i in rankings[policy][:k]]
        edge=(policy in ('graph_5','ndu_shadow','ordinary_same_profile','hash_budget')
              and has_edge and picks[0][0]!=picks[1][0]
              and title_in(lookup[picks[0]], picks[1][0]))
        evidence=[[title,pos,lookup[title,pos]] for title,pos in picks]
        actions=['BIND','COMPOSE_LEXICAL_EDGE' if edge else 'NO_OBSERVED_EDGE','VERIFY_TOP2']
        if k>2:
            actions.extend(['EXPAND_3','VERIFY_FINAL'])
        actions.append('STOP')
        reward=independent_reward(row,picks,lookup)
        out[policy]=dict(citations=[[a,b] for a,b in picks], input_sha256=digest(evidence),
            evidence_bytes=sum(len(text.encode('utf-8')) for _,_,text in evidence),
            citation_slots=k,reward_proxy_units=reward,
            utility_proxy_units=reward-TARIFF*k,
            lexical_edge_observed=bool(edge),operations=actions)
    return dict(source_sha256=digest(row),candidate_sentence_count=len(sentences),
                lexical_link_found=bool(has_edge),policies=out)


def audit(public_path, owner_path, hidden_path, plan_path, seal_path, output_path):
    started=time.process_time_ns()
    public,owner,hidden,plan,seal=(load(x) for x in (
        public_path,owner_path,hidden_path,plan_path,seal_path))
    if (type(public) is not list or len(public)!=source.N_EXPECTED
            or type(owner) is not dict or owner.get('schema')!=SOURCE_SCHEMA
            or owner.get('public_sha256')!=digest(public)
            or owner.get('hidden_sha256')!=digest(hidden)
            or owner.get('original_cases')!=source.N_EXPECTED
            or owner.get('authority')!='DENY_ALL'
            or type(plan) is not dict or plan.get('schema')!='hepta.v16.hotpot-group-budget-plan.v1'
            or plan.get('source_sha256')!=digest(public)
            or plan.get('owner_sha256')!=digest(owner)
            or plan.get('plan_sha256')!=digest({k:v for k,v in plan.items() if k!='plan_sha256'})
            or plan.get('policies')!=list(POLICIES) or plan.get('tariff_units')!=TARIFF
            or plan.get('stop_tie')!='STOP' or plan.get('held_gold_visible_to_proposer') is not False
            or plan.get('reader_forwards')!=0 or plan.get('training_updates')!=0
            or plan.get('no_NDU_FBSDE_solver') is not True
            or plan.get('authority')!='DENY_ALL' or plan.get('production_accepted') is not False
            or type(seal) is not dict or seal.get('schema')!='hepta.v16.hotpot-group-evidence-traces.v1'
            or seal.get('source_sha256')!=digest(public)
            or seal.get('owner_sha256')!=digest(owner)
            or seal.get('plan_sha256')!=plan['plan_sha256']
            or seal.get('records_sha256')!=digest(seal.get('records'))
            or seal.get('completed_questions')!=source.N_EXPECTED
            or seal.get('policy_outputs_no_hidden_labels') is not True
            or seal.get('no_pretrained_reader_calls') is not True
            or seal.get('no_training') is not True or seal.get('no_answer_generation') is not True
            or seal.get('no_NDU_FBSDE_solver') is not True
            or seal.get('authority')!='DENY_ALL' or seal.get('production_accepted') is not False):
        raise ValueError('untrusted source, altered commitment, gold boundary or false scientific authority')
    if (type(hidden) is not dict or type(seal['records']) is not dict
            or len({r['id'] for r in public})!=source.N_EXPECTED
            or set(seal['records'])!={r['id'] for r in public}
            or set(hidden)!={r['id'] for r in public}):
        raise ValueError('missing/duplicate source or original gold family')
    check_paths=Path(__file__).parent
    materials={'v15_ranker_sha256':sha256((check_paths/'v15_evidence_proposer.py').read_bytes()).hexdigest(),
               'v16_producer_sha256':sha256((check_paths/'v16_hotpot_group.py').read_bytes()).hexdigest()}
    if any(plan.get(k)!=v for k,v in materials.items()):
        raise ValueError('changed source executable after plan seal')
    accum={key:dict(n=0,f1=0.,recall=0.,precision=0.,exact=0,docs=0.,slots=0,bytes=0,edge=0)
           for key in POLICIES}
    stratified=defaultdict(lambda:dict(n=0,recall=0.))
    sentence_scans=0
    for row in public:
        qid=row['id']
        expected=replay_one(row)
        actual=seal['records'][qid]
        if actual!=expected:
            raise ValueError('producer record fails independent source-only algorithm replay')
        sentence_scans+=expected['candidate_sentence_count']
        gold=hidden[qid]
        if (type(gold) is not dict or set(gold)!={'answer','supporting_facts','type','level'}
                or type(gold['answer']) is not str or gold['type'] not in ('bridge','comparison')
                or gold['level'] not in ('easy','medium','hard')):
            raise ValueError('original publisher hidden gold invalid')
        originals={(t,i) for t,para in row['context'] for i,_ in enumerate(para)}
        support={tuple(x) for x in gold['supporting_facts']}
        if not support or not support<=originals:
            raise ValueError('gold support not in original public evidence')
        true_docs={t for t,_ in support}
        for policy,item in actual['policies'].items():
            citations={tuple(c) for c in item['citations']}
            hits=len(citations&support)
            pre=hits/len(citations)
            rec=hits/len(support)
            f1=2*pre*rec/(pre+rec) if pre+rec else 0.
            stat=accum[policy]
            stat['n']+=1;stat['f1']+=f1;stat['recall']+=rec;stat['precision']+=pre
            stat['exact']+=int(citations==support)
            stat['docs']+=len({t for t,_ in citations}&true_docs)/len(true_docs)
            stat['slots']+=item['citation_slots'];stat['bytes']+=item['evidence_bytes']
            stat['edge']+=int(item['lexical_edge_observed'])
            band=stratified[(policy,gold['type'],gold['level'])]
            band['n']+=1;band['recall']+=rec
    if sentence_scans!=seal.get('unique_shared_source_scans'):
        raise ValueError('forged source scan or double-billed shared source work')
    report=[]
    for policy in POLICIES:
        a=accum[policy];n=a['n']
        if n!=source.N_EXPECTED:
            raise ValueError('partial original corpus statistics')
        report.append(dict(policy=policy,questions=n,
            support_F1_macro=a['f1']/n,support_recall_macro=a['recall']/n,
            support_precision_macro=a['precision']/n,support_exact_rate=a['exact']/n,
            document_recall_macro=a['docs']/n,mean_citation_slots=a['slots']/n,
            mean_evidence_bytes=a['bytes']/n,observed_lexical_link_rate=a['edge']/n))
    if report[5]!=dict(report[6],policy='ndu_shadow'):
        raise ValueError('false NDU advantage over same-objective ordinary DP')
    result=dict(schema='hepta.v16.hotpot-independent-support-review.v1',
        source_sha256=digest(public),hidden_sha256=digest(hidden),
        producer_records_sha256=seal['records_sha256'],reviewed_questions=source.N_EXPECTED,
        unique_original_questions=source.N_EXPECTED,original_shared_sentence_scans=sentence_scans,
        summary=report,by_type_level=[dict(policy=p,type=t,level=l,
            questions=v['n'],support_recall_macro=v['recall']/v['n'])
            for (p,t,l),v in sorted(stratified.items())],
        ndu_and_ordinary_same_profile_identical=True,held_truth_loaded_postseal=True,
        question_overlap_not_source_independent=True,not_prospective=True,
        human_support_retrieval_only=True,actual_final_answers_generated=False,
        actual_pretrained_reader_forwards=0,actual_NDU_FBSDE_solutions=0,
        complete_lifecycle_cost_unverified=True,
        independent_external_signer=False,production_accepted=False,
        model_selected=False,authority='DENY_ALL',
        review_cpu_ns=time.process_time_ns()-started)
    result['summary_sha256']=digest(report)
    write_once(output_path,result)
    return result


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    for name in ('public','owner','hidden','plan','seal','output'):
        cli.add_argument('--'+name,required=True)
    x=cli.parse_args()
    result=audit(x.public,x.owner,x.hidden,x.plan,x.seal,x.output)
    print(json.dumps(dict(questions=result['reviewed_questions'],
        summary_sha256=result['summary_sha256'],summary=result['summary'],
        authority=result['authority'])))


if __name__=='__main__':
    main()
