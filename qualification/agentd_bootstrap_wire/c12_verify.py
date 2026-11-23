"""Recompute Git's SHA1 tree IDs and projected overlay without writing a Git object."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

p=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent
base='43e5da1bb81369e4e999adfa8558f5ccb5460eb6'
current='c12ee03f3185d5a13949faca54f066dfd634e509'
candidate='2b75c8df6b804b87dd8c3cbca8d8a4b37d1d97d4'
selected_blob='054075188a68c0b6673c5779108be6556358d6c6'
manifests=json.loads(gzip.decompress((p/'c12-index.json.gz').read_bytes()))
def tree_id(rows):
    entries=[]
    for name, (mode,kind,sha) in rows.items():
        key=name.encode()+ (b'/' if kind=='tree' else b'')
        record=mode.lstrip('0').encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)
        entries.append((key,record))
    payload=b''.join(r for k,r in sorted(entries))
    return hashlib.sha1(b'tree '+str(len(payload)).encode()+b'\0'+payload).hexdigest()
expected=json.loads((p/'c12-merkle.json').read_bytes())
names=['codex-rs','hepta-agentd','src','authority_host_learning_resident_transport_tests.rs']
for source in ('base','c12'):
    for i,tree in enumerate(manifests):
        key=tree['prefix']; arm=0 if source=='base' else 1
        assert tree_id(tree[source])==expected[key]['trees'][arm]
        assert len(tree[source])==expected[key]['counts'][arm]
        if i:
            assert manifests[i-1][source][names[i-1]][2]==tree_id(tree[source])
        assert [n for n in sorted(set(tree['base'])|set(tree['c12'])) if tree['base'].get(n)!=tree['c12'].get(n)]==[names[i]]
before=manifests[-1]['c12']; after={k:list(v) for k,v in before.items()}
bootstrap='authority_host_publication_bootstrap.rs'
assert before[bootstrap][2]=='270d025b44c5d3f5aed8d3438b7fc6f34ff9dab8'
after[bootstrap][2]=selected_blob
tree=tree_id(after)
for i in reversed(range(3)):
    rows={k:list(v) for k,v in manifests[i]['c12'].items()}
    rows[names[i]][2]=tree
    tree=tree_id(rows)
result={'base':base, 'current':current, 'candidate':candidate, 'root_trees':expected['.']['trees'],
        'one_change_on_current':expected[manifests[3]['prefix']]['delta'][0],
        'bootstrap_before':before[bootstrap][2],'bootstrap_after':selected_blob, 'projected_combined_tree':tree,
        'source_only':True,'combined_has_native_or_clippy_run_in_this_evidence':False}
print(json.dumps(result,indent=2))
