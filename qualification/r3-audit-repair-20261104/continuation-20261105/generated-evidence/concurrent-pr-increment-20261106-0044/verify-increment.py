#!/usr/bin/env python3
"""Offline verification only. No network, child process or repository execution."""
import base64
import difflib
import gzip
import hashlib
import json
import sys
from pathlib import Path

def meta(data):
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}

def check(data, expected):
    actual=meta(data)
    assert all(actual[k]==expected[k] for k in actual),(actual,expected)
    return actual

def restore(manifest, read):
    compressed=bytearray()
    for part in manifest['parts']:
        assert part['compressed_offset']==len(compressed)
        transport=read(part['name']);check(transport,part['transport'])
        decoded=base64.b64decode(transport.strip(),validate=True)
        check(decoded,part['decoded']);compressed.extend(decoded)
    check(compressed,manifest['compressed'])
    wire=gzip.decompress(compressed);check(wire,manifest['uncompressed_transport'])
    records=json.loads(wire);files={}
    for row in records:
        name=row['logical_name']
        assert name not in files and not Path(name).is_absolute() and '..' not in Path(name).parts
        files[name]=base64.b64decode(row['bytes_base64'],validate=True)
    assert len(files)==len(manifest['originals'])==manifest['original_file_count']
    assert set(files)=={x['logical_name'] for x in manifest['originals']}
    for item in manifest['originals']:check(files[item['logical_name']],item)
    assert sum(map(len,files.values()))==manifest['original_byte_total']
    return files

def payload(result):
    assert not result.get('isError')
    data=result.get('structuredContent')
    return data if data is not None else json.loads(next(x['text'] for x in result['content'] if x['type']=='text'))

def un(result):
    data=payload(result)
    return json.loads(data['content']) if isinstance(data.get('content'),str) else data

