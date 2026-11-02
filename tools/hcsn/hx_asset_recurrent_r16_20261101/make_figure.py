"""Plot existing functional records only; no model/financial evaluations."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root, output_prefix):
    names = ['ASSET_PROTOCOL.json', 'ASSET_AUDIT_V1.json.gz', 'ASSET_TRAINING_V1.json.gz', 'ASSET_RESULT_CHECK_V1.json']
    data = {}
    for name in names:
        raw = (root/name).read_bytes()
        data[name] = json.loads(gzip.decompress(raw) if name.endswith('.gz') else raw)
    protocol, audit, train, check = [data[name] for name in names]
    assert audit['audit_passed'] and train['training_passed'] and check['passed']
    paths = [Path(str(output_prefix)+suffix) for suffix in ('.png', '.svg', '_PROVENANCE.json')]
    if any(path.exists() for path in paths):
        raise FileExistsError('Figure outputs are create-only')
    boundaries = {tuple(row['theta']): row['boundary'] for row in check['native_branch_reference']['boundaries']}
    theta_sequence = [row['effective_theta_before_update'] for row in train['history']]+[train['effective_theta_final']]
    boundary_sequence = np.asarray([boundaries[tuple(theta)] for theta in theta_sequence])
    losses = np.asarray([row['terminal_loss_before_update'] for row in train['history']]+[train['final_loss']])
    margin = np.asarray(train['final_trajectory']['margin'])
    normal = np.linalg.norm(audit['temporal']['comparisons']['step_theta']['observed'], axis=1)
    detached = np.linalg.norm(audit['temporal']['detach_negative_control']['step_theta_gradients'], axis=1)
    plt.rcParams.update({'font.size': 9, 'axes.titlesize': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 2, figsize=(11.3, 7.6), layout='constrained')
    fig.suptitle('Actual H-X fixed-potential cell: functional BPTT evidence\n16 Euler steps; 8 fixed sequences; 12 updates; no quality-comparison claim', fontsize=13)
    ax = axes[0, 0]
    ax.plot(np.arange(len(boundary_sequence)), boundary_sequence, 'o-', color='#215a8c', label='Financial boundary b')
    probe = train['fixed_physical_fixture']['represented_assets_initial'][3]
    ax.axhline(probe, color='#b23b38', linestyle='--', label=f'Fixed physical V = {probe:.4f}')
    ax.set(title='A  Boundary moves against a fixed physical input', xlabel='Optimizer update', ylabel='Boundary / physical asset units')
    ax.legend(frameon=False, fontsize=8, loc='upper left'); ax.grid(alpha=.2)
    ax = axes[0, 1]
    times = np.arange(len(margin))*protocol['cell']['dt']
    for sample in range(margin.shape[1]): ax.plot(times, margin[:, sample], linewidth=1.2, alpha=.85)
    lo, hi = float(margin.min())-.003, max(.003, float(margin.max())+.003)
    ax.axhspan(lo, 0., color='#e6e9ed', alpha=.6); ax.axhline(0., color='#333333', linestyle='--', linewidth=.8)
    final_branch = check['actual_branch_checks']['final']
    ax.set(ylim=(lo, hi), title=f"B  Final sampled margins: {final_branch['actual_default_states']}/{final_branch['states_checked']} default states", xlabel='Euler time (sampled states)', ylabel='x = log(V / b)')
    ax.grid(alpha=.2)
    ax = axes[1, 0]
    relative = 100.*(losses/losses[0]-1.)
    ax.plot(np.arange(len(losses)), relative, 'o-', color='#5e478a')
    ax.axhline(0., color='#555555', linewidth=.6)
    ax.set(title='C  Very small same-batch loss change', xlabel='Optimizer update', ylabel='Relative training-loss change (%)')
    ax.text(.03, .12, f'Final reduction: {-relative[-1]:.5f}%\nNo generalization or effectiveness evidence', transform=ax.transAxes, fontsize=9)
    ax.grid(alpha=.2)
    ax = axes[1, 1]
    ax.plot(np.arange(len(normal)), normal, 'o-', color='#1c7657', label='True time-unrolled graph')
    ax.plot(np.arange(len(detached)), detached, 's--', color='#b35f21', label='State-detached negative control')
    ax.set(title='D  Early financial parameters influence terminal loss', xlabel='Parameter-use time step', ylabel='Per-step theta VJP norm (mixed parameter units)')
    ax.ticklabel_format(axis='y', style='sci', scilimits=(0, 0)); ax.legend(frameon=False, fontsize=8); ax.grid(alpha=.2)
    fig.savefig(paths[0], dpi=160, facecolor='white'); fig.savefig(paths[1], facecolor='white'); plt.close(fig)
    result = {'schema': 'hcsn.fixed-potential-functional-figure.v1', 'source_sha256': {name: sha(root/name) for name in names},
              'script_sha256': sha(__file__), 'matplotlib_version': matplotlib.__version__,
              'files': [{'name': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)} for path in paths[:2]],
              'financial_kernel_calls': 0, 'training_reruns': 0,
              'caption': 'Existing fixed-z functional records. Boundary movement and BPTT are observed, while default occupancy increases and the training loss change is tiny. Lines join Euler samples; they are not analytic trajectories or spike events.'}
    with paths[2].open('x') as f: f.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True); parser.add_argument('--output-prefix', type=Path, required=True)
    args = parser.parse_args(); main(args.root, args.output_prefix)
