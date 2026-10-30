"""Independent prepared-data, EM trajectory and readout candidate reconstruction."""

import gzip
import json
from pathlib import Path

import numpy as np

from .audit_transport import Archive, acquired_public, digest, file_sha, transport_records
from .audit_replay import LEARNED
from .reference import noise_objective


def load_npz(path):
    with np.load(path, allow_pickle=False) as source:
        return {key: source[key].item() if source[key].ndim == 0 else source[key].copy() for key in source.files}


def dynamics(data, model, receipt, checks):
    errors = data['target'] - data['initial_output']
    means = np.quantile(errors, [0.25, 0.75])
    variances = np.full(2, max(float(np.var(errors)) / 2, 0.01))
    weights = np.full(2, 0.5)
    initial = receipt['prior_initial']
    for key, value in [('weights', weights), ('means', means), ('variances', variances)]:
        checks.close(initial[key], value, 'initial_dynamics_' + key, 2e-13)
    losses = []
    for _ in range(80):
        # Direct component density, separate from the primary log-space EM.
        density = np.exp(-0.5 * (errors[:, None] - means) ** 2 / variances) / np.sqrt(2 * np.pi * variances)
        joint = density * weights
        total = joint.sum(axis=1)
        checks.require(np.all(total > 0), 'independent EM density representable')
        losses.append(float(-np.log(total).mean()))
        responsibilities = joint / total[:, None]
        mass = responsibilities.sum(axis=0)
        weights = np.maximum(mass / len(errors), 1e-6)
        weights /= weights.sum()
        means = (responsibilities * errors[:, None]).sum(axis=0) / mass
        variances = np.maximum((responsibilities * (errors[:, None] - means) ** 2).sum(axis=0) / mass, 1e-4)
    order = np.argsort(means)
    for key, value in [('weights', weights[order]), ('means', means[order]), ('variances', variances[order])]:
        checks.close(model['prior'][key], value, 'independent_EM_final_' + key, 3e-10)
        checks.require(model['prior'][key] == receipt['prior_final'][key], 'model/fitting receipt binding')
    checks.close(receipt['training_nll_by_iteration'], losses, 'independent_EM_NLL_trajectory', 3e-10)
    checks.require(initial != model['prior'] and receipt['prior_parameters_changed'], 'actual mixture parameter change')
    checks.close(model['gaussian_prior']['means'], [float(errors.mean())], 'Gaussian empirical mean', 3e-13)
    checks.close(model['gaussian_prior']['variances'], [float(np.var(errors))], 'Gaussian empirical variance', 3e-13)
    checks.close(model['calibration']['error_variance'], float(np.var(errors)), 'training error variance calibration', 3e-13)
    checks.require(receipt['gaussian_prior'] == model['gaussian_prior'] and receipt['em_steps'] == 80,
                   'Gaussian prior and exact completed EM count binding')
    final_density = np.exp(-0.5 * (errors[:, None] - means) ** 2 / variances) / np.sqrt(2 * np.pi * variances)
    final_nll = float(-np.log(final_density @ weights).mean())
    saved = model['prior']
    saved_density = np.exp(-0.5 * (errors[:, None] - saved['means']) ** 2 / saved['variances']) / np.sqrt(2 * np.pi * np.asarray(saved['variances']))
    checks.close(float(-np.log(saved_density @ saved['weights']).mean()), final_nll, 'final-parameter independent prior NLL', 3e-10)
    sensor_errors = np.concatenate([data['self_evaluation'] - data['target'], data['wait_evaluation'] - data['target']])
    declared = np.concatenate([data['sensor_variance'], data['wait_variance']])
    scale = float(np.mean(sensor_errors ** 2 / declared))
    checks.close(model['calibration']['noise_scale'], scale, 'actual supervised sensor scale', 3e-13)
    checks.close(receipt['noise_scale_final'], scale, 'sensor scale receipt', 3e-13)
    checks.close(noise_objective(np.log(scale), sensor_errors, declared)[1], 0, 'noise objective stationary derivative', 3e-15)
    checks.require(receipt['confirmation_used'] is False and receipt['training_rows'] == len(errors), 'fitting data scope')
    raw = []
    for i in range(len(errors)):
        for count in (1, 2):
            observations = [data['self_evaluation'][i] - data['initial_output'][i]]
            variances = [data['sensor_variance'][i]]
            if count == 2:
                observations.append(data['wait_evaluation'][i] - data['initial_output'][i])
                variances.append(data['wait_variance'][i])
            precision = sum(1 / value for value in variances)
            residual = sum(y / v for y, v in zip(observations, variances)) / precision
            raw.append([residual, np.log(1 / precision), np.log(data['repair_cost'][i])])
    raw = np.asarray(raw)
    center, spread = raw.mean(axis=0), np.maximum(raw.std(axis=0), 1e-8)
    checks.close(model['calibration']['public_center'], center, 'public feature center', 3e-13)
    checks.close(model['calibration']['public_scale'], spread, 'public feature scale', 3e-13)
    centers = ((raw - center) / spread)[np.linspace(0, len(raw) - 1, 43).astype(int)]
    checks.close(model['calibration']['history_centers'], centers, 'shared history radial centers', 3e-13)
    return {'initial_prior_nll': losses[0], 'last_recorded_pre_update_nll': losses[-1],
            'final_prior_nll_after_80_updates': final_nll, 'actual_supervised_noise_scale': scale,
            'noise_nll_at_initial_scale': noise_objective(0.0, sensor_errors, declared)[0],
            'noise_nll_at_fitted_scale': noise_objective(np.log(scale), sensor_errors, declared)[0],
            'noise_gradient_at_fitted_scale': noise_objective(np.log(scale), sensor_errors, declared)[1]}


