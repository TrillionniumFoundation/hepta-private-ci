"""Engineering fixture repair adapter; published package helpers remain immutable."""
import argparse
from copy import deepcopy
from pathlib import Path

from . import joint_inference_package as package, joint_task as task

HERE = Path(__file__).resolve().parent
ORIGINAL = {'joint_inference_package.py': 'd3314a8fd13a1363afc39413ea81d4f01c71ea4a7b2268cdef499777c957958c',
            'joint_package_benchmark.py': 'da3bd67fa6e71c36b6839932d072ad2394e1803980fc1b05cf4a27fa43ac15a6',
            'joint_package_benchmark_protocol.json': '0928f2f47be832d318a5e731a673a134a1b02151b8ada5b8e0466140c5276cb2'}
AMENDMENT = dict(reason='Original engineering fixture used dt1.0 absent from frozen export support; replace only that fixture duration with registered dt.75',
    timing='After main confirmation started; no confirmation result inspected; before any package benchmark',
    changes='No weights, projection, numeric precision, 400 actual worlds, 20 candidate sources, 48 hypotheses or thresholds changed',
    prior_failure='First derive exit1 KeyError(1.0,0), complete CPU .157527 seconds; original output and source snapshot retained')


def verify_original():
    if any(package.sha(HERE/name) != digest for name, digest in ORIGINAL.items()):
        raise ValueError('published auxiliary source mutated')


def registered_rows():
    public = deepcopy(package.fixture_rows()[0]['public'])
    assert public['duration'] == [.25, .5, 1., 1.5, .5, .25]
    public['duration'][2] = .75
    protocol = package.read(HERE/'joint_protocol.json')
    supported = set(protocol['train_domain']['durations']+protocol['ood_domain']['durations'])
    assert set(public['duration']) <= supported
    rows = []
    for bit in (0, 1):
        state = task.initial(public)
        for action in (2, 1, 1, 1, 1, 1):
            rows.append(dict(public=deepcopy(public), state=deepcopy(state)))
            due = task.due_request(public, state, action)
            state = task.successor(public, state, action, None if due is None else dict(observation_tick=due, observation=bit))
        rows.append(dict(public=deepcopy(public), state=deepcopy(state)))
    return rows


def derive_registered(root, out, published_model_commit):
    verify_original(); root, out = Path(root), Path(out)
    frozen = package.read(root/'MODEL_FREEZE.json'); source_digest = package.sha(__file__)
    if len(published_model_commit) != 40 or set(published_model_commit)-set('0123456789abcdef'):
        raise ValueError('published final model commit required')
    if len(frozen['models']) != 20: raise ValueError('all20 final models required')
    repository = HERE.parents[2]
    if any(package.sha(repository/p) != h for p, h in frozen['sources'].items()): raise ValueError('frozen source mutated')
    if any(package.sha(root/p) != h for p, h in frozen['models'].items()): raise ValueError('frozen weight mutated')
    rows = registered_rows(); out.mkdir(parents=True, exist_ok=False); models = {}
    for relative, digest in sorted(frozen['models'].items()):
        target = out/relative
        models[relative] = package.package_file(root/relative, target, target.with_name('provenance.json'), digest, rows=rows)
    verify_original()
    if package.sha(__file__) != source_digest: raise ValueError('adapter source mutated')
    result = dict(schema='joint-numpy-package-freeze-v1', published_model_commit=published_model_commit,
        model_freeze_sha256=package.sha(root/'MODEL_FREEZE.json'), package_source_sha256=package.sha(package.__file__),
        registered_adapter_source_sha256=source_digest, original_auxiliary_sha256=ORIGINAL, engineering_amendment=AMENDMENT, models=models)
    package.write(out/'PACKAGE_FREEZE.json', result)
    return result


def benchmark_registered(root, packages, confirmation, out):
    verify_original(); frozen = package.read(Path(packages)/'PACKAGE_FREEZE.json')
    if frozen['registered_adapter_source_sha256'] != package.sha(__file__): raise ValueError('adapter/freeze mismatch')
    from .joint_package_benchmark import benchmark
    result = benchmark(root, packages, confirmation, out)
    verify_original()
    if frozen['registered_adapter_source_sha256'] != package.sha(__file__): raise ValueError('adapter source mutated')
    package.write(Path(out)/'REGISTERED_ADAPTER.json', dict(source_sha256=package.sha(__file__), original_auxiliary_sha256=ORIGINAL,
        package_freeze_sha256=package.sha(Path(packages)/'PACKAGE_FREEZE.json'), engineering_amendment=AMENDMENT))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('stage', choices=('derive', 'benchmark'))
    for name in ('root', 'out'): p.add_argument('--'+name, required=True)
    for name in ('published-model-commit', 'packages', 'confirmation'): p.add_argument('--'+name)
    a = p.parse_args()
    if a.stage == 'derive': derive_registered(a.root, a.out, a.published_model_commit)
    else: benchmark_registered(a.root, a.packages, a.confirmation, a.out)


if __name__ == '__main__': main()
