"""Refresh evidence-linked closure statuses without running or inventing experiments."""
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT/name).read_text())


def main():
    source = read('upstream_source_manifest.json')
    rust_build = read('rust_build_report.json')
    rust_replay = read('rust_replay_validation.json')
    typed = read('upstream_adapter_validation.json')
    joint = read('joint_replay_results/fixed_weights/validation.json')
    trained = []
    proposals = []
    for path in sorted((ROOT/'joint_replay_results').glob('*/validation.json')):
        value = json.loads(path.read_text())
        if value.get('model_origin') == 'completed_parameter_artifact' and value.get('all_passed'):
            trained.append({'report': str(path.relative_to(ROOT)),
                            'artifact_sha256': value['model_artifact_sha256'],
                            'cases': len(value['checks'])})
            proposal_path = path.parent/'review_only_shadow_proposal.json'
            if proposal_path.exists():
                proposal = json.loads(proposal_path.read_text())
                if proposal['all_passed'] and proposal['model_artifact_sha256'] == value['model_artifact_sha256']:
                    proposals.append({'report': str(proposal_path.relative_to(ROOT)),
                                      'artifact_sha256': proposal['model_artifact_sha256'],
                                      'actual_hidden_feature_count': proposal['actual_hidden_feature_count']})
    entries = [
        {'id': 'R5-SOURCE', 'status': 'closed_offline_research',
         'claim': 'Latest main exact SHA and byte-identical real interface source are verified.',
         'passed': source['all_upstream_files_byte_identical'] and len(source['files']) == 62,
         'evidence': ['repo_evidence/evidence.json', 'upstream_source_manifest.json']},
        {'id': 'R5-RUST-BUILD', 'status': 'closed_offline_research',
         'claim': 'An isolated verified toolchain compiled the bounded checkpoint bridge; dependencies are locked and vendored.',
         'passed': rust_build['all_passed'],
         'evidence': ['rust_toolchain_provenance.json', 'rust_build_report.json', 'rust_bridge/Cargo.lock']},
        {'id': 'R5-PHYSICAL-REPLAY', 'status': 'closed_offline_research',
         'claim': 'Rust transport preserves complete Brownian checkpoint/RNG/known-input state and Python resumes the actual sampled trajectory bitwise.',
         'passed': rust_replay['all_passed'],
         'limits': 'Rust does not simulate Brownian physics; one synthetic two-component trace is used.',
         'evidence': ['rust_replay_validation.json', 'rust_bridge/fixtures/exact_replay_fixture.json']},
        {'id': 'R5-OFFICIAL-TYPES', 'status': 'closed_offline_research',
         'claim': 'Three unchanged upstream library targets actually compile; real input codecs/digests and five research contract tests pass.',
         'passed': typed['all_passed'],
         'limits': 'Reduced research workspace, not all upstream targets, full monorepo tests, owner execution, or production activation.',
         'evidence': ['upstream_adapter_validation.json', 'upstream_source_manifest.json']},
        {'id': 'R5-JOINT-RESTORE', 'status': 'closed_offline_research',
         'claim': 'Committed-boundary CTMC/control/RNG/deadline/resource/action snapshots resume exact continuations; semantic tampering and old ticks are rejected.',
         'passed': joint['all_passed'], 'restores': len(joint['checks']),
         'negative_cases': len(joint['negative_cases']),
         'limits': 'Python single-episode research owner; no mid-event/crash/distributed durability claim.',
         'evidence': ['joint_replay_results/fixed_weights/validation.json', 'joint_checkpoint.py']},
        {'id': 'R5-TRAINED-JOINT-RESTORE',
         'status': 'closed_offline_research' if trained else 'pending_completed_training_artifact',
         'claim': 'Apply the same complete-state recovery check to a completed trained parameter artifact.',
         'passed': bool(trained), 'completed_reports': trained,
         'next_action': 'Run validate_joint_checkpoint.py --checkpoint <completed model.pt> --output-name <run label>; no holdout task metric is required.'},
        {'id': 'R5-TRAINED-TYPED-SHADOW',
         'status': 'closed_offline_research' if proposals else 'pending_completed_training_artifact',
         'claim': 'Actual trained sampled latent features pass through the compiled official input types as a review-only shadow proposal.',
         'passed': bool(proposals), 'completed_reports': proposals,
         'limits': 'Prospective input only, no real owner execution/receipt, no registered stochastic-state replacement, no production activation.'},
        {'id': 'R5-TARGET-HOST', 'status': 'open_external_input',
         'claim': 'A real target host such as dot is authenticated and executable.', 'passed': False,
         'missing': 'No verified target execution endpoint is connected. Local scratch identity and an ssh binary do not establish host access.',
         'evidence': ['execution_environment.json', 'repo_evidence/evidence.json'],
         'next_action': 'Use a specifically provisioned target execution capability; verify host identity, source/model hashes and actual device metadata before recording a target result.'},
        {'id': 'R5-OWNER-RECEIPT', 'status': 'open_external_input',
         'claim': 'The actual inference owner executed the selected model and produced its bound receipt.', 'passed': False,
         'missing': 'No owner runtime or genuine invocation receipt was available; fixture/digest-only substitutes are not execution evidence.',
         'evidence': ['repo_evidence/evidence.json', 'replay_results/official_typed_shadow.json'],
         'next_action': 'Invoke the existing NeuronFeatureDriver/inference.control owner on an authorized host and retain the actual model/runtime/device tuple, measured latency/memory and owner witness.'},
        {'id': 'R5-FUTURE-WINDOW', 'status': 'open_external_input',
         'claim': 'A frozen candidate is evaluated on an independent real future outcome window.', 'passed': False,
         'missing': 'No source-backed real input/outcome window after freeze/selection was received. Synthetic shift and parser fixtures are different evidence.',
         'evidence': ['repo_evidence/evidence.json'],
         'next_action': 'Provide immutable actual event/outcome data with provenance, freeze/cutoff times, observation and label-availability times, an independent window and content hashes.'},
        {'id': 'R5-REAL-CELLS', 'status': 'open_external_input',
         'claim': 'Real 64/256/1024/4096 Cell component workloads have measured utility, negative transfer, RSS, tail latency and throughput.', 'passed': False,
         'missing': 'No actual Cell identity/workload/state replay and target resource measurements are connected. Local copied-state scaling remains a proxy.',
         'evidence': ['execution_environment.json', 'repo_evidence/evidence.json'],
         'next_action': 'Replay genuine owner workloads with the stated Cell unit and all component/model/queue costs on the verified target.'},
        {'id': 'R5-REGISTERED-JOINT-OWNER', 'status': 'open_upstream_implementation',
         'claim': 'A registered stochastic execution/checkpoint profile is integrated with the real journal and independent witness.', 'passed': False,
         'missing': 'The experimental envelope is unregistered and joint CTMC/resource execution is Python; no real-owner journal/CAS/crash protocol is installed.',
         'evidence': ['rust_bridge/src/lib.rs', 'joint_checkpoint.py', 'upstream_adapter_validation.json'],
         'next_action': 'Review a new bounded profile/version and owner adapter in the actual repository, preserve V1 rejection, implement journal/witness and recovery semantics, then run repository-required just fmt/just test and Bazel lock gates for the actual changes.'},
    ]
    if any(e['status'].startswith('closed') and not e['passed'] for e in entries):
        raise AssertionError('A claimed closure has no passing evidence')
    report = {'schema': 'rrsnn.r5-blocker-closure-ledger.v1',
              'generated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'all_production_blockers_closed': False, 'entries': entries,
              'interpretation': 'Offline implementation gaps and external/production evidence gates are distinct; no synthetic dataset, local host or fixture receipt substitutes for missing production evidence.'}
    (ROOT/'closure_ledger.json').write_text(json.dumps(report, indent=2)+'\n')
    artifacts = ['README.txt', 'closure_ledger.json', 'execution_environment.json',
                 'repo_evidence/evidence.json', 'repo_evidence/source_manifest.json',
                 'upstream_source_manifest.json', 'rust_toolchain_provenance.json',
                 'rust_build_report.json', 'rust_replay_validation.json',
                 'upstream_adapter_validation.json', 'complete_offline_replay.json',
                 'bin/rrsnn-offline-replay-bridge', 'bin/rrsnn-hepta-type-adapter',
                 'rust_bridge/Cargo.lock', 'upstream_snapshot/codex-rs/Cargo.lock',
                 'joint_replay_results/fixed_weights/validation.json']
    artifacts += [item['report'] for item in trained]
    artifacts += [item['report'] for item in proposals]
    hashes = []
    for name in artifacts:
        path = ROOT/name
        data = path.read_bytes()
        hashes.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    provenance = {'schema': 'rrsnn.r5-deliverable-provenance.v1',
                  'upstream_main_sha': source['exact_commit'], 'artifacts': hashes,
                  'source_files': 'upstream_source_manifest.json',
                  'external_evidence_files': 'repo_evidence/source_manifest.json',
                  'exclude_from_delivery': ['toolchain/', 'toolchain_downloads/', 'cargo_cache/',
                                            'rust_bridge/target/', 'upstream_snapshot/target/', '**/__pycache__/'],
                  'keep_vendored_dependencies': ['rust_bridge/vendor/', 'upstream_snapshot/codex-rs/vendor/']}
    (ROOT/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
    print(json.dumps({'closed_offline': sum(e['status']=='closed_offline_research' for e in entries),
                      'pending_trained_artifact': not bool(trained),
                      'open_external': sum(e['status']=='open_external_input' for e in entries),
                      'open_upstream_implementation': sum(e['status']=='open_upstream_implementation' for e in entries)}))


if __name__ == '__main__':
    main()
