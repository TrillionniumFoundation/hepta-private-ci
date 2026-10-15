"""Frozen 700-update, three-seed synthetic paired-world training diagnostic.

This deliberately repeats all 16 semantic possibilities in TRAIN and only
holds out order permutations; it is NOT a source-disjoint natural task study.
Outputs actual CPU costs, identical training streams and every failed seed.
The feature tensors are constructed symbols, NOT Granite97 Encoder activations.
"""
import hashlib
import json
import random
import time

import torch
from torch.nn import functional as F

from cross_fact_bridge import matched_reader_pair

SEEDS = (41, 47, 53)
UPDATES = 700
BATCH_SIZE = 64
TRAIN_REPEATS = 8
TEST_REPEATS = 3


def paired_world_rows(seed, repeats):
    if type(seed) is not int or type(repeats) is not int or not 1 <= repeats <= 32:
        raise ValueError('bounded generation inputs required')
    rng = random.Random(seed)
    columns = [[], [], [], [], [], [], []]
    for _ in range(repeats):
        for world in range(2):
            for store_swap in range(2):
                for object_id in range(2):
                    for candidate_color in range(2):
                        facts = torch.zeros(4, 1, 8)
                        for fact_id in range(2):
                            owner = fact_id ^ world
                            facts[fact_id, 0, 0] = 1
                            facts[fact_id, 0, 2 + fact_id] = 1
                            facts[fact_id, 0, 4 + owner] = 1
                            facts[fact_id + 2, 0, 1] = 1
                            facts[fact_id + 2, 0, 4 + fact_id] = 1
                            facts[fact_id + 2, 0, 6 + (fact_id ^ store_swap)] = 1
                        facts = facts[torch.tensor(rng.sample(range(4), 4))]
                        question = torch.zeros(1, 8)
                        question[0, 2 + object_id] = 1
                        candidate = torch.zeros(1, 8)
                        candidate[0, 6 + candidate_color] = 1
                        for column, value in enumerate((facts, question, candidate)):
                            columns[column].append(value)
                        for column, shape in enumerate(((4, 1), (1,), (1,)), 3):
                            columns[column].append(torch.ones(shape, dtype=torch.bool))
                        columns[6].append(int(candidate_color == ((object_id ^ world) ^ store_swap)))
    return tuple(torch.stack(values) for values in columns[:6]), torch.tensor(columns[6], dtype=torch.long)


def _optimizer_bytes(optimizer):
    return sum(value.numel() * value.element_size()
               for state in optimizer.state.values() for value in state.values()
               if isinstance(value, torch.Tensor))


def execute_pilot():
    torch.set_num_threads(1)
    train, targets = paired_world_rows(17, TRAIN_REPEATS)
    test, labels = paired_world_rows(71, TEST_REPEATS)
    result = dict(schema='hepta.cross-fact.synthetic-paired-world.v1',
                  torch_version=torch.__version__, seeds=list(SEEDS), updates=UPDATES,
                  batch_size=BATCH_SIZE, train_rows=len(targets), test_rows=len(labels),
                  test_unique_semantic_combinations=16, train_repeat_count=TRAIN_REPEATS,
                  test_repeat_count=TEST_REPEATS,
                  pretrained_encoder_used=False, real_granite97_used=False,
                  source_disjoint_semantics=False, prospective_efficacy_established=False,
                  equal_parameter_budget=True, equal_training_examples=True,
                  equal_training_stream=True, equal_arithmetic_budget=False,
                  authority='DENY_ALL', seed_results=[])
    for seed in SEEDS:
        cross, local = matched_reader_pair(input_dim=8, hidden_dim=16, seed=seed)
        count_cross = sum(p.numel() for p in cross.parameters())
        count_local = sum(p.numel() for p in local.parameters())
        if count_cross != count_local:
            raise ValueError('unmatched parameter counts')
        seed_result = dict(seed=seed, parameter_count=count_cross, added_parameters=4 * 16**2,
                           arms={})
        for mode, model in (('cross_fact', cross), ('local', local)):
            optimizer = torch.optim.AdamW(model.parameters(), lr=.003, foreach=False)
            rng = random.Random(seed)
            training_digest = hashlib.sha256()
            start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
            model.train()
            for step in range(UPDATES):
                indices = rng.sample(range(len(targets)), BATCH_SIZE)
                training_digest.update(bytes(indices))
                batch = torch.tensor(indices)
                optimizer.zero_grad(set_to_none=True)
                logits = model(*(part[batch] for part in train), steps=2)
                loss = F.cross_entropy(logits, targets[batch])
                if not torch.isfinite(loss):
                    raise ValueError('nonfinite training objective')
                loss.backward()
                optimizer.step()
            model.eval().requires_grad_(False)
            with torch.no_grad():
                predictions = model(*test, steps=2).argmax(-1)
                correct = int((predictions == labels).sum().item())
            seed_result['arms'][mode] = dict(correct=correct, total=len(labels),
                completed_updates=UPDATES, training_exposures=UPDATES * BATCH_SIZE,
                train_stream_sha256=training_digest.hexdigest(),
                final_loss=float(loss.detach().item()),
                optimizer_tensor_bytes=_optimizer_bytes(optimizer),
                cpu_ns=time.process_time_ns() - start_cpu,
                wall_ns=time.perf_counter_ns() - start_wall)
        if seed_result['arms']['cross_fact']['train_stream_sha256'] != seed_result['arms']['local']['train_stream_sha256']:
            raise RuntimeError('matched training streams differed')
        result['seed_results'].append(seed_result)
    return result


if __name__ == '__main__':
    print(json.dumps(execute_pilot(), sort_keys=True, allow_nan=False))
