"""No-gold, no-model, equal-Top-K natural-question evidence selectors.

V15 intentionally tests cheap baselines and a heuristic title-entity bridge only.
It DOES NOT answer questions or infer semantic relation roles from arbitrary text.
Per-question candidate pool is the 10 ORIGINAL public distractor paragraphs.
"""
from collections import Counter
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import re
import time

from v15_hotpot_source import SCHEMA, N_EXPECTED, digest, load, write_once

SCHEMA_PRED = 'hepta.v15.hotpotqa-sourceblind-evidence.v1'
ARMS = ('bm25', 'title_link', 'scrambled_link', 'hash_random')
BUDGETS = (2, 5)
STOP = set('a an the of in on by to for from and or is are was were as that which what where when who how whose with at did does do have has had it its this those these their he she his her they but about after before been being than more most'.split())
WORDS = re.compile(r"[\w]+(?:['’][\w]+)?", re.UNICODE)


def tokens(text):
    return [x.casefold() for x in WORDS.findall(text) if x.casefold() not in STOP and len(x) > 1]


def contains_title(sentence, title):
    name = tokens(title)
    if not name or len(name) > 18:
        return False
    sent = tokens(sentence)
    return any(sent[i:i+len(name)] == name for i in range(len(sent)-len(name)+1))


def corpus_features(context, question):
    sentences = [(title, i, sentence) for title, para in context for i, sentence in enumerate(para)]
    if not sentences or len(sentences) > 8192:
        raise ValueError('bounded complete candidate sentences required')
    q = Counter(tokens(question))
    bags = [Counter(tokens(title) + tokens(sent)) for title, _, sent in sentences]
    n = len(sentences)
    df = Counter(term for bag in bags for term in bag)
    avg_length = sum(sum(bag.values()) for bag in bags) / n or 1.
    scores = []
    for bag in bags:
        length = sum(bag.values())
        score = sum(
            min(2, freq) * math.log1p((n - df.get(word, 0) + .5) / (df.get(word, 0) + .5))
            * (bag[word] * 2.2 / (bag[word] + 1.2 * (.25 + .75 * length / avg_length)))
            for word, freq in q.items() if bag.get(word)
        )
        scores.append(score)
    # Make tie handling a function of original source identity, not insertion order.
    order = sorted(range(n), key=lambda i: (-scores[i], sentences[i][0].casefold(), sentences[i][1]))
    return sentences, scores, order


def bridge_ranking(context, sentences, scores, order, *, broken):
    titles = [title for title, _ in context]
    keys = {t: i for i, t in enumerate(titles)}
    assert len(keys) == len(titles)
    by_title = {}
    for index, (title, _, _) in enumerate(sentences):
        by_title.setdefault(title, []).append(index)
    anchors = order[:min(16, len(order))]
    best = None
    best_weight = float('-inf')
    for anchor in anchors:
        anchor_title, _, anchor_sentence = sentences[anchor]
        for original_title in titles:
            if original_title == anchor_title or not contains_title(anchor_sentence, original_title):
                continue
            # The lesion changes ONLY the graph-linked target (not public text,
            # question, BM25 lexical score or candidate count).
            target_title = titles[(keys[original_title] + 1) % len(titles)] if broken else original_title
            if target_title == anchor_title or target_title not in by_title:
                continue
            target = min(by_title[target_title], key=lambda i: (-scores[i], sentences[i][1]))
            pair = (anchor, target)
            value = scores[anchor] + scores[target] + 2.5
            if value > best_weight:
                best, best_weight = pair, value
    if best is None:
        # Without an observed title link, the bridge has NO certified relation;
        # use the original BM25 ordering, not an invented edge or gold support.
        return order, False
    ranked = list(dict.fromkeys((*best, *order)))
    return ranked, True


def predict_one(row):
    if not isinstance(row, dict) or set(row) != {'id', 'question', 'context'}:
        raise ValueError('public question and paragraphs only (no gold)')
    qid, question, context = row['id'], row['question'], row['context']
    if not isinstance(qid, str) or not isinstance(question, str) or not isinstance(context, list):
        raise ValueError('bounded question and context required')
    candidates, scores, bm25 = corpus_features(context, question)
    linked, observed = bridge_ranking(context, candidates, scores, bm25, broken=False)
    damaged, _ = bridge_ranking(context, candidates, scores, bm25, broken=True)
    randomized = sorted(range(len(candidates)), key=lambda i: sha256(
        f'hepta-v15-hash-null/{qid}/{candidates[i][0]}/{candidates[i][1]}'.encode()).digest())
    rankings = dict(bm25=bm25, title_link=linked, scrambled_link=damaged,
                    hash_random=randomized)
    selections = {}
    for arm in ARMS:
        selections[arm] = {
            str(k): [[candidates[i][0], candidates[i][1]] for i in rankings[arm][:k]]
            for k in BUDGETS
        }
    return selections, dict(candidates=len(candidates), title_link_found=observed)


