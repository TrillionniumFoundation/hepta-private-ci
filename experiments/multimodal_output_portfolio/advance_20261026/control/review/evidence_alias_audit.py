"""Metadata proof of an observation-support mismatch; no source/model execution."""

import hashlib
import json
import math
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
CONTROL = HERE.parent
ADVANCE = CONTROL.parent


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    allocation_path = ADVANCE / 'SOURCE_ALLOCATION.json'
    likelihood_path = CONTROL / 'AUDIO_LIKELIHOOD.json'
    if sha(allocation_path) != '42d0c47056dda930cb851c9ae59f330747de8bb863f18b79c47eea830f69b262':
        raise ValueError('Original source allocation changed')
    if sha(likelihood_path) != '1fff72a9ad1470b1ead327a82811642f0b14c45ca61f454b2f60292e246d5946':
        raise ValueError('Original frozen likelihood changed')
    allocation, likelihood = json.loads(allocation_path.read_text()), json.loads(likelihood_path.read_text())
    census = {}
    for name in ('qualification_id', 'confirmation'):
        role = allocation['roles'][name]; rows = role['audio_rows_by_source_digit']
        duplicate_pairs, equal_pairs, affected = [], [], set()
        for pair in range(role['pair_count']):
            left, right = rows[2 * pair:2 * pair + 2]
            if left['label'] == right['label']:
                equal_pairs.append(pair)
            if left['sha256'] == right['sha256']:
                if left['path'] != right['path'] or left['label'] != right['label']:
                    raise ValueError('Unexpected identity or label conflict')
                duplicate_pairs.append(pair); affected.add(role['pair_writer_ids'][pair])
        if duplicate_pairs != equal_pairs:
            raise ValueError('The expected exact equal-digit evidence-alias mechanism differs')
        census[name] = {'pairs': role['pair_count'], 'same_WAV_pairs': len(duplicate_pairs),
                       'equal_digit_pairs': len(equal_pairs), 'affected_writer_clusters': len(affected),
                       'fraction': len(duplicate_pairs) / role['pair_count'],
                       'all_equal_digit_pairs_reuse_identical_WAV': True}
    digit = likelihood['digit_observation_by_target']
    pair = likelihood['pair_observation_by_target']
    masses = []
    for target in range(10):
        theoretical = 1 - math.fsum(digit[observed][target] ** 2 for observed in range(10))
        actual = math.fsum(pair[left * 10 + right][11 * target]
                          for left in range(10) for right in range(10) if left != right)
        if not math.isclose(actual, theoretical, rel_tol=0., abs_tol=1e-12) or actual <= 0:
            raise ValueError('The frozen pair table no longer has the stated unsupported mass')
        masses.append({'true_equal_digit': target, 'target_code': 11 * target,
            'kron_off_diagonal_probability': actual, 'formula_one_minus_sum_squared_digit_likelihood': theoretical,
            'actual_allowed_off_diagonal_probability_for_identical_waveform': 0.})
    dependencies = [allocation_path, likelihood_path, CONTROL / 'audio_likelihood.py',
                    ADVANCE / 'cases.py', ADVANCE / 'native/host.py',
                    ADVANCE.parent / 'next_20261025/media/audio_sources.py',
                    ADVANCE.parent / 'next_20261025/media/repair/model.py']
    result = {'schema': 'hepta.advance.evidence-alias-support-audit.v1',
        'status': 'known_observation_support_misspecification', 'recorded_ns': time.time_ns(),
        'source_and_frozen_model_sha256': {str(path.resolve()): sha(path) for path in dependencies},
        'source_census': census, 'per_digit_unsupported_probability': masses,
        'identity_argument': 'Two identical SHA-bound WAVs pass through the same deterministic normalization, frozen eval-mode CNN and argmax. Their observed labels are equal. Thus P(left_observation != right_observation | equal target and the registered identical-WAV mechanism)=0, regardless of unknown per-digit error rates.',
        'frozen_model_argument': 'The registered pair law is kron(L,L). For target(t,t), its off-diagonal mass equals 1-sum_o L(o|t)^2 and is strictly positive in every frozen target-diagonal column.',
        'scientific_conclusion': 'Conditional independence is known to fail for this source subset. The frozen joint observation law does not have the correct support; this is stronger than an unverified same-speaker correlation assumption.',
        'causal_attribution': 'No attribution of the dynamic selected-action ECE failure or any primary outcome to this discrepancy is established by this metadata audit.',
        'candidate_or_protocol_modified': False, 'new_model_or_waveform_observations_opened': False,
        'scope': 'Only immutable metadata and the already frozen likelihood were read. Original qualification, confirmation and failed results remain intact. Any corrected alias-conditioned or joint observation model requires a separately registered candidate and independent qualification.',
        'audit_source_sha256': sha(__file__)}
    with (HERE / 'EVIDENCE_ALIAS_AUDIT.json').open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'census': census, 'per_digit_off_diagonal_mass': [row['kron_off_diagonal_probability'] for row in masses],
        'sha256': sha(HERE / 'EVIDENCE_ALIAS_AUDIT.json')}))


if __name__ == '__main__':
    main()
