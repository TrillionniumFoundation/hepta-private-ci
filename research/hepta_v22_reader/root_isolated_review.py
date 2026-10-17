"""V22 private, root-isolated assignment of V21 original source-blind tickets.

The original V21 96-ticket *owner* packet must NOT be distributed to reviewers:
its alternative evidence treatments for a question and multiple questions from
one original conversation would contaminate an arm-blind sufficiency judgment.

Each exposed slot sees <=1 ticket per real LoCoMo source root. Every ticket
receives exactly two distinct slot assignments. Slots are *not human identities*;
external signer identity and independence remain unverified and DENY_ALL.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import shutil
import stat

import blinded_sufficiency as v21
import source_first as v17

SCHEMA = 'hepta.v22.root-isolated-blinded-evidence.shadow.v1'
ROSTER = 'blinded-private.json'
IDENTITY = 'identity-private.json'
OBSERVATION = 'observation-sanitized.json'
MAX_SLOTS = 32
TWO = 2


def _private(path):
    p = Path(path)
    if (not p.is_file() or p.is_symlink() or
            stat.S_IMODE(p.stat().st_mode) & 0o077):
        raise ValueError('untrusted or exposed private review input')
    return v17.read(p)


def _get_intake(folder):
    root = Path(folder)
    if not root.is_dir() or root.is_symlink() or stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError('private owner folder must be an isolated 0700 directory')
    a,b,c = (root / s for s in (ROSTER, IDENTITY, OBSERVATION))
    v21.validate_private(a,b,c)
    return _private(a), _private(b), _private(c)


def derive(roster, ident, parent):
    """Source-root disjoint slot matching, determined only by private V21 keys.

    Because every source root has <= MAX_SLOTS/2 unique tickets, the minimum
    possible number of root-isolated reviewer slots is exactly twice the largest
    source-root ticket count. Cross-root slots can be reused safely *only if*
    the externally designated people really remain separate and blinded.
    """
    tickets = roster['tickets']
    logical = ident['logical_to_ticket']
    secret = bytes.fromhex(ident['raw_blinding_key_hex'])
    if len(secret) != 32 or len(tickets) != 96 or len(logical) != 120:
        raise ValueError('private source plan census incomplete')
    roots = defaultdict(set)
    ticket_root = {}
    for rid, tid in logical.items():
        bits = rid.split('|')
        if len(bits) != 2 or bits[1] not in v17.ARMS:
            raise ValueError('invalid original request identity')
        case = bits[0]
        if case.count('/') != 1 or not case.split('/')[1].startswith('q'):
            raise ValueError('unfrozen original question identity')
        root = case.split('/')[0]
        if root not in v17.ROOTS or tid not in tickets:
            raise ValueError('foreign source root/ticket')
        if tid in ticket_root and ticket_root[tid] != root:
            raise ValueError('cross-root alias mixes distinct publisher conversations')
        roots[root].add(tid)
        ticket_root[tid] = root
    if set(roots) != set(v17.ROOTS) or set(ticket_root) != set(tickets):
        raise ValueError('missing source roots or orphaned review ticket')

    slots_needed = TWO * max(len(items) for items in roots.values())
    if not 2 <= slots_needed <= MAX_SLOTS:
        raise ValueError('reviewer capacity inadequate to prevent source contamination')
    def shuffle_key(domain, value):
        return hmac.new(secret, (SCHEMA+'\0'+domain+'\0'+value).encode(), sha256).digest()

    assigned = {}
    root_by_slot = defaultdict(set)
    for root in sorted(roots):
        tickets_ordered = sorted(roots[root], key=lambda t: (shuffle_key('ticket:'+root,t),t))
        reviewer_slots = sorted(range(slots_needed),
                                key=lambda i: (shuffle_key('slot:'+root,str(i)),i))
        for index, tid in enumerate(tickets_ordered):
            pair = sorted(reviewer_slots[2*index:2*index+2])
            if len(pair) != 2 or pair[0] == pair[1]:
                raise ValueError('missing independent review exposure slots')
            for slot in pair:
                if root in root_by_slot[slot]:
                    raise ValueError('cross-arm or cross-question root exposure')
                root_by_slot[slot].add(root)
            assigned[tid] = pair
    if set(assigned) != set(tickets):
        raise ValueError('uncovered original source review ticket')
    return dict(schema=SCHEMA+'.owner-assignment',
                parent_roster_sha256=v17.digest(roster),
                parent_identity_sha256=v17.digest(ident),
                parent_observation_sha256=v17.digest(parent),
                source_roots=len(roots), logical_requests=len(logical),
                unique_tickets=len(tickets), slots=slots_needed,
                total_exposures=sum(len(pair) for pair in assigned.values()),
                assignments={t:assigned[t] for t in sorted(assigned)},
                root_by_ticket={t:ticket_root[t] for t in sorted(ticket_root)},
                source_root_ticket_counts={r:len(roots[r]) for r in sorted(roots)},
                authority='DENY_ALL',
                external_reviewers_authenticated=False,
                sufficiency_certified=False,
                production_authorized=False)


def _packets(plan, roster):
    packet_roster = {n: [] for n in range(plan['slots'])}
    for tid, pair in plan['assignments'].items():
        for slot in pair:
            packet_roster[slot].append(roster['tickets'][tid])
    return {slot:dict(schema=SCHEMA+'.private-reviewer-slot',
                      source_owner_sha256=plan['parent_roster_sha256'],
                      reviewer_slot=slot,
                      tickets=sorted(packet_roster[slot],key=lambda t:t['ticket_id']),
                      gold_answers_or_model_outputs_included=False,
                      other_policy_variants_included=False,
                      human_reviewer_identity_authenticated=False,
                      authority='DENY_ALL')
            for slot in range(plan['slots'])}


def _receipt(plan, packets):
    return dict(schema=SCHEMA+'.sanitized-observation',
                parent_observation_sha256=plan['parent_observation_sha256'],
                parent_roster_sha256=plan['parent_roster_sha256'],
                original_source_roots=plan['source_roots'],
                original_questions=30, logical_requests=plan['logical_requests'],
                distinct_tickets=plan['unique_tickets'],
                reviewer_slots=plan['slots'], reviewer_exposures=plan['total_exposures'],
                max_per_source_root_per_slot=1,
                reviewer_packet_counts=[len(packets[i]['tickets']) for i in sorted(packets)],
                assignment_sha256=v17.digest(plan),
                packet_digests=[v17.digest(packets[i]) for i in sorted(packets)],
                actual_human_reviews_received=False,
                independent_reviewer_identities_verified=False,
                evidence_sufficiency_certified=False,
                reader_semantic_accuracy_verified=False,
                model_pretrained_forwards_this_step=0,
                ndu_system2_learning_verified=False,
                production_authorized=False,
                decision='HOLD_NO_GO')


def prepare(intake_dir, target_dir):
    roster, ident, parent = _get_intake(intake_dir)
    plan = derive(roster,ident,parent)
    packets = _packets(plan,roster)
    receipt = _receipt(plan,packets)
    target = Path(target_dir)
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ValueError('reviewer private packets must be create-only')
    target.mkdir(mode=0o700)
    try:
        packet_folder = target/'reviewer-slots'
        packet_folder.mkdir(mode=0o700)
        v17.write_once(target/'owner-assignment-private.json',plan)
        for slot,packet in sorted(packets.items()):
            v17.write_once(packet_folder/f'slot-{slot:02}.json',packet)
        v17.write_once(target/'observation-sanitized.json',receipt)
        for directory in (packet_folder,target):
            fd=os.open(directory,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
    except BaseException:
        shutil.rmtree(target)
        raise
    return receipt


def verify_private(intake_dir, target_dir):
    roster, ident, parent = _get_intake(intake_dir)
    target=Path(target_dir)
    if not target.is_dir() or target.is_symlink() or stat.S_IMODE(target.stat().st_mode)&0o077:
        raise ValueError('reviewer owner folder not private')
    plan = derive(roster,ident,parent)
    expected = _packets(plan,roster)
    want = _receipt(plan,expected)
    observed = _private(target/'observation-sanitized.json')
    stored = _private(target/'owner-assignment-private.json')
    folder = target/'reviewer-slots'
    if not folder.is_dir() or folder.is_symlink() or stat.S_IMODE(folder.stat().st_mode)&0o077:
        raise ValueError('reviewer packets not private')
    files = sorted(folder.iterdir())
    names = sorted(f'slot-{i:02}.json' for i in expected)
    if [p.name for p in files] != names or observed != want or stored != plan:
        raise ValueError('reviewer assignment or digest changed after source seal')
    for slot, packet in expected.items():
        if _private(folder/f'slot-{slot:02}.json') != packet:
            raise ValueError('reviewer slot gained extra original root/arm or false citation')
        roots = [plan['root_by_ticket'][t['ticket_id']] for t in packet['tickets']]
        if len(roots) != len(set(roots)):
            raise ValueError('same reviewer exposed to multiple tickets from one root')
    return dict(schema=SCHEMA+'.private-replay-verification',
                original_tickets=len(roster['tickets']),
                assigned_exposures=plan['total_exposures'],
                reviewer_slots=plan['slots'],
                root_isolation_verified=True,
                real_reviewer_identity_authenticated=False,
                no_model_answers_scored=True,
                production_authorized=False,decision='HOLD_NO_GO')


def verify_public(path):
    o=v17.read(path)
    fields={'schema','parent_observation_sha256','parent_roster_sha256',
            'original_source_roots','original_questions','logical_requests',
            'distinct_tickets','reviewer_slots','reviewer_exposures',
            'max_per_source_root_per_slot','reviewer_packet_counts',
            'assignment_sha256','packet_digests','actual_human_reviews_received',
            'independent_reviewer_identities_verified','evidence_sufficiency_certified',
            'reader_semantic_accuracy_verified','model_pretrained_forwards_this_step',
            'ndu_system2_learning_verified','production_authorized','decision'}
    if type(o) is not dict or set(o)!=fields:
        raise ValueError('not a recognized source-only assignment receipt')
    if (o['schema']!=SCHEMA+'.sanitized-observation' or
        o['original_source_roots']!=10 or o['original_questions']!=30 or
        o['logical_requests']!=120 or o['distinct_tickets']!=96 or
        type(o['reviewer_slots']) is not int or not 2<=o['reviewer_slots']<=MAX_SLOTS or
        o['reviewer_exposures']!=192 or o['max_per_source_root_per_slot']!=1 or
        type(o['reviewer_packet_counts']) is not list or
        len(o['reviewer_packet_counts'])!=o['reviewer_slots'] or
        any(type(v) is not int or v<0 or v>10 for v in o['reviewer_packet_counts']) or
        sum(o['reviewer_packet_counts'])!=192 or
        type(o['packet_digests']) is not list or len(o['packet_digests'])!=o['reviewer_slots'] or
        o['model_pretrained_forwards_this_step']!=0 or
        any(o[k] is not False for k in (
          'actual_human_reviews_received','independent_reviewer_identities_verified',
          'evidence_sufficiency_certified','reader_semantic_accuracy_verified',
          'ndu_system2_learning_verified','production_authorized')) or
        o['decision']!='HOLD_NO_GO'):
        raise ValueError('fabricated human/Reader authority or incomplete reviewer exposure')
    for name in ('parent_observation_sha256','parent_roster_sha256','assignment_sha256'):
        val=o[name]
        if type(val) is not str or len(val)!=64 or any(ch not in '0123456789abcdef' for ch in val):
            raise ValueError('invalid provenance digest')
    for item in o['packet_digests']:
        if type(item) is not str or len(item)!=64 or any(ch not in '0123456789abcdef' for ch in item):
            raise ValueError('invalid reviewer packet digest')
    return dict(schema=SCHEMA+'.public-negative-verified',
                exposure_slots=o['reviewer_slots'],
                exposures=o['reviewer_exposures'],
                independent_human_reviews=0,
                production_authorized=False,decision='HOLD_NO_GO')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare')
    a.add_argument('--private-v21',required=True)
    a.add_argument('--output',required=True)
    a=sub.add_parser('verify-private')
    a.add_argument('--private-v21',required=True)
    a.add_argument('--private-v22',required=True)
    a=sub.add_parser('verify-public')
    a.add_argument('--receipt',required=True)
    v=ap.parse_args()
    if v.action=='prepare':
        response=prepare(v.private_v21,v.output)
    elif v.action=='verify-private':
        response=verify_private(v.private_v21,v.private_v22)
    else:response=verify_public(v.receipt)
    print(json.dumps(response,sort_keys=True))


if __name__=='__main__':main()
