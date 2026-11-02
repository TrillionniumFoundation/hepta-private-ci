"""Predeclared raw/slim replay on existing confirmation worlds; never fits/generates."""
import argparse
from pathlib import Path
import resource
import time

import numpy as np
from scipy.stats import t as student_t

from . import joint_campaign as campaign, joint_task as task
from .joint_inference_package import exact, read, sha, write
from .joint_law import IndependentLaw

HERE = Path(__file__).resolve().parent


def intervals(aggregate, protocol):
    critical = float(student_t.ppf(1-.05/(2*48), 4)); result = {}
    def interval(values):
        values = np.asarray(values); mean = float(values.mean())
        half = float(critical*values.std(ddof=1)/np.sqrt(5))
        return dict(mean=mean, lower=mean-half, upper=mean+half, fit_values=values.tolist())
    for fmt in ('raw', 'slim'):
        for split in ('iid', 'ood'):
            for family in protocol['families'][1:]:
                p, n = aggregate[fmt+'/'+split+'/renewal'], aggregate[fmt+'/'+split+'/'+family]
                assert [r['fit'] for r in p] == [r['fit'] for r in n] == protocol['fits']
                quality = interval([x['utility']-y['utility'] for x, y in zip(p, n)])
                cpu = interval([np.log(x['full_execution_cpu_seconds']/y['full_execution_cpu_seconds']) for x, y in zip(p, n)])
                latency = interval([np.log(x['wall_p95_seconds']/y['wall_p95_seconds']) for x, y in zip(p, n)])
                throughput = interval([np.log(x['serial_service_throughput']/y['serial_service_throughput']) for x, y in zip(p, n)])
                gates = dict(quality_noninferior=quality['lower'] > -.02, cpu_saving=cpu['upper'] < float(np.log(.90)),
                    wall_latency_not_degraded=latency['upper'] < float(np.log(1.05)), throughput_not_degraded=throughput['lower'] > float(np.log(.95)))
                result[fmt+'/'+split+'/'+family] = dict(quality=quality, log_cpu_ratio=cpu, log_wall_p95_ratio=latency,
                    log_serial_service_throughput_ratio=throughput, gates=gates, passed=all(gates.values()))
    return result