def head_candidates(model, fits, train_rows, dev_rows, checks):
    gain = np.asarray([s['realized_gain'] for r in train_rows for s in r['stages']])
    dev_gain = np.asarray([[r['stages'][0]['realized_gain'], r['stages'][1]['realized_gain'],
                            r['stages'][0]['public']['wait_cost']] for r in dev_rows])
    dev_wait = np.asarray([r['stages'][0]['values']['wait_gain'] for r in dev_rows])
    dev_stop = np.asarray([r['stages'][0]['stop_utility'] for r in dev_rows])
    for arm in LEARNED:
        x = np.asarray([s['features'][arm] for r in train_rows for s in r['stages']])
        z = np.asarray([s['features'][arm] for r in dev_rows for s in r['stages']])
        fit = fits[arm]
        checks.require(digest(x.tolist()) == fit['training_feature_sha256']
                       and digest(gain.tolist()) == fit['training_gain_sha256'], 'readout training input binding')
        center, scale = x.mean(axis=0), x.std(axis=0)
        center[0], scale[0] = 0, 1
        scale = np.where(scale > 1e-8, scale, 1)
        standardized = (x - center) / scale
        computed = []
        checks.require(len(fit['candidates']) == 15, 'complete readout candidate grid')
        for strength_index, strength in enumerate((0.001, 0.01, 0.1)):
            penalty = np.eye(x.shape[1]) * strength
            penalty[0, 0] = 0
            hessian = standardized.T @ standardized / len(x) + penalty
            rhs = standardized.T @ gain / len(x)
            eigenvalues, eigenvectors = np.linalg.eigh(hessian)
            rate = 0.9 / max(float(eigenvalues[-1]), 1e-8)
            transformed = eigenvectors.T @ rhs
            # Closed spectral reconstruction of the recorded 600 gradient steps.
            factor = 1 - rate * eigenvalues
            iterate = lambda count: eigenvectors @ ((1 - factor ** count) / eigenvalues * transformed)
            final, before_final = iterate(600), iterate(599)
            gradient = hessian @ before_final - rhs
            raw = final / scale
            raw[0] -= float(raw @ center)
            predicted = (z @ raw).reshape(-1, 2)
            for offset_index, offset in enumerate((-0.1, -0.05, 0.0, 0.05, 0.1)):
                candidate = fit['candidates'][strength_index * 5 + offset_index]
                checks.require(candidate['l2'] == strength and candidate['offset'] == offset
                               and candidate['steps'] == 600, 'registered candidate geometry')
                checks.close(candidate['weights'], raw, 'spectral readout trajectory weights', 5e-8)
                checks.close(candidate['learning_rate'], rate, 'readout learning rate', 5e-13)
                checks.close(candidate['gradient_norm'], np.linalg.norm(gradient), 'pre-final-update gradient norm', 3e-10)
                checks.close(candidate['training_mse'], np.mean((x @ raw - gain) ** 2), 'readout training MSE', 3e-10)
                # Use independently verified saved weights to avoid changing a
                # discrete tie solely through eigensolver roundoff in this audit.
                scores = (z @ candidate['weights']).reshape(-1, 2) + offset
                first = np.argmax(np.column_stack([np.zeros(len(scores)), scores[:, 0], dev_wait]), axis=1)
                second = scores[:, 1] > 0
                utility = dev_stop + np.where(first == 1, dev_gain[:, 0],
                    np.where(first == 2, -dev_gain[:, 2] + second * dev_gain[:, 1], 0))
                checks.close(candidate['development_utility'], utility.mean(), 'independent candidate utility', 3e-12)
                checks.require(candidate['development_waits'] == int((first == 2).sum()), 'candidate paid waits')
                computed.append({**candidate, 'development_utility': float(utility.mean())})
        chosen = max(computed, key=lambda row: (row['development_utility'], row['l2'], -abs(row['offset'])))
        checks.require(model['heads'][arm] == {key: chosen[key] for key in ('weights', 'offset', 'l2')}, 'actual selected readout')
        checks.require(digest(chosen['weights']) == fit['selected_weights_sha256'], 'selected readout digest')
        checks.close(fit['parameter_l2_change'], np.linalg.norm(chosen['weights']), 'actual readout parameter change', 3e-12)


