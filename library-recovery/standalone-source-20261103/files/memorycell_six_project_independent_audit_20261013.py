#!/usr/bin/env python3
"""Independent read-only verification of exact Git source bytes in two pinned Actions ZIPs.

Does not execute downloaded code, judge semantic sufficiency, or authorize production.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SOURCE_ZIP_SHA = 'a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4'
REOPEN_ZIP_SHA = '59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36'
SOURCE_MANIFEST_GIT_BLOB = '5c7ba1b6dd4cafb445794346afb21687816f726e'
ORIGINAL_COMMIT = '6ac55532cd3f65d02438cda7f642dc22afb107fe'
REPO_ID = 'TrillionniumFoundation/hepta-private-ci'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_digest(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def strict_json(raw):
    def object_pairs(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError('duplicate JSON field')
            d[k] = v
        return d
    def invalid(x):
        raise ValueError('nonfinite number')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=object_pairs, parse_constant=invalid)


def sealed(zip_path, expected_sha, maximum=16 * 1024 * 1024):
    raw = zip_path.read_bytes()
    if digest(raw) != expected_sha or len(raw) > maximum:
        raise ValueError('outer artifact ZIP byte pin mismatch or size exceeded')
    with zipfile.ZipFile(zip_path) as z:
        members = {}
        total = 0
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            if (p.is_absolute() or '..' in p.parts or '\\' in info.filename
                or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16)
                or info.filename in members):
                raise ValueError('unsafe or duplicate ZIP member')
            total += info.file_size
            if total > 32 * 1024 * 1024 or len(members) >= 128:
                raise ValueError('archive physical census exceeded')
            members[info.filename] = z.read(info)
    manifest = members.get('SHA256SUMS')
    if manifest is None:
        raise ValueError('missing SHA256SUMS')
    listed = set()
    for line in manifest.decode('utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (?:\./)?(.+)', line)
        if match is None:
            raise ValueError('invalid SHA256SUMS line')
        expect, name = match.groups()
        if name in listed or name == 'SHA256SUMS' or name not in members:
            raise ValueError('invalid SHA256SUMS member census')
        listed.add(name)
        if digest(members[name]) != expect:
            raise ValueError('SHA256SUMS member tampered')
    if listed != set(members) - {'SHA256SUMS'}:
        raise ValueError('incomplete manifest')
    return members


def audit(source_path, replay_path):
    src = sealed(source_path, SOURCE_ZIP_SHA)
    rep = sealed(replay_path, REOPEN_ZIP_SHA)
    if src['tested-commit.txt'].decode().strip() != ORIGINAL_COMMIT:
        raise ValueError('source-generating SHA mismatch')
    if rep['reopened-source-commit.txt'].decode().strip() != ORIGINAL_COMMIT:
        raise ValueError('independent checker source SHA mismatch')
    inv_raw = src['original/inventory.json']
    inv = strict_json(inv_raw)
    ready = strict_json(src['original/READY.json'])
    r1 = strict_json(src['reopen.log'])
    r2 = strict_json(rep['reopen.log'])
    if r1 != r2:
        raise ValueError('independent-reopen receipt differs')
    if (ready['inventory_sha256'] != digest(inv_raw)
        or ready['source_manifest_git_blob_sha1'] != SOURCE_MANIFEST_GIT_BLOB
        or inv['source_manifest_git_blob_sha1'] != SOURCE_MANIFEST_GIT_BLOB
        or inv['original_file_bindings'] != 32
        or ready['verified_file_bindings'] != 32
        or inv['original_commit_objects'] != 14
        or ready['verified_commit_objects'] != 14
        or inv['source_family_proxies'] != 6
        or inv['total_original_bytes'] != 1558460
        or r2['verified_original_byte_count'] != inv['total_original_bytes']
        or r2['verified_original_file_bindings'] != 32
        or r2['verified_original_commit_objects'] != 14
        or r2['original_binary_reopen_completed'] is not True):
        raise ValueError('source/independent-reopen census differs')
    rows = inv['files']
    if not isinstance(rows, list) or len(rows) != 32:
        raise ValueError('invalid file census')
    names = set()
    total = 0
    non_utf8 = []
    repos = set()
    for record in rows:
        sha = record['blob_sha']
        name = 'original/blobs/' + sha + '.blob'
        if name in names or not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('duplicate/invalid file identity')
        names.add(name)
        raw = src[name]
        if (git_digest(raw) != sha or digest(raw) != record['sha256']
            or len(raw) != record['bytes']):
            raise ValueError('original file byte hash differs')
        repos.add(record['repo'])
        total += len(raw)
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError:
            non_utf8.append(sha)
    recorded_blob_names = {k for k in src if k.startswith('original/blobs/')}
    if (names != recorded_blob_names or len(repos) != 6
        or total != 1558460 or len(non_utf8) != 1
        or non_utf8 != ['a772b57bdd5aa26fbedd07cb057b9006239e784e']
        or inv['non_utf8_original_blobs'] != 1):
        raise ValueError('source identity count, original bytes or encoding census differs')
    if (any(x.get('production_accepted') is not False for x in (ready, inv, r1, r2))
        or inv['independent_semantic_review'] is not False
        or inv['model_calls'] != 0):
        raise ValueError('research source cannot be promoted')
    return {
        'schema':'hepta.memory-cell.six-project-independent-byte-audit.v1',
        'source_repo':REPO_ID,
        'generating_commit':ORIGINAL_COMMIT,
        'source_run_id':38320847158,
        'source_artifact_id':11778273351,
        'source_zip_sha256':SOURCE_ZIP_SHA,
        'independent_reopen_artifact_id':11779107585,
        'independent_reopen_zip_sha256':REOPEN_ZIP_SHA,
        'source_manifest_git_blob_sha1':SOURCE_MANIFEST_GIT_BLOB,
        'inventory_sha256':digest(inv_raw),
        'source_manifest_members':len(src)-1,
        'reopen_manifest_members':len(rep)-1,
        'source_family_proxies':len(repos),
        'verified_commit_objects':14,
        'verified_original_blob_files':len(rows),
        'verified_original_bytes':total,
        'non_utf8_original_blobs':len(non_utf8),
        'latin1_blob_sha1':non_utf8[0],
        'independent_reopen_verified':True,
        'origin_git_blob_sha1_and_raw_sha256_rehashed':True,
        'original_source_bytes_are_complete':True,
        'historical_review_discussions_complete':False,
        'source_sufficiency_independently_judged':False,
        'new_reader_inference_calls':0,
        'independent_future_window_authenticated':False,
        'parametric_training_qualified':False,
        'production_accepted':False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('reopen', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = audit(args.source,args.reopen)
    with args.output.open('x', encoding='utf-8') as target:
        json.dump(result,target,ensure_ascii=False,sort_keys=True,indent=2)
        target.write('\n')
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))

if __name__=='__main__':
    main()
