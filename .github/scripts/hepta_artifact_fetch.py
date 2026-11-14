#!/usr/bin/env python3
"""SHA-pinned original GitHub Actions artifact transport; research-only.

The GitHub REST endpoint is called with the short-lived Actions token. GitHub
responds with an HTTPS signed-blob redirect; that second request MUST NOT carry
GitHub's bearer token. Both the original endpoint and signed URL are validated.
No cached/synthetic replacement is permitted when acquisition fails.
"""

import argparse
import hashlib
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = 'TrillionniumFoundation/hepta-private-ci'
ARCHIVE_ID = 11870475540
EXPECTED_SHA256 = '195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7'
MAX_BYTES = 2_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, reason, headers, newurl):
        return None


def signed_blob_location(url):
    """Validate a server-provided artifact redirect, not a user URL."""
    if not isinstance(url, str) or not url or any(ch in url for ch in ('\r', '\n', '\x00')):
        raise ValueError('missing or malformed signed artifact location')
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or '').lower()
    permitted = (host.endswith('.blob.core.windows.net') or
                 host.endswith('.actions.githubusercontent.com') or
                 host == 'actions.githubusercontent.com')
    if (p.scheme != 'https' or not permitted or p.username is not None or
            p.password is not None or p.port not in (None, 443) or p.fragment or
            not p.path or not p.query):
        raise ValueError('untrusted signed artifact location')
    return url


def download_original(token, output, *, repo=REPO, artifact_id=ARCHIVE_ID,
                      expected_sha=EXPECTED_SHA256, max_bytes=MAX_BYTES,
                      opener=None):
    """Download bounded, verified original archive. Never write on failure."""
    if repo != REPO or type(artifact_id) is not int or artifact_id != ARCHIVE_ID:
        raise ValueError('unexpected repository or original artifact')
    if (not isinstance(token, str) or not token or '\r' in token or '\n' in token or
            not isinstance(expected_sha, str) or
            re.fullmatch(r'[0-9a-f]{64}', expected_sha) is None or
            expected_sha != EXPECTED_SHA256 or
            type(max_bytes) is not int or max_bytes != MAX_BYTES):
        raise ValueError('invalid authentication or immutable source lock')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError('refuse overwrite, replay or symlink destination')
    opener = opener or urllib.request.build_opener(_NoRedirect)
    api = f'https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip'
    req = urllib.request.Request(api, method='GET', headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    # An explicit 302 is expected; never reuse the bearer Request for blob GET.
    try:
        with opener.open(req, timeout=120) as response:
            raise ValueError('GitHub artifact API did not return a signed redirect')
    except urllib.error.HTTPError as exc:
        if exc.code != 302:
            raise ValueError(f'original artifact REST request failed: HTTP {exc.code}') from exc
        location = signed_blob_location(exc.headers.get('Location'))
        exc.close()
    # Independently constructed new request: no Bearer, GitHub auth or headers.
    signed_request = urllib.request.Request(location, method='GET')
    try:
        with opener.open(signed_request, timeout=120) as response:
            if urllib.parse.urlsplit(response.geturl()).hostname != urllib.parse.urlsplit(location).hostname:
                raise ValueError('signed blob unexpectedly redirected')
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'signed blob unavailable: HTTP {exc.code}') from exc
    if len(data) > max_bytes or hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError('missing, oversized or changed original artifact bytes')
    # Atomic create-only destination; a failure can never be a success-shaped ZIP.
    with output.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {'original_artifact_id': artifact_id, 'sha256': expected_sha, 'bytes': len(data)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    token = os.environ.get('GH_TOKEN', '')
    result = download_original(token, args.output)
    print(f"Original artifact {result['original_artifact_id']}: "
          f"SHA256 {result['sha256']}, {result['bytes']} bytes; bearer never sent to blob host")


if __name__ == '__main__':
    main()
