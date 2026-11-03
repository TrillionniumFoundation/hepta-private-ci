"""One offline entry point: build, spike replay, official codec, joint ledger resume.

Requires the adjacent frozen rrsnn_experiments runtime and rrsnn_v2 audit engine.
Default uses the delivered Linux x86_64 binaries and their recorded hashes.
--build rebuilds both Rust targets solely from vendored locked dependencies.
It does not download dependencies, use a production host, or issue an owner call.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--checkpoint', type=Path,
                        help='Optional completed v2 model.pt for the joint CTMC checkpoint check.')
    parser.add_argument('--joint-output-name', default=None)
    args = parser.parse_args()
    if hasattr(os, 'sched_setaffinity') and 6 in os.sched_getaffinity(0):
        os.sched_setaffinity(0, {6})
    environment = dict(os.environ)
    environment['OMP_NUM_THREADS'] = '1'
    environment['OPENBLAS_NUM_THREADS'] = '1'
    environment['MKL_NUM_THREADS'] = '1'
    steps = []

    def run(command):
        start = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT.parents[1], env=environment,
                                capture_output=True, text=True)
        steps.append({'command': command, 'exit_code': result.returncode,
                      'wall_seconds': time.perf_counter() - start,
                      'stdout': result.stdout, 'stderr': result.stderr})
        print(json.dumps({'command': command, 'exit_code': result.returncode}), flush=True)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:] or result.stdout[-2000:])

    try:
        if args.build:
            run([sys.executable, str(ROOT / 'build_rust_bridge.py')])
            run([sys.executable, str(ROOT / 'build_upstream_adapter.py')])
        from build_upstream_adapter import verify_sources
        source_count = verify_sources()
        binaries = {}
        for filename, report_name in [
            ('rrsnn-offline-replay-bridge', 'rust_build_report.json'),
            ('rrsnn-hepta-type-adapter', 'upstream_adapter_validation.json'),
        ]:
            report = json.loads((ROOT / report_name).read_text())
            assert report['all_passed']
            actual = sha(ROOT / 'bin' / filename)
            assert actual == report['binary_sha256'], filename
            binaries[filename] = actual
        run([sys.executable, str(ROOT / 'validate_rust_bridge.py'), '--use-prebuilt'])
        request = ROOT / 'upstream_snapshot/codex-rs/rrsnn-adapter/fixtures/feature_request.json'
        produced = ROOT / 'replay_results/official_typed_shadow_replayed.json'
        run([str(ROOT / 'bin/rrsnn-hepta-type-adapter'), str(request), str(produced)])
        expected = json.loads((ROOT / 'replay_results/official_typed_shadow.json').read_text())
        assert json.loads(produced.read_text()) == expected
        replay = json.loads((ROOT / 'rust_replay_validation.json').read_text())
        assert replay['all_passed']
        label = args.joint_output_name or ('trained_parameters' if args.checkpoint else 'fixed_weights')
        joint_command = [sys.executable, str(ROOT / 'validate_joint_checkpoint.py'), '--output-name', label]
        if args.checkpoint:
            joint_command += ['--checkpoint', str(args.checkpoint.resolve())]
        run(joint_command)
        joint = json.loads((ROOT / 'joint_replay_results' / label / 'validation.json').read_text())
        assert joint['all_passed']
        proposal_path = None
        if args.checkpoint:
            proposal_path = ROOT / 'joint_replay_results' / label / 'review_only_shadow_proposal.json'
            run([sys.executable, str(ROOT / 'build_trained_shadow.py'), '--joint-result',
                 str(ROOT / 'joint_replay_results' / label / 'validation.json')])
            assert json.loads(proposal_path.read_text())['all_passed']
        result = {
            'schema': 'rrsnn.complete-offline-replay.v1', 'all_passed': True,
            'build_requested': args.build, 'upstream_files_byte_identical': source_count,
            'binary_sha256': binaries, 'spike_replay_checks': replay['checks'],
            'official_type_projection_reproduced': True,
            'joint_ctmc_resource_checkpoints_passed': len(joint['checks']),
            'joint_ctmc_negative_cases_passed': len(joint['negative_cases']),
            'joint_model_artifact_sha256': joint['model_artifact_sha256'],
            'joint_model_origin': joint['model_origin'],
            'trained_typed_shadow_proposal': None if proposal_path is None else str(proposal_path.relative_to(ROOT)),
            'trained_typed_shadow_proposal_sha256': None if proposal_path is None else sha(proposal_path),
            'official_owner_executed': False, 'target_host_accessed': False,
            'production_activation_allowed': False,
            'fixture_scope': 'Actually sampled synthetic engine path; not a live Hepta Cell trace.',
            'steps': steps,
        }
    except Exception as error:
        result = {'schema': 'rrsnn.complete-offline-replay.v1', 'all_passed': False,
                  'error': repr(error), 'steps': steps}
        raise
    finally:
        (ROOT / 'complete_offline_replay.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'steps'}, indent=2))


if __name__ == '__main__':
    main()