def plan(public_file, source_manifest_file, destination):
    public, manifest = load(public_file), load(source_manifest_file)
    if (manifest.get('schema') != SCHEMA or manifest.get('original_cases') != N_EXPECTED
            or manifest.get('public_sha256') != digest(public)
            or len(public) != N_EXPECTED
            or any(type(c) is not dict or set(c) != {'id', 'question', 'context'} for c in public)
            or manifest.get('authority') != 'DENY_ALL'):
        raise ValueError('original, complete label-free public HotpotQA dev required')
    data = dict(schema='hepta.v15.evidence-ranking-preregistration.v1',
                public_sha256=digest(public), owner_manifest_sha256=digest(manifest),
                held_questions=len(public), arms=list(ARMS),budgets=list(BUDGETS),
                BM25_k1=1.2, BM25_b=.75, title_link_bonus=2.5, seed='hash-of-public-id',
                on_question_context_only=True, global_held_corpus_statistics_used=False,
                no_train_labels_consumed=True, no_held_labels_consumed=True,
                human_original_source=True, source_time_prospective=False,
                provides_final_answer=False, pretrained_forwards=0,
                optimizer_steps=0, authority='DENY_ALL', model_selected=False,
                production_accepted=False)
    data['plan_sha256'] = digest({k:v for k,v in data.items() if k != 'plan_sha256'})
    write_once(destination, data)
    return data


def propose(public_file, source_manifest_file, plan_file, destination):
    public, manifest, config = load(public_file), load(source_manifest_file), load(plan_file)
    if (config.get('schema') != 'hepta.v15.evidence-ranking-preregistration.v1'
            or config.get('plan_sha256') != digest({k:v for k,v in config.items() if k != 'plan_sha256'})
            or config.get('public_sha256') != digest(public)
            or config.get('owner_manifest_sha256') != digest(manifest)
            or config.get('arms') != list(ARMS) or config.get('budgets') != list(BUDGETS)
            or config.get('global_held_corpus_statistics_used') is not False
            or config.get('no_held_labels_consumed') is not True
            or config.get('authority') != 'DENY_ALL'):
        raise ValueError('registered, complete label-blind model plan required')
    started = time.process_time_ns()
    all_scores = {}
    count = linked = 0
    for row in public:
        if row['id'] in all_scores:
            raise ValueError('duplicate public source ID')
        prediction, trace = predict_one(row)
        all_scores[row['id']] = prediction
        count += trace['candidates']
        linked += bool(trace['title_link_found'])
    if len(all_scores) != N_EXPECTED:
        raise ValueError('missing original dev question predictions')
    receipt = dict(schema=SCHEMA_PRED,source_sha256=digest(public),
                   source_owner_sha256=digest(manifest), plan_sha256=config['plan_sha256'],
                   answers_or_gold_never_read=True, candidate_sentence_evaluations=count,
                   questions_with_observed_title_link=linked, completed_questions=len(all_scores),
                   proposals=all_scores, cpu_ns=time.process_time_ns() - started,
                   optimizer_updates=0, pretrained_calls=0, model_selected=False,
                   actual_answer_generation=False, license='CC-BY-SA-4.0',
                   authority='DENY_ALL', production_accepted=False)
    receipt['proposal_sha256'] = digest(all_scores)
    write_once(destination, receipt)
    return receipt


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='action', required=True)
    for cmd in ('plan', 'propose'):
        p = sub.add_parser(cmd)
        p.add_argument('--public', required=True)
        p.add_argument('--owner', required=True)
        p.add_argument('--output', required=True)
        if cmd == 'propose': p.add_argument('--plan', required=True)
    args = cli.parse_args()
    r = (plan(args.public, args.owner, args.output) if args.action == 'plan'
         else propose(args.public, args.owner, args.plan, args.output))
    print(json.dumps({k: v for k, v in r.items() if k in ('schema','plan_sha256','proposal_sha256','cpu_ns','completed_questions','candidate_sentence_evaluations')}))


if __name__ == '__main__':
    main()
