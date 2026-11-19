"""Label-blind, source-grounded finite Cell-Group evidence-budget study.

BIND/COMPOSE/VERIFY/STOP are typed evidence operations, NOT learned neural
reasoning. `ndu_shadow` is a finite additive-utility special case, NOT FBSDE.
No answer/hidden labels/model weights are read by the producer.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

import v15_evidence_proposer as v15
from v15_hotpot_source import SCHEMA as SOURCE_SCHEMA, digest, load, write_once
import v15_hotpot_source as source

PLAN_SCHEMA = 'hepta.v16.hotpot-group-budget-plan.v1'
TRACE_SCHEMA = 'hepta.v16.hotpot-group-evidence-traces.v1'
POLICIES = ('bm25_2', 'bm25_5', 'graph_5', 'lesion_5', 'hash_5',
            'ndu_shadow', 'ordinary_same_profile', 'hash_budget')
CITATION_TARIFF_UNITS = 18  # registered proxy-cost units, NOT CPU/token/dollars
MAX_CANDIDATES = 8192


def sha_bytes(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def expected_materials():
    return {'v15_ranker_sha256': sha_bytes(v15.__file__),
            'v16_producer_sha256': sha_bytes(__file__)}


def check_public(public, owner):
    if (type(public) is not list or len(public) != source.N_EXPECTED
            or type(owner) is not dict or owner.get('schema') != SOURCE_SCHEMA
            or owner.get('original_cases') != source.N_EXPECTED
            or owner.get('public_sha256') != digest(public)
            or owner.get('original_sha256') != source.SOURCE_SHA256
            or owner.get('dataset_split') != 'distractor_validation'
            or owner.get('source_license') != 'CC-BY-SA-4.0'
            or owner.get('authority') != 'DENY_ALL'
            or owner.get('production_accepted') is not False):
        raise ValueError('original complete public corpus or owner identity mismatch')
    seen = set()
    for row in public:
        if (type(row) is not dict or set(row) != {'id', 'question', 'context'}
                or type(row['id']) is not str or row['id'] in seen
                or type(row['question']) is not str or not row['question']
                or type(row['context']) is not list or not row['context']):
            raise ValueError('duplicate, gold-bearing or incomplete public question')
        seen.add(row['id'])
    return True


def proxy_reward(row, picks, source_map):
    """Integer source-only *proxy*, not task correctness or expected NDU value."""
    titles = {title for title, _ in picks}
    terms = set(v15.tokens(row['question']))
    covered = set()
    for citation in picks:
        title, position = citation
        covered.update(v15.tokens(title + ' ' + source_map[(title, position)]))
    return 60 * min(len(titles), 3) + 40 * len(terms & covered) // max(1, len(terms))


def canonical_action_trace(picks, edge):
    actions = ['BIND', 'COMPOSE_LEXICAL_EDGE' if edge else 'NO_OBSERVED_EDGE',
               'VERIFY_TOP2']
    if len(picks) > 2:
        actions.extend(['EXPAND_3', 'VERIFY_FINAL'])
    actions.append('STOP')
    return actions


def run_one(row):
    if type(row) is not dict or set(row) != {'id', 'question', 'context'}:
        raise ValueError('no hidden labels, answers, or extra public fields')
    candidates, scores, bm25 = v15.corpus_features(row['context'], row['question'])
    if not 5 <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError('requires at least 5 real original source sentences')
    source_map = {(title, pos): text for title, pos, text in candidates}
    if len(source_map) != len(candidates):
        raise ValueError('source sentence identity alias')
    linked, observed = v15.bridge_ranking(row['context'], candidates, scores, bm25, broken=False)
    lesion, _ = v15.bridge_ranking(row['context'], candidates, scores, bm25, broken=True)
    random_rank = sorted(range(len(candidates)), key=lambda i: sha256(
        ('hepta-v15-hash-null/' + row['id'] + '/' + candidates[i][0] + '/' + str(candidates[i][1])).encode()).digest())
    ranking = {'bm25_2': bm25, 'bm25_5': bm25, 'graph_5': linked,
               'lesion_5': lesion, 'hash_5': random_rank,
               'ndu_shadow': linked, 'ordinary_same_profile': linked,
               'hash_budget': linked}
    group = {}
    first_two = [(candidates[i][0], candidates[i][1]) for i in linked[:2]]
    first_five = [(candidates[i][0], candidates[i][1]) for i in linked[:5]]
    u2 = proxy_reward(row, first_two, source_map) - 2 * CITATION_TARIFF_UNITS
    u5 = proxy_reward(row, first_five, source_map) - 5 * CITATION_TARIFF_UNITS
    # Strict STOP on tie. Ordinary exhaustive Bellman must agree with
    # the marginal-value controller under the SAME declared linear objective.
    continue_shadow = (proxy_reward(row, first_five, source_map)
                       - proxy_reward(row, first_two, source_map) > 3 * CITATION_TARIFF_UNITS)
    ordinary_best = min([(2, -u2), (5, -u5)], key=lambda pair: (pair[1], pair[0]))[0]
    if (5 if continue_shadow else 2) != ordinary_best:
        raise ValueError('finite additive-control and exhaustive reference diverged')
    for policy in POLICIES:
        budget = 5 if policy in ('bm25_5', 'graph_5', 'lesion_5', 'hash_5') else 2
        if policy == 'ndu_shadow':
            budget = 5 if continue_shadow else 2
        elif policy == 'ordinary_same_profile':
            budget = ordinary_best
        elif policy == 'hash_budget':
            budget = 5 if sha256(('hepta-v16-budget-null/' + row['id']).encode()).digest()[0] < 128 else 2
        selections = [(candidates[i][0], candidates[i][1]) for i in ranking[policy][:budget]]
        if len(selections) != budget or len(set(selections)) != budget:
            raise ValueError('duplicate or missing source-bound citation')
        # Claims only a literal article-title mention, never a valid semantic edge.
        edge = (policy in ('graph_5', 'ndu_shadow', 'ordinary_same_profile', 'hash_budget')
                and observed and len(selections) >= 2
                and selections[0][0] != selections[1][0]
                and v15.contains_title(source_map[selections[0]], selections[1][0]))
        cites = [[title, pos] for title, pos in selections]
        evidence = [[title, pos, source_map[(title, pos)]] for title, pos in selections]
        reward = proxy_reward(row, selections, source_map)
        group[policy] = dict(citations=cites, input_sha256=digest(evidence),
            evidence_bytes=sum(len(text.encode('utf-8')) for _, _, text in evidence),
            citation_slots=len(cites), reward_proxy_units=reward,
            utility_proxy_units=reward - CITATION_TARIFF_UNITS * len(cites),
            lexical_edge_observed=bool(edge),
            operations=canonical_action_trace(selections, bool(edge)))
    if group['ndu_shadow'] != group['ordinary_same_profile']:
        raise ValueError('false policy-specific gain from identical evidence and objective')
    return dict(source_sha256=digest(row), candidate_sentence_count=len(candidates),
                lexical_link_found=bool(observed), policies=group)


def make_plan(public_file, owner_file, output_file):
    public, owner = load(public_file), load(owner_file)
    check_public(public, owner)
    m = dict(schema=PLAN_SCHEMA, source_sha256=digest(public),
        owner_sha256=digest(owner), official_source_sha256=owner['original_sha256'],
        policies=list(POLICIES), tariff_units=CITATION_TARIFF_UNITS,
        proxy='60*min(unique_titles,3)+40*covered_query_terms//max(1,query_terms)',
        stop_tie='STOP', action_budget_slots=[2, 5],
        independent_source_groups_not_established=True,
        full_source_scan_per_question_required=True,
        original_HotpotQA_validation=True, reader_forwards=0,
        training_updates=0, final_answers_generated=False,
        no_NDU_FBSDE_solver=True, no_learned_cell=True,
        held_gold_visible_to_proposer=False, model_selected=False,
        authority='DENY_ALL', production_accepted=False,
        **expected_materials())
    m['plan_sha256'] = digest(m)
    write_once(output_file, m)
    return m


def propose(public_file, owner_file, plan_file, output_file):
    public, owner, plan = load(public_file), load(owner_file), load(plan_file)
    check_public(public, owner)
    if (type(plan) is not dict or plan.get('schema') != PLAN_SCHEMA
            or plan.get('plan_sha256') != digest({k:v for k,v in plan.items() if k!='plan_sha256'})
            or plan.get('source_sha256') != digest(public) or plan.get('owner_sha256') != digest(owner)
            or plan.get('policies') != list(POLICIES) or plan.get('tariff_units') != CITATION_TARIFF_UNITS
            or plan.get('held_gold_visible_to_proposer') is not False
            or plan.get('reader_forwards') != 0 or plan.get('training_updates') != 0
            or plan.get('authority') != 'DENY_ALL' or plan.get('production_accepted') is not False
            or any(plan.get(k) != v for k, v in expected_materials().items())):
        raise ValueError('preregistered source/blind/material/authority mismatch')
    start = time.process_time_ns()
    records = {}
    for row in public:
        if row['id'] in records:
            raise ValueError('duplicate source ID')
        records[row['id']] = run_one(row)
    if len(records) != source.N_EXPECTED:
        raise ValueError('incomplete original 7405-case source cohort')
    result = dict(schema=TRACE_SCHEMA, source_sha256=digest(public),
        owner_sha256=digest(owner), plan_sha256=plan['plan_sha256'],
        completed_questions=len(records), producer_cpu_ns=time.process_time_ns()-start,
        unique_shared_source_scans=sum(r['candidate_sentence_count'] for r in records.values()),
        records=records, records_sha256=digest(records),
        policy_outputs_no_hidden_labels=True, single_shared_rank_calculation_per_question=True,
        no_pretrained_reader_calls=True, no_training=True, no_answer_generation=True,
        no_NDU_FBSDE_solver=True, source_time_prospective=False,
        authority='DENY_ALL', model_selected=False, production_accepted=False)
    write_once(output_file, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('plan', 'propose'):
        s = sub.add_parser(name)
        s.add_argument('--public', required=True)
        s.add_argument('--owner', required=True)
        s.add_argument('--output', required=True)
        if name == 'propose':
            s.add_argument('--plan', required=True)
    args = parser.parse_args()
    result = make_plan(args.public, args.owner, args.output) if args.action == 'plan' else propose(
        args.public, args.owner, args.plan, args.output)
    print(json.dumps({k: result.get(k) for k in ('schema', 'plan_sha256', 'records_sha256',
                                      'completed_questions', 'unique_shared_source_scans')}))


if __name__ == '__main__':
    main()
