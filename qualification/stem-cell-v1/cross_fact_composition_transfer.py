"""Actual CPU train/eval on a held-out TWO-HOP symbolic composition.

Exploratory, not preregistered: 5 of 6 object->color permutations are TRAIN;
the sixth is never exposed to fitting. Both arms have the same parameters,
initial base weights, optimization steps and exact training draw order. This
uses constructed 11D role tokens, not Granite97 or real language.
"""
import argparse
import hashlib
import itertools
import json
import random
import time

import torch
from torch.nn import functional as F

from cross_fact_bridge import matched_reader_pair

PERMUTATIONS = tuple(itertools.permutations(range(3)))
HELD_OUT_COMPOSITION = (2, 0, 1)
SEEDS = (41, 47, 53)
ARMS = ('cross_fact', 'local')
UPDATES = 800
BATCH_SIZE = 64


def source_panel(role, *, fact_order_seed):
    """One source per owner/storage graph; exclude an entire composed mapping.

    Every row carries all six original facts, a question object and a proposed
    color. Candidate labels are separate metadata, never one of six features.
    """
    if role not in ('train', 'heldout') or type(fact_order_seed) is not int:
        raise ValueError('registered role and order seed required')
    shuffled = random.Random(fact_order_seed)
    columns = [[] for _ in range(6)]
    labels, graphs, questions, compositions = [], [], [], []
    for owners in PERMUTATIONS:
        for colors in PERMUTATIONS:
            composition = tuple(colors[owners[obj]] for obj in range(3))
            if (composition == HELD_OUT_COMPOSITION) != (role == 'heldout'):
                continue
            graph = (owners, colors)
            for obj in range(3):
                for option in range(3):
                    facts = torch.zeros(6, 1, 11)
                    for index in range(3):
                        facts[index, 0, 0] = 1  # Object -> owner edge
                        facts[index, 0, 2 + index] = 1
                        facts[index, 0, 5 + owners[index]] = 1
                    for index in range(3):
                        facts[3 + index, 0, 1] = 1  # Owner -> color edge
                        facts[3 + index, 0, 5 + index] = 1
                        facts[3 + index, 0, 8 + colors[index]] = 1
                    facts = facts[torch.tensor(shuffled.sample(range(6), 6))]
                    question = torch.zeros(1, 11)
                    question[0, 2 + obj] = 1
                    candidate = torch.zeros(1, 11)
                    candidate[0, 8 + option] = 1
                    for index, value in enumerate((facts, question, candidate)):
                        columns[index].append(value)
                    for index, shape in enumerate(((6, 1), (1,), (1,)), 3):
                        columns[index].append(torch.ones(shape, dtype=torch.bool))
                    labels.append(int(option == composition[obj]))
                    graphs.append(graph)
                    questions.append((graph, obj))
                    compositions.append(composition)
    return dict(features=tuple(torch.stack(values) for values in columns),
                labels=torch.tensor(labels, dtype=torch.long),
                graph_ids=tuple(graphs), question_ids=tuple(questions),
                composition_ids=tuple(compositions))


def checked_panels(train, test):
    for panel in (train, test):
        n = len(panel['labels'])
        if any(len(panel[name]) != n for name in ('graph_ids', 'question_ids', 'composition_ids')):
            raise ValueError('incomplete aligned source membership')
    t, h = set(train['composition_ids']), set(test['composition_ids'])
    if (h != {HELD_OUT_COMPOSITION} or HELD_OUT_COMPOSITION in t
            or len(t) != 5 or len(train['labels']) != 270 or len(test['labels']) != 54
            or set(train['graph_ids']) & set(test['graph_ids'])
            or (int(train['labels'].sum()), int(test['labels'].sum())) != (90, 18)):
        raise ValueError('disjoint balanced composition/source panel violated')
    for panel in (train, test):
        # Each complete question must contain all three candidates with one
        # true label. Rows must be group-ordered, not candidate-scored first.
        for first in range(0, len(panel['labels']), 3):
            if (panel['question_ids'][first:first+3] != (panel['question_ids'][first],) * 3
                    or int(panel['labels'][first:first+3].sum()) != 1):
                raise ValueError('not a complete question/candidate slate')


def _score(logits, labels):
    probabilities = logits.softmax(-1)[:, 1]
    predicted = probabilities > .5
    correct = predicted.eq(labels).reshape(-1, 3)
    true_positive = int((predicted & labels.bool()).sum())
    false_positive = int((predicted & ~labels.bool()).sum())
    false_negative = int((~predicted & labels.bool()).sum())
    return dict(correct=int(correct.sum()), total=len(labels),
                complete_questions=int(correct.all(-1).sum()), questions=len(labels)//3,
                positive_f1=(2*true_positive/(2*true_positive+false_positive+false_negative)
                             if 2*true_positive+false_positive+false_negative else 0.),
                brier=float((probabilities-labels.float()).square().mean()),
                cross_entropy=float(F.cross_entropy(logits, labels)))


