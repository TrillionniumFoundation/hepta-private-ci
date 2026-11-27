"""Independent synthetic metadata probes; never launches the native audit or a model."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

SOURCE=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve()
sys.path.insert(0,str(SOURCE))
from test_native_envelope_v2 import fixture,raw,identity
from metadata_io import Inputs
import native_envelope as gate


def rewrite(spec, value):
    Path(spec['path']).write_bytes(raw(value));spec['identity']=identity(Path(spec['path']))


def run_case(name, mutation):
    root=OUT/name;root.mkdir()
    spec,external,pins=fixture(root)
    envelope=json.loads(Path(spec['path']).read_bytes())
    receipt_spec=envelope['bootstrap_receipt'];receipt=json.loads(Path(receipt_spec['path']).read_bytes())
    # Chronological positive control: bootstrap starts at8, preflight8..8.25,
    # audit10..11, after-PID scan11.2, bootstrap prefix ends11.3; GNUwhole5.
    receipt['before']['observed_monotonic']=8.
    receipt['after']['observed_monotonic']=11.2
    receipt['whole_bootstrap_wall_prefix_seconds']=3.3
    receipt['own_CPU_prefix_seconds']=.03
    if mutation=='zero_GNU_CPU':
        timefile=Path(envelope['gnu_time']['path'])
        lines=timefile.read_text().splitlines()
        lines=[line.split(':',1)[0]+': 0.00' if line.strip().startswith(('User time (seconds):','System time (seconds):')) else line for line in lines]
        timefile.write_text('\n'.join(lines)+'\n');envelope['gnu_time']['identity']=identity(timefile)
    if mutation=='bootstrap_prefix_beyond_whole':receipt['whole_bootstrap_wall_prefix_seconds']=1960.
    if mutation=='after_PID_scan_beyond_whole':receipt['after']['observed_monotonic']=2000.
    rewrite(receipt_spec,receipt);rewrite(spec,envelope)
    with patch.object(gate,'BOOTSTRAP',pins):
        admitted=gate.verify_native(spec,Inputs(),external)
    return {'case':name,'mutation':mutation,'current_gate_accepted':True,
        'bootstrap_prefix':receipt['whole_bootstrap_wall_prefix_seconds'],'after_PID_monotonic':receipt['after']['observed_monotonic'],
        'result':admitted,'fixture_scope':'All artifacts synthetic. Only the qualified-source trust anchor is explicitly patched to synthetic source bytes; parser, identity checks and native gate execute unchanged.'}


OUT.mkdir(exist_ok=False)
cases=[run_case(name,mutation) for name,mutation in [('positive_control',None),('native_CPU_too_small','zero_GNU_CPU'),
    ('bootstrap_prefix_too_large','bootstrap_prefix_beyond_whole'),('PID_scan_after_native_exit','after_PID_scan_beyond_whole')]]
report={'schema':'independent-native-envelope-cost-counterexamples-v1','cases':cases,
    'real_native_or_C2_or_model_or_E_access':False,'model_or_oracle_execution':False,
    'software_tests_reexecuted':False,'scientific_admission':'HOLD',
    'conclusion':'Current gate accepts contradictory synthetic native/child timing or CPU accounts. This is a prospective consumer gap, not a claim about any real execution.'}
(OUT/'COUNTEREXAMPLES.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'cases':len(cases),'all_currently_accepted':True,'no_actual_native_execution':True}))
