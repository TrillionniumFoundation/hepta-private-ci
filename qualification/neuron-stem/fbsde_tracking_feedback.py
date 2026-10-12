"""Verified local feedback can change pair ranking; scalar smoothing cannot.

Frozen Encoder/base snapshots remain immutable. Candidate parameters are separate
and all candidates receive exactly the same 54 source-operation labels, including
known-frame replay. Nothing here authorizes production adoption or certifies risk.
"""
import copy
from itertools import combinations
import hashlib
import math
from pathlib import Path
import time
from four_gate_common import digest, require, strict_loads
from four_gate_capture import tensor_digest
from fbsde_tracking import make_gate, training_rows, lexical_vector, slot_text

PAIRS = tuple(combinations(range(3), 2))
KINDS = ('frozen', 'residual', 'finetuned', 'linear')


def identity(module):
    return digest({k: tensor_digest(v) for k, v in module.state_dict().items()})


def load_base(torch, root):
    root = Path(root)
    for name in ('heads.pt', 'fit.json', 'calibration.json', 'design.json'):
        path = root/name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 1_000_000,
                'bounded original Head source')
    fit = strict_loads((root/'fit.json').read_bytes())
    design = strict_loads((root/'design.json').read_bytes())
    require(design['profile'] == 'input_tied_challenge_v1', 'explicit frozen source profile')
    require(fit['training_sha256'] == digest(training_rows()) and
            fit['heads_bytes_sha256'] == hashlib.sha256((root/'heads.pt').read_bytes()).hexdigest(),
            'original training/byte identity')
    states = torch.load(root/'heads.pt', map_location='cpu', weights_only=True)
    require(type(states) is list and len(states) == 3, 'three original Heads')
    members = []
    for state in states:
        m = make_gate(torch); m.load_state_dict(state, strict=True)
        m.eval().requires_grad_(False); members.append(m)
    require([identity(m) for m in members] == fit['members'], 'original tensor identity')
    return members, fit


def validate_feedback(rows, predictions, disallowed_sources=()):
    """Consistency only: these simulator receipts have no external owner signature."""
    require(type(rows) is list and 1 <= len(rows) <= 4096 and len(rows) == len(predictions),
            'complete feedback stream')
    seen = set()
    for row, predicted in zip(rows, predictions):
        require(set(row) == {'source', 'pair', 'prediction_sha256', 'observer', 'sequence'},
                'typed local feedback receipt')
        source = row['source']
        require(type(source) is dict and set(source) == {'text', 'names', 'source_id'},
                'public source fields only')
        key = source['source_id']
        require(key == digest(source['text']) and key not in seen and key not in disallowed_sources,
                'duplicate or heldout feedback source')
        seen.add(key)
        require(type(predicted['index']) is int and type(row['sequence']) is int, 'integer chronology')
        require(row['prediction_sha256'] == digest(predicted) and predicted['source'] == source
                and row['sequence'] == 2*predicted['index']+1, 'feedback not bound to prior prediction')
        require(row['observer'] == 'simulator_source_verifier' and predicted['phase'] == 'before_feedback',
                'explicit simulator provenance')
        require(type(row['pair']) is list and tuple(row['pair']) in PAIRS, 'valid local operation label')
    return digest(rows)


def candidate_scores(torch, kind, models, x):
    require(kind in KINDS, 'registered candidate')
    base, residual, finetuned, linear = models
    if kind == 'linear':
        scores = linear(x).squeeze(-1)
        return torch.stack([scores]*3)
    scores = torch.stack([m(x) for m in (finetuned if kind == 'finetuned' else base)])
    return scores + residual(x).squeeze(-1)[None] if kind == 'residual' else scores


def fit_candidates(torch, members, rows):
    nn = torch.nn; torch.manual_seed(104395303)
    residual = nn.Linear(128, 1); linear = nn.Linear(128, 1)
    for model in (residual, linear):
        nn.init.zeros_(model.weight); nn.init.zeros_(model.bias)
    finetuned = [copy.deepcopy(m).train().requires_grad_(True) for m in members]
    models = (members, residual, finetuned, linear); original_ids = [identity(m) for m in members]
    x = torch.tensor([[lexical_vector(slot_text(r['source']['text'], r['source']['names'], j))
                       for j in range(3)] for r in rows])
    y = torch.tensor([PAIRS.index(tuple(r['pair'])) for r in rows])
    jobs = []
    for kind in KINDS[1:]:
        parameters = (list(residual.parameters()) if kind == 'residual' else
                      [p for m in finetuned for p in m.parameters()] if kind == 'finetuned' else
                      list(linear.parameters()))
        started = time.process_time_ns()
        optim = torch.optim.AdamW(parameters, lr=.01); losses = []
        for _ in range(160):
            optim.zero_grad(); s = candidate_scores(torch, kind, models, x)
            logits = torch.stack([s[:,:,a]+s[:,:,b] for a,b in PAIRS], dim=-1)
            # Mean member loss. Same observations, optimizer steps and ceiling.
            loss = sum(nn.functional.cross_entropy(z, y) for z in logits)/3
            require(torch.isfinite(loss).item(), 'finite update loss')
            loss.backward(); optim.step(); losses.append(float(loss.detach()))
            require(time.process_time_ns()-started <= 15_000_000_000, 'candidate fit CPU budget exhausted')
        jobs.append({'kind': kind, 'steps': 160, 'lr': .01, 'losses': losses,
                     'trainable_parameters': sum(p.numel() for p in parameters),
                     'cpu_ns': time.process_time_ns()-started, 'feedback_sha256': digest(rows)})
    for m in (*members, residual, *finetuned, linear): m.eval().requires_grad_(False)
    require([identity(m) for m in members] == original_ids, 'feedback changed frozen parent')
    return models, jobs


def states_json(models):
    base, residual, tuned, linear = models
    def state(m): return {k: v.detach().tolist() for k,v in m.state_dict().items()}
    return {'base': [state(m) for m in base], 'residual': state(residual),
            'finetuned': [state(m) for m in tuned], 'linear': state(linear)}
