"""Fixed synthetic worker; no arbitrary script, artifact or dataset path input."""
import hashlib
import json
from pathlib import Path
import sys
import os
import time

ROOT=Path(__file__).resolve().parent
FILES=('cell_field_fixed_worker.py','cell_field_fixed_gate.py','cell_field_fixed_fixture.py','cell_field_fixed_sources.json','cell_field_fixed_adapter.py','cell_field_fixed_actions.py','cell_field_fixed_summary.py',
       'cell_field_control.py','cell_field_state.py',
       'cell_learning_models.py','cell_learning_metrics.py')

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate key')
        result[key]=value
    return result

def main():
    raw=sys.stdin.buffer.read(16385)
    if len(raw)>16384:raise ValueError('oversized request')
    request=json.loads(raw,object_pairs_hook=unique)
    if set(request)!={'fixture','action','mode','sources','fault','limits','interpreter_sha256','stop_window','request_sha256'}:raise ValueError('request fields')
    identity=request.pop('request_sha256')
    if hashlib.sha256(canonical(request)).hexdigest()!=identity:raise ValueError('request digest')
    if hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()!=request['interpreter_sha256']:raise ValueError('interpreter mismatch')
    if request['fixture']!='synthetic-linear36-h3-v1' or set(request['sources'])!=set(FILES):raise ValueError('fixed fixture/source only')
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest for name,digest in request['sources'].items()):raise ValueError('source mismatch')
    if request['stop_window'] not in (None,'started','terminal'):raise ValueError('fixed stop window')
    if request['fault'] not in ('none','hang','before_output','after_output','stderr_overflow','wrong_request'):raise ValueError('unknown fixed fault')
    if request['fault']=='hang':time.sleep(60)
    if request['fault']=='before_output':sys.exit(12)
    if request['fault']=='stderr_overflow':os.write(2,b'x'*24576);sys.exit(14)
    sys.path.insert(0,str(ROOT))
    from cell_field_fixed_fixture import build_synthetic_references
    from cell_field_fixed_adapter import fixed_impulse_predictions
    for filename in FILES[1:]:
        if filename in ('cell_field_fixed_gate.py','cell_field_fixed_sources.json'):continue
        module=sys.modules[Path(filename).stem]
        if Path(module.__file__).resolve()!=(ROOT/filename).resolve():raise ValueError('import source mismatch')
    ref=build_synthetic_references(('linear',))['linear']
    result=fixed_impulse_predictions(ref,request['action'],mode=request['mode'])
    response={'request_sha256':identity if request['fault']!='wrong_request' else '0'*64,
              'fields':result['fields'].tolist()}
    sys.stdout.buffer.write(canonical(response)+b'\n');sys.stdout.buffer.flush()
    if request['fault']=='after_output':sys.exit(13)

if __name__=='__main__':main()
