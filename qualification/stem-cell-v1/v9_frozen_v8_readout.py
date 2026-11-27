"""Re-forward existing V8 trained weights on NEW synthetic 2-6 hop public tasks.

The original V8 token bank and its seed=619 random lexical vectors are preserved
for object, person, box/color and two-hop relation types. New kinds use separate
previously-unused dimensions. This is NOT a real Granite/ModernBERT forward.
No V9 fitting, label access, checkpoint selection or future-task claims.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

import torch
from safetensors.torch import load_file
from v9_typed_graph import PATTERNS, TYPES, digest
from v9_blind_benchmark import read, write_once
from bridge_reader import build_reader
from endpoint_v8 import build_endpoint

ARMS = ('base', 'bridge', 'wide', 'endpoint')
SEEDS = (41, 47, 53)
ORIGINAL = ('object', 'person', 'color', 'own', 'store', 'question', 'candidate')
EXTRA = ('shelf', 'room', 'building', 'district', 'relation2', 'relation3', 'relation4', 'relation5')
V8_LOCKED_SHA256 = {
    '41/base': '6c2c73799f22056536b035859887922bf5181eb4efa66830938d4c5eb13d89bf',
    '41/bridge': '3512cffc03ed87c29dd6c0ff246730038ac47a6751bd12aaf98059cc766f31a8',
    '41/wide': 'cc3014a5933c9d7e845b1ccbea7ee8ddf50833dc5f82cba2349a24fd9d110bca',
    '41/endpoint': '0381f5cb41112826c8075d8b5330f6d69b2641b290c13b5ef605e926c93e42a4',
    '47/base': 'fe1f2516d970fabecda97760c3cd93afc994d725b299cb0f1018c8b76b7a6e03',
    '47/bridge': '711eb47ce3da8c936db392ac31dea5bf6f8587ef89fa17989f3efd9eb83b7dfc',
    '47/wide': '02ff6b4bc9d32af0f27b9837e255dcf269ead466ed151facde458086790ea59a',
    '47/endpoint': 'f884356bd2a2fb5e6c412e6404d2cb9837ed065ec070976ef203b1eb06024e7e',
    '53/base': '3f24cb5824d0b61349fa7ad243d6c1172fdab32178614235e521e14cb7fbe864',
    '53/bridge': 'df8d901a2b8913c4e01d7c39c9182f5901332eecf178231af5b1ade9d18575f2',
    '53/wide': '305593f3f209c55dcb5a8b519b08577252b61dede7d70af7178c1f8a781bcbef',
    '53/endpoint': '2a78e933b30095f908a9a07793daa261adbd5bac2f76dc939d29719109f170e7',
}


def sha_bytes(raw):
    return sha256(raw).hexdigest()


class OriginalV8SyntheticBank:
    """Original seed/version locked; NEVER substitute this for pretrained features."""
    def __init__(self):
        self.cache = {}

    def word(self, kind, item):
        key = kind, item
        if key not in self.cache:
            vec = torch.zeros(384, dtype=torch.float32)
            if kind in ORIGINAL:
                vec[ORIGINAL.index(kind)] = 3.
            elif kind in EXTRA:
                vec[137 + EXTRA.index(kind)] = 3.
            else:
                raise ValueError('registered grammar token kind required')
            gen = torch.Generator().manual_seed(int(sha_bytes(f'619/{item}'.encode())[:15], 16))
            vec[8:136] = torch.randn(128, generator=gen) * .7
            self.cache[key] = vec
        return self.cache[key]

    @staticmethod
    def node_kind(rank):
        return ('object', 'person', 'color', 'shelf', 'room', 'building', 'district')[rank]

    def encode(self, rows):
        if not rows or len(rows) > 16 or len({len(r['facts']) for r in rows}) != 1:
            raise ValueError('one compatible 1-16-row batch required')
        b, f = len(rows), len(rows[0]['facts'])
        if f < 4 or f > 12:
            raise ValueError('fixed 2-6 hop relation facts required')
        facts = torch.zeros(b, f, 3, 384)
        question = torch.zeros(b, 2, 384)
        candidate = torch.zeros(b, 2, 384)
        for j, row in enumerate(rows):
            for i, line in enumerate(row['facts']):
                matches = [(k, p.fullmatch(line)) for k, p in enumerate(PATTERNS)]
                matched = [(k, m) for k, m in matches if m is not None]
                if len(matched) != 1:
                    raise ValueError('unrecognized public grammar evidence')
                k, match = matched[0]
                left, right = match.groups()
                role = ('own', 'store')[k] if k < 2 else f'relation{k}'
                facts[j, i, 0] = self.word(self.node_kind(k), left)
                facts[j, i, 1] = self.word(self.node_kind(k + 1), right)
                facts[j, i, 2] = self.word(role, role.upper())
            from v9_typed_graph import QUESTION, CANDIDATE
            qm, cm = QUESTION.fullmatch(row['question']), CANDIDATE.fullmatch(row['candidate'])
            if qm is None or cm is None or qm[2] != cm[2]:
                raise ValueError('incompatible query and candidate')
            target_kind = self.node_kind(TYPES.index(qm[2]))
            question[j, 0] = self.word('object', qm[1])
            question[j, 1] = self.word('question', 'ASK')
            candidate[j, 0] = self.word(target_kind, cm[1])
            candidate[j, 1] = self.word('candidate', 'ANS')
        return facts, question, candidate, torch.ones(b,f,3,dtype=torch.bool),\
            torch.ones(b,2,dtype=torch.bool), torch.ones(b,2,dtype=torch.bool)


def load_exact_v8_weights(folder, seed, arm):
    if seed not in SEEDS or arm not in ARMS:
        raise ValueError('registered seed/model arm required')
    name = f'weights-{seed}-{arm}.safetensors'
    path = Path(folder) / f'verified-seed{seed}' / name
    if not path.is_file() or path.stat().st_size > 300_000:
        raise FileNotFoundError('original V8 pretrained-on-synthetic weight file absent or oversized')
    fingerprint = sha_bytes(path.read_bytes())
    if fingerprint != V8_LOCKED_SHA256[f'{seed}/{arm}']:
        raise ValueError('immutable V8 synthetic weight archive SHA256 mismatch')
    model = build_endpoint(seed) if arm == 'endpoint' else build_reader(arm, seed)
    state = load_file(str(path), device='cpu')
    model.load_state_dict(state, strict=True)
    model.eval().requires_grad_(False)
    return model, dict(file=name, sha256=fingerprint,
                       parameter_count=sum(p.numel() for p in model.parameters()),
                       selected_before_v9_corpus=True, original_Granite_weights=False)


def run(public_path, prior_weights_root, output_path):
    public = read(public_path)
    if (type(public) is not list or len(public) != 1248
            or any(set(x) != {'case_id','source_group','facts','question','candidate'} for x in public)):
        raise ValueError('complete label-blind V9 public corpus required')
    by_panel = {}
    for case in public:
        pieces = case['case_id'].split('/')
        if len(pieces) != 5:
            raise ValueError('source group identity missing')
        by_panel.setdefault((pieces[0], int(pieces[1])), []).append(case)
    bank = OriginalV8SyntheticBank()
    prepared = {}
    for cohort, cases in by_panel.items():
        prepared[cohort] = []
        for start in range(0, len(cases), 16):
            subset = cases[start:start + 16]
            prepared[cohort].append((subset, bank.encode(subset)))
    torch.set_num_threads(1)
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    records, sources = {}, {}
    for seed in SEEDS:
        for arm in ARMS:
            model, source = load_exact_v8_weights(prior_weights_root, seed, arm)
            sources[f'{seed}/{arm}'] = source
            column = {}
            with torch.no_grad():
                for _, batches in prepared.items():
                    for cases, x in batches:
                        p = model(*x, steps=3).softmax(-1)[:,1].tolist()
                        for case, value in zip(cases, p):
                            if case['case_id'] in column:
                                raise RuntimeError('duplicate scored case')
                            column[case['case_id']] = value
            if len(column) != len(public) or any(not 0 <= v <= 1 for v in column.values()):
                raise RuntimeError('complete finite probability panel required')
            records[f'{seed}/{arm}'] = column
    payload = dict(schema='hepta.v9.previous-synthetic-head-zero-shot.v1',
                   provenance='ORIGINAL_V8_SYNTHETIC_TRAINED_WEIGHTS_NOT_GRANITE',
                   public_sha256=digest(public), weight_files=sources,
                   candidate_ids=[x['case_id'] for x in public],
                   probabilities=records,
                   actual_pretrained_encoder_forwards=0, optimizer_updates=0,
                   inference_depth=3, V9_label_access=False, V9_checkpoint_selection=False,
                   cpu_ns=time.process_time_ns()-start_cpu,
                   wall_ns=time.perf_counter_ns()-start_wall,
                   model_selected=False, production_accepted=False,
                   authority='DENY_ALL')
    payload['probs_sha256'] = digest(records)
    write_once(output_path, payload)
    return payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--public',type=Path,required=True)
    p.add_argument('--previous-v8',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    r=run(args.public,args.previous_v8,args.output)
    print(json.dumps({'neural_rows':len(r['candidate_ids'])*len(r['probabilities']),
                      'source_sha256':r['public_sha256'],'cpu_ns':r['cpu_ns'],
                      'authority':r['authority'],'pretrained_forwards':0}))

if __name__=='__main__':
    main()
