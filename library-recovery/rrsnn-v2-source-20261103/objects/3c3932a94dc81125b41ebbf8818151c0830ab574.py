"""Project an actual trained-policy validation latent through official Hepta types.

Consumes an already passed joint restore fixture, never a performance holdout.
Output is a review-only prospective input with no owner execution or activation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--joint-result', type=Path, required=True)
    args = parser.parse_args()
    if hasattr(os, 'sched_setaffinity') and 6 in os.sched_getaffinity(0):
        os.sched_setaffinity(0, {6})
    validation_path = args.joint_result.resolve()
    validation = json.loads(validation_path.read_text())
    assert validation['all_passed'] and validation['model_origin'] == 'completed_parameter_artifact'
    artifact = Path(validation['model_artifact'])
    assert sha(artifact) == validation['model_artifact_sha256']
    training_path = artifact.parent/'training.json'
    training = json.loads(training_path.read_text())
    assert training['checkpoint_sha256'] == sha(artifact)
    for path, expected in training['source_hashes'].items():
        assert sha(ROOT.parent/path) == expected, path
    chosen = next(row for row in validation['checks'] if row['case'] == 'A')
    fixture_path = ROOT/chosen['fixture_file']
    assert sha(fixture_path) == chosen['fixture_sha256']
    fixture = json.loads(fixture_path.read_text())
    final = fixture['expected_final']
    observation = final['payload']['committed_events'][-1]
    features = observation['latent']
    assert len(features) == validation['operator_profile']['hidden_size'] == 8
    destination = validation_path.parent
    frame = {
        'schema': 'rrsnn.trained-latent-observation.v1',
        'model_artifact_sha256': sha(artifact),
        'model_weights_sha256': validation['model_weights_sha256'],
        'training_receipt_sha256': sha(training_path),
        'model_run_name': training['run_name'], 'model_seed': training['seed'],
        'model_source_hashes': training['source_hashes'],
        'joint_validation_sha256': sha(validation_path),
        'joint_fixture_sha256': sha(fixture_path),
        'execution_checkpoint_payload_sha256': final['payload_sha256'],
        'feature_definition': 'tanh of actually sampled finite-CTMC evidence at a committed observation; eight hidden components',
        'feature_values_float32': features,
        'scenario': final['payload']['scenario'], 'clock_model_units': observation['time'],
        'event_index': observation['event_index'],
        'data_scope': 'User A-style deadline pattern with fixed synthetic values; correctness fixture only, not a holdout performance comparison.',
        'official_owner_executed': False, 'real_future_window': False,
    }
    frame_path = destination/'trained_latent_features.json'
    frame_path.write_text(json.dumps(frame, indent=2, allow_nan=False)+'\n')
    request = {
        'schema': 'rrsnn.hepta-shadow-feature-request.v1',
        'tickId': 'tick:rrsnn-trained-sampled-seed101-A',
        'subjectId': 'subject:synthetic-trained-validation-A',
        'logicalSequence': 1,
        'monotonicTimeMicros': int(observation['time']*1_000_000),
        'checkpointDigest': '0'*64,
        'objectiveDigest': hashlib.sha256(b'rrsnn.review-only.trained-feature-projection').hexdigest(),
        'nduSnapshotDigest': hashlib.sha256(b'rrsnn.offline-fixture.ndu:not-a-real-owner').hexdigest(),
        'bodyGeneration': None, 'modulatorDigest': None,
        'features': features, 'sourceArtifactSha256': sha(frame_path),
        'sourceKind': 'trained_model_latent_observation',
    }
    request_path = destination/'trained_shadow_request.json'
    request_path.write_text(json.dumps(request, indent=2, allow_nan=False)+'\n')
    binary = ROOT/'bin/rrsnn-hepta-type-adapter'
    adapter_build = json.loads((ROOT/'upstream_adapter_validation.json').read_text())
    assert adapter_build['all_passed'] and sha(binary) == adapter_build['binary_sha256']
    adapted_path = destination/'trained_typed_shadow_input.json'
    command = [str(binary), str(request_path), str(adapted_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    adapted = json.loads(adapted_path.read_text())
    assert adapted['featureVectorQ24'] == [round(value*(1 << 24)) for value in features]
    assert adapted['sourceArtifactSha256'] == sha(frame_path)
    assert adapted['maximumAbsoluteQuantizationError'] <= .5/(1 << 24)
    assert adapted['officialRuntimeReceipt'] is None and not adapted['officialOwnerExecuted']
    proposal = {
        'schema': 'rrsnn.review-only-trained-hepta-shadow-proposal.v1',
        'all_passed': True, 'candidate': training['run_name'], 'seed': training['seed'],
        'upstream_commit': adapted['upstreamCommit'],
        'model_artifact_sha256': sha(artifact),
        'model_weights_sha256': validation['model_weights_sha256'],
        'training_receipt_sha256': sha(training_path),
        'source_latent_artifact': str(frame_path.relative_to(ROOT)),
        'source_latent_sha256': sha(frame_path),
        'joint_validation_sha256': sha(validation_path),
        'official_type_adapter_binary_sha256': sha(binary),
        'actual_hidden_feature_count': len(features),
        'maximum_absolute_q24_error': adapted['maximumAbsoluteQuantizationError'],
        'typed_shadow': adapted,
        'official_owner_executed': False, 'official_owner_receipt': None,
        'activation_approved': False, 'production_activation_allowed': False,
        'real_future_window': False, 'holdout_performance_opened': False,
        'semantic_limits': [
            'Actual trained weights and sampled latent are used, on a synthetic correctness scenario.',
            'This is a prospective initial V1 input. Zero predecessor does not name a committed production checkpoint.',
            'The source latent artifact binds the trained model, real sampled execution state and fixed scenario; it is not an authenticated owner receipt.',
            'The artificial time-to-microseconds mapping is not a latency measurement.',
            'The true RR dynamics and joint state have not replaced Hepta NeuronRuntime V1 sparse dynamics.',
        ],
        'command': command, 'command_stdout': result.stdout,
    }
    proposal_path = destination/'review_only_shadow_proposal.json'
    proposal_path.write_text(json.dumps(proposal, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'all_passed': True, 'model_artifact_sha256': sha(artifact),
                      'features': features, 'q24': adapted['featureVectorQ24'],
                      'maximum_absolute_q24_error': proposal['maximum_absolute_q24_error'],
                      'proposal_file': str(proposal_path)}, indent=2))


if __name__ == '__main__':
    main()
