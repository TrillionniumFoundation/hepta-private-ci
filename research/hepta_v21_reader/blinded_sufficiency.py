"""V21 source-first, *model-blind* human evidence-sufficiency intake.

Build 96 unique original Qwen evidence messages from the 120 V17/V19 logical
requests. Private tickets contain source text and NEVER enter Git or Actions
artifacts. The Git-visible record contains numeric counts and SHA digests only.
No human review is performed or certified by this module; DENY_ALL always.
"""
import argparse
from collections import Counter
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import stat

import source_first as v17
import v19_qwen_reference as qwen

SCHEMA = 'hepta.v21.source-first-blind-evidence-review.shadow.v1'
VERDICTS = ('sufficient', 'insufficient', 'indeterminate')
RECEIPT_FIELDS = frozenset((
    'schema','original_corpus_sha256','original_source_roots','original_questions',
    'logical_evidence_requests','distinct_evidence_tickets','aliases_reused',
    'original_reference_plan_sha256','sealed_private_roster_sha256',
    'sealed_private_mapping_sha256','gold_or_reader_answers_in_packet',
    'original_pretrained_model_calls','publisher_evidence_human_certified',
    'human_reviewer_results_received','independent_reviewer_signatures_verified',
    'model_improvement_verified','automatic_cell_split_authorized',
    'production_authorized','decision'
))
N_LOGICAL = 120
N_PHYSICAL = 96
N_CASES = 30


def _source_tree(paths):
    paths = [Path(p) for p in paths]
    if any(not p.is_file() or p.is_symlink() for p in paths):
        raise ValueError('source-first files missing or symlinked')
    if len({p.parent.resolve() for p in paths}) != 1:
        raise ValueError('source-first files must come from one immutable directory')
    source_dir = paths[0].parent
    for name in ('hidden.json', 'locomo.json', 'original.zip', 'postseal-original.zip',
                 'reader-135m-private.json', 'qwen-physical-private.json'):
        if (source_dir/name).exists() or (source_dir/name).is_symlink():
            raise ValueError('review intake cannot see publisher gold or model outputs')
    return source_dir


