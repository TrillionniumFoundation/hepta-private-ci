"""Seal the completed research checkout without modifying scientific evidence."""

import json
from pathlib import Path
import sys

ROOT = Path('/dev/shm/hepta-round6-d831a963ef2f/hepta-analytic')
OUTPUT = Path('/dev/shm/hepta-round6-d831a963ef2f/final_bundle_001')
RECEIPTS = Path('/dev/shm/hepta-round6-d831a963ef2f/final_packaging_001')
sys.path.insert(0, str(ROOT))

from experiments.analytic_event_neuron.round6 import artifact_bundle as bundle
from experiments.analytic_event_neuron.round6 import lifecycle

ROUND = ROOT / 'experiments/analytic_event_neuron/round6'
RUN = ROUND / 'evidence/registered_001'
EXPECTED_FREEZE = '1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1'
EXPECTED_RESULTS = '303e98b4c6679f7dd827bb2c3a7083d96010984adbba43e1c6548b7930f53a69'
EXPECTED_AUDIT = 'ef2ef939432eaa457b97def830f8719030e5050afa79457e4c663d33e5f977f2'
EXPECTED_NATIVE = 'b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179'

frozen = lifecycle.verify(RUN, EXPECTED_FREEZE)
assert bundle.sha(RUN / 'RESULTS.json') == EXPECTED_RESULTS
assert bundle.sha(ROUND / 'evidence/review_confirmation_registered_001/REVIEW.json') == EXPECTED_AUDIT
assert bundle.sha(RUN / 'native/analytic_event') == EXPECTED_NATIVE
review = json.loads((ROUND / 'evidence/report_review_001/FINAL_REPORT_REVIEW.json').read_text())
assert review['passed'] is True
assert review['report_sha256'] == bundle.sha(ROUND / 'REPORT.md')
assert review['report_source_sha256'] == bundle.sha(ROUND / 'REPORT_SOURCE.json')

manifest = bundle.pack(ROOT, OUTPUT)
result = {
    'schema': 'hepta.round6.complete-research-package.v1',
    'passed': True,
    'source': str(ROOT),
    'bundle': str(OUTPUT),
    'manifest_sha256': bundle.sha(OUTPUT / 'BUNDLE.json'),
    'packing_script_sha256': bundle.sha(Path(__file__)),
    'artifact_bundle_helper_sha256': bundle.sha(Path(bundle.__file__)),
    'archive': manifest['archive'],
    'parts': len(manifest['parts']),
    'files': sum(m['kind'] == 'file' for m in manifest['members']),
    'directories': sum(m['kind'] == 'dir' for m in manifest['members']),
    'uncompressed_file_bytes': sum(m['bytes'] for m in manifest['members']),
    'frozen_scientific_source_files': len(frozen['sources_sha256']),
    'freeze_sha256': EXPECTED_FREEZE,
    'results_sha256': EXPECTED_RESULTS,
    'confirmation_review_sha256': EXPECTED_AUDIT,
    'native_sha256': EXPECTED_NATIVE,
    'report_sha256': review['report_sha256'],
    'report_source_sha256': review['report_source_sha256'],
    'source_snapshot_unchanged_during_packing': True,
    'scope': 'Complete Round6 research checkout and evidence, not the full historical Git repository.',
    'joint_research_gate_pass': False,
    'production_promotion': False,
}
assert lifecycle.verify(RUN, EXPECTED_FREEZE) == frozen
assert bundle.sha(RUN / 'RESULTS.json') == EXPECTED_RESULTS
with (RECEIPTS / 'PACKING_RESULT.json').open('x') as out:
    json.dump(result, out, indent=2, sort_keys=True)
    out.write('\n')
print(json.dumps(result), flush=True)
