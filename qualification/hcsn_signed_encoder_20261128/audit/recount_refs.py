"""Offline check of a frozen refs list, its two inventories and delta evidence tables."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

def refs(path):
    return dict((name,oid) for oid,name in (row.split(b'\t',1) for row in gzip.decompress(path.read_bytes()).splitlines()) if name.startswith(b'refs/'))

def oidset(path):
    return {r.split(b'\t',1)[0] for r in path.open('rb')}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def set_hash(items):
    return digest(b''.join(x+b'\n' for x in sorted(items)))

def check(root):
    stage=root/'refs-namespace'
    raw=gzip.decompress((stage/'all_refs.tsv.gz').read_bytes())
    ad=refs(stage/'all_refs.tsv.gz')
    ann={n[:-3]:v for n,v in ad.items() if n.endswith(b'^{}')}
    ns={n:ann.get(n,oid) for n,oid in ad.items() if not n.endswith(b'^{}')}
    nsp=Counter(n.split(b'/')[1].decode() for n in ns)
    target_sha=len(set(ns.values()))
    held=oidset(stage/'public_heads_tags/all_blobs.tsv')
    pr=oidset(stage/'pull/all_blobs.tsv')
    old=oidset(root/'results/all_blobs.tsv')|oidset(root/'tags/tag_all_unique_input.tsv')
    current=held|pr; new=current-old
    meta=json.loads((stage/'advertised_tree_coverage.json').read_bytes())
    structure=json.loads((stage/'verified_ref_structure.json').read_bytes())
    addtab=(stage/'additional_oids.tsv').read_bytes()
    assert digest(raw)==meta['scope_git_advertisement_sha256']
    assert set_hash(current)==meta['combined_sorted_oid_sha256']==structure['independent_blob_identity_set_sha256']
    assert set_hash(new)==meta['additional_sorted_oid_sha256']
    assert {r.split(b'\t',1)[0] for r in addtab.splitlines()}==new
    assert digest(addtab)==meta['additional_table_uncompressed_sha256']
    assert target_sha==meta['distinct_advertised_commit_targets']==structure['verified_raw_commit_ids']
    binary=gzip.decompress((stage/'delta/other/roster.tsv.gz').read_bytes())
    rawids={x.split(b'\t',1)[0] for x in binary.splitlines()}
    source=oidset(stage/'delta/source/files.tsv')
    assert source.isdisjoint(rawids) and source|rawids==new
    import sqlite3
    db=sqlite3.connect(f'file:{stage}/delta/source/work/screen.sqlite?mode=ro',uri=True)
    actual={oid.encode():size for oid,size in db.execute('select oid,size from files')}
    assert actual.keys()==source
    out={'refs':dict(nsp),'commit_targets':target_sha,'both':len(current),'heads_tags':len(held),'pr':len(pr),'pr_only':len(pr-held),'ads_minus_earlier':len(new),'earlier_minus_ads':len(old-current),'new_source':len(source),'new_source_verified_bytes':sum(actual.values()),'new_other':len(rawids),'oid_set_sha256':set_hash(current),'freestanding_program':'Recount independently joins original frozen rows and verifies the reference, blob-set and delta digests.'}
    recovered=stage/'delta/recovery_9de7'
    if (recovered/'receipt.json').exists():
        info=json.loads((recovered/'receipt.json').read_bytes())
        detail=gzip.decompress((recovered/'verified_objects.tsv.gz').read_bytes())
        assert digest(detail)==info['merged_uncompressed_table_sha256']
        result={r[0]:int(r[2]) for r in (x.split(b'\t') for x in detail.splitlines())}
        assert result.keys()==rawids
        out.update(increment_all_objects=len(result)+len(actual),increment_all_bytes=sum(result.values())+sum(actual.values()),reconstructed_binary_bytes=sum(result.values()),reconstructed_binary_ids=len(result))
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path,nargs='?',default=Path.home()/'.local/state/hepta-hcsn-1140569-audit')
    print(json.dumps(check(parser.parse_args().root),indent=2,sort_keys=True))
