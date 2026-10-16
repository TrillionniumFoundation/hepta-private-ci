"""Owner-private blind intake for four exact original V18 Reader answers per case.

No model calls and no human judgments are generated. The HMAC seed and arm map
must stay owner-private and NEVER be uploaded to public GitHub/Actions.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from v18_factorial_original_reader import ALL_ARMS, digest, htext, sealed


def build(plan, v17, new_outputs, old_outputs, secret):
    if type(secret)is not bytes or len(secret)<32:
        raise ValueError('unguessable owner-only HMAC key required')
    if (new_outputs.get('plan_sha256')!=digest(plan) or
        old_outputs.get('plan_sha256')!=digest(v17) or
        new_outputs.get('requests')!=58 or old_outputs.get('requests')!=64):
        raise ValueError('original sealed model outputs required')
    questions=[];mapping=[];names=set()
    for case in plan['cases']:
        for arm in ALL_ARMS:
            if arm in ('full_full_heading','focused_focus_heading'):
                rid=case[arm];req=v17['requests'][rid];out=old_outputs['raw_answers'][rid]
            else:
                rid=case['cross_arms'][arm]['request_id']
                if case['cross_arms'][arm]['reused_v17']:
                    req=v17['requests'][rid];out=old_outputs['raw_answers'][rid]
                else:
                    req=plan['new_requests'][rid];out=new_outputs['raw_answers'][rid]
            prompt=req['prompt'];sid=case['case_id']
            tag=hmac.new(secret,(sid+'\x00'+arm+'\x00'+rid).encode(),hashlib.sha256).hexdigest()
            if tag in names or out['case_id']!=sid or out['source_ids']!=req['source_ids']:
                raise ValueError('blinded ticket collision or changed original answer')
            names.add(tag)
            questions.append({'ticket_id':tag,'source_request_sha256':rid,
                'full_question_and_delivered_source_prompt':prompt,
                'unaltered_original_reader_answer':out['answer_text'],
                'answer_sha256':out['answer_sha256'],
                'independent_correctness_judgment':None,
                'independent_source_sufficiency_judgment':None,
                'independent_citation_entailment_judgment':None,
                'independent_reviewer_id':None})
            mapping.append({'ticket_id':tag,'family':case['family'],'case_id':sid,
                'intervention_arm':arm,'request_sha256':rid})
    if len(questions)!=128 or len(mapping)!=128:
        raise ValueError('incomplete 32x4 original Reader review census')
    questions.sort(key=lambda x:x['ticket_id']);mapping.sort(key=lambda x:x['ticket_id'])
    return {'schema':'hepta.stem.v18.blind-review.pending.v1','tickets':questions,
            'human_opinions_received':0,'all_judgments_independent':False,
            'not_for_public_repository':True,'production_authorized':False}, {
            'schema':'hepta.stem.v18.owner-only-arm-map.v1','owner_secret_hex':secret.hex(),
            'mapping':mapping,'not_for_reviewers':True,'not_for_public_repository':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--v17-plan',required=True)
    p.add_argument('--new-answers',required=True);p.add_argument('--v17-answers',required=True)
    p.add_argument('--tickets',required=True);p.add_argument('--owner-map',required=True)
    a=p.parse_args();raw=lambda p:json.loads(Path(p).read_text())
    tickets,secret=build(raw(a.plan),raw(a.v17_plan),raw(a.new_answers),raw(a.v17_answers),secrets.token_bytes(32))
    sealed(a.tickets,tickets);sealed(a.owner_map,secret)
    print(json.dumps({'blinded_tickets':len(tickets['tickets']),
        'human_reviews_received':0,'owner_map_private':True,'production_authorized':False}))

if __name__=='__main__':main()
