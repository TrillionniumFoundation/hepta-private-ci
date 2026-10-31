set -euo pipefail
hepta_final_bundle=/absolute/path/to/downloaded/final_bundle_001
hepta_publication=/absolute/path/to/downloaded/FINAL_PUBLICATION.json
hepta_helper=/absolute/path/to/downloaded/artifact_bundle.py
hepta_transport_python=python
hepta_final_manifest=$(
  "$hepta_transport_python" -B - "$hepta_publication" "$hepta_helper" <<'PYFINAL'
import hashlib, json, re, sys
from pathlib import Path
index = json.loads(Path(sys.argv[1]).read_text())
expected = index['manifest_sha256']
if index['bundle_path'] != 'experiments/analytic_event_neuron/round6/evidence/final_bundle_001':
    raise ValueError('Unexpected final bundle path')
if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
    raise ValueError('Invalid final manifest identity')
if hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest() != '3c98bfe234c1bfba14b72e114f771cd18c06fc900d754be3c59d3145a12cbb66':
    raise ValueError('Bundle helper differs from the reviewed source')
print(expected)
PYFINAL
)
hepta_final_parent=$(mktemp -d -t hepta-round6-final.XXXXXX)
"$hepta_transport_python" -B "$hepta_helper" verify "$hepta_final_bundle" \
  --expected-manifest-sha256 "$hepta_final_manifest"
"$hepta_transport_python" -B "$hepta_helper" restore \
  "$hepta_final_bundle" "$hepta_final_parent/research" \
  --expected-manifest-sha256 "$hepta_final_manifest"
