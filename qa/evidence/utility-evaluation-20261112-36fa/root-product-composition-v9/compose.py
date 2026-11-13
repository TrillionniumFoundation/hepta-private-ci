"""Compose immutable source proposals by exact byte splices; no repository code runs."""
from pathlib import Path
import json, hashlib
OUT = Path('/tmp/hepta-36fa-root-product-composition-v9')
PREV = Path('/tmp/hepta-36fa-root-product-composition-v8')
LAYERS = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(), 'git_blob': hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
base_raw = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/PROPOSED_NONRUST_8EBB_GRAPH.json').read_bytes()
assert pin(base_raw)['git_blob'] == '7c515dbe48ae3ab42ccc85d916e38675db06ced2'
base = {e['path']: {k: e[k] for k in ('bytes','sha256','git_blob')} for e in json.loads(base_raw)['files']}
prev_raw = (PREV/'PREQUALIFICATION_COMPOSITION_REVIEW.json').read_bytes()
assert pin(prev_raw)['git_blob'] == 'ba9a9406bb4fb2786a9ff269f8e9a86da1634154'
current, sources = base.copy(), {}
for e in json.loads(prev_raw)['files']:
    b = (PREV/'after'/e['path']).read_bytes()
    assert pin(b) == e['after'] and e['before'] == base.get(e['path'])
    current[e['path']], sources[e['path']] = e['after'], b
layers = []
for name, expected in [
    ('prefreeze-source-layer-v1','c66c54e9989023b79f62b10575350293d21301a0'),
    ('prefreeze-ready-increment-v1','3181789965054fd440568f0ac4d4e242194d34f3'),
    ('common-startup-increment-v1','07cb756ca663e7fd802e008e258cb3828d73e636'),
    ('prefreeze-mechanism-tests-layer-v1','474fe0d12b9d73cb94136e4e46d09394e495bbe3'),
]:
    d = LAYERS/name
    raw = (d/'SOURCE_PACKET.json').read_bytes()
    assert pin(raw)['git_blob'] == expected
    packet = json.loads(raw)
    splice_raw = (d/'EXACT_SOURCE_SPLICES.json').read_bytes()
    splices = json.loads(splice_raw)['splices']
    rows, used = [], []
    assert len({e['path'] for e in packet['entries']}) == len(packet['entries'])
    for e in packet['entries']:
        p = e['path']; after = e['after_utf8'].encode()
        assert pin(after) == e['after'] and (d/'after'/p).read_bytes() == after
        if e['before'] is None:
            assert p not in current and e['before_utf8'] is None
            assert not any(s['path'] == p for s in splices)
            proof = {'new_path_absent': True}
        else:
            before = e['before_utf8'].encode()
            assert pin(before) == e['before'] == current[p]
            if p in sources: assert before == sources[p]
            cur, applied = before, []
            for i,s in enumerate(splices):
                if s['path'] != p: continue
                used.append(i)
                if s.get('kind') == 'exact_suffix_append':
                    assert len(cur) == s['before_bytes']
                    offset, old, new = len(cur), b'', s['append_utf8'].encode()
                else:
                    old, new = s['before_utf8'].encode(), s['after_utf8'].encode()
                    if 'offset_in_sequential_preimage' in s:
                        offset = s['offset_in_sequential_preimage']
                    else:
                        assert cur.count(old) == 1, (name,p,i,'ambiguous preimage')
                        offset = cur.index(old)
                    assert cur[offset:offset+len(old)] == old
                cur = cur[:offset]+new+cur[offset+len(old):]
                applied.append((offset,old,new))
            assert cur == after, (name,p,'full forward')
            for offset,old,new in reversed(applied):
                assert cur[offset:offset+len(new)] == new
                cur = cur[:offset]+old+cur[offset+len(new):]
            assert cur == before, (name,p,'full inverse')
            proof = {'splices':len(applied),'full_forward_and_inverse_equal':True}
        current[p], sources[p] = e['after'], after
        rows.append({'path':p,'before':e['before'],'after':e['after'],**proof})
    assert sorted(used) == list(range(len(splices)))
    layers.append({'name':name,'packet':pin(raw),'splices':pin(splice_raw),'files':rows})
new = sorted(set(current)-set(base))
modified = sorted(p for p in base if current[p] != base[p])
assert set(sources) == set(new+modified) and not set(base)-set(current)
report = {
    'format':'hepta-root-partial-product-composition-v9',
    'base_source':'b6084394a4a38ab495c16eaba09e879f04a96f8e',
    'previous_composition':pin(prev_raw),'layers':layers,
    'files_before':len(base),'files_after':len(current),'changed_paths':len(sources),
    'new_files':len(new),'modified_original_files':len(modified),'original_files_unchanged':len(base)-len(modified),
    'files':[{'path':p,'before':base.get(p),'after':current[p]} for p in sorted(sources)],
    'remaining':['same-session Task/Material/V3 actual CLI wiring','final caller/protection/contract/test/workflow union',
                 'original compiler/source/native gates','real authorized A-independent B-C and daemon/Root cold recovery'],
    'repository_code_executed':False,'H_calls_in_this_composition':0,'source_Git_mutation':False,
    'qualification':False,'real_qualified_chains':0,
}
for p,b in sources.items():
    f = OUT/'after'/p; f.parent.mkdir(parents=True,exist_ok=True)
    with f.open('xb') as h: h.write(b)
b = (json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (OUT/'PREQUALIFICATION_COMPOSITION_REVIEW.json').open('xb') as h: h.write(b)
print(json.dumps({'review':pin(b),'changed_paths':len(sources),'new_files':len(new),'modified_original_files':len(modified),'files_after':len(current),'qualification':False}))
