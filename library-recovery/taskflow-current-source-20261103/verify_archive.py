#!/usr/bin/env python3
"""Verify exact source bytes in a TaskFlow preservation archive without executing them."""
import argparse
import hashlib
import json
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('archive')
args = parser.parse_args()
with tarfile.open(args.archive, 'r:gz') as archive:
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(names) != len(set(names)):
        raise SystemExit('duplicate archive member names')
    manifest = json.load(archive.extractfile('SOURCE_MANIFEST.json'))
    checked = 0
    for item in manifest['objects']:
        member = archive.getmember(item['object_path'])
        if not member.isfile():
            raise SystemExit('source object is not a regular file')
        data = archive.extractfile(member).read()
        identity = (len(data), hashlib.sha256(data).hexdigest(),
                    hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest())
        expected = (item['bytes'], item['sha256'], item['git_blob_sha1'])
        if identity != expected:
            raise SystemExit('source identity mismatch: ' + item['object_path'])
        checked += 1
    if checked != manifest['unique_source_objects']:
        raise SystemExit('source count mismatch')
print(json.dumps({'source_members_verified': checked, 'source_executed': False}))
