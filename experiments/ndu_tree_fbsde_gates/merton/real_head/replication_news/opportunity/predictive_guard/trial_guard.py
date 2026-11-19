"""Actual inherited Head execution with a separately metered predictive-model guard."""
from __future__ import annotations
import argparse
import os
import platform
import sys
import time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'compiled'))
sys.path.insert(0, str(HERE.parent.parent))
from benchmark import lifecycle
from compile_policy import SharedPolicy, build, sources as parent_sources
from material_news import encode, loads, packet, sha, write
from study import config as scenarios, fit_prior, training_only
from online import setup, timed
from guard import GuardedAsset

FILES = ('guard.py', 'exact_null.py', 'trial_guard.py', 'audit_guard.py', 'test_guard.py', 'protocol.json', 'README.md')


def sources():
    return {n: sha((HERE/n).read_bytes()) for n in FILES} | {'parent/'+n: v for n,v in parent_sources().items()}


def config():
    return loads((HERE/'protocol.json').read_bytes())


def run(material, output):
    output.mkdir(parents=True, exist_ok=False)
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    a, receipt = packet(material/'worker.npz')
    training_only(material, output/'train.npz')
    prior = fit_prior(output/'train.npz', output/'prior.json')
    compilation = build(output/'prior.json', receipt['worker_sha256'], output/'policy.json')
    asset, loading = timed(lambda: SharedPolicy(output/'policy.json', compilation['asset_sha256'],
                         receipt['worker_sha256'], sha((output/'prior.json').read_bytes())))
    (mean, scale, x), prep = timed(lambda: setup(a))
    order = np.argsort(a['cal_hashes'], kind='stable')
    ids = tuple(a['cal_ids'][order].tolist())
    rows = []
    with (output/'journal.jsonl').open('xb') as journal:
        for repeat in range(config()['repeats']):
            arms = config()['arms'][repeat:]+config()['arms'][:repeat]
            for scenario in scenarios()['scenarios']:
                for arm in arms:
                    def emit(e):
                        journal.write(encode({'repeat':repeat,'scenario':scenario['name'],'arm':arm,**e})+b'\n')
                        journal.flush(); os.fsync(journal.fileno())
                    guarded = arm.startswith('guarded_')
                    proxy, adapter_clock = timed(lambda: GuardedAsset(asset,prior['curves'],ids)) if guarded else (asset, {'cpu_ns':0,'wall_ns':0})
                    implementation = 'shared_'+arm[8:] if guarded else arm
                    try:
                        row = lifecycle(a,x,prior,proxy,implementation,scenario,emit)
                    except Exception as exc:
                        emit({'kind':'failure','error':type(exc).__name__}); raise
                    row['arm'] = arm; row['repeat'] = repeat
                    row['cpu_ns'] += adapter_clock['cpu_ns']; row['wall_ns'] += adapter_clock['wall_ns']
                    if guarded: row['phases'].append({'kind':'guard_adapter_prepare',**adapter_clock})
                    monitor = proxy.lookups[0].monitor if guarded else None
                    row['predictive_records'] = monitor.records if monitor else []
                    row['predictive_alarm'] = monitor.alarm if monitor else False
                    row['guard_scope'] = asset.scope_digest if guarded else None
                    rows.append(row)
                    write(output/f'{repeat}-{scenario["name"]}-{arm}.json',row)
    seal = {'schema':'hepta.merton.predictive-guard-seal.v1','posture':'RESEARCH_ONLY_DENY_ALL',
            'source_sha256':sources(),'protocol_sha256':sha((HERE/'protocol.json').read_bytes()),
            'worker_sha256':receipt['worker_sha256'],'prior_sha256':sha((output/'prior.json').read_bytes()),
            'journal_sha256':sha((output/'journal.jsonl').read_bytes()),'compilation':compilation,'loading':loading,
            'preparation':prep,'mean':mean.tolist(),'scale':scale.tolist(),
            'prior_fits_physically_executed':1,'prior_updates':512,'shared_table_owners':1,
            'actual_online_updates':sum(r['actual_steps'] for r in rows),
            'new_sources':0,'fresh_encoder_calls':0,'heldout_labels_loaded':False,
            'guard_is_accuracy_guarantee':False,'fleet_wide_error_bound':False,
            'runtime':{'python':platform.python_version(),'numpy':np.__version__},
            'command_cpu_ns':time.process_time_ns()-c0,'command_wall_ns':time.perf_counter_ns()-w0,'rows':rows}
    write(output/'sealed.json',seal)
    print(encode({'lifecycles':len(rows),'online_updates':seal['actual_online_updates'],
                  'observed_alarms':sum(r['predictive_alarm'] for r in rows)}).decode())
    return seal


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--material',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.material,a.output)