def audit_seed(directory, replay, checks):
    directory = Path(directory)
    before_calls, before_ticks = replay.native.calls, replay.native.original_sparse_ticks
    receipt = json.loads((directory / 'TRAINING_RECEIPT.json').read_text())
    for key, filename in [('model_file_sha256', 'MODELS.json'), ('training_rows_sha256', 'TRAINING_ROWS.json.gz'),
                          ('training_data_sha256', 'TRAIN.npz'), ('development_data_sha256', 'DEVELOPMENT.npz')]:
        checks.require(file_sha(directory / filename) == receipt[key], 'prepared artifact identity')
    model = json.loads((directory / 'MODELS.json').read_text())
    with gzip.open(directory / 'TRAINING_ROWS.json.gz', 'rt') as stream:
        collections = json.load(stream)
    train = load_npz(directory / 'TRAIN.npz')
    dynamics_review = dynamics(train, model, receipt['dynamics'], checks)
    base_model = {key: model[key] for key in ('prior', 'gaussian_prior', 'calibration')}
    archive_files, original_roundtrip_ns = 0, 0
    for split, filename, archive_key, count_key in [('train', 'TRAIN.npz', 'training_archive', 'train_rows'),
            ('development', 'DEVELOPMENT.npz', 'development_archive', 'development_rows')]:
        data = load_npz(directory / filename)
        rows = collections[split]
        checks.require(len(rows) == len(data['target']) == receipt[count_key], 'prepared row count')
        checks.require(digest(data['ids'].tolist()) == model[split + '_ids_sha256' if split == 'development' else 'training_ids_sha256'], 'prepared training/development identity')
        archive = Archive(directory, receipt[archive_key], checks)
        try:
            for i, row in enumerate(rows):
                checks.require(row['case'] == str(data['ids'][i]) and len(row['stages']) == 2, 'both supervised potentials present')
                prefix = f'case-{i}'
                values, records, _ = transport_records(archive, prefix, checks)
                checks.require(len(records) == 11, 'complete supervised transport operations')
                for name, column in [('initial', 'initial_output'), ('sensor', 'self_evaluation'), ('wait_sensor', 'wait_evaluation'),
                                     ('sensor_variance', 'sensor_variance'), ('wait_variance', 'wait_variance'),
                                     ('repair_cost', 'repair_cost'), ('wait_cost', 'wait_cost')]:
                    checks.require(values[name] == float(data[column][i]), 'prepared actual data readback')
                owner = replay.owner([row['case'], 'shared'], digest(base_model), 'event')
                checkpoint = '0' * 64
                for stage_index, stage in enumerate(row['stages']):
                    original_roundtrip_ns += sum(r['subprocess_roundtrip_ns'] for r in stage['runtime']['native'])
                    original_roundtrip_ns += sum(r['subprocess_roundtrip_ns'] for arm in LEARNED for r in stage['native'][arm])
                    public = acquired_public(values, stage_index == 1, checks)
                    checks.require(public == stage['public'], 'prepared acquired public equality')
                    checkpoint, independent = replay.stage(owner, stage['runtime'], model, 'event', public, stage_index + 1, checkpoint)
                    replay.values(stage['values'], independent)
                    for arm in LEARNED:
                        feature = replay.features(public, stage['runtime']['law'], model, arm,
                            row['case'] + f'/stage{stage_index}/{arm}', stage['native'][arm])
                        checks.close(stage['features'][arm], feature, 'prepared independent ' + arm + ' features', 2e-12)
                    target = float(data['target'][i])
                    gain = (public['initial'] - target) ** 2 - (values[f'potential{stage_index}'] - target) ** 2 - public['repair_cost']
                    checks.close(stage['realized_gain'], gain, 'actual supervised delivery gain', 3e-12)
                    checks.close(stage['stop_utility'], 1 - (public['initial'] - target) ** 2, 'supervised stop utility', 3e-12)
                    checks.require(values[f'potential{stage_index}'] == public['initial'] + stage['values']['repair_amount'], 'actual potential amount')
                replay.archived_owner(archive, prefix, owner, row['stages'])
            archive_files += len(archive.files)
        finally:
            archive.close()
    head_candidates(model, receipt['fits'], collections['train'], collections['development'], checks)
    checks.require(receipt['native']['requests'] == replay.native.calls - before_calls
                   and receipt['native']['ticks'] == replay.native.original_sparse_ticks - before_ticks,
                   'all original supervised native requests and ticks replayed')
    checks.require(receipt['native']['roundtrip_ns'] == original_roundtrip_ns, 'complete original training native cost ledger')
    return {'seed': receipt['seed'], 'namespace': receipt['namespace'], 'train_rows': receipt['train_rows'],
            'development_rows': receipt['development_rows'], 'readout_candidates_verified': 45,
            'EM_steps_independently_reconstructed': 80, 'archive_members_verified': archive_files,
            'dynamics_review': dynamics_review}
