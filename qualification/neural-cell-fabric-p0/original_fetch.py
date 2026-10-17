"""Strict original Actions ZIP downloader. No credential forwarding on redirects.

Downloads only four immutable archived artifacts from THIS original repository;
never fetches model weights. The authenticated GitHub API request deliberately
rejects redirect-following, then a fresh token-free opener retrieves the ZIP.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import stat
import urllib.error
import urllib.parse
import urllib.request

REPO = 'TrillionniumFoundation/hepta-private-ci'
ARTIFACTS = {
    'agnews': (11890616195, '0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'),
    'features': (12083071509, '3d8d6b7bed80f1f5efb1a17fd1df94208bef4239e5bbbbcd29e63262fb6e025d'),
    'trial': (12083091720, '8bd2d2ba3b2de9f2fe1b99042b471c016d78f90c8305d7d82c91bf1a23138bed'),
    'targets': (12080419743, '140191b7915923b51a447c9cabc43d6dbba96060ae4dee90716f1fd2539821fb'),
    'public': (12080649303, '51e258a7a721a03f402e6606cffb57f52e5ee35a458f5f75218eaafabd9fe698'),
}


class ArtifactDenied(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_blob_url(location: str) -> str:
    """Accept only trusted, HTTPS, tokenless archive delivery endpoints."""
    if type(location) is not str or not 1 <= len(location) <= 8192:
        raise ArtifactDenied('invalid archive redirect')
    url = urllib.parse.urlsplit(location)
    hostname = url.hostname or ''
    allowed = (hostname.endswith('.blob.core.windows.net') or
               hostname.endswith('.actions.githubusercontent.com') or
               hostname == 'actions.githubusercontent.com')
    if not (url.scheme == 'https' and allowed and not url.username and not url.password
            and url.port in (None, 443) and not url.fragment):
        raise ArtifactDenied('archive redirect hostname or scheme not authorized')
    return location


def download_original(kind: str, out: Path, token: str) -> dict:
    if kind not in ARTIFACTS or not token or not isinstance(token, str):
        raise ArtifactDenied('missing registered kind or GitHub token')
    if (out.exists() or out.is_symlink() or out.parent.is_symlink() or
            not out.parent.is_dir() or stat.S_IMODE(out.parent.stat().st_mode) & 0o077):
        raise ArtifactDenied('output parent must be private and create-only')
    number, digest = ARTIFACTS[kind]
    uri = f'https://api.github.com/repos/{REPO}/actions/artifacts/{number}/zip'
    auth = urllib.request.Request(uri, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'Hepta-P04-Source-Locked-Research',
    })
    opener = urllib.request.build_opener(NoRedirect())
    try:
        # The explicit no-redirect handler is essential: NEVER send GitHub
        # authorization to a temporary cloud blob URL.
        try:
            with opener.open(auth, timeout=30) as response:
                if response.status not in (301, 302, 303, 307, 308):
                    raise ArtifactDenied('expected artifact location redirect')
                location = response.headers.get('Location')
        except urllib.error.HTTPError as response:
            if response.code not in (301, 302, 303, 307, 308):
                raise ArtifactDenied('GitHub Actions archive request failed') from None
            location = response.headers.get('Location')
        safe_blob_url(location)
        # A completely NEW request has no authorization, cookies, or token.
        clean = urllib.request.Request(location, headers={
            'User-Agent': 'Hepta-P04-Artifact-Bytes',
        })
        with opener.open(clean, timeout=90) as response:
            if response.status != 200:
                raise ArtifactDenied('non-200 archive blob')
            payload = response.read(2_000_001)
        if len(payload) > 2_000_000 or hashlib.sha256(payload).hexdigest() != digest:
            raise ArtifactDenied('immutable original ZIP checksum mismatch')
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        return {'artifact_id': number, 'sha256': digest, 'bytes': len(payload),
                'authority': 'DENY_ALL'}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ArtifactDenied('original artifact retrieval not verified') from e


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--kind', choices=sorted(ARTIFACTS), required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    token = os.getenv('GH_TOKEN', '')
    if os.getenv('GITHUB_REPOSITORY', REPO) != REPO:
        raise ArtifactDenied('cross-repository source denied')
    print(download_original(args.kind, args.out, token))


if __name__ == '__main__':
    main()
