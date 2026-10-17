"""Read-only download of strictly registered Actions ZIP bytes, without auth redirects."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

SHA = re.compile(r'[0-9a-f]{64}\Z')
ROLES = ('source_v3', 'source_v4', 'granite47', 'granite97', 'mmbert140', 'cheap_v4')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        return None


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def get_api_json(url, token):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'hepta-stem-original-artifact-v5'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read(16384))


def download_one(repo, token, meta, output):
    require(re.fullmatch(r'TrillionniumFoundation/hepta-private-ci', repo) is not None,
            'unexpected repo owner')
    require(type(meta) is dict and set(meta) == {'run_id', 'artifact_id', 'archive_sha256',
            'json_member', 'json_sha256'}, 'incomplete artifact identity')
    require(type(meta['artifact_id']) is int and meta['artifact_id'] > 0 and
            type(meta['run_id']) is int and meta['run_id'] > 0 and
            type(meta['archive_sha256']) is str and SHA.fullmatch(meta['archive_sha256']) and
            type(meta['json_sha256']) is str and SHA.fullmatch(meta['json_sha256']),
            'pending, unsigned or unpinned original archive')
    root = f'https://api.github.com/repos/{repo}/actions/artifacts/{meta["artifact_id"]}'
    info = get_api_json(root, token)
    require(info.get('id') == meta['artifact_id'] and info.get('expired') is False and
            info.get('workflow_run', {}).get('id') == meta['run_id'],
            'original artifact id/run ownership mismatch')
    digest = info.get('digest')
    require(digest is None or digest == 'sha256:' + meta['archive_sha256'],
            'GitHub original ZIP metadata digest changed')
    opener = urllib.request.build_opener(NoRedirect())
    req = urllib.request.Request(root + '/zip', headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'hepta-stem-original-artifact-v5'})
    try:
        with opener.open(req, timeout=30):
            raise ValueError('original API did not return expected external redirect')
    except urllib.error.HTTPError as error:
        require(error.code in (302, 303, 307, 308), 'unexpected GitHub download response')
        target = error.headers.get('Location')
    require(type(target) is str, 'missing original GitHub archive Location')
    parsed = urllib.parse.urlsplit(target)
    require(parsed.scheme == 'https' and parsed.username is None and parsed.password is None and
            parsed.port is None and parsed.hostname and
            (parsed.hostname.endswith('.actions.githubusercontent.com') or
             parsed.hostname.endswith('.blob.core.windows.net') or
             parsed.hostname.endswith('.githubusercontent.com')),
            'unexpected original archive storage host')
    # Do not carry the GitHub authorization header to the signed external URL.
    with urllib.request.urlopen(urllib.request.Request(target, headers={
            'User-Agent': 'hepta-stem-original-artifact-v5'}), timeout=60) as response:
        raw = response.read(65537)
    require(0 < len(raw) <= 65536 and
            hashlib.sha256(raw).hexdigest() == meta['archive_sha256'],
            'original complete ZIP changed, oversized or unavailable')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as dest:
        dest.write(raw)
    return {'id': meta['artifact_id'], 'run_id': meta['run_id'],
            'complete_archive_sha256': meta['archive_sha256'], 'bytes': len(raw)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--role', choices=ROLES, required=True, action='append')
    args = p.parse_args()
    repo = os.environ.get('GITHUB_REPOSITORY')
    token = os.environ.get('GH_TOKEN')
    require(repo == 'TrillionniumFoundation/hepta-private-ci' and
            type(token) is str and len(token) > 20, 'missing read-only GitHub artifact owner')
    lock = json.loads(Path(args.manifest).read_text())
    require(lock.get('schema') == 'hepta.stem.original-hard-charge.lock.v5' and
            lock.get('authority') == 'DENY_ALL', 'wrong research artifact registry')
    result = {}
    for role in args.role:
        require(role not in result, 'duplicate artifact role')
        result[role] = download_one(repo, token, lock['artifacts'][role],
                                    Path(args.output_dir) / (role + '.zip'))
    print(json.dumps({'original_archive_custody': result,
                      'production_authorized': False, 'authority': 'DENY_ALL'}, sort_keys=True))


if __name__ == '__main__':
    main()
