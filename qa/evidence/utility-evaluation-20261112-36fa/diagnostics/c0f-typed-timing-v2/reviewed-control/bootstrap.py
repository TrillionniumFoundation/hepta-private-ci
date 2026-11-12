import hashlib,json,os,sys
from pathlib import Path
payload=sys.stdin.buffer.read()
if hashlib.sha256(payload).hexdigest() != 'b97d1491b8505d85c7eaba0f9f70608c3abc082070708c4cfffcc303f51fe66d':
    raise RuntimeError('exact reviewed control packet differs')
data=json.loads(payload)
if data['run_identity'] != 'hepta-utility-36fa-c0f-typed-timing-v2':
    raise RuntimeError('diagnostic identity differs')
control=Path('/home/qian-qi/hepta-utility-36fa-evidence/prepared-c0f-typed-timing-v2')
if control.parent.resolve() != control.parent or not control.parent.is_dir():
    raise RuntimeError('control parent is not the known real evidence directory')
control.mkdir(exist_ok=False)
if [x['name'] for x in data['files']] != ['driver.py','worker.py','input.json']:
    raise RuntimeError('unexpected control file set')
observed=[]
for item in data['files']:
    raw=item['content'].encode()
    if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise RuntimeError('control payload identity differs')
    path=control/item['name']
    with path.open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    actual=path.read_bytes()
    if actual != raw:
        raise RuntimeError('control full file readback differs')
    observed.append({'path':str(path),'bytes':len(actual),'sha256':hashlib.sha256(actual).hexdigest()})
record={'event':'control_bundle_read_back','run_identity':data['run_identity'],'files':observed}
with (control/'TRANSFER_READBACK.json').open('x') as stream:
    json.dump(record,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps(record,sort_keys=True),flush=True)
os.execv(sys.executable,[sys.executable,'-B',str(control/'driver.py'),str(control/'input.json')])