def prepare(paths, reference_plan, output_dir, *, blinding_key=None):
    """Prepare actual evidence content privately; emit a sanitized observation.

    Only a privileged review owner receives private tickets + the private alias
    map. A model worker must never receive those paths. Untrusted evidence text
    is never interpreted as instructions or authority.
    """
    _source_tree(paths)
    plan = qwen.validate(paths, reference_plan)
    public = v17.read(paths[0])
    owner = v17.read(paths[1])
    if (owner.get('schema') != v17.SCHEMA+'.owner' or
        owner.get('public_sha256') != v17.digest(public) or
        owner.get('hidden_sha256') is None or
        owner.get('authority') != 'DENY_ALL' or
        owner.get('production_accepted') is not False or
        plan.get('publisher_answer_labels_not_exposed') is not True or
        plan.get('production_authorized') is not False or
        plan.get('decision') != 'HOLD_NO_GO'):
        raise ValueError('original owner/plan cannot support model-blind review')
    if (set(x['id'] for x in public) != set(v17.ROOTS) or
        len(plan['cases']) != N_CASES or len(plan['entries']) != N_LOGICAL):
        raise ValueError('original source group/case universe incomplete')
    original_roots = {x['id']: x for x in public}
    by_message = {}
    logical_to_message = {}
    expected_logical = {cid+'|'+arm for cid in plan['cases'] for arm in v17.ARMS}
    if set(plan['entries']) != expected_logical:
        raise ValueError('one or more frozen source-policy requests missing')
    for rid, entry in sorted(plan['entries'].items()):
        if (type(entry) is not dict or
            entry.get('message_sha256') != v17.digest(entry.get('messages')) or
            entry.get('case_id')+'|'+entry.get('arm') != rid or
            entry.get('arm') not in v17.ARMS):
            raise ValueError('unbound original 135M / Qwen source request')
        case_id = entry['case_id']
        root = case_id.split('/')[0]
        if root not in original_roots:
            raise ValueError('unknown original conversation family')
        data = original_roots[root]
        questions = {x['id']:x['question'] for x in data['questions']}
        docs = {x['id']:x for x in data['utterances']}
        question = questions.get(case_id)
        refs = entry.get('source_ids')
        if (type(question) is not str or type(refs) is not list or
            len(refs)>3 or len(set(refs)) != len(refs) or
            any(x not in docs for x in refs)):
            raise ValueError('publisher question or citation address absent')
        messages = qwen.message(question, refs, docs)
        if messages != entry['messages'] or entry['question_sha256'] != v17.sha_text(question):
            raise ValueError('citation content changed despite a valid SHA manifest')
        item = {
            'question': question,
            'evidence': [dict(source_id=ref, speaker=docs[ref]['speaker'],
                              excerpt=docs[ref]['text'][:240]) for ref in refs],
        }
        key = entry['message_sha256']
        if key in by_message:
            if by_message[key]['content'] != item:
                raise ValueError('shared physical input has contradictory source bytes')
        else:
            by_message[key] = dict(content=item, original_root=root,
                                   canonical_input_sha256=key)
        logical_to_message[rid] = key
    if (len(by_message) != N_PHYSICAL or len(logical_to_message) != N_LOGICAL or
        len({k.split('|')[0] for k in logical_to_message}) != N_CASES):
        raise ValueError('96 unique source inputs and 120 action aliases required')
    if blinding_key is None:
        blinding_key = secrets.token_bytes(32)
    if type(blinding_key) is not bytes or len(blinding_key) != 32:
        raise ValueError('private blinding key must have 256 bits')
    tickets = {}
    mapping = {}
    for source_sha, row in by_message.items():
        blind_id = hmac.new(blinding_key, (SCHEMA+'\0'+source_sha).encode(), sha256).hexdigest()
        if blind_id in tickets:
            raise ValueError('blinded ticket ID collision')
        content = row['content']
        tickets[blind_id] = dict(ticket_id=blind_id,
                                 ticket_sha256=v17.digest(content),
                                 question=content['question'],
                                 evidence=content['evidence'])
        mapping[source_sha] = blind_id
    aliases = {rid:mapping[source_sha] for rid,source_sha in logical_to_message.items()}
    # The mapping with raw case and arm names MUST stay with the reviewer owner.
    roster = dict(schema=SCHEMA+'.private-blind-roster',
                  tickets={k:tickets[k] for k in sorted(tickets)},
                  source_first_note='not certified sufficient; no model or gold exposed',
                  authority='DENY_ALL')
    identity = dict(schema=SCHEMA+'.private-identity',
                    logical_to_ticket={k:aliases[k] for k in sorted(aliases)},
                    source_to_ticket={k:mapping[k] for k in sorted(mapping)},
                    raw_blinding_key_hex=blinding_key.hex(),
                    original_reference_plan_sha256=plan['plan_sha256'],
                    authority='DENY_ALL')
    summary = dict(schema=SCHEMA+'.sanitized-source-observation',
                   original_corpus_sha256=v17.CORPUS_SHA,
                   original_source_roots=len(v17.ROOTS),
                   original_questions=N_CASES,
                   logical_evidence_requests=N_LOGICAL,
                   distinct_evidence_tickets=N_PHYSICAL,
                   aliases_reused=N_LOGICAL-N_PHYSICAL,
                   original_reference_plan_sha256=plan['plan_sha256'],
                   sealed_private_roster_sha256=v17.digest(roster),
                   sealed_private_mapping_sha256=v17.digest(identity),
                   gold_or_reader_answers_in_packet=False,
                   original_pretrained_model_calls=0,
                   publisher_evidence_human_certified=False,
                   human_reviewer_results_received=False,
                   independent_reviewer_signatures_verified=False,
                   model_improvement_verified=False,
                   automatic_cell_split_authorized=False,
                   production_authorized=False,
                   decision='HOLD_NO_GO')
    dest=Path(output_dir)
    if dest.exists() or dest.is_symlink() or not dest.parent.is_dir():
        raise ValueError('private review folder must not exist')
    dest.mkdir(mode=0o700)
    try:
        for name,part in [('blinded-private.json',roster), ('identity-private.json',identity),
                          ('observation-sanitized.json',summary)]:
            v17.write_once(dest/name,part)
        # Best-effort parent directory durability; never disclose blinding key.
        fd=os.open(dest,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except BaseException:
        shutil.rmtree(dest)
        raise
    return summary



def verify_public_receipt(path):
    """Validate one Git-safe digest/count observation, not private contents."""
    obs=v17.read(path)
    if (type(obs) is not dict or set(obs) != RECEIPT_FIELDS or
        obs.get('schema') != SCHEMA+'.sanitized-source-observation' or
        obs.get('original_corpus_sha256') != v17.CORPUS_SHA or
        obs.get('original_source_roots') != 10 or obs.get('original_questions') != N_CASES or
        obs.get('logical_evidence_requests') != N_LOGICAL or
        obs.get('distinct_evidence_tickets') != N_PHYSICAL or
        obs.get('aliases_reused') != N_LOGICAL-N_PHYSICAL or
        obs.get('original_pretrained_model_calls') != 0 or
        obs.get('gold_or_reader_answers_in_packet') is not False or
        any(obs.get(k) is not False for k in (
            'publisher_evidence_human_certified','human_reviewer_results_received',
            'independent_reviewer_signatures_verified','model_improvement_verified',
            'automatic_cell_split_authorized','production_authorized')) or
        obs.get('decision') != 'HOLD_NO_GO' or
        any(type(obs.get(k)) is not str or len(obs[k]) != 64 or
            any(ch not in '0123456789abcdef' for ch in obs[k]) for k in (
            'original_reference_plan_sha256','sealed_private_roster_sha256',
            'sealed_private_mapping_sha256'))):
        raise ValueError('nonpublic content, forged original census or unwarranted authority')
    return dict(schema=SCHEMA+'.public-aggregate-verified',
                original_questions=N_CASES, distinct_tickets=N_PHYSICAL,
                original_reader_ran=False, external_review_complete=False,
                production_authorized=False, decision='HOLD_NO_GO')

def validate_private(roster_file, identity_file, observation_file):
    """Read-only consistency check. Cannot certify an external human reviewer."""
    paths=[Path(p) for p in (roster_file,identity_file,observation_file)]
    if any(not p.is_file() or p.is_symlink() or stat.S_IMODE(p.stat().st_mode)&0o077
           for p in paths):
        raise ValueError('missing or nonprivate review custody')
    roster,ident,receipt=map(v17.read,paths)
    if (type(roster) is not dict or set(roster) != {'schema','tickets',
          'source_first_note','authority'} or roster.get('authority') != 'DENY_ALL' or
        type(ident) is not dict or set(ident) != {'schema','logical_to_ticket',
          'source_to_ticket','raw_blinding_key_hex','original_reference_plan_sha256',
          'authority'} or ident.get('authority') != 'DENY_ALL' or
        type(receipt) is not dict or set(receipt) != RECEIPT_FIELDS or
        roster.get('schema')!=SCHEMA+'.private-blind-roster' or
        ident.get('schema')!=SCHEMA+'.private-identity' or
        receipt.get('schema')!=SCHEMA+'.sanitized-source-observation' or
        receipt.get('sealed_private_roster_sha256')!=v17.digest(roster) or
        receipt.get('sealed_private_mapping_sha256')!=v17.digest(ident) or
        receipt.get('original_corpus_sha256') != v17.CORPUS_SHA or
        receipt.get('original_source_roots') != len(v17.ROOTS) or
        receipt.get('original_questions') != N_CASES or
        receipt.get('logical_evidence_requests') != N_LOGICAL or
        receipt.get('distinct_evidence_tickets') != N_PHYSICAL or
        receipt.get('aliases_reused') != N_LOGICAL-N_PHYSICAL or
        receipt.get('original_reference_plan_sha256') != ident.get('original_reference_plan_sha256') or
        receipt.get('original_pretrained_model_calls') != 0 or
        receipt.get('gold_or_reader_answers_in_packet') is not False or
        receipt.get('publisher_evidence_human_certified') is not False or
        receipt.get('human_reviewer_results_received') is not False or
        receipt.get('independent_reviewer_signatures_verified') is not False or
        receipt.get('model_improvement_verified') is not False or
        receipt.get('automatic_cell_split_authorized') is not False or
        receipt.get('production_authorized') is not False or
        receipt.get('decision')!='HOLD_NO_GO'):
        raise ValueError('forged review material or premature scientific claim')
    tickets=roster.get('tickets')
    logical=ident.get('logical_to_ticket')
    bysource=ident.get('source_to_ticket')
    if (type(tickets) is not dict or len(tickets)!=N_PHYSICAL or
        type(logical) is not dict or len(logical)!=N_LOGICAL or
        type(bysource) is not dict or len(bysource)!=N_PHYSICAL or
        set(logical.values())!=set(tickets) or set(bysource.values())!=set(tickets) or
        set(logical)!={cid+'|'+arm for cid in
                        {x.split('|')[0] for x in logical} for arm in v17.ARMS}):
        raise ValueError('review tickets or logical alias census incomplete')
    key=bytes.fromhex(ident.get('raw_blinding_key_hex',''))
    if len(key)!=32 or any(hmac.new(key,(SCHEMA+'\0'+sid).encode(),sha256).hexdigest()!=bid
                        for sid,bid in bysource.items()):
        raise ValueError('private blind randomization key cannot reproduce IDs')
    for tid,record in tickets.items():
        if type(record) is not dict or record.get('ticket_id')!=tid or set(record)!={'ticket_id','ticket_sha256','question','evidence'}:
            raise ValueError('unbound private human-review ticket')
        if (type(record['question']) is not str or type(record['evidence']) is not list or
            len(record['evidence']) > 3 or
            any(type(e) is not dict or set(e) != {'source_id','speaker','excerpt'} or
                any(type(v) is not str or len(v) > 512 for v in e.values())
                for e in record['evidence'])):
            raise ValueError('review ticket source geometry changed')
        if record['ticket_sha256']!=v17.digest(dict(question=record['question'],evidence=record['evidence'])):
            raise ValueError('private evidence/question byte manipulation')
    return dict(schema=SCHEMA+'.local-custody-consistent', tickets=len(tickets),
                aliases=len(logical), independently_signed_human_review=False,
                production_authorized=False, decision='HOLD_NO_GO')


def reconcile_shadow_reviews(roster_file, opinion_a_file, opinion_b_file, output_file):
    """Two data-only shadow inputs. Identity strings alone are NOT signatures.

    External signature/trust-store verification remains a separate prerequisite;
    even unanimous decisions here cannot authorize a grounded-answer claim.
    """
    roster=v17.read(roster_file)
    if (type(roster) is not dict or set(roster) != {'schema','tickets',
        'source_first_note','authority'} or roster.get('schema')!=SCHEMA+'.private-blind-roster'
        or roster.get('authority')!='DENY_ALL'):
        raise ValueError('unsupported source-blind review roster')
    tickets=roster.get('tickets')
    a=v17.read(opinion_a_file);b=v17.read(opinion_b_file)
    if type(tickets) is not dict or len(tickets)!=N_PHYSICAL:
        raise ValueError('missing source-bounded original review tickets')
    for x in (a,b):
        if (type(x) is not dict or set(x)!={'schema','roster_sha256','reviewer_id','verdicts','authority'} or
            x['schema']!=SCHEMA+'.unsigned-review-input' or x['roster_sha256']!=v17.digest(roster) or
            type(x['reviewer_id']) is not str or not 1<=len(x['reviewer_id'])<=100 or
            type(x['verdicts']) is not dict or set(x['verdicts'])!=set(tickets) or
            x['authority']!='DENY_ALL'):
            raise ValueError('unregistered reviewer data or incomplete blinded review')
        for tid,judgment in x['verdicts'].items():
            if (type(judgment) is not dict or set(judgment)!={'ticket_sha256','sufficiency'} or
                judgment['ticket_sha256']!=tickets[tid]['ticket_sha256'] or
                judgment['sufficiency'] not in VERDICTS):
                raise ValueError('reviewer verdict detached from immutable source')
    if a['reviewer_id']==b['reviewer_id']:
        raise ValueError('two records claim the same reviewer')
    agreement=Counter();unresolved=0
    for tid in tickets:
        x=a['verdicts'][tid]['sufficiency'];y=b['verdicts'][tid]['sufficiency']
        if x==y and x!='indeterminate':agreement[x]+=1
        else:unresolved+=1
    result=dict(schema=SCHEMA+'.unsigned-two-reviewer-reconciliation',
                original_review_tickets=len(tickets),
                source_blind_agreed_sufficient=agreement['sufficient'],
                source_blind_agreed_insufficient=agreement['insufficient'],
                disagreement_or_indeterminate=unresolved,
                reviewers_claimed_distinct=2,
                independent_reviewer_identity_cryptographically_verified=False,
                evidence_sufficiency_certified=False,
                semantic_correctness_or_citation_entailment_verified=False,
                production_authorized=False,decision='HOLD_NO_GO')
    v17.write_once(output_file,result)
    return result


def cli():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare')
    for name in ('public','owner','v17-plan','annotation','v17-requests','reference-plan','private-folder'):
        p.add_argument('--'+name,required=True)
    p=sub.add_parser('verify-public')
    p.add_argument('--receipt',required=True)
    p=sub.add_parser('verify-private')
    for name in ('roster','identity','observation'):p.add_argument('--'+name,required=True)
    p=sub.add_parser('unsigned-two-reviewer-shadow')
    for name in ('roster','review-a','review-b','output'):p.add_argument('--'+name,required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        source=[getattr(args,n.replace('-','_')) for n in
                ('public','owner','v17-plan','annotation','v17-requests')]
        result=prepare(source,args.reference_plan,args.private_folder)
    elif args.command=='verify-public':
        result=verify_public_receipt(args.receipt)
    elif args.command=='verify-private':
        result=validate_private(args.roster,args.identity,args.observation)
    else:
        result=reconcile_shadow_reviews(args.roster,args.review_a,args.review_b,args.output)
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':cli()