def _optimizer_bytes(optimizer):
    return sum(value.numel() * value.element_size() for state in optimizer.state.values()
               for value in state.values() if isinstance(value, torch.Tensor))


def run(*, updates=UPDATES):
    if type(updates) is not int or not 1 <= updates <= UPDATES:
        raise ValueError('bounded exploratory training budget required')
    torch.set_num_threads(1)
    started = time.process_time_ns(), time.perf_counter_ns()
    train, test = source_panel('train', fact_order_seed=17), source_panel('heldout', fact_order_seed=71)
    checked_panels(train, test)
    report = dict(schema='hepta.cross-fact.composition-transfer.cpu.v1',
                  status='research_only', encoder_pretrained=False,
                  input_representation='constructed_binary_role_tokens_11d',
                  heldout_composition=list(HELD_OUT_COMPOSITION),
                  source_disjoint_graphs=True, source_disjoint_composition=True,
                  novel_vocabulary=False, user_language_task=False,
                  selection_based_on_holdout=False, pretrained_improvement_established=False,
                  equal_training_updates=True, equal_parameter_counts=True,
                  equal_training_input_stream=True, equal_training_flops=False,
                  training_graphs=len(set(train['graph_ids'])),
                  heldout_graphs=len(set(test['graph_ids'])),
                  heldout_questions=len(test['labels'])//3, train_rows=len(train['labels']),
                  heldout_rows=len(test['labels']), updates_per_arm=updates,
                  batch_size=BATCH_SIZE, torch_version=torch.__version__, seed_results=[])
    for seed in SEEDS:
        models = dict(zip(ARMS, matched_reader_pair(input_dim=11, hidden_dim=24, seed=seed)))
        parameters = [sum(p.numel() for p in model.parameters()) for model in models.values()]
        if parameters[0] != parameters[1]:
            raise RuntimeError('mismatched trainable parameter count')
        batches = [random.Random(seed+step).sample(range(len(train['labels'])), BATCH_SIZE)
                   for step in range(updates)]
        # hash the exact shared sample schedule once and reuse physical indices.
        schedule_hash = hashlib.sha256(json.dumps(batches, separators=(',', ':')).encode()).hexdigest()
        row = dict(seed=seed, parameter_count=parameters[0],
                   added_adapter_parameters=4 * 24**2, schedule_sha256=schedule_hash, arms={})
        for arm in ARMS:
            model = models[arm].train()
            optimizer = torch.optim.AdamW(model.parameters(), lr=.003, foreach=False)
            start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
            for indices in batches:
                index = torch.tensor(indices, dtype=torch.long)
                batch = tuple(t[index] for t in train['features'])
                optimizer.zero_grad(set_to_none=True)
                logits = model(*batch, steps=2)
                loss = F.cross_entropy(logits, train['labels'][index])
                if not torch.isfinite(loss):
                    raise ValueError('nonfinite training loss')
                loss.backward()
                optimizer.step()
            model.eval().requires_grad_(False)
            with torch.no_grad():
                train_logits = model(*train['features'], steps=2)
                heldout_logits = model(*test['features'], steps=2)
            row['arms'][arm] = dict(train=_score(train_logits, train['labels']),
                                   heldout=_score(heldout_logits, test['labels']),
                                   completed_updates=updates, exposures=updates * BATCH_SIZE,
                                   optimizer_tensor_bytes=_optimizer_bytes(optimizer),
                                   cpu_ns=time.process_time_ns()-start_cpu,
                                   wall_ns=time.perf_counter_ns()-start_wall)
        if row['arms']['cross_fact']['optimizer_tensor_bytes'] != row['arms']['local']['optimizer_tensor_bytes']:
            raise RuntimeError('optimizer tensor storage mismatch')
        report['seed_results'].append(row)
    report['total_cpu_ns'] = time.process_time_ns()-started[0]
    report['total_wall_ns'] = time.perf_counter_ns()-started[1]
    report['heldout_always_negative_correct'] = 36
    report['heldout_always_negative_complete_questions'] = 0
    report['model_selection_permitted'] = False
    report['production_authorized'] = False
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--updates', type=int, default=UPDATES)
    args = parser.parse_args()
    print(json.dumps(run(updates=args.updates), sort_keys=True, allow_nan=False))
