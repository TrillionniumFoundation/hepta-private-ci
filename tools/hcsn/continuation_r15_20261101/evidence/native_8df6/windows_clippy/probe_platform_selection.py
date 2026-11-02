"""Exercise real Bazel platform filtering in a tiny synthetic rule graph.

This does not build Rust, test Windows, or change a repository target constraint.
The failing compatible action checks that compatibility filtering cannot turn a
real action failure into success. All target labels remain explicitly requested.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


FILES = {
    'MODULE.bazel': 'module(name = "hcsn_platform_selection_probe")\n',
    'probe.bzl': '''def _ok(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".txt")
    ctx.actions.write(output, ctx.label.name + " was built")
    return [DefaultInfo(files = depset([output]))]

def _bad(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".txt")
    ctx.actions.run_shell(
        outputs = [output],
        command = "echo INTENTIONAL_COMPATIBLE_ACTION_FAILURE >&2; exit 23",
    )
    return [DefaultInfo(files = depset([output]))]

ok = rule(implementation = _ok)
bad = rule(implementation = _bad)
''',
    'BUILD.bazel': '''load(":probe.bzl", "bad", "ok")
constraint_setting(name = "abi")
constraint_value(name = "msvc", constraint_setting = ":abi")
constraint_value(name = "gnullvm", constraint_setting = ":abi")
constraint_value(name = "unix", constraint_setting = ":abi")
platform(name = "msvc_platform", constraint_values = [":msvc"])
platform(name = "gnullvm_platform", constraint_values = [":gnullvm"])
platform(name = "unix_platform", constraint_values = [":unix"])
ok(name = "common_ok", tags = ["manual"])
ok(name = "cross_only", tags = ["manual"], target_compatible_with = [":gnullvm"])
ok(name = "unix_only", tags = ["manual"], target_compatible_with = [":unix"])
bad(name = "compatible_failure", tags = ["manual"], target_compatible_with = [":msvc"])
''',
}


def main(bazel, output, cache, java_trust_store):
    if output.exists():
        raise FileExistsError(output)
    receipt = {'schema': 'hcsn.bazel-platform-selection-probe.v1',
               'started_at_utc': datetime.now(timezone.utc).isoformat(),
               'bazel_sha256': hashlib.sha256(bazel.read_bytes()).hexdigest(),
               'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'scope': 'Real Bazel 9 compatibility/action behavior on a synthetic Linux-hosted graph; no repository, Windows or Rust build.',
               'java_trust_store': str(java_trust_store) if java_trust_store else None,
               'java_trust_store_sha256': hashlib.sha256(java_trust_store.read_bytes()).hexdigest() if java_trust_store else None,
               'fixture_sources': FILES, 'cases': [], 'passed': False}
    try:
        with tempfile.TemporaryDirectory(prefix='hcsn-platform-selection-') as directory:
            root = Path(directory)
            for name, content in FILES.items():
                (root/name).write_text(content)
            startup = [str(bazel), '--batch', '--ignore_all_rc_files',
                    '--output_user_root='+str(cache), '--host_jvm_args=-Xmx256m',
                    '--host_jvm_args=-XX:ActiveProcessorCount=2']
            if java_trust_store:
                startup.append('--host_jvm_args=-Djavax.net.ssl.trustStore='+str(java_trust_store))
            base = startup+['build', '--keep_going', '--lockfile_mode=off',
                    '--host_platform=//:unix_platform', '--jobs=1', '--spawn_strategy=local']
            common_targets = ['//:common_ok', '//:cross_only', '//:unix_only']
            cases = [
                ('explicit incompatibility is a baseline failure', 'msvc', False, common_targets, False, 'is incompatible and cannot be built'),
                ('declared incompatible targets filtered; native common target builds', 'msvc', True, common_targets, True, 'Build completed successfully'),
                ('compatible action failure remains a failure', 'msvc', True, common_targets+['//:compatible_failure'], False, 'INTENTIONAL_COMPATIBLE_ACTION_FAILURE'),
                ('Unix qualification remains buildable on its own platform', 'unix', True, common_targets, True, 'Build completed successfully'),
                ('cross target remains buildable on its own platform', 'gnullvm', True, common_targets, True, 'Build completed successfully'),
            ]
            for name, platform, skip, targets, success, diagnostic in cases:
                command = base+['--platforms=//:'+platform+'_platform']
                if skip:
                    command.append('--skip_incompatible_explicit_targets')
                command += ['--', *targets]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=90)
                text = result.stdout+result.stderr
                passed = (result.returncode == 0) == success and diagnostic in text
                if success:
                    expected = ['common_ok', {'msvc': None, 'unix': 'unix_only', 'gnullvm': 'cross_only'}[platform]]
                    for target in filter(None, expected):
                        passed = passed and (root/'bazel-bin'/f'{target}.txt').read_text() == target+' was built'
                receipt['cases'].append({'name': name, 'command': command, 'targets': targets,
                    'expected_success': success, 'expected_diagnostic': diagnostic,
                    'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
                    'passed': bool(passed)})
                if not passed:
                    raise AssertionError('Probe case did not reach the intended semantic outcome: '+name)
        receipt['passed'] = True
    finally:
        with output.open('x') as f:
            json.dump(receipt, f, indent=2); f.write('\n')
        print(json.dumps({'passed': receipt['passed'], 'cases': len(receipt['cases']), 'output': str(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bazel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--java-trust-store', type=Path)
    arguments = parser.parse_args()
    main(arguments.bazel, arguments.output, arguments.cache, arguments.java_trust_store)
