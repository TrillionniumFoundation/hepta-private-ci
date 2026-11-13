#!/usr/bin/env python3
"""Extend the immutable 35-file assembly with frozen test and Material inputs."""
from pathlib import Path
import difflib, hashlib, json

ROOT = Path(__file__).resolve().parent
PREVIOUS = ROOT / 'assembled-v1'
base = json.loads((ROOT/'SOURCE_BASE_TREE.json').read_text())
previous_manifest = json.loads((PREVIOUS/'MANIFEST.json').read_text())
originals = json.loads((ROOT/'new-increment-actual-originals.json').read_text())

def identity(data):
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}

def equal(data,pin):
    assert identity(data) == {k:pin[k] for k in ('bytes','sha256','git_blob')}

before,after = {},{}
history = list(previous_manifest['exact_operations'])
for row in previous_manifest['changes']:
    p=row['path']
    after[p]=(PREVIOUS/'after'/p).read_bytes()
    equal(after[p],row['after'])
    before[p]=None if row['before'] is None else (PREVIOUS/'before'/p).read_bytes()
    if before[p] is not None:
        equal(before[p],row['before'])
        assert identity(before[p])['git_blob'] == base['files'][p]
    else:
        assert p not in base['files']

layers = [('shared-original-readback-ten-test-increment-v1','testsPacket.json',
           '04fb77b4afb11c55ddbee1f0d4a631b4c1cf14ea'),
          ('fresh-provider-material-rebuilt-v1','materialPacket.json',
           '4a2aabfb2cca405e57aa26994ebe97cdcd6e6b94')]
for label,name,sha in layers:
    raw=(ROOT/name).read_bytes()
    assert identity(raw)['git_blob']==sha
    packet=json.loads(raw)
    assert packet['base_commit']==base['commit']
    for row in packet['changes']:
        p=row['path']
        assert row['mode']=='100644'
        new=row['after_text'].encode()
        equal(new,row['after'])
        if p in after:
            assert row['before'] is not None
            equal(after[p],row['before'])
            prior=after[p]
        elif row['before'] is None:
            assert p not in base['files']
            before[p]=prior=None
        else:
            prior=originals[row['before']['git_blob']].encode()
            equal(prior,row['before'])
            assert base['files'][p]==row['before']['git_blob']
            before[p]=prior
        after[p]=new
        history.append({'layer':label,'path':p,'operation':'exact declared predecessor',
                        'declared_before':row['before'],
                        'actual_before':None if prior is None else identity(prior),
                        'actual_after':identity(new)})

out=ROOT/'assembled-v2'
out.mkdir(exist_ok=False)
changes,patch=[],[]
for p in sorted(after):
    old,new=before[p],after[p]
    for kind,data in [('before',old),('after',new)]:
        if data is None:
            continue
        target=out/kind/p
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:
            f.write(data)
    changes.append({'path':p,'mode':'100644',
                    'before':None if old is None else identity(old),
                    'before_text':None if old is None else old.decode(),
                    'after':identity(new),'after_text':new.decode()})
    patch.extend(difflib.unified_diff([] if old is None else old.decode().splitlines(keepends=True),
                                    new.decode().splitlines(keepends=True),
                                    fromfile='/dev/null' if old is None else 'a/'+p,tofile='b/'+p))
with (out/'changes.patch').open('x') as f:
    f.writelines(patch)
parts,pending=[],[]
for change in changes:
    proposed=pending+[change]
    if pending and len(json.dumps(proposed,ensure_ascii=False,sort_keys=True).encode())>400000:
        parts.append(pending)
        pending=[change]
    else:
        pending=proposed
if pending:
    parts.append(pending)
status='HOLD_UNFORMATTED_UNCOMPILED_UNEXECUTED_FULL_FRESH_PUBLIC_ORCHESTRATION_INCOMPLETE'
packets=[]
for n,part in enumerate(parts,1):
    name=f'SOURCE_PACKET.part-{n:02d}.json'
    raw=(json.dumps({'format':'hepta.combined_source_preparation.part.v2',
                     'base_commit':base['commit'],'source_src_tree':base['src_tree'],
                     'status':status,'part':n,'parts':len(parts),'changes':part},
                    ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    with (out/name).open('xb') as f:
        f.write(raw)
    packets.append({'path':name,**identity(raw),'source_files':len(part)})
report={'format':'hepta.combined_source_preparation.v2',
        'base_source':base['commit'],'source_src_tree':base['src_tree'],
        'previous_manifest':identity((PREVIOUS/'MANIFEST.json').read_bytes()),
        'status':status,'source_paths':len(changes),
        'modified_original_paths':sum(c['before'] is not None for c in changes),
        'new_paths':sum(c['before'] is None for c in changes),
        'layers':list(dict.fromkeys(h['layer'] for h in history)),
        'exact_operations':history,'source_packets':packets,
        'changes':[{k:v for k,v in c.items() if k not in ('before_text','after_text')} for c in changes],
        'completed_preparation':['Six evaluated/Published export tests and four original shared-transport tests mounted.',
                                'Same actual A material builder and retained future C Admission added; Fresh T/E not pre-executed.',
                                'Three test-only shared-client observations mounted; actual trainer read advances the original slot.'],
        'still_required':['Actual full Fresh public multi-process ten-owner orchestration and cold recovery.',
                          'Version-owned actual C/NextUse readiness service with original opaque selection purpose.',
                          'Complete CALLERS/protected/allowlist/QA/Root workflow registration.',
                          'Original just fix/fmt/test and candidate-specific source/native qualification.',
                          'Legitimate external authorities, independent observed B and frozen complete costs.'],
        'source_ref_moved':False,'h_calls':0,'formatter_or_cargo_or_tests_executed':False,
        'real_qualified_task_chains':0}
with (out/'MANIFEST.json').open('x') as f:
    json.dump(report,f,ensure_ascii=False,indent=2,sort_keys=True)
    f.write('\n')
print(json.dumps({'manifest':identity((out/'MANIFEST.json').read_bytes()),
                  'source_paths':len(changes),'modified_original_paths':report['modified_original_paths'],
                  'new_paths':report['new_paths'],'packets':packets,'status':status},sort_keys=True))
