set -euo pipefail
hepta_final_bundle=/dev/shm/hepta-round6-d831a963ef2f/final_restore_001/input_bundle
hepta_publication=/dev/shm/hepta-round6-d831a963ef2f/final_restore_001/FINAL_PUBLICATION_INPUT.json
hepta_helper=/dev/shm/hepta-round6-d831a963ef2f/hepta-analytic/experiments/analytic_event_neuron/round6/artifact_bundle.py
hepta_transport_python=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python
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

cd "$hepta_final_parent/research"
hepta_python=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python
"$hepta_python" -B -m experiments.analytic_event_neuron.round6.lifecycle verify \
  --run-dir experiments/analytic_event_neuron/round6/evidence/registered_001 \
  --expected-freeze-sha256 1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1
