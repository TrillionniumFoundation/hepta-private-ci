"""Prospective identified finite service study; prior scalar failures are retained."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from . import controller, model, world

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPECS = (
    ('A_ordinary_light', 'ordinary', 'light', 'full', 'full_priors'),
    ('B_ordinary_value', 'ordinary', 'value', 'full', 'full_priors'),
    ('C_analytic_light', 'analytic', 'light', 'full', 'full_priors'),
    ('D_analytic_value', 'analytic', 'value', 'full', 'full_priors'),
    ('joint_train_factor_execute', 'analytic', 'value', 'factorized', 'full_priors'),
    ('factor_train_joint_execute', 'analytic', 'value', 'full', 'factorized_priors'),
    ('factor_train_factor_execute', 'analytic', 'value', 'factorized', 'factorized_priors'),
    ('joint_train_mean_execute', 'analytic', 'value', 'mean', 'full_priors'),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def source_hashes():
    return {name: sha(HERE / name) for name in ('campaign.py', 'world.py', 'model.py', 'controller.py', 'analysis.py')}


def freeze(out):
    out.mkdir(parents=True, exist_ok=False)
    protocol = dict(schema='hcsn-distribution-value-r2.v1', frozen_utc=datetime.now(timezone.utc).isoformat(), source_hashes=source_hashes(),
        predecessor='experiments/hcsn_joint_dynamics_20261101/REPORT_ZH.md: prior scalar task stays negative; this is a redesigned finite mechanism study',
        fit_seeds=[211, 337, 499], train_contexts=24, trajectories_per_train_context=64, trajectory_duration=5.,
        training='Shared fully observed physical transition counts/exposures and state-labelled READ calibration; balanced cue-state-bit identification. Both full-law cores and both controllers receive identical fitted models, never trueQ or sampled hidden test X,Y.',
        prior_fit='Full joint empirical MLE versus independently fitted product-marginal MLE from identical stratified samples; not neural network retraining',
        test_context_seed=318617, test_contexts=6, test_domain='New independent context features from[-1,1]^2 under same fixed rate-function family; training context features from[-.8,.8]^2; not an unknown generator family',
        world_seed=891317, episodes_per_cell=64, cue_count=8, profiles=controller.PROFILES, decision_horizon=3, kernel_precision='FP64',
        actions=dict(STOP_0='submit fixed hidden target bit0', STOP_1='submit bit1', READ='advance.15, pay read fee, receive noisy target-bit and outage indicator', WAIT='advance.9, receive outage indicator', RESET='preserve unknown bit, reset physical X0, advance.25, pay reset fee, receive outage indicator'),
        observations='Raw cue, public context, known prices/durations, own actions, noisy READ bits, and interval outage bit. Exact event counts and hidden states appear only in terminal settlement/audit records, never planner features.',
        outage_fee=controller.EVENT_FEE, reward='terminal bit correctness minus actual READ/RESET fees, elapsed-time fee and actual repeated-outage fee',
        light_controller='Rolling one-action lookahead, all5 actions considered, same3-action execution horizon', value_controller='Exact finite remaining-horizon belief DP under fitted model; 1e-10 action tie tolerance and14decimal belief memoization',
        main_2x2=[spec[0] for spec in SPECS[:4]], secondary=[spec[0] for spec in SPECS[4:]],
        bootstrap=dict(draws=2000, seed=638911, unit='heldout context, with equal cue/profile/episode and three independently fitted model averages', scope='Conditional on these three fitted models and this registered context domain; six context clusters give limited population evidence'),
        primary=dict(analytic_increment='D-B complete actual utility, positive for each fit and context-bootstrap lower bound>0', distribution_mechanism='D minus joint-train/factorized-execution on association cues2/3, positive for each fit and context-bootstrap lower bound>0 plus actual action differences', adoption='Original learned-network and real AV gates remain open regardless of this finite witness'),
        reporting='All5 main2x2 contrasts; all4 training/execution cells, mean-projection intervention, first actions and complete action counts. Zero-width same-law intervals do not establish population certainty.',
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, device='CPU', threads=1), energy_joules=None)
    write(out / 'PROTOCOL.json', protocol)
    print(json.dumps(dict(protocol_sha256=sha(out / 'PROTOCOL.json'), source_hashes=source_hashes())))


def prepare(out, protocol):
    assert source_hashes() == protocol['source_hashes']
    fits = []
    for seed in protocol['fit_seeds']:
        started, cpu = time.perf_counter(), time.process_time()
        arrays = world.training(seed)
        raw = out / f'train_{seed}.npz'; np.savez_compressed(raw, **arrays)
        candidate = model.fit(arrays)
        candidate_path = out / f'candidate_{seed}.json'; write(candidate_path, candidate)
        fits.append(dict(seed=seed, candidate=candidate_path.name, sha256=sha(candidate_path), training_raw=raw.name, training_raw_sha256=sha(raw), cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - started))
    checks, maximum = 0, 0.
    rng = np.random.default_rng(775381)
    for record in fits:
        candidate = json.loads((out / record['candidate']).read_text())
        for context in rng.uniform(-1, 1, (20, 2)):
            for duration in controller.DURATIONS.values():
                ordinary, ordinary_count = model.kernels(candidate, context, 'ordinary', duration)
                analytic, analytic_count = model.kernels(candidate, context, 'analytic', duration)
                error = max(max(float(np.max(np.abs(a-b))) for a, b in zip(ordinary, analytic)), float(np.max(np.abs(ordinary_count - analytic_count))))
                maximum = max(maximum, error)
                assert error < 1e-11
                assert np.max(np.abs((analytic[0] + analytic[1]).sum(1) - 1)) < 1e-11
                assert np.all(analytic_count >= analytic[1].sum(1) - 1e-11)
                checks += 3
        priors = np.asarray(candidate['full_priors'])
        coordinate = np.repeat([0, 1, 2, 0], 2)
        assert priors[0] @ coordinate == priors[1] @ coordinate == 1
        assert np.array_equal(model.project(priors[0], 'mean'), model.project(priors[1], 'mean'))
        assert np.array_equal(model.project(priors[2], 'factorized'), model.project(priors[3], 'factorized'))
        checks += 3
    assert source_hashes() == protocol['source_hashes']
    write(out / 'NUMERICAL_DEVELOPMENT.json', dict(passed=True, checks=checks, max_full_killed_count_error=maximum, scope='Independent generic uniformization versus SciPy augmented/killed exponentials on development contexts; exact matched-mean/marginal prior identities'))
    write(out / 'ALL_CANDIDATES.json', dict(protocol_sha256=sha(out / 'PROTOCOL.json'), source_hashes=source_hashes(), fits=fits))
    print(json.dumps(dict(fits=len(fits), candidate_manifest_sha256=sha(out / 'ALL_CANDIDATES.json'), checks=checks, maximum=maximum)))


def rollout(policy, prior, physical_rates, cue, profile, context_index, episode, world_seed):
    key = [world_seed, context_index, cue, profile, episode]
    state, target = world.initial(cue, np.random.default_rng(np.random.SeedSequence(key + [99])))
    belief, total_fee, elapsed = prior.copy(), 0., 0.
    actions = np.full(4, 255, np.uint8); observations = actions.copy(); before = actions.copy(); after = actions.copy(); events = np.zeros(4, np.uint8)
    fees = np.zeros(4); durations = fees.copy()
    for step in range(4):
        _, action, _ = policy.solve(belief, 3 - step)
        actions[step], before[step] = action, state
        if action < 2:
            after[step] = state
            correct = int(action == target)
            return correct - total_fee, correct, target, actions, observations, before, after, events, fees, durations
        rng = np.random.default_rng(np.random.SeedSequence(key + [step]))
        if action == 4:
            state = 0
        duration = controller.DURATIONS[action]
        state, count, _ = world.advance(state, duration, physical_rates, rng)
        observation = int(count > 0)
        if action == 2:
            bit = target if rng.random() < world.READ_ACCURACY[state] else 1 - target
            observation = 2 * observation + bit
        fee = controller.PROFILES[profile][2] * duration + controller.EVENT_FEE * count
        fee += controller.PROFILES[profile][0] if action == 2 else controller.PROFILES[profile][1] if action == 4 else 0
        total_fee += fee; elapsed += duration
        observations[step], after[step], events[step], fees[step], durations[step] = observation, state, count, fee, duration
        belief = policy.observe(belief, action, observation)
    raise RuntimeError('Missing terminal action')


def confirm(out, protocol):
    candidates = json.loads((out / 'ALL_CANDIDATES.json').read_text())
    assert candidates['source_hashes'] == source_hashes() == protocol['source_hashes']
    assert candidates['protocol_sha256'] == sha(out / 'PROTOCOL.json')
    for record in candidates['fits']:
        assert sha(out / record['candidate']) == record['sha256']
    destination = out / 'confirmation'; destination.mkdir()
    write(destination / 'FREEZE.json', dict(candidate_manifest_sha256=sha(out / 'ALL_CANDIDATES.json'), source_hashes=source_hashes(), opened_utc=datetime.now(timezone.utc).isoformat()))
    contexts = np.random.default_rng(protocol['test_context_seed']).uniform(-1, 1, (protocol['test_contexts'], 2))
    rows, root_rows = [], []
    for record in candidates['fits']:
        candidate = json.loads((out / record['candidate']).read_text()); seed = record['seed']
        for ci, context in enumerate(contexts):
            physical_rates = world.rates(context)  # Environment side only, never a Policy argument.
            for cue in range(protocol['cue_count']):
                for profile in range(len(controller.PROFILES)):
                    raw = []
                    for name, engine, control, projection, prior_field in SPECS:
                        started, cpu = time.perf_counter(), time.process_time()
                        policy = controller.Policy(candidate, context, profile, engine, control, projection)
                        prior = np.asarray(candidate[prior_field][cue])
                        value, action, q = policy.solve(prior, 3)
                        root_rows.append(dict(seed=seed, context=ci, cue=cue, profile=profile, arm=name, predicted_root_value=value, root_action=action, root_q=q))
                        outcomes = [rollout(policy, prior, physical_rates, cue, profile, ci, episode, protocol['world_seed']) for episode in range(protocol['episodes_per_cell'])]
                        utility, correct, target = [np.asarray([row[i] for row in outcomes]) for i in range(3)]
                        actions, obs, before, after, events, fees, durations = [np.stack([row[i] for row in outcomes]) for i in range(3, 10)]
                        raw.append(dict(utility=utility, correct=correct, target=target, actions=actions, obs=obs, before=before, after=after, events=events, fees=fees, durations=durations))
                        rows.append(dict(seed=seed, context=ci, cue=cue, profile=profile, arm=name, utility=float(utility.mean()), accuracy=float(correct.mean()), cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - started, root_action=action, action_counts=np.bincount(actions[actions != 255], minlength=5).tolist(), policy_cache_nodes=len(policy.cache)))
                    path = destination / f'fit{seed}_context{ci}_cue{cue}_price{profile}.npz'
                    np.savez_compressed(path, **{key: np.stack([record[key] for record in raw]) for key in raw[0]})
            print(json.dumps(dict(seed=seed, context=ci, complete=True)), flush=True)
    write(destination / 'CONTEXTS.json', dict(context_features=contexts.tolist(), true_rates_environment_only=[world.rates(context).tolist() for context in contexts], candidate_context_interface='features only, through fitted rate coefficients'))
    write(destination / 'ROWS.json', rows); write(destination / 'ROOT_Q.json', root_rows)
    from .analysis import analyze
    analyze(out)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('phase', choices=('freeze', 'prepare', 'confirm')); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.phase == 'freeze':
        freeze(args.out)
    else:
        protocol = json.loads((args.out / 'PROTOCOL.json').read_text())
        prepare(args.out, protocol) if args.phase == 'prepare' else confirm(args.out, protocol)


if __name__ == '__main__':
    main()
