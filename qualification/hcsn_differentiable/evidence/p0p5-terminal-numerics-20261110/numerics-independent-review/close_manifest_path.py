"""Close the reviewer's filename assumption without rerunning the numerical audit."""
from pathlib import Path
import hashlib
import json
import zipfile

HERE = Path(__file__).parent
BASE = HERE.parent / 'terminal-numerics-final-evidence-v1'


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


review = json.loads((HERE / 'REVIEW.json').read_bytes())
require(review['errors'] == ['original data manifest identity'], 'unexpected original review failure')
require(identity(HERE / 'review.py')['sha256'] == '40c1d288e3f9aa972df305090355daa80b5bbb3c6151bee3b745f8044fcebc76', 'original reviewer source changed')
for path, spec in review['input_identities'].items():
    require(identity(Path(path)) == spec, 'upstream input changed: ' + path)
with zipfile.ZipFile(BASE / 'postmortem/FULL-RESULT.zip') as archive:
    source = json.loads(archive.read('RESULT.json'))
expected_path = '/home/qian-qi/hepta-hcsn-discriminative-20261109-7e8f70f19cba/execution/data/data-manifest.json'
record = source['original_identity_closure']['checks'][expected_path]
expected_sha = '0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb'
require(record == {'expected_sha256': expected_sha, 'observed_sha256': expected_sha, 'matches': True}, 'actual data-manifest record mismatch')
require(review['data_manifest_sha256'] == expected_sha, 'plan/replay data manifest differs')
result = {
    'schema': 'independent-review-manifest-path-closure-v1',
    'status': 'sole_reviewer_filename_assumption_closed',
    'original_review': identity(HERE / 'REVIEW.json'),
    'original_review_source': identity(HERE / 'review.py'),
    'original_full_result_zip': identity(BASE / 'postmortem/FULL-RESULT.zip'),
    'actual_recorded_data_manifest_path': expected_path,
    'actual_recorded_identity': record,
    'explanation': 'The first reviewer required a basename manifest.json. The original recorded file is data-manifest.json; the original plan, source closure and prior independent full-D replay all bind its same SHA. This was a reviewer pathname assumption, not an upstream mismatch.',
    'original_review_exit2_and_cost_preserved': True,
    'all_original_review_input_identities_rechecked_unchanged': True,
    'numerical_or_model_operations': 0,
    'formula_or_stage_reexecution': False,
    'scientific_admission': 'HOLD',
    'whole_training_domain_admission': 'HOLD',
}
with (HERE / 'MANIFEST-PATH-CLOSURE.json').open('x') as stream:
    stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'status': result['status'], 'data_manifest_sha256': expected_sha}))
