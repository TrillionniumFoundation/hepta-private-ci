"""Private, arm-blind V19 independent human review intake.

The owner-only mapping and publisher targets MUST NOT be published. Tickets do
NOT claim any review occurred, certify source sufficiency, or grant FinalUse.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import hmac
import json
from pathlib import Path
from v17_source_focusing import read,sealed,digest,htext
from v19_paired_postseal import ARMS

SCHEMA='hepta.stem.v19.blind-review.original-intake.v1'


def prepare(plan, v17plan, v18plan, v17raw, v18raw, v19raw, source, secret):
    if type(secret)is not bytes or len(secret)<32:raise ValueError('private reviewer shuffle seed insufficient')
    if (len(plan.get('cases',[]))!=32 or v17raw.get('plan_sha256')!=digest(v17plan)
        or v18raw.get('plan_sha256')!=digest(v18plan) or v19raw.get('plan_sha256')!=digest(plan)
        or v17raw.get('requests')!=64 or v18raw.get('requests')!=58 or v19raw.get('requests')!=23):
        raise ValueError('unsealed upstream original answers')
    old17={x['case_id']:x for x in v17plan['cases']}
    old18={x['case_id']:x for x in v18plan['cases']}
    tickets=[]; private=[]; seen=set()
    for case in plan['cases']:
        cid=case['case_id'];fam=case['family']
        if cid not in old17 or cid not in old18:raise ValueError('source case changed')
        questions={q['id']:q['text'] for q in source['families'][fam]['questions']}
        docs={d['id']:d['text'] for d in source['families'][fam]['passages']}
        witness=case['witness_id'];whole=docs[witness]
        for arm in ARMS:
            if arm=='full_original':
                rid=old17[cid]['arms']['formatted_full'];a=v17raw['raw_answers'][rid];part=whole
            elif arm=='single_sentence':
                spec=old18[cid]['cross_arms']['focused_full_heading'];rid=spec['request_id']
                a=(v17raw if spec['reused_v17'] else v18raw)['raw_answers'][rid]
                begin,end=old17[cid]['focus_offsets'];part=whole[begin:end]
            else:
                spec=case['arms'][arm];rid=spec['request_id'];a=(v17raw if spec['reuse']=='v17' else v19raw)['raw_answers'][rid]
                part=whole[spec['span'][0]:spec['span'][1]]
            if a['case_id']!=cid or a['source_ids']!=case['source_ids'] or a['answer_sha256']!=htext(a['answer_text']):raise ValueError('altered original response')
            masked={z:docs[z] for z in case['source_ids']};masked[witness]=part
            displayed=[{'label':f'E{i}','text':masked[z]} for i,z in enumerate(case['source_ids'],1)]
            ticketid=hmac.new(secret, (cid+'\0'+rid+'\0'+arm).encode(), sha256).hexdigest()
            if ticketid in seen:raise ValueError('replayed ticket identity')
            seen.add(ticketid)
            tickets.append({'ticket_id':ticketid,'question':questions[cid],
                            'evidence':displayed,'original_reader_answer':a['answer_text'],
                            'review_fields':{'factually_correct':None,'sources_sufficient':None,
                                             'answer_entails_source':None,'critical_source_needed':None},
                            'instructions':'Independently judge semantic factual correctness and evidence sufficiency. Do not use publisher target labels or infer the hidden experimental arm.'})
            private.append({'ticket_id':ticketid,'case_id':cid,'family':fam,'arm':arm,'request_id':rid,
                            'answer_sha256':a['answer_sha256'],'source_id_sha256':digest(case['source_ids']),
                            'publisher_target_unavailable_to_reviewer':True})
    if len(tickets)!=128 or len(private)!=128:raise ValueError('incomplete blinded reviewer tickets')
    tickets.sort(key=lambda x:x['ticket_id']);private.sort(key=lambda x:x['ticket_id'])
    # Ticket receipts contain sensitive original source and answer text: owner-only.
    return ({'schema':SCHEMA+'.private-reviewer-tickets','count':128,'tickets':tickets,
             'zero_external_judgments':True,'publisher_labels_present':False,
             'independent_review_claimed':False,'production_authorized':False},
            {'schema':SCHEMA+'.private-owner-mapping','count':128,'mapping':private,
             'source_plan_sha256':digest(plan),'private_seed_sha256':sha256(secret).hexdigest(),
             'human_attestation_received':False,'production_authorized':False})


def main():
    p=argparse.ArgumentParser()
    for key in ('plan','v17-plan','v18-plan','v17-answers','v18-answers','v19-answers','source','secret','tickets','owner-map'):
        p.add_argument('--'+key,required=True)
    a=p.parse_args()
    secret=Path(a.secret).read_bytes()
    t,m=prepare(read(a.plan),read(a.v17_plan),read(a.v18_plan),read(a.v17_answers),read(a.v18_answers),read(a.v19_answers),read(a.source),secret)
    sealed(a.tickets,t);sealed(a.owner_map,m)
    print(json.dumps({'tickets':len(t['tickets']),'independent_reviews_received':0,'owner_mapping_separate':True},sort_keys=True))

if __name__=='__main__':main()
