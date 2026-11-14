#!/usr/bin/env python3
"""Review, stage, or verify the frozen audit package; never invokes Git/network.

Default action only validates the plan against the original source workspace.
Use --stage DEST after review. Existing destination files are never overwritten.
Use --verify-package DEST to check a staged package without original raw logs.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import io
import json
import pathlib
import re
import sys
import urllib.parse

LIMIT = 512_000
PREFIX_ROOT = pathlib.Path('/workspace/scratch/e42bf1712d56')

# Scanner output contains rule/count/path only. It never returns matched values.
SECRET_RULES = {
    'github_token': re.compile(r'(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'aws_access_key_id': re.compile(r'(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])'),
    'provider_secret_token': re.compile(r'(?<![A-Za-z0-9_])(?:sk-(?:proj-|svcacct-|ant-api\d+-)?[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{24,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{30,})'),
    'private_key_block': re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    'bearer_or_basic_credential': re.compile(r'(?i)\bauthorization\b["\s:=]+(?:bearer|basic)\s+([A-Za-z0-9_./+~=-]{20,})'),
    'secret_assignment': re.compile(r'(?im)(?:^|[\s,{])(?:["\']?)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|aws_secret_access_key)(?:["\']?)\s*[:=]\s*["\']?([A-Za-z0-9_./+~=-]{24,})'),
}
URL_PATTERN = re.compile(r'https?://[^\s<>"\'`\\]+')
SIGNED_QUERY_KEYS = {
    'x-amz-signature', 'x-amz-credential', 'x-amz-security-token',
    'x-goog-signature', 'x-goog-credential', 'sig', 'signature',
    'key-pair-id', 'awsaccesskeyid', 'access_token', 'token', 'jwt',
}
PLACEHOLDERS = {'redacted', 'masked', 'placeholder', 'example', 'dummy', 'changeme', 'not-a-real', 'your-api-key', 'your_api_key'}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_rel(value: str) -> pathlib.Path:
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe relative path in manifest')
    return pathlib.Path(*path.parts)


def source_bytes(root: pathlib.Path, relative: str) -> bytes:
    path = root / safe_rel(relative)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Source is missing, non-regular, or symlink: {relative}')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Source escapes selected root: {relative}')
    return path.read_bytes()


def natural_gzip(data: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0, compresslevel=9) as stream:
        stream.write(data)
    return output.getvalue()


def render(data: bytes, transform: str) -> bytes:
    if transform == 'copy':
        return data
    if transform == 'gzip_original_log':
        return natural_gzip(data)
    raise ValueError(f'Unsupported transform: {transform}')


def scan_text(data: bytes, is_gzip: bool = False) -> list[dict]:
    if is_gzip:
        data = gzip.decompress(data)
    # Only text and naturally compressed original text logs are publishable here.
    text = data.decode('utf-8', errors='strict')
    if '\x00' in text:
        raise ValueError('Unexpected binary content in planned text')
    hits = []
    for rule, pattern in SECRET_RULES.items():
        count = 0
        for match in pattern.finditer(text):
            token = match.group(1) if match.lastindex else match.group(0)
            lowered = token.lower()
            if any(marker in lowered for marker in PLACEHOLDERS):
                continue
            count += 1
        if count:
            hits.append({'rule': rule, 'count': count})
    signed_count = 0
    url_text = html.unescape(text).replace('\\u0026', '&').replace('\\u003d', '=').replace('\\/', '/')
    for match in URL_PATTERN.finditer(url_text):
        candidate = match.group(0).replace('&amp;', '&').rstrip('),.;]')
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.username or parsed.password:
            hits.append({'rule': 'url_userinfo', 'count': 1})
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        keys = {key.lower() for key, value in pairs if value}
        for _, value in pairs:
            if value.startswith(('https://', 'http://')):
                keys.update(key.lower() for key, content in urllib.parse.parse_qsl(urllib.parse.urlsplit(value).query) if content)
        if keys.intersection(SIGNED_QUERY_KEYS):
            signed_count += 1
    if signed_count:
        hits.append({'rule': 'signed_or_credential_download_url', 'count': signed_count})
    return hits


def validate_manifest(manifest_path: pathlib.Path) -> tuple[dict, bytes]:
    data = manifest_path.read_bytes()
    if len(data) > LIMIT:
        raise ValueError('Manifest exceeds hard Git blob limit')
    if scan_text(data):
        raise ValueError('Manifest itself has sensitive-pattern findings; values withheld')
    manifest = json.loads(data)
    if manifest['git_blob_hard_limit_bytes'] != LIMIT:
        raise ValueError('Manifest limit is not the fixed 512000-byte policy')
    destinations = [entry['published_path'] for entry in manifest['files']]
    if len(destinations) != len(set(destinations)):
        raise ValueError('Duplicate destination path')
    for entry in manifest['files']:
        safe_rel(entry['source_path'])
        safe_rel(entry['published_path'])
        if entry['published_bytes'] > LIMIT:
            raise ValueError(f'Planned blob exceeds limit: {entry["published_path"]}')
        if entry['scan_findings']:
            raise ValueError(f'Sensitive-pattern finding in selected file: {entry["source_path"]}')
    return manifest, data


def verify_inputs(manifest: dict, source_root: pathlib.Path) -> int:
    total = 0
    for entry in manifest['files']:
        data = source_bytes(source_root, entry['source_path'])
        if len(data) != entry['source_bytes'] or sha256(data) != entry['source_sha256']:
            raise ValueError(f'Frozen source changed: {entry["source_path"]}')
        if scan_text(data, entry['source_path'].endswith('.gz')):
            raise ValueError(f'Sensitive-pattern finding: {entry["source_path"]}; values withheld')
        output = render(data, entry['transform'])
        if len(output) != entry['published_bytes'] or sha256(output) != entry['published_sha256']:
            raise ValueError(f'Output fingerprint changed: {entry["source_path"]}')
        if len(output) > LIMIT:
            raise ValueError(f'Output exceeds hard limit: {entry["source_path"]}')
        total += len(output)
    return total


def verify_package(manifest: dict, manifest_bytes: bytes, destination: pathlib.Path) -> int:
    total = 0
    for entry in manifest['files']:
        data = source_bytes(destination, entry['published_path'])
        if len(data) > LIMIT or len(data) != entry['published_bytes'] or sha256(data) != entry['published_sha256']:
            raise ValueError(f'Published fingerprint/limit mismatch: {entry["published_path"]}')
        if scan_text(data, entry['published_path'].endswith('.gz')):
            raise ValueError(f'Sensitive-pattern finding: {entry["published_path"]}; values withheld')
        if entry['transform'] == 'gzip_original_log' and sha256(gzip.decompress(data)) != entry['source_sha256']:
            raise ValueError(f'Original log identity mismatch: {entry["published_path"]}')
        total += len(data)
    copied_manifest = source_bytes(destination, manifest['manifest_self']['published_path'])
    if copied_manifest != manifest_bytes:
        raise ValueError('Copied manifest differs from reviewed manifest')
    return total + len(copied_manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=pathlib.Path, default=pathlib.Path(__file__).with_name('MANIFEST.json'))
    parser.add_argument('--source-root', type=pathlib.Path, default=PREFIX_ROOT)
    parser.add_argument('--expected-manifest-sha256')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--stage', type=pathlib.Path, metavar='DEST')
    action.add_argument('--verify-package', type=pathlib.Path, metavar='DEST')
    args = parser.parse_args()
    try:
        manifest, manifest_bytes = validate_manifest(args.manifest)
        if args.expected_manifest_sha256 and sha256(manifest_bytes) != args.expected_manifest_sha256:
            raise ValueError('Manifest does not match the review-pinned SHA256')
        if args.verify_package:
            total = verify_package(manifest, manifest_bytes, args.verify_package)
            print(json.dumps({'mode': 'verify_package', 'files': len(manifest['files']) + 1, 'bytes': total, 'status': 'verified'}, ensure_ascii=False))
            return 0
        total = verify_inputs(manifest, args.source_root) + len(manifest_bytes)
        result = {'mode': 'review_only', 'files': len(manifest['files']) + 1, 'bytes': total,
                  'max_blob_bytes': max([len(manifest_bytes)] + [x['published_bytes'] for x in manifest['files']]),
                  'unbundled_references': len(manifest['missing_references']), 'remote_actions': 0}
        if args.stage:
            destination = args.stage.resolve()
            targets = [(entry, destination / safe_rel(entry['published_path'])) for entry in manifest['files']]
            manifest_target = destination / safe_rel(manifest['manifest_self']['published_path'])
            for target in [path for _, path in targets] + [manifest_target]:
                if target.exists() or target.is_symlink():
                    raise ValueError('Refusing to overwrite an existing destination file')
                if not target.resolve().is_relative_to(destination):
                    raise ValueError('Destination escapes package root')
            # All source hashes, scans and destinations are checked before copying.
            for entry, target in targets:
                original = source_bytes(args.source_root, entry['source_path'])
                if sha256(original) != entry['source_sha256']:
                    raise ValueError(f'Source changed during staging: {entry["source_path"]}')
                data = render(original, entry['transform'])
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(data)
            manifest_target.parent.mkdir(parents=True, exist_ok=True)
            with manifest_target.open('xb') as stream:
                stream.write(manifest_bytes)
            total = verify_package(manifest, manifest_bytes, destination)
            result.update(mode='staged', bytes=total, status='verified')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as error:
        # Error messages are paths/rules only; matched credential values are never printed.
        print(f'package validation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