def benchmark(root, packages, confirmation, out):
    root, packages, confirmation, out = map(Path, (root, packages, confirmation, out))
    frozen, packed = read(root/'MODEL_FREEZE.json'), read(packages/'PACKAGE_FREEZE.json')
    protocol, registration = read(HERE/'joint_protocol.json'), read(HERE/'joint_package_benchmark_protocol.json')
    if registration['helper_source_sha256'] != sha(HERE/'joint_inference_package.py'):
        raise ValueError('registered helper mutated')
    if packed['model_freeze_sha256'] != sha(root/'MODEL_FREEZE.json') or len(packed['models']) != 20:
        raise ValueError('package freeze mismatch')
    if protocol['fits'] != registration['data']['fits'] or protocol['families'] != registration['arms']['families']:
        raise ValueError('registration mismatch')
    manifests = {}
    for fit in protocol['fits']:
        for split in ('iid', 'ood'):
            path = confirmation/f'cohort_{fit}_{split}.json'; cohort = read(path)
            if len(cohort['records']) != 40 or cohort['published_source_commit'] != packed['published_model_commit']:
                raise ValueError('exact published original cohort required')
            manifests[(fit, split)] = (path, cohort)
    bound_paths = [Path(__file__), HERE/'joint_inference_package.py', HERE/'joint_package_benchmark_protocol.json',
                   root/'MODEL_FREEZE.json', packages/'PACKAGE_FREEZE.json']+[path for path, _ in manifests.values()]
    bound_hashes = {str(path): sha(path) for path in bound_paths}
    def verify():
        if any(sha(path) != digest for path, digest in bound_hashes.items()): raise ValueError('auxiliary source/freeze/manifest mutation')
        repository = HERE.parents[2]
        if any(sha(repository/p) != h for p, h in frozen['sources'].items()): raise ValueError('source mutation')
        for relative, digest in frozen['models'].items():
            entry = packed['models'][relative]
            if sha(root/relative) != digest or entry['original_sha256'] != digest:
                raise ValueError('raw model mutation')
            if sha(packages/relative) != entry['package']['sha256']:
                raise ValueError('package mutation')
            sidecar = (packages/relative).with_name('provenance.json')
            if sha(sidecar) != entry['sidecar']['sha256']: raise ValueError('sidecar mutation')
        for _, cohort in manifests.values():
            if any(sha(confirmation/p) != h for p, h in cohort['files'].items()): raise ValueError('cohort mutation')
            if any((confirmation/p).exists() for p in cohort['expected_missing']): raise ValueError('missing packet appeared')
    verify(); out.mkdir(parents=True, exist_ok=False)
    identity = dict(source_sha256=sha(__file__), protocol_sha256=sha(HERE/'joint_package_benchmark_protocol.json'),
        package_freeze_sha256=sha(packages/'PACKAGE_FREEZE.json'), model_freeze_sha256=sha(root/'MODEL_FREEZE.json'),
        cohort_manifest_sha256={str(path.name): sha(path) for path, _ in manifests.values()}, bound_hashes=bound_hashes)
    write(out/'STARTED.json', identity)
    aggregate, setup, count, pairs = {}, {}, 0, 0
    cpu, wall = time.process_time(), time.perf_counter()
    law = IndependentLaw(protocol['truth_raw'])
    for fit in protocol['fits']:
        adapter = task.ContentAdapter(); setup[str(fit)] = adapter.setup
        confusion = frozen['data'][str(fit)]['confusion']
        for split in ('iid', 'ood'):
            cohort = manifests[(fit, split)][1]
            groups = {(fmt, family): [] for fmt in ('raw', 'slim') for family in protocol['families']}
            arms = list(groups); order = []
            rng = np.random.default_rng(registration['arms']['order_seed']+fit*1000000+(0 if split == 'iid' else 100000))
            for original_record in cohort['records']:
                record = dict(original_record, folder=str(confirmation/original_record['id']))
                oracle = task.Oracle(read(Path(record['folder'])/'public.json'), law, confusion)
                pair = {}
                for i in rng.permutation(8):
                    fmt, family = arms[int(i)]
                    relative = f'fit_{fit}/model_{family}/model.json'
                    episode = campaign.execute(record, (root if fmt == 'raw' else packages)/relative, 'value', adapter, oracle)
                    outcome = episode['outcome']
                    for unit in ('cpu', 'wall'):
                        share = adapter.setup[f'load_{unit}_seconds']/640
                        outcome[f'decoder_setup_amortized_{unit}_seconds'] = share
                        outcome[f'full_execution_{unit}_seconds'] += share
                    groups[(fmt, family)].append(episode); pair[(fmt, family)] = episode
                    order.append(dict(world=record['id'], format=fmt, family=family)); count += 1
                for family in protocol['families']:
                    a, b = pair[('raw', family)], pair[('slim', family)]
                    exact(a['final_state'], b['final_state'])
                    exact([d['action'] for d in a['decisions']], [d['action'] for d in b['decisions']])
                    exact([d['scores'] for d in a['decisions']], [d['scores'] for d in b['decisions']])
                    exact(a['outcome']['utility'], b['outcome']['utility']); pairs += 1
            write(out/f'order_{fit}_{split}.json', order)
            for (fmt, family), episodes in groups.items():
                means = {key: float(np.mean([e['outcome'][key] for e in episodes])) for key in episodes[0]['outcome']}
                means['wall_p95_seconds'] = float(np.quantile([e['outcome']['full_execution_wall_seconds'] for e in episodes], .95))
                means['serial_service_throughput'] = 40/sum(e['outcome']['full_execution_wall_seconds'] for e in episodes)
                aggregate.setdefault(fmt+'/'+split+'/'+family, []).append(dict(fit=fit, **means))
                write(out/f'fit_{fit}_{split}_{fmt}_{family}.json.gz', dict(means=means, episodes=episodes))
            print(dict(stage='package_replay', fit=fit, split=split), flush=True)
    verify()
    if count != 3200 or pairs != 1600: raise AssertionError('incomplete replay')
    tests = intervals(aggregate, protocol)
    robust = {split+'/'+family: all(tests[fmt+'/'+split+'/'+family]['passed'] for fmt in ('raw', 'slim'))
              for split in ('iid', 'ood') for family in protocol['families'][1:]}
    result = dict(schema='joint-package-replay-v1', identity=identity, fit_means=aggregate, intervals48=tests,
        robustness=robust, decoder_setup=setup, requests=count, exact_raw_slim_pairs=pairs, new_fits=0, new_worlds=0,
        timed_loop_cpu_seconds=time.process_time()-cpu, timed_loop_wall_seconds=time.perf_counter()-wall,
        complete_process_usage=campaign.cpu_usage(), maximum_resident_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        scope='same frozen weights and original worlds; auxiliary48 family; original14/24 unchanged; no GPU/energy/native or network-service claim')
    write(out/'SUMMARY.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'packages', 'confirmation', 'out'): p.add_argument('--'+name, required=True)
    a = p.parse_args(); benchmark(a.root, a.packages, a.confirmation, a.out)


if __name__ == '__main__': main()
