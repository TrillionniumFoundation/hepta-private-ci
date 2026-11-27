"""Prepare two fixed public parents and the exact source47 ABSTAIN receipt.

Only stdlib parsing and exact-byte checks. Never execute the submitted payload,
import Torch, extract test.npz, calculate a model output, or choose a parent.
"""
import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import time
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
SEEDS = (83, 137)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_bytes(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write(path, value):
    write_bytes(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode())


def checked(raw, expected):
    if len(raw) != expected['bytes'] or sha(raw) != expected['sha256']:
        raise ValueError('exact public byte commitment differs')
    return raw


def fetch(item):
    repo = 'TrillionniumFoundation/hepta-private-ci'
    url = 'https://raw.githubusercontent.com/'+repo+'/'+item['commit']+'/'+item['path']
    request = urllib.request.Request(url, headers={'User-Agent': 'hepta-boundary-transfer-public-research'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.geturl() != url:
            raise ValueError('public URL redirected outside its exact source')
        raw = response.read(item['bytes']+1)
    checked(raw, item)
    blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if blob != item['git_blob']:
        raise ValueError('public Git blob differs')
    return raw


def members(raw, expected, member_cap=262144):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise ValueError('bounded ZIP members differ from the complete allowlist')
    for item in archive.infolist():
        path, mode = Path(item.filename), item.external_attr >> 16
        if (path.is_absolute() or '..' in path.parts or item.is_dir() or item.file_size > member_cap or
                stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
            raise ValueError('unsafe bounded ZIP member')
    return archive


def prepare(binding_path, archive_path, destination):
    start, cpu = time.monotonic(), time.process_time()
    binding = json.loads(binding_path.read_text())
    if binding['status'] != 'FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW' or binding['parent_order'] != [83,137]:
        raise ValueError('unreviewed transfer identity or changed parent order')
    for name, item in binding['adapter_files'].items():
        checked((HERE/name).read_bytes(), item)
    destination.mkdir(parents=True, exist_ok=False)
    original = checked(archive_path.read_bytes(), binding['predecessor_artifact'])
    archive = members(original, binding['predecessor_artifact']['files'], 1048576)
    for name, item in binding['predecessor_artifact']['files'].items():
        checked(archive.read(name), item)
    source = destination/'source47'
    source.mkdir(exist_ok=False)
    for name, item in binding['source_abstention_files'].items():
        write_bytes(source/name, checked(archive.read(item['archive_member']), item))
    result = json.loads((source/'RESULT.json').read_text())
    if (result['status'] != 'ABSTAIN_OR_ABORTED' or result['error'] != "Abstain('MULTIPLE_CERTIFIED_ROOTS')" or
            any(result['counts'][key] != 0 for key in ('forwards','backwards','analytic_solves','optimizer_steps'))):
        raise ValueError('exact source47 unavailable-COPY condition differs')
    manifests = {}
    for seed in SEEDS:
        manifests[seed] = json.loads(checked((HERE/('public_inputs_seed%d.json'%seed)).read_bytes(),
                                           binding['parent_manifests'][str(seed)]))
    shared = manifests[83]
    common = ('source_commit','inputs','data_contract','payload_script','inner_zip_sha256','payload_members',
              'normalizer_sha256','normalizer_f32_le_hex','aliases')
    if any(manifests[137][key] != shared[key] for key in common):
        raise ValueError('declared parents do not share the frozen public source/data')
    public, receipts = {}, []
    for item in shared['inputs']:
        spec = dict(item, commit=shared['source_commit'])
        raw = fetch(spec)
        public[Path(item['path']).name] = raw
        receipts.append(dict(path=item['path'], bytes=len(raw), sha256=sha(raw), git_blob=item['git_blob']))
    contract = fetch(shared['data_contract'])
    erratum = json.loads(contract)['source_integrity_erratum']
    if (erratum['excluded_actor_emotion'] != [[7,3]] or
            erratum['expected_queries'] != dict(train=80,dev=32,retain=28,test=48)):
        raise ValueError('frozen public exclusion contract differs')
    receipts.append(dict(shared['data_contract'], source_integrity_verified=True))
    outer = members(public['t4_payload.zip'], {'t4_submitted.py'})
    submitted = checked(outer.read('t4_submitted.py'), shared['payload_script'])
    constants = [node.value for node in ast.walk(ast.parse(submitted))
                 if isinstance(node,ast.Constant) and isinstance(node.value,bytes)]
    if len(constants) != 1:
        raise ValueError('exactly one static payload bytes literal required')
    inner = base64.b64decode(constants[0], validate=True)
    if sha(inner) != shared['inner_zip_sha256']:
        raise ValueError('static inner payload ZIP differs')
    listing = {item['path']:item for item in shared['payload_members']}
    payload = members(inner, listing)
    # The bounded outer checkpoint ZIP is hash-pinned; only the declared
    # two parents and original seal are read, never any other arm/checkpoint.
    checkpoints = zipfile.ZipFile(io.BytesIO(public['selected_checkpoints.zip']))
    if len(checkpoints.namelist()) != len(set(checkpoints.namelist())):
        raise ValueError('duplicate checkpoint archive members')
    history = json.loads(public['lowlevel_results.json'])
    prepared = []
    for seed in SEEDS:
        manifest = manifests[seed]
        parent = destination/('parent%d'%seed)
        parent.mkdir(exist_ok=False)
        write_bytes(parent/'data_contract.json', contract)
        for name,item in listing.items():
            if name == 'data/test.npz':
                continue
            raw = checked(payload.read(name), item)
            target = parent/'source'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            write_bytes(target, raw)
        spec = manifest['checkpoint']
        raw = checked(checkpoints.read(spec['archive_member']), spec)
        seal = checkpoints.read(spec['seal_member'])
        if sha(seal) != spec['seal_sha256'] or json.loads(seal)['centered_%d'%seed] != sha(raw):
            raise ValueError('original parent checkpoint seal differs')
        write_bytes(parent/'parent.pt', raw)
        fit = [row for row in history['rows'] if row['mode']=='fit' and row['arm']=='centered' and row['seed']==seed]
        evaluation = [row for row in history['rows'] if row['mode']=='eval' and row['arm']=='centered' and row['seed']==seed]
        if len(fit)!=1 or len(evaluation)!=1 or fit[0]['checkpoint'] != spec['sha256']:
            raise ValueError('unique historical parent identity differs')
        write(parent/'golden_retain.json', evaluation[0]['retain'])
        golden = checked((parent/'golden_retain.json').read_bytes(), manifest['golden_retain_export'])
        receipt = dict(schema='hepta.boundary-transfer-public-prepared.v1', seed=seed,
            input_manifest_sha256=binding['parent_manifests'][str(seed)]['sha256'],
            inputs=receipts, golden_retain_sha256=sha(golden), parent_sha256=sha(raw),
            source47_result_sha256=binding['source_abstention_files']['RESULT.json']['sha256'],
            historical_test_fields_used=False, test_npz_extracted=False, submitted_script_executed=False,
            model_calls=0, candidate_fits=0, parent_source_copied_as_regular_files=True)
        write(parent/'PREPARED.json', receipt)
        prepared.append(receipt)
    write(destination/'PREPARED.json', dict(schema='hepta.boundary-transfer-all-prepared.v1',
        binding_sha256=sha(binding_path.read_bytes()), fixed_parent_order=list(SEEDS),
        prepared=prepared, public_downloads=4, artifact_download_retries=0,
        source47_copy_unavailable=True, model_calls=0, fits=0, test_calls=0,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-start))


if __name__ == '__main__':
    if len(sys.argv)!=5:
        raise SystemExit('prepare_public.py BINDING SOURCE47_ZIP NEW_PREPARED NEW_RECEIPT')
    binding_path, archive_path, destination, receipt_path = (Path(value).resolve() for value in sys.argv[1:])
    try:
        prepare(binding_path, archive_path, destination)
    except BaseException as error:
        write(receipt_path, dict(status='FAILED_BEFORE_MODEL', error=repr(error),
              model_calls=0, fits=0, retries=0, partial_inputs_may_exist=True))
        raise
    else:
        write(receipt_path, dict(status='PREPARED', model_calls=0, fits=0, retries=0,
              aggregate_preparation_receipt_sha256=sha((destination/'PREPARED.json').read_bytes())))
