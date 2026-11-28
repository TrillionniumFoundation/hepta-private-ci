"""Exercise exact catalog admission with real artifacts and isolated mutations."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

from test_network_host_abi import FULL_MODULE_PROFILES, native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[1]


def encode(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def verify(args, report):
    if sys.flags.optimize:
        raise RuntimeError('catalog qualification cannot disable assertions')
    library = args.library_dir.resolve(strict=True)
    admitted = {}
    native_inputs(library / 'network_host.so', ROOT / 'network_host.hepta', args.build_profile, admitted)
    report['admitted'] = admitted
    modules = FULL_MODULE_PROFILES[args.build_profile]
    expected_field = f'full{len(modules)}_manifest_verified'
    if (admitted['native_build'][expected_field] is not True
            or admitted['native_build']['module_count'] != len(modules)):
        raise RuntimeError('the exact selected catalog was not admitted')
    report['controls'] = []
    with tempfile.TemporaryDirectory(prefix='codex-hia-catalog-') as temporary:
        base = Path(temporary)
        source, native = base / 'hia', base / 'native'
        for filename in admitted['inputs']:
            original = Path(filename)
            if library in original.parents:
                destination = native / original.relative_to(library)
            elif ROOT in original.parents and original != Path(__file__).with_name('test_network_host_abi.py'):
                destination = source / original.relative_to(ROOT)
            else:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
        native_inputs(native / 'network_host.so', source / 'network_host.hepta', args.build_profile, {})
        report['controls'].append({'case': 'complete-private-copy', 'accepted': True})

        def reject(label, replacements=None, profile=None, reason=''):
            replacements = replacements or {}
            originals = {path: path.read_bytes() for path in replacements}
            try:
                for path, value in replacements.items():
                    path.write_bytes(value)
                try:
                    native_inputs(native / 'network_host.so', source / 'network_host.hepta',
                                  profile or args.build_profile, {})
                except RuntimeError as error:
                    if reason not in str(error):
                        raise AssertionError(f'{label} rejected for the wrong reason: {error}') from error
                    report['controls'].append({'case': label, 'accepted': False, 'error': str(error)})
                else:
                    raise AssertionError(f'{label} admitted a mismatched complete build')
            finally:
                for path, value in originals.items():
                    path.write_bytes(value)

        for profile in FULL_MODULE_PROFILES:
            if profile != args.build_profile:
                reject('wrong-profile-' + profile, profile=profile, reason='lock/compiler/module contract')
        reject('unknown-profile', profile='full-native-unreviewed', reason='unknown native build profile')
        build_path, lock_path = native / 'build.json', source / 'toolchain.json'
        build = json.loads(build_path.read_bytes())
        lock = json.loads(lock_path.read_bytes())

        def catalog(label, names):
            changed_lock = copy.deepcopy(lock)
            changed_lock['modules'] = names
            changed = copy.deepcopy(build)
            changed['toolchain'] = changed_lock
            changed['toolchain_lock_sha256'] = hashlib.sha256(encode(changed_lock)).hexdigest()
            changed['modules'] = {name: build['modules'].get(name, build['modules']['network_host'])
                                  for name in names}
            reject(label, {lock_path: encode(changed_lock), build_path: encode(changed)},
                   reason='lock/compiler/module contract')

        catalog('missing-last-module', modules[:-1])
        catalog('missing-original-module', modules[1:])
        catalog('duplicate-module', [*modules, modules[-1]])
        catalog('reordered-modules', [modules[1], modules[0], *modules[2:]])
        catalog('unreviewed-extra-module', [*modules, 'unreviewed'])
        catalog('substituted-module', [*modules[:-1], 'unreviewed'])
        for name in ('network_host', modules[-1]):
            changed = copy.deepcopy(build)
            del changed['modules'][name]
            reject('missing-built-' + name, {build_path: encode(changed)},
                   reason='lock/compiler/module contract')
        changed = copy.deepcopy(build)
        changed['modules']['unreviewed'] = build['modules']['network_host']
        reject('extra-built-module', {build_path: encode(changed)}, reason='lock/compiler/module contract')
        for key, value in [('schema', 'unreviewed'), ('status', 'failed'), ('build_mode', 'seed-only'),
                           ('compiler_fixed_point', False), ('compiler_sha256', '0' * 64)]:
            changed = copy.deepcopy(build)
            changed[key] = value
            reason = 'rejects incremental or unknown schemas' if key == 'schema' else 'lock/compiler/module contract'
            reject('wrong-build-' + key, {build_path: encode(changed)}, reason=reason)
        for key, value in [('revision', '0' * 40), ('target', 'aarch64-unknown-linux-gnu'),
                           ('entry_profiles', {})]:
            changed_lock, changed = copy.deepcopy(lock), copy.deepcopy(build)
            changed_lock[key] = value
            changed['toolchain'] = changed_lock
            changed['toolchain_lock_sha256'] = hashlib.sha256(encode(changed_lock)).hexdigest()
            reject('wrong-toolchain-' + key, {lock_path: encode(changed_lock), build_path: encode(changed)},
                   reason='lock/compiler/module contract')
        for name in ('B1', 'B2', 'B3'):
            path = native / 'bootstrap' / f'{name}.image.bin'
            reject('changed-' + name, {path: path.read_bytes() + b'\0'}, reason='native input identity mismatch')
        for name in ('build.py', 'cargo_build.rs'):
            path = source / name
            reject('changed-' + name, {path: path.read_bytes() + b'\n'}, reason='native input identity mismatch')
        for name in ['network_host', *modules[38:]]:
            paths = [source / f'{name}.hepta', native / f'{name}.o', native / f'{name}.input.bin',
                     native / f'{name}.so', native / f'{name}.namespaced.o',
                     native / f'libcodex_hia_{name}.a', native / f'libcodex_hia_{name}.so']
            for path in paths:
                reject('changed-' + path.name, {path: path.read_bytes() + b'\0'},
                       reason='native input identity mismatch')
            path = native / f'{name}.link'
            reject('changed-' + path.name, {path: path.read_bytes() + b'\n'},
                   reason='actual static-link receipt mismatch')
        native_inputs(native / 'network_host.so', source / 'network_host.hepta', args.build_profile, {})
        report['controls'].append({'case': 'restored-private-copy', 'accepted': True})
    report['inputs_unchanged'] = recheck_inputs(admitted)
    if not report['inputs_unchanged']:
        raise RuntimeError('original source or artifact changed during isolated controls')
    report['rejected_controls'] = sum(not row['accepted'] for row in report['controls'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=list(FULL_MODULE_PROFILES), required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('report must be new; preserve earlier evidence')
    report = {'schema': 'codex.hia.native-build-profile-controls.v1', 'passed': False,
              'requested_profile': args.build_profile, 'native_code_executed': False,
              'scope': 'Complete source/compiler/object/link admission and isolated refusal controls; ABI execution is separate.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        verify(args, report)
        report['passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        args.report.write_bytes(encode(report))
    print(json.dumps({'passed': True, 'rejected_controls': report['rejected_controls'],
                      'module_count': report['admitted']['native_build']['module_count']}))


if __name__ == '__main__':
    main()