def main(root):
    manifest=json.loads((root/'archive/manifest.json').read_bytes())
    files=restore(manifest,lambda name:(root/'archive'/name).read_bytes())
    j=lambda name:json.loads(files[name])
    old_manifest=j('baseline-1644-v7/manifest.original.json')
    old_files=restore(old_manifest,lambda name:files['baseline-1644-v7/'+name])
    old_bytes=old_files['search-and-pr-metadata.original.json']
    assert old_bytes==files['baseline-1644-v7/search-and-pr-metadata.original.json']
    assert meta(old_bytes)['blob']=='e61462bd1004b9e3ea643591c39f772890561136'
    old=json.loads(old_bytes)
    old_pr={r['pr']:un(r['result']['value']) for r in old['pr_reads']}
    capture=j('capture-manifest.json');rows=j('initial-comparison.json')['rows']
    current={};heads={}
    for item in capture['captures']:
        if 'pr' not in item:
            continue
        i=item['pr'];assert i not in current
        pr=un(j(f'raw/pr-{i}.api.original.json'))
        head=un(j(f'heads/pr-{i}.commit.original.json'))
        assert i==pr['number'] and pr['head']['sha']==head['sha']==item['head']
        assert head['tree']['sha']==item['tree']
        assert files[f'bodies/pr-{i}.body.md']==(pr['body'] or '').encode()
        current[i]=pr;heads[i]=head
    assert len(current)==30 and len(set(capture['fixed_16']))==16
    changes=[]
    for row in rows:
        i=row['pr'];before=old_pr[i];after=current[i]
        assert before['head_sha']==row['old_head'] and after['head']['sha']==row['new_head']
        assert after['base']['sha']==row['new_base'] and before['base_sha']==row['old_base']
        assert after['state']==row['new_state']=='open' and after['draft']==row['new_draft'] is True
        assert after['mergeable']==row['new_mergeable'] and after['mergeable_state']==row['new_mergeable_state']
        assert before['head_sha']!=after['head']['sha'] if row['head_changed'] else before['head_sha']==after['head']['sha']
        assert (before['body']!=after['body'])==row['body_changed']
        patch=''.join(difflib.unified_diff((before['body'] or '').splitlines(keepends=True),
            (after['body'] or '').splitlines(keepends=True),fromfile=f'v7/pr-{i}.body.md',tofile=f'current/pr-{i}.body.md')).encode()
        assert patch==files[f'diffs/pr-{i}.body.patch']
        assert hashlib.sha256(patch).hexdigest()==row['body_patch_sha256']
        changes.append({'pr':i,'head_changed':row['head_changed'],'body_changed':row['body_changed']})
    assert sum(x['head_changed'] for x in changes)==4 and sum(x['body_changed'] for x in changes)==8
    search=un(j('discovery/search-page-1.original.json'))
    pages=[un(j(f'discovery/rest-page-{i}.original.json')) for i in [1,2]]
    # Discovery original wrappers may retain request metadata around the MCP result.
    if 'result' in search:search=un(search['result'])
    pages=[un(p['result']) if isinstance(p,dict) and 'result' in p else p for p in pages]
    assert search['total_count']==len(search['items'])==19 and search['incomplete_results'] is False
    assert len({x['number'] for x in search['items']})==19
    assert [len(x) for x in pages]==[25,25]
    all_pr=pages[0]+pages[1];assert len({x['number'] for x in all_pr})==50
    cut=capture['cutoff']
    eligible={x['number'] for x in all_pr if x['updated_at']>cut and x['state']=='open'}
    search_ids={x['number'] for x in search['items']}
    assert len(eligible)==22 and eligible-search_ids=={4849,4888,4891} and not search_ids-eligible
    discovery=j('discovery-proof.json')
    assert eligible==set(discovery['qualifying_ids'])
    assert max(x['updated_at'] for x in pages[1])==discovery['second_page_max_updated']=='2026-11-05T15:49:09Z'
    assert next(x['number'] for x in all_pr if x['updated_at']<=cut)==4892
    comps={}
    for plan in j('source-compare-plan.json'):
        i=plan['pr'];outer=j(f'comparisons/pr-{i}.page-1.original.json');data=un(outer['result'])
        assert outer['plan']==plan and data['base_commit']['sha']==plan['old']
        assert data['commits'][-1]['sha']==plan['new']==current[i]['head']['sha']
        assert data['total_commits']==len(data['commits'])<100 and len(data['files'])<300
        assert len({x['filename'] for x in data['files']})==len(data['files'])
        comps[i]=data
    assert len(comps)==7
    review=j('SOURCE_REVIEW.json');source_results=[]
    for item in review['selected_sources']:
        data=files[item['source_file']];check(data,item)
        obj=j(item['full_GET_envelope']);raw=payload(obj['result'])['content'].encode()
        assert raw==data and item['blob']==obj['expected_blob_sha']
        actual=next(x for x in comps[item['pr']]['files'] if x['filename']==item['source_path'])
        assert actual['sha']==item['blob'] and current[item['pr']]['head']['sha']==item['head']
        source_results.append({k:item[k] for k in ['pr','head','source_path','bytes','sha256','blob']})
    assert len(source_results)==11
    protocol=next(x for x in comps[4895]['files'] if x['filename']=='codex-rs/hepta-agent-protocol/src/lib.rs')['patch']
    assert '\n pub const MAX_CONTROL_FRAME_BYTES: u64 = 65_536;' in protocol
    assert '\n pub const MAX_AUTOMATION_EFFECT_WIRE_BYTES: usize = 24 * 1024;' in protocol
    assert '+pub const MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES: usize = 64 * 1024;' in protocol
    assert 49508*2==99016 and 24576<49508<=65536<99016
    for gate in ['B16','B18','B19']:assert review[gate]['new_closure_evidence_independently_qualified'] is False
    assert review['all_blockers_closed'] is False
    result={'schema':'hepta-concurrent-PR-offline-verification-v1','status':'PASS_EVIDENCE_INTEGRITY_ONLY',
        'archive_members':len(files),'original_bytes':manifest['original_byte_total'],
        'archive_compressed':manifest['compressed'],'old_complete_original':meta(old_bytes),
        'PR_metadata_head_body_verified':30,'fixed16_changes':changes,
        'fixed16_head_changes':4,'fixed16_body_changes':8,'search_total':19,
        'REST_unique_read':50,'observed_qualifying_union':22,
        'search_missing_directly_observed':[4849,4888,4891],
        'not_an_atomic_repository_census':True,
        'comparisons':[{'pr':i,'commits':d['total_commits'],'files':len(d['files']),
            'files_without_inline_patch':sum('patch' not in f for f in d['files'])} for i,d in sorted(comps.items())],
        'full_GET_source_and_document_bytes_verified':source_results,
        'packet_original_inline_limit':24576,'packet_original_JSON_frame_limit':65536,
        'packet_new_separate_raw_body_limit':65536,'fixed_body_bytes':49508,'hex_characters':99016,
        'external_Chain_endpoint_independently_qualified':False,
        'author_native_claims_independently_qualified':False,'B16':'OPEN','B18':'SCIENTIFIC_HOLD','B19':'OPEN / HOLD_NO_GO / DENY_ALL',
        'native_or_repository_source_code_executed':False,'all_blockers_closed':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent)
