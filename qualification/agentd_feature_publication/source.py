"""Read the exact private enum boundary, historical donor and original acceptance path."""
import json, re, sys
from hashlib import sha1
from pathlib import Path
from collections import Counter

base,candidate,donor=map(Path,sys.argv[1:])
root=Path(__file__).resolve().parent
path=Path('codex-rs/hepta-agentd/src/circuit_feature_current.rs')
old,new,upstream=(base/path).read_bytes(),(candidate/path).read_bytes(),donor.read_bytes()
def blob(data):return sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
assert [blob(x) for x in (old,new,upstream)]==['cf84a80c1d0eedbf8fee6d9dffccd5d4730b87a3','2bff88a5537cfd8776ef96c4d340f698041c8a66','3b98a5d15c8b09fd1185a4f27941376e15ba7a3f']
x=b'    Update {\n        original: PublishedNeuronGenerationUpdateV1,\n        previous: PublishedCircuitFeatureCompletionV1,'
y=b'            Publication::Update { original, previous },'
assert old.count(x)==old.count(y)==1
assert old.replace(x,x.replace(b': PublishedCircuitFeatureCompletionV1,',b': Box<PublishedCircuitFeatureCompletionV1>,' )).replace(y,b'            Publication::Update {\n                original,\n                previous: Box::new(previous),\n            },')==new
assert upstream.replace(b'pub use retained_publication::version::OriginalCircuitRetainedPublicationTaskV1;\n',b'')==new
marker=b'    pub(crate) fn from_update<'
assert old.split(marker,1)[1].split(y,1)[0]==new.split(marker,1)[1].split(b'            Publication::Update {\n',1)[0]
members={}
for p in sorted((base/path.parent).glob('*.rs')):
    raw=p.read_bytes()
    lines=[i+1 for i,s in enumerate(raw.splitlines()) if re.search(rb'\bPublication::(?:Update|Initial)\b',s)]
    if lines:members[p.name]={'base':blob(raw),'explicit_variant_sites':lines}
src=base/path.parent
controls=['circuit_feature_learning_receipt_tests.rs','circuit_q24_task_test_support.rs','cell_q24_retained_learning_source_tests.rs','neuron_generation_initial_bootstrap.rs','neuron_generation_update_bootstrap.rs']
proof={}
for name in controls:
    data=(src/name).read_bytes();assert data==(candidate/path.parent/name).read_bytes();proof[name]=blob(data)
j=json.loads((root/'strict-base.json').read_bytes())
strict=[row for row in j if row['diagnostic']=='large size difference between variants']
sys.path.insert(0,str(base.resolve()/'scripts'))
from hepta_caller_manifest import load_manifest
manifest=load_manifest(base/'CALLERS.toml')
protected={row['path'] for row in manifest['protected_file']}
roster=[]
for row in strict:
    p=base/row['path'];line=p.read_text().splitlines()[row['line']-1].strip()
    m=re.match(r'(?:(pub(?:\((?:super|crate)\))?) )?enum (\w+)',line)
    assert m,line
    roster.append({'path':row['path'],'line':row['line'],'type':m[2],'visibility':m[1] or 'private','protected':row['path'] in protected})
counts=dict(Counter(i['visibility'] for i in roster))
assert counts=={'private':12,'pub':6,'pub(crate)':2,'pub(super)':15}
print(json.dumps({'base':'c12ee03f3185d5a13949faca54f066dfd634e509','product':'6d65e2ee95f37d1f4983e3ba7393ed8ac2163c80','donor':'24abd04c825cb0d5d0ce27b52ac5008eda13dde4','git_blobs':list(map(blob,[old,new,upstream])),'counts':counts,'diagnostics':roster,'explicit_sites':members,'unchanged_production_and_fixture_blobs':proof},sort_keys=True,indent=2))
