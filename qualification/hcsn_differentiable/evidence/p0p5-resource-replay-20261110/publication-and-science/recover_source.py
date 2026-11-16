"""Recover exact readonly artifacts from bounded text transport and seal a new handoff."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

WORK=Path(__file__).resolve().parent
OUT=WORK.parent/'full-D-publication-and-science-handoff-v1'


def identity(path):
    raw=Path(path).read_bytes()
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def save(path,value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def items(path):
    for block in json.loads(path.read_bytes())['content']:
        if block['type']=='text':
            for row in json.loads(block['text']).get('files',[]):
                raw=row['text'].encode()
                assert len(raw)==row['size'] and hashlib.sha256(raw).hexdigest()==row['sha256']
                yield row,raw


def main():
    OUT.mkdir(exist_ok=False)
    metadata_item,metadata_raw=next(items(WORK/'TEXT-MANIFEST-READBACK.json'))
    transport=json.loads(metadata_raw)
    texts={Path(row['path']).name:raw for name in ['TEXT-CHUNKS-0-READBACK.json','TEXT-CHUNKS-1-READBACK.json']
           for row,raw in items(WORK/name)}
    archives={}
    for name,record in transport['files'].items():
        raw=bytearray()
        for chunk in record['chunks']:
            text=texts[chunk['filename']]
            assert len(text)==chunk['text_bytes'] and hashlib.sha256(text).hexdigest()==chunk['text_sha256']
            part=base64.b64decode(text,validate=True)
            assert len(part)==chunk['bytes'] and hashlib.sha256(part).hexdigest()==chunk['sha256']
            assert chunk['offset']==len(raw)
            raw.extend(part)
        assert len(raw)==record['bytes'] and hashlib.sha256(raw).hexdigest()==record['sha256']
        target=OUT/name
        with target.open('xb') as stream:stream.write(raw)
        with ZipFile(target) as zipped:
            names=zipped.namelist()
            assert len(names)==len(set(names)) and zipped.testzip() is None
            assert all(not Path(n).is_absolute() and '..' not in Path(n).parts and '\\' not in n for n in names)
            members={n:dict(bytes=len(zipped.read(n)),sha256=hashlib.sha256(zipped.read(n)).hexdigest()) for n in names if not n.endswith('/')}
            if name.startswith('full-D'):
                expected=json.loads(zipped.read('MANIFEST.json'))
                for n,entry in expected.items():
                    assert members[n]=={k:entry[k] for k in ['bytes','sha256']}
                save(OUT/'PUBLICATION-MEMBERS.json',expected)
        archives[name]=dict(**identity(target),members=len(members),CRC_and_all_bytes_verified=True)
    provenance={}
    for row,raw in items(WORK/'READBACK.json'):
        prefix='launch' if '/science-artifact-collection-launch-v1/' in row['path'] else 'collection'
        rel=Path(prefix)/Path(row['path']).name
        path=OUT/rel;path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        provenance[str(rel)]=dict(native_path=row['path'],version=row['version'],**identity(path))
    # Copy sources and authorization intent. No raw base64 is needed in the curated result.
    for name in ['collect_native.py','starter.py','PLAN.json','NATIVE-INTENT.json','NATIVE-ACK.json',
                 'encode_existing_native.py','TEXT-TRANSPORT-ACK.json']:
        shutil.copy2(WORK/name,OUT/name)
    (OUT/'TEXT-TRANSPORT-MANIFEST.json').write_bytes(metadata_raw)
    failures=json.loads((WORK/'PUBLICATION-BINARY-READBACK.json').read_bytes())
    save(OUT/'BINARY-TRANSPORT-FAILURES.json',dict(
        first_attempt=dict(requests=4,completion='collector script failed parsing a tool-error response after all awaited reads',
            failure='SyntaxError: Unexpected token o, tool call e... is not valid JSON',individual_responses_retained=False,
            CPU_seconds=None,wall_seconds=None,mutations=0),
        second_attempt=failures,scope='Read-only binary transport MCP request timeouts. Native files were already complete; no download/upload/model operation was repeated.'))
    save(OUT/'READBACK-PROVENANCE.json',provenance)
    collection=json.loads((OUT/'collection/RESULT.json').read_bytes())
    receipt=json.loads((OUT/'launch/receipt.json').read_bytes())
    assert collection['status']=='completed' and receipt['returncode']==0
    summary=dict(schema='full-D-publication-and-science-artifact-handoff-v1',status='exact_native_originals_recovered',
        archives=archives,collection=identity(OUT/'collection/RESULT.json'),outer=identity(OUT/'launch/receipt.json'),
        scientific_admission='HOLD',overall_CI='not_all_CI; this is the exact hosted science artifact only',
        source_head='cd3b7ac49294174a98e02636247615534c19bd89',tested_merge='f63b067ac577a6eea363c37d1358f65dc7b4f4ba',
        common_tree='4bb4995c3c1058d268c032a0d15cdfe9297a6ff8',run_id=42890048946,attempt=1,artifact_id=13797877354,
        head_tree_context_scope='Supplied and separately checked by root; this job verifies exact artifact bytes without rerunning CI.',
        full_D_release_asset_id=732788592,release_id=440410488,publish_release=False,
        native_collection_whole_child_wall_seconds=receipt['complete_child_wall_seconds'],
        native_collection_waited_child_and_descendant_CPU_seconds=receipt['complete_waited_child_and_descendant_CPU_seconds'],
        own_wrapper_CPU_seconds=receipt['own_process_CPU_seconds'],
        nested_stage_scopes=collection['tasks'],text_encoding=transport,
        tool_transport_CPU_seconds=None,tool_transport_complete_wall_seconds=None,
        scope='This archive collects the exact previous full-D publication logs/receipts and one CI artifact download. It performs no training, forward, numerical oracle, asset publication or CI rerun.')
    save(OUT/'SUMMARY.json',summary)
    (OUT/'README.md').write_text('''# Exact full-D publication originals and hosted science artifact

Both native originals have been recovered byte-for-byte and independently rechecked on the cloud. The full-D publication archive is 82,271 B with SHA256 d42daa4bc1d65328b9f34d921a5e4c1f181aa89ed44b916a939434bb9ffdf6b8 and 52 members. It preserves both the failed v1 publication attempt and successful v2 attempt, all raw gh/curl stdout/stderr, launch receipts and frozen publication source. The original full-D handoff remains unchanged.

The hosted science artifact is the exact 77,859 B GitHub archive for run 42890048946 attempt 1, artifact 13797877354, SHA256 cab12a2f8f73660e3436e68c2dc84f072f1be857dc5513e8f956c995f2e7d743. All 14 members pass CRC and safe unique-name checks. The source head, merge and shared tree are contextual identities separately verified by root; this collector verifies the provided archive commitment. It made one artifact GET, did not rerun CI, and did not upload or publish this archive. A successful hosted science job does not establish all CI passing.

The collection child ran for 4.2782243269030005 s and used 0.327397 s waited child-plus-descendant CPU. This includes 0.042037267005071044 s local publication packaging and 4.146056958008558 s artifact GET/verification; those nested stage measurements must not be added to the whole child. The wrapper own CPU was 0.060658237 s. Two binary transport attempts timed out; those read-only tool costs are unknown and retained as failures. Recovery then encoded the existing native files for bounded text transport in 0.003481175983324647 s measured main interval and 0.003480918999999999 s main CPU; import/startup/transport overhead is excluded. No second artifact download, model replay, or release upload occurred.

SUMMARY.json and the exact collection/launch receipts preserve cost scopes. COPY_LIST.json selects only frozen source, artifacts and original receipts; raw base64 transport pages remain in the working directory and are not duplicated here.
''')
    shutil.copy2(Path(__file__),OUT/'recover_source.py')
    files={str(p.relative_to(OUT)):identity(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
    save(OUT/'MANIFEST.json',dict(schema='native-publication-CI-readonly-handoff-manifest-v1',files=files))
    entries={n:dict(source=str(OUT/n),**v) for n,v in files.items()}
    entries['MANIFEST.json']=dict(source=str(OUT/'MANIFEST.json'),**identity(OUT/'MANIFEST.json'))
    save(OUT/'COPY_LIST.json',dict(destination_prefix='publication/full-D-and-science-native-v1',files=entries))
    target=OUT.parent/'full-D-publication-and-science-handoff-v1.zip'
    with ZipFile(target,'x',compression=ZIP_DEFLATED) as zipped:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():zipped.write(p,str(p.relative_to(OUT)))
    with ZipFile(target) as zipped:assert zipped.testzip() is None
    print(json.dumps(dict(directory=str(OUT),archive=dict(path=str(target),**identity(target)),
        manifest=identity(OUT/'MANIFEST.json'),copy_list=identity(OUT/'COPY_LIST.json'),summary=identity(OUT/'SUMMARY.json'))))


if __name__=='__main__':main()
