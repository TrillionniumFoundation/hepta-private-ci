"""Build an offline adapter against three byte-identical upstream Rust crates.

Only the generated minimal workspace and the research adapter belong to this
experiment. Original upstream crate files are never formatted or rewritten.
This is not a full Hepta checkout build, target-host run, or owner execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import tomllib

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / 'upstream_snapshot/codex-rs'
ADAPTER = WORKSPACE / 'rrsnn-adapter'
UPSTREAM_SHA = 'f8c9419df6ddeb36ff8b522a50219981fb8d9345'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_sources():
    manifest = json.loads((ROOT / 'upstream_source_manifest.json').read_text())
    for row in manifest['files']:
        data = (ROOT / 'upstream_snapshot' / row['path']).read_bytes()
        assert len(data) == row['bytes'], row['path']
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == row['git_blob_sha'], row['path']
        assert hashlib.sha256(data).hexdigest() == row['sha256'], row['path']
    return len(manifest['files'])


def prepare():
    original = (ROOT / 'repo_evidence/codex-rs__Cargo.toml.upstream.txt').read_text()
    metadata = tomllib.loads(original)['workspace']['package']
    lint_section = original.split('[workspace.lints]', 1)[1].split('[workspace.metadata.cargo-shear]', 1)[0]
    minimal = ('# GENERATED research workspace; not the upstream root Cargo.toml.\n'
               '# The three upstream crate manifests and source trees remain byte-identical.\n'
               '[workspace]\nresolver = "2"\nmembers = ["hepta-types", "hepta-infer-core", "hepta-neuron", "rrsnn-adapter"]\n\n'
               '[workspace.package]\n' + ''.join(f'{k} = {json.dumps(metadata[k])}\n' for k in ['version', 'edition', 'license']) +
               '\n[workspace.dependencies]\nserde = { version = "=1.0.228", features = ["rc"] }\n'
               '# Exact upstream lock version; float_roundtrip is a research input-parser feature.\n'
               'serde_json = { version = "=1.0.149", features = ["float_roundtrip"] }\n'
               'sha2 = "=0.10.9"\npretty_assertions = "=1.4.1"\n\n[workspace.lints]' + lint_section +
               '\n[profile.release]\ncodegen-units = 4\n')
    cargo = WORKSPACE / 'Cargo.toml'
    if cargo.exists():
        assert cargo.read_text() == minimal, 'generated workspace changed unexpectedly'
    else:
        cargo.write_text(minimal)
    fixture_path = ROOT / 'rust_bridge/fixtures/exact_replay_fixture.json'
    fixture = json.loads(fixture_path.read_text())
    fixture_request = {
        'schema': 'rrsnn.hepta-shadow-feature-request.v1',
        'tickId': 'tick:rrsnn-offline-replay-1', 'subjectId': 'subject:synthetic-exact-fixture',
        'logicalSequence': 1, 'monotonicTimeMicros': 1_000_000,
        'checkpointDigest': '0' * 64,
        'objectiveDigest': hashlib.sha256(b'rrsnn.offline-fixture.objective:checkpoint-transport').hexdigest(),
        'nduSnapshotDigest': hashlib.sha256(b'rrsnn.offline-fixture.ndu:not-a-real-owner').hexdigest(),
        'bodyGeneration': None, 'modulatorDigest': None,
        'features': fixture['checkpoint_at_split']['evidence'],
        'sourceArtifactSha256': digest(fixture_path), 'sourceKind': 'synthetic_execution_state',
    }
    fixture_dir = ADAPTER / 'fixtures'
    fixture_dir.mkdir(exist_ok=True)
    (fixture_dir / 'feature_request.json').write_text(json.dumps(fixture_request, indent=2) + '\n')
    return fixture_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    source_count = verify_sources()
    request = prepare()
    environment = dict(os.environ)
    environment['PATH'] = str(ROOT / 'toolchain/bin') + os.pathsep + environment['PATH']
    environment['CARGO_HOME'] = str(ROOT / 'cargo_cache')
    environment['CARGO_TARGET_DIR'] = str(ROOT / 'upstream_snapshot/target')
    environment['CARGO_BUILD_JOBS'] = '1'
    if hasattr(os, 'sched_setaffinity') and 6 in os.sched_getaffinity(0):
        os.sched_setaffinity(0, {6})
    steps = []

    def run(command):
        begun = time.perf_counter()
        result = subprocess.run(command, cwd=WORKSPACE, env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        steps.append({'command': command, 'returncode': result.returncode,
                      'wall_seconds': time.perf_counter() - begun, 'output': result.stdout})
        print(json.dumps({'command': command, 'returncode': result.returncode,
                          'output_tail': result.stdout[-4500:]}), flush=True)
        if result.returncode:
            raise RuntimeError('Build/validation step failed')
        return result.stdout

    try:
        if args.fetch:
            lock = WORKSPACE / 'Cargo.lock'
            if not lock.exists():
                shutil.copyfile(ROOT / 'repo_evidence/codex-rs__Cargo.lock.upstream.txt', lock)
            run(['cargo', 'fetch'])
            run(['cargo', 'vendor', '--locked', '--offline', '--versioned-dirs', 'vendor'])
            config = WORKSPACE / '.cargo/config.toml'
            config.parent.mkdir(exist_ok=True)
            config.write_text('[source.crates-io]\nreplace-with = "vendored-sources"\n'
                              '[source.vendored-sources]\ndirectory = "vendor"\n[net]\noffline = true\n')
        run(['cargo', 'fmt', '-p', 'rrsnn-hepta-type-adapter'])
        verify_sources()
        test_output = run(['cargo', 'test', '--locked', '--offline', '-p', 'rrsnn-hepta-type-adapter'])
        assert '5 passed; 0 failed' in test_output
        run(['cargo', 'build', '--locked', '--offline', '--release', '-p', 'rrsnn-hepta-type-adapter'])
        binary = ROOT / 'bin/rrsnn-hepta-type-adapter'
        binary.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'upstream_snapshot/target/release/rrsnn-hepta-type-adapter', binary)
        binary.chmod(0o755)
        output = ROOT / 'replay_results/official_typed_shadow.json'
        output.parent.mkdir(exist_ok=True)
        run([str(binary), str(ADAPTER / 'fixtures/feature_request.json'), str(output)])
        shadow = json.loads(output.read_text())
        features = shadow['featureVectorQ24']
        expected_features = [round(v * (1 << 24)) for v in request['features']]
        assert features == expected_features
        feature_bytes = b'hepta.neuron.input-features.q24.v1' + struct.pack('>Q', len(features))
        feature_bytes += b''.join(struct.pack('>q', v) for v in features)
        feature_digest = hashlib.sha256(feature_bytes).hexdigest()
        official_input = shadow['officialInput']
        assert official_input['inputFeatureDigest'] == feature_digest
        ids = b''.join(struct.pack('>I', len(request[k].encode())) + request[k].encode()
                       for k in ['tickId', 'subjectId'])
        tick_bytes = b'hepta.neuron.tick-input.v1' + ids
        tick_bytes += struct.pack('>QQ', request['logicalSequence'], request['monotonicTimeMicros'])
        for value in [request['checkpointDigest'], feature_digest, request['objectiveDigest'], request['nduSnapshotDigest']]:
            tick_bytes += bytes.fromhex(value)
        tick_bytes += b'\0\0'
        tick_bytes += b''.join(struct.pack('>q', v) for v in features)
        assert hashlib.sha256(tick_bytes).hexdigest() == shadow['officialInputSemanticDigest']
        assert shadow['officialRuntimeReceipt'] is None and not shadow['officialOwnerExecuted']
        actual_lock = tomllib.loads((WORKSPACE / 'Cargo.lock').read_text())
        upstream_lock = tomllib.loads((ROOT / 'repo_evidence/codex-rs__Cargo.lock.upstream.txt').read_text())
        upstream_packages = {(p['name'], p['version']): p.get('checksum') for p in upstream_lock['package']}
        external_packages = [p for p in actual_lock['package'] if p.get('source', '').startswith('registry+')]
        for p in external_packages:
            assert upstream_packages[(p['name'], p['version'])] == p['checksum'], p['name']
        report = {
            'schema': 'rrsnn.upstream-types-build-and-contract.v1', 'all_passed': True,
            'scope': 'Unmodified library targets of three upstream crates compiled as dependencies in a reduced research workspace; not every upstream target, the full monorepo, or a production host.',
            'upstream_commit': UPSTREAM_SHA, 'upstream_files_byte_identical': verify_sources(),
            'upstream_crates_compiled': ['codex-hepta-types', 'codex-hepta-infer-core', 'codex-hepta-neuron'],
            'research_tests_passed': 5, 'upstream_unit_tests_not_run': True,
            'official_owner_executed': False, 'official_runtime_receipt': None,
            'full_upstream_workspace_compiled': False, 'production_activation_allowed': False,
            'binary_sha256': digest(binary), 'binary_bytes': binary.stat().st_size,
            'lock_sha256': digest(WORKSPACE / 'Cargo.lock'),
            'source_manifest_sha256': digest(ROOT / 'upstream_source_manifest.json'),
            'workspace_manifest_sha256': digest(WORKSPACE / 'Cargo.toml'),
            'research_serde_json_feature': 'float_roundtrip',
            'all_external_versions_and_checksums_in_upstream_lock': True,
            'external_packages': [{'name': p['name'], 'version': p['version'], 'checksum': p['checksum']} for p in external_packages],
            'independent_python_feature_and_tick_digests_match': True,
            'official_input_feature_count': len(features),
            'maximum_absolute_quantization_error': shadow['maximumAbsoluteQuantizationError'],
            'fixture_sha256': request['sourceArtifactSha256'],
            'steps': steps,
        }
    except Exception as error:
        report = {'schema': 'rrsnn.upstream-types-build-and-contract.v1', 'all_passed': False,
                  'upstream_files_verified_before_build': source_count,
                  'error': repr(error), 'steps': steps}
        raise
    finally:
        (ROOT / 'upstream_adapter_validation.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
