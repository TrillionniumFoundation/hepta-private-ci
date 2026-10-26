"""Freeze the only old-five-action primary contrast before opening new writers."""

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SHARED = REPO.parent / 'ndu-next-assets/shared'
VIEWS = ('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted',
         'missing_untrusted', 'missing_unknown', 'both_missing')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def implementation_closure(entrypoints):
    pending, visited = list(entrypoints), set()
    while pending:
        path = pending.pop().resolve()
        if path in visited:
            continue
        visited.add(path)
        package = '.'.join(path.relative_to(REPO).with_suffix('').parts[:-1])
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom):
                name = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module
                if name:
                    names = [name, *(name + '.' + a.name for a in node.names if a.name != '*')]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                module = REPO.joinpath(*name.split('.'))
                candidates = [module.with_suffix('.py'), module / '__init__.py']
                candidates += [p / '__init__.py' for p in module.parents if p.is_relative_to(REPO)]
                pending += [p for p in candidates if p.is_file() and p not in visited]
    return visited


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Never replace an opened or frozen confirmation protocol')
    selected_path = HERE / 'SELECTED_VALUE.json'
    selected = json.loads(selected_path.read_text())['candidate']
    checkpoint = Path(selected['checkpoint'])
    if selected['ridge'] != .1 or sha(checkpoint) != selected['checkpoint_sha256']:
        raise ValueError('The earlier fixed-grid selected candidate changed')
    predictor = Path('/tmp/hepta-ndu-next-native-h2/development-002/predictor.json')
    calibration = Path('/tmp/hepta-ndu-next-native-h2/calibrator-001/calibration.json')
    value = json.loads(checkpoint.read_text())
    if value['predictor_sha256'] != sha(predictor) or value['calibration_sha256'] != sha(calibration):
        raise ValueError('Admission model/calibration identity differs from training')
    allocation_path = HERE.parent / 'SOURCE_ALLOCATION.json'
    allocation = json.loads(allocation_path.read_text())
    if (sha(allocation_path) != '42d0c47056dda930cb851c9ae59f330747de8bb863f18b79c47eea830f69b262'
            or allocation['roles']['confirmation']['writer_count'] != 85
            or allocation['roles']['confirmation']['pair_count'] != 170):
        raise ValueError('The common fresh cohort changed')
    root_registration = HERE.parent / 'REGISTRATION.json'
    root = json.loads(root_registration.read_text())
    if root['analysis_policy']['per_family_alpha'] != .05 / 3:
        raise ValueError('The shared-panel three-family multiplicity rule changed')
    files = implementation_closure([HERE / name for name in (
        'confirm.py', 'online.py', 'analyze_confirm.py', 'register_confirm.py')])
    files.update([checkpoint, predictor, calibration, selected_path, allocation_path, root_registration,
        HERE / 'DEVELOPMENT_PROTOCOL.json', HERE / 'DEVELOPMENT_RESULTS.json',
        HERE.parents[1] / 'abc_followup/control/PROTOCOL-v2.json',
        SHARED / 'abc2-runs/training-001/seed-17/output_ndu/model.pt',
        SHARED / 'abc3-runs/controllers-001/seed-17/output_ndu/controller.pt',
        SHARED / 'abc3-runs/public-sensor-001/sensor.pt',
        SHARED / 'abc2-runs/base-recovery-001/reward-observer.pt',
        SHARED / 'abc2-runs/qualification-001/secondary-observer.pt'])
    pins = {str(path.resolve()): sha(path) for path in sorted(files)}
    spec = {'schema': 'hepta.advance.old-five-confirmation-protocol.v1',
        'registered_ns': time.time_ns(), 'study': 'constrained_control',
        'source_roles': ['confirmation'], 'source_allocation_sha256': sha(allocation_path),
        'frozen_candidate_sha256': pins, 'candidate': str(checkpoint), 'predictor': str(predictor),
        'calibration': str(calibration), 'seed': 17, 'draws': 2, 'views': list(VIEWS),
        'policies': ['masked_teacher', 'constrained_paired'],
        'source': {'allocation': str(allocation_path), 'cache': str(REPO.parent / 'ndu-next-assets/qmnist'),
                   'pairs': 170, 'writers': 85, 'role': 'advance_confirmation'},
        'evaluation': {'observation_namespace': 'advance-old-five-observation-v1',
            'initial_namespace': 'advance-old-five-initial-v1', 'future_namespace': 'advance-old-five-future-v1',
            'order_seed': 202610261802},
        'inference': {'alpha': .05 / 3, 'resamples': 16384, 'bootstrap_seed': 202610261803,
            'primary': 'CE(U - .002 * attempted non-stop actions), constrained_paired minus masked_teacher',
            'gamma': 2., 'action_cost': .002, 'primary_success': 'Lower two-sided paired writer-cluster percentile bound >0 and no operational failure',
            'price_grid_per_ms': [0., .000001, .00001, .0001, .001, .01],
            'unit': '85 writers; both pairs and every view/draw remain together, conditional on one fixed trained seed17',
            'cost_scope': 'Measured online requests include actual initialization, generation, shared feature/admission computation, only the selected value head, durable choice, and output persistence/readback. Candidate H1 retains a diagnostic public clone. Offline counterfactuals, private judges, resident loading and source decoding are separate within the whole-process receipt. Unit action cost is the fixed training cost, not a conversion of measured CPU or wall time.',
            'secondary_scope': 'Delta MSE, selection bias, realized feasible regret, strict success, correctness ECE and fixed price grid are descriptive. Initial-selected ECE scores actual terminal strict success, including later rejection/failure=0; H2 moment bias uses actual terminal utility minus all subsequent attempted-action costs. The deployed full-fit H1 continuation differs from training OOF policies, and no original calibration qualification is inherited. No secondary improvement can replace a failed primary and no extra efficacy claim is allocated alpha.'},
        'nonanticipation': 'Policy receives only public current tensors and horizon. Each actual action is durably committed before decoder innovations; all source/target/RNG identities stay with the driver. The function boundary is auditable Python data flow, not a hostile-code sandbox.',
        'paired_randomness': 'Both policies share initial seed per source/view and future seed per source/view/draw/full committed path. The two draws share initial draft and are not independent clusters. Only identical full paths reuse a future innovation.',
        'counterfactual_rule': 'After both actual paired requests have ended, enumerate all five actions at each candidate-visited H1 parent. Reuse the actual selected result; all other draws use the same path-specific future rule. Include rejected/disabled actions in raw evidence, but compute regret only over the exact registered H1 feasible mask. Semantic H1 remains disabled. No oracle outcome returns to online choice.',
        'rejection_and_failures': 'Empty feasible sets yield explicit rejection utility -1 and strict success0, retaining already paid costs; they are never ordinary stop. Every operational or diagnostic failure remains recorded; any primary operational failure blocks efficacy admission.',
        'scope': 'Frozen old text/image generator and original five refinement actions. This is not the separate100-code four-modal renderer and does not inherit native resource/owner qualification. The exact static correctness mask is common; unknown future owner resource tails are not claimed modeled.',
        'new_sources_opened': False, 'production_authority': False, 'CI_queried_or_managed': False}
    with args.output.open('x') as stream:
        json.dump(spec, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'protocol': str(args.output), 'sha256': sha(args.output),
        'pinned_files': len(pins), 'model_outcomes_opened': False}))


if __name__ == '__main__':
    main()
