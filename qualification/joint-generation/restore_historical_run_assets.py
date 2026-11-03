"""Restore five original historical assets for static inspection, never experiments."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import zlib

ASSET_PATHS = ('qualification/joint-generation/runs/codex-cloud-core-c1-t2/telemetry.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-decision-diagnostic-q1/diagnostic.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-decision-diagnostic-q1/predictions.npz', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-profile-d1/profile.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-timing-d2/timing.json')
MARKER_PATHS = ('qualification/joint-generation/runs/codex-cloud-core-c1-t2/test-opened.json', 'qualification/joint-generation/core_confirmation/core-c1-test-opened.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-decision-diagnostic-q1/START.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-profile-d1/START.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-profile-d1/RUNNING.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-timing-d2/START.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-timing-d2/RUNNING.json')
SIDECAR_PATHS = ('qualification/joint-generation/runs/codex-cloud-core-c1-t2/retained-manifest.json', 'qualification/joint-generation/runs/codex-cloud-core-c1-training-receipt-diagnostic/ADMIN.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-decision-diagnostic-q1/manifest.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-decision-diagnostic-q1/protocol.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-profile-d1/manifest.json', 'qualification/joint-generation/runs/accounting-cache-development-diagnostic-20261023-c1/shared-ledger-fixture.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-timing-d2/manifest.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-timing-d2/checksums.json', 'qualification/joint-generation/runs/codex-cloud-efficient-r2-shared-timing-d2/protocol.json')
DESCRIPTOR = 'qualification/joint-generation/compressed-historical-run-assets-manifest.json'
BASE = 'qualification/joint-generation/'
CORE = BASE+'runs/codex-cloud-core-c1-t2/'
Q1 = BASE+'runs/codex-cloud-efficient-r2-decision-diagnostic-q1/'
D1 = BASE+'runs/codex-cloud-efficient-r2-shared-profile-d1/'
D2 = BASE+'runs/codex-cloud-efficient-r2-shared-timing-d2/'
ADMIN = BASE+'runs/codex-cloud-core-c1-training-receipt-diagnostic/ADMIN.json'
FIXTURE = BASE+'runs/accounting-cache-development-diagnostic-20261023-c1/shared-ledger-fixture.json'
NOTE_PATH = 'inspection-metadata/INSPECTION.txt'
RECEIPT_PATH = 'inspection-metadata/RESTORATION.json'
NOTE = (b'Historical five-artifact inspection overlay, not a complete checkout or runnable experiment.\n'
        b'INCOMPLETE unless RESTORATION.json is present and all target/marker bytes verify.\n'
        b'Original scientific failures, costs, source drift, protocols and seals remain historical.\n'
        b'Never run historical producer, diagnostic, worker, evaluator or model code here.\n')
H = lambda body: hashlib.sha256(body).hexdigest()

class ContractError(ValueError):
    pass

def require(ok, reason):
    if not ok: raise ContractError(reason)

def strict_json(body):
    def pairs(items):
        value={}
        for key,item in items:
            require(key not in value,'json-duplicate-key')
            value[key]=item
        return value
    def constant(value): raise ContractError('json-nonfinite')
    def number(value):
        result=float(value); require(math.isfinite(result),'json-float-overflow'); return result
    return json.loads(body,object_pairs_hook=pairs,parse_constant=constant,parse_float=number)

def canonical(value):
    return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode('ascii')

def no_links(path):
    # Trusted local filesystem only; no hostile concurrent mutation guarantee.
    path=Path(os.path.abspath(path))
    for part in [*reversed(path.parents),path]:
        require(not part.is_symlink(),'symlink')
    return path

def roots(source, output, *, fresh):
    source=no_links(source); output=no_links(output)
    require(source.is_dir(),'source-root')
    require(source!=output and source not in output.parents and output not in source.parents,'overlapping-roots')
    require(output.parent.is_dir(),'output-parent')
    if fresh: require(not output.exists(),'existing-output')
    else: require(output.is_dir(),'output-root')
    return source,output

def bounded_read(path, maximum, expected_bytes=None, expected_hash=None):
    path=no_links(path)
    require(stat.S_ISREG(path.stat().st_mode),'regular-file')
    require(path.stat().st_size<=maximum,'file-bound')
    body=path.read_bytes()
    require(len(body)<=maximum,'file-bound')
    if expected_bytes is not None: require(len(body)==expected_bytes,'input-size')
    if expected_hash is not None: require(H(body)==expected_hash,'input-hash')
    return body

def descriptor(source):
    value=strict_json(bounded_read(source/DESCRIPTOR,16384))
    require(type(value) is dict and set(value)=={'schema','assets','markers','sidecars'},'descriptor-fields')
    require(value['schema']=='joint-historical-assets-gzip-v1','schema')
    for group,expected in [('assets',ASSET_PATHS),('markers',MARKER_PATHS),('sidecars',SIDECAR_PATHS)]:
        items=value[group]; require(type(items) is list and len(items)==len(expected),'entry-count')
        seen=set()
        for entry in items:
            fields=({'path','compressed_bytes','compressed_sha256','original_bytes','original_sha256'}
                    if group=='assets' else {'path','bytes','sha256'})
            require(type(entry) is dict and set(entry)==fields,'entry-fields')
            path=entry['path']; require(type(path) is str and path in expected and path not in seen,'entry-path')
            seen.add(path)
            byte_fields=(('compressed_bytes',511999),('original_bytes',2000000)) if group=='assets' else (('bytes',16384),)
            for key,limit in byte_fields: require(type(entry[key]) is int and 0<entry[key]<=limit,'byte-bound')
            for key in (('compressed_sha256','original_sha256') if group=='assets' else ('sha256',)):
                require(type(entry[key]) is str and re.fullmatch('[0-9a-f]{64}',entry[key]) is not None,'digest')
        require(seen==set(expected),'entry-set')
    return value

def decompress_one(body, entry):
    decoder=zlib.decompressobj(31)
    raw=decoder.decompress(body,entry['original_bytes']+1)
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'gzip-integrity')
    require(len(raw)==entry['original_bytes'] and H(raw)==entry['original_sha256'],'raw-integrity')
    return raw

def relations(raw, parsed, metadata_raw, metadata_json):
    checked=[]
    def relation(ok,label): require(ok,'relation:'+label); checked.append(label)
    def bytes_hash(value,path):
        return type(value) is dict and type(value.get('bytes')) is int and value['bytes']==len(raw[path]) and value.get('sha256')==H(raw[path])
    core=metadata_json[CORE+'retained-manifest.json']
    matches=[item for item in core['files'] if item.get('file')=='telemetry.json']
    relation(len(matches)==1 and bytes_hash(matches[0],CORE+'telemetry.json'),'core-retained')
    relation(bytes_hash(metadata_json[ADMIN]['input_files']['telemetry.json'],CORE+'telemetry.json'),'core-admin')
    qmf=metadata_json[Q1+'manifest.json']['files']
    relation(qmf['diagnostic.json']==H(raw[Q1+'diagnostic.json']) and qmf['predictions.npz']==H(raw[Q1+'predictions.npz']),'q1-manifest')
    prediction=parsed[Q1+'diagnostic.json']['predictions']
    relation(prediction.get('file')=='predictions.npz','q1-filename')
    relation(bytes_hash(prediction,Q1+'predictions.npz'),'q1-predictions')
    relation(parsed[Q1+'diagnostic.json']['protocol_sha256']==H(metadata_raw[Q1+'protocol.json'])==metadata_json[Q1+'START.json']['protocol_sha256'],'q1-protocol')
    relation(bytes_hash(metadata_json[D1+'manifest.json']['files']['profile.json'],D1+'profile.json'),'d1-manifest')
    fixture=metadata_json[FIXTURE]
    relation(fixture.get('source')=='runs/codex-cloud-efficient-r2-shared-profile-d1/profile.json' and fixture.get('source_field')=='shared_ledger' and fixture.get('source_sha256')==H(raw[D1+'profile.json']),'d1-fixture')
    relation(bytes_hash(metadata_json[D2+'manifest.json']['timing.json'],D2+'timing.json'),'d2-manifest')
    checksums=metadata_json[D2+'checksums.json']['files']
    relation(bytes_hash(checksums['timing.json'],D2+'timing.json'),'d2-checksums')
    relation(parsed[D2+'timing.json']['protocol_sha256']==H(metadata_raw[D2+'protocol.json'])==metadata_json[D2+'START.json']['protocol_sha256'],'d2-protocol')
    for filename in ('START.json','RUNNING.json'):
        item=checksums[filename]; body=metadata_raw[D2+filename]
        relation(type(item.get('bytes')) is int and item['bytes']==len(body) and item.get('sha256')==H(body),'d2-marker-'+filename)
    return checked

def verified_inputs(source):
    source=no_links(source); require(source.is_dir(),'source-root')
    manifest=descriptor(source)
    maps={group:{entry['path']:entry for entry in manifest[group]} for group in ('assets','markers','sidecars')}
    metadata_raw={}; metadata_json={}
    for group,paths in [('markers',MARKER_PATHS),('sidecars',SIDECAR_PATHS)]:
        for path in paths:
            entry=maps[group][path]
            body=bounded_read(source/path,16384,entry['bytes'],entry['sha256'])
            metadata_raw[path]=body; metadata_json[path]=strict_json(body)
    compressed={}
    for path in ASSET_PATHS:
        entry=maps['assets'][path]
        compressed[path]=bounded_read(source/(path+'.gz'),511999,entry['compressed_bytes'],entry['compressed_sha256'])
    raw={}; parsed={}
    for path in ASSET_PATHS:
        raw[path]=decompress_one(compressed[path],maps['assets'][path])
        if path.endswith('.json'): parsed[path]=strict_json(raw[path])
    checks=relations(raw,parsed,metadata_raw,metadata_json)
    return {'manifest':manifest,'maps':maps,'assets':raw,'metadata_raw':metadata_raw,'metadata_json':metadata_json,'relations':checks}

def inspect_output(source, output, prepared=None):
    source,output=roots(source,output,fresh=False)
    prepared=verified_inputs(source) if prepared is None else prepared
    raw={}
    for path in ASSET_PATHS:
        entry=prepared['maps']['assets'][path]
        raw[path]=bounded_read(output/path,2000000,entry['original_bytes'],entry['original_sha256'])
    for path in MARKER_PATHS:
        entry=prepared['maps']['markers'][path]
        body=bounded_read(output/path,16384,entry['bytes'],entry['sha256'])
        require(body==prepared['metadata_raw'][path],'marker-copy')
    parsed={path:strict_json(body) for path,body in raw.items() if path.endswith('.json')}
    checked=relations(raw,parsed,prepared['metadata_raw'],prepared['metadata_json'])
    allowed=set(ASSET_PATHS)|set(MARKER_PATHS)|{NOTE_PATH,RECEIPT_PATH}
    allowed_dirs={parent.as_posix() for name in allowed for parent in Path(name).parents if parent!=Path('.')}
    found=set();found_dirs=set()
    for path in output.rglob('*'):
        require(not path.is_symlink(),'output-symlink')
        relative=path.relative_to(output).as_posix();mode=path.lstat().st_mode
        if stat.S_ISREG(mode):found.add(relative)
        elif stat.S_ISDIR(mode):
            require(relative in allowed_dirs,'extra-output-directory');found_dirs.add(relative)
        else:raise ContractError('special-output-entry')
    require(found_dirs==allowed_dirs,'output-directory-set')
    require(found.issubset(allowed),'extra-output')
    require((set(ASSET_PATHS)|set(MARKER_PATHS)|{NOTE_PATH}).issubset(found),'missing-output')
    require(bounded_read(output/NOTE_PATH,4096)==NOTE,'inspection-note')
    # Existing receipts never excuse absent/changed historical files.
    if RECEIPT_PATH in found:
        receipt=strict_json(bounded_read(output/RECEIPT_PATH,16384))
        require(receipt.get('status')=='COMPLETE' and receipt.get('scientific_execution_performed') is False,'inspection-receipt')
    return checked

def restore(source, output):
    source,output=roots(source,output,fresh=True)
    prepared=verified_inputs(source)
    # Every input and semantic relation has passed before O is created.
    output.mkdir(exist_ok=False)
    (output/'inspection-metadata').mkdir()
    with (output/NOTE_PATH).open('xb') as stream: stream.write(NOTE)
    values={**prepared['assets'],**{path:prepared['metadata_raw'][path] for path in MARKER_PATHS}}
    for path,body in values.items():
        target=output/path; target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream: stream.write(body)
    checked=inspect_output(source,output,prepared)
    receipt={'status':'COMPLETE','scope':'five-artifact-inspection','scientific_execution_performed':False,
             'source_root':str(source),'output_root':str(output),'descriptor_sha256':H(bounded_read(source/DESCRIPTOR,16384)),
             'files':{path:{'bytes':len(body),'sha256':H(body)} for path,body in values.items()},
             'consumed_relations':checked,'historical_runtime':'Not executed; CORE selection dependency and evaluation-source SHA drift remain unresolved.',
             'completeness':'12 exact historical files only, not whole manifest, checkout, experiment, source closure or branch CI.'}
    body=canonical(receipt); require(len(body)<=16384,'receipt-bound')
    with (output/RECEIPT_PATH).open('xb') as stream: stream.write(body)
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=restore(args.source_root,args.out)
    print(json.dumps({'status':result['status'],'scope':result['scope'],'files':len(result['files']),'scientific_execution_performed':False},sort_keys=True))
