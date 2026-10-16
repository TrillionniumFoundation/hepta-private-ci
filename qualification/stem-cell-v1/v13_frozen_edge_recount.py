"""V13 compact ORIGINAL Granite97 frozen entity-link diagnostic.

Research-only / DENY_ALL. The public grammar supplies exact relation type and two
candidate facts per hop; this is NOT end-to-end natural-language reasoning.
Zero new pretrained Encoder forwards and zero optimizer steps.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile

import torch
from torch.nn import functional as F

FEATURE_SHA = '12af9d0a77be31b4bf6229e2ed1e58c80cff41e1380c1e1d175e79ad1ab9543f'
PUBLIC_SHA = 'efee1e07fdb26cb9f3222a86244ad8a41062b0c647a3be762d76c688826995af'
PATTERNS = (
    r'The ([a-z]+) belongs to ([A-Z][a-z]+)\.',
    r'([A-Z][a-z]+) stores all their possessions in the ([a-z]+) box\.',
    r'The ([a-z]+) box is on the ([a-z]+) shelf\.',
    r'The ([a-z]+) shelf is in the ([a-z]+) room\.',
    r'The ([a-z]+) room is in the ([a-z]+) building\.',
    r'The ([a-z]+) building is in the ([a-z]+) district\.',
)


def digest(obj):
    return sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def recount(features, public):
    for file, expected in ((features, FEATURE_SHA), (public, PUBLIC_SHA)):
        if sha256(Path(file).read_bytes()).hexdigest() != expected:
            raise ValueError('original SHA-pinned experiment archive required')
    with ZipFile(public) as archive:
        if archive.testzip() is not None:
            raise ValueError('original public ZIP CRC failure')
        cases = json.loads(archive.read('public.json'))
    with ZipFile(features) as archive:
        if archive.testzip() is not None:
            raise ValueError('original pretrained feature ZIP CRC failure')
        meta = json.loads(archive.read('real-features/metadata.json'))
        receipt = json.loads(archive.read('real-features/real-encoder-receipt.json'))
        packed = archive.read('real-features/tokens.pt')
    if (len(cases) != 1248 or len(meta['tensor_sha256']) != 827
            or receipt['public_sha256'] != digest(cases)
            or receipt['bank_file_sha256'] != sha256(packed).hexdigest()
            or receipt['actually_executed_encoder_batches'] != 104
            or receipt['frozen_weight_verified'] is not True
            or receipt['held_labels_accessed'] is not False
            or receipt['authority'] != 'DENY_ALL'):
        raise ValueError('original pretrained source / weight evidence is incomplete')
    tokens = torch.load(BytesIO(packed), weights_only=True, map_location='cpu')
    if not isinstance(tokens, dict) or set(tokens) != set(meta['tensor_sha256']):
        raise ValueError('incomplete original token inventory')
    normalized = {}
    for text, x in tokens.items():
        if (x.dtype != torch.float32 or x.ndim != 2 or x.shape[-1] != 384
                or not torch.isfinite(x).all()
                or sha256(x.contiguous().numpy().tobytes()).hexdigest() != meta['tensor_sha256'][text]):
            raise ValueError('physical TokenBank embedding bytes were changed')
        normalized[text] = F.normalize(x.mean(0), dim=0)
    by_world = {}
    for case in cases:
        parts = case['case_id'].split('/')
        if len(parts) != 5 or parts[0] not in ('train', 'held_known', 'held_novel'):
            raise ValueError('registered source identity required')
        k = tuple(parts[:4])
        facts = tuple(case['facts'])
        if k in by_world and by_world[k] != facts:
            raise ValueError('two candidate cases disagree on evidence')
        by_world[k] = facts
    if len(by_world) != 624:
        raise ValueError('exact source-world count required')
    stats = defaultdict(lambda: [0, 0])
    independent = defaultdict(set)
    torch.set_num_threads(1)
    for (role, depth_str, group, world), facts in sorted(by_world.items()):
        if role == 'train':
            continue
        depth = int(depth_str)
        if len(facts) != 2 * depth or not 2 <= depth <= 6:
            raise ValueError('complete bounded relation chain required')
        edges = defaultdict(list)
        for statement in facts:
            candidates = [(i, m) for i, pattern in enumerate(PATTERNS)
                          if (m := re.fullmatch(pattern, statement))]
            if len(candidates) != 1:
                raise ValueError('unknown or ambiguous public relation')
            i, match = candidates[0]
            edges[i].append((statement, match.group(1), match.group(2)))
        if any(len(edges[stage]) != 2 for stage in range(depth)):
            raise ValueError('two typed facts at each stage required')
        independent[role, depth].add(group)
        for stage in range(depth - 1):
            for src_text, src_subject, src_object in edges[stage]:
                alternatives = edges[stage + 1]
                pred = max(alternatives,
                           key=lambda e: float(normalized[src_text] @ normalized[e[0]]))
                stats[role, depth][0] += int(pred[1] == src_object)
                stats[role, depth][1] += 1
    if len(independent) != 10 or any(len(s) != 24 for s in independent.values()):
        raise ValueError('24 original independent groups per held depth required')
    rows = [dict(role=role, depth=depth, correct=val[0], choices=val[1],
                 source_groups=len(independent[role, depth]))
            for (role, depth), val in sorted(stats.items())]
    totals = {}
    for role in ('held_known', 'held_novel'):
        r = [x for x in rows if x['role'] == role]
        n, correct = sum(x['choices'] for x in r), sum(x['correct'] for x in r)
        totals[role] = dict(correct=correct, choices=n, accuracy=correct / n,
                            unique_source_groups=120)
    return dict(schema='hepta.v13.frozen-granite-link-recount.v1',
                public_sha256=digest(cases), original_encoder_batches=104,
                new_encoder_forwards=0, new_optimizer_steps=0,
                grammar_supplies_relation_type_and_candidates=True,
                rows=rows, totals=totals, whole_question_success_not_measured=True,
                model_selected=False, production_accepted=False, authority='DENY_ALL')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--features', required=True, type=Path)
    cli.add_argument('--public', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    report = recount(args.features, args.public)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report['totals'], sort_keys=True))


if __name__ == '__main__':
    main()
