"""Fixed official Bazel payloads; no Bazelisk selection, cache fallback, or rc wrapper."""
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import urllib.parse
import urllib.request

from a32_sshsig_guard import digest, require, save

VERSION = '9.3.0'
RELEASE_METADATA_SHA256 = '151d6053a623bbe8a59a94006154c298abca1dff24e99c5f212c18e16bc8599b'
ASSETS = {
    'linux': {'name': 'bazel-9.3.0-linux-x86_64', 'bytes': 77023347,
              'sha256': 'd302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8'},
    'win32': {'name': 'bazel-9.3.0-windows-x86_64.exe', 'bytes': 68435391,
              'sha256': '64aff24f986df98291f4da2795fd4b3e831c0af3f74bd7aa8eb56c49cb28b1e3'},
}


class ReleaseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        parsed = urllib.parse.urlparse(url)
        require(parsed.scheme == 'https' and parsed.hostname in
                {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
                and parsed.username is None and parsed.password is None and parsed.port in (None, 443),
                'unexpected official release redirect')
        return super().redirect_request(request, fp, code, message, headers, url)


def payload(platform, opener=None):
    require(platform in ASSETS, 'unsupported Bazel host')
    asset = ASSETS[platform]
    url = 'https://github.com/bazelbuild/bazel/releases/download/' + VERSION + '/' + asset['name']
    opener = opener or urllib.request.build_opener(ReleaseRedirects()).open
    # Network deadline only: no subprocess timeout or termination path.
    with opener(url, timeout=120) as stream:
        raw = stream.read(asset['bytes'] + 1)
    require(len(raw) == asset['bytes'] and digest(raw) == asset['sha256'], 'Bazel payload size/hash mismatch')
    require(raw.startswith(b'\x7fELF' if platform == 'linux' else b'MZ'), 'unexpected Bazel executable format')
    return raw, {'url': url, **asset}


def configure(output_base, platform, env, home):
    # Match the removed action's config.js/index.js: overwrite home .bazelrc;
    # Windows also writes HOME/.bazelrc. All its optional caches were disabled.
    targets = [home / '.bazelrc']
    if platform == 'win32' and env.get('HOME'):
        targets.append(Path(env['HOME']) / '.bazelrc')
    value = str(output_base).replace('\\', '/')
    require(value and not any(char.isspace() for char in value), 'unsupported output-base rc whitespace')
    raw = ('startup --output_base=' + value + '\n').encode()
    seen, rows = set(), []
    for target in targets:
        require(target.is_absolute() and target.parent.is_dir() and not target.is_symlink(), 'unsupported Bazel home rc target')
        key = os.path.normcase(str(target.resolve()))
        if key in seen:
            continue
        seen.add(key)
        previous = None
        if target.exists():
            status = target.stat()
            require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1, 'nonregular/shared existing home rc')
            before = target.read_bytes()
            previous = {'bytes': len(before), 'sha256': digest(before)}
        target.write_bytes(raw)
        require(target.read_bytes() == raw, 'Bazel rc readback mismatch')
        rows.append({'path': str(target), 'before': previous, 'bytes': len(raw), 'sha256': digest(raw)})
    return rows


def install(q):
    q.guard()
    require(sys.platform in ASSETS and q.state['runner_arch'] == 'X64', 'Bazel release requires native X64 host')
    build = Path(os.environ['RUNNER_TEMP']) / 'a32-b'
    require(build.is_dir() and not build.is_symlink(), 'existing isolated build root required')
    require(Path(os.environ['BAZEL_OUTPUT_BASE']) == build / 'o', 'Bazel output-base differs from isolated paths')
    require(not build.is_relative_to(q.root) and not build.is_relative_to(q.evidence), 'tool must remain outside source/evidence')
    folder = build / 'bazel-bin'
    folder.mkdir()  # No implicit retry/reuse of any earlier payload.
    raw, record = payload(sys.platform)
    binary = folder / ('bazel.exe' if sys.platform == 'win32' else 'bazel')
    with binary.open('xb') as stream:
        stream.write(raw)
    if sys.platform == 'linux':
        binary.chmod(0o755)  # Only this newly created ordinary user tool.
    home = Path(os.environ['USERPROFILE']) if sys.platform == 'win32' else Path.home()
    record.update(schema='a32.sshsig-fixed-bazel.v1', platform=sys.platform, version=VERSION, binary_path=str(binary),
                  release_metadata_sha256=RELEASE_METADATA_SHA256, bazelisk_used=False,
                  home_rc=configure(build / 'o', sys.platform, os.environ, home), caches_enabled=False)
    save(q.evidence / 'bazel-installation.json', record)
    output = q.run('install-bazel-version', [str(binary), '--version'])
    require(output.decode().strip() == 'bazel ' + VERSION, 'wrong pinned Bazel binary version')
    require(binary.read_bytes() == raw, 'Bazel payload changed during version query')
    record['version_observed'] = output.decode().strip()
    record['binary_rechecked_after_version'] = True
    save(q.evidence / 'bazel-installation.json', record)
    with open(os.environ['GITHUB_PATH'], 'a', encoding='utf-8') as stream:
        print(str(folder), file=stream)
    q.guard()


def verify_installation(q):
    record = json.loads((q.evidence / 'bazel-installation.json').read_bytes())
    require(record['platform'] == sys.platform and record['version_observed'] == 'bazel ' + VERSION,
            'missing/wrong pinned Bazel installation')
    selected = shutil.which('bazel')
    binary = Path(record['binary_path'])
    require(selected and Path(selected).resolve() == binary.resolve() and binary.is_file() and not binary.is_symlink(),
            'PATH no longer selects the pinned Bazel payload')
    raw = binary.read_bytes()
    require(len(raw) == ASSETS[sys.platform]['bytes'] and digest(raw) == ASSETS[sys.platform]['sha256'],
            'selected Bazel payload changed')
    for row in record['home_rc']:
        target = Path(row['path'])
        require(not target.is_symlink() and target.is_file() and target.stat().st_nlink == 1, 'home rc representation changed')
        raw = target.read_bytes()
        require(len(raw) == row['bytes'] and digest(raw) == row['sha256'], 'Bazel home rc changed')


def receipt(folder, platform):
    record = json.loads((folder / 'bazel-installation.json').read_bytes())
    asset = ASSETS[platform]
    require(record.get('schema') == 'a32.sshsig-fixed-bazel.v1' and record.get('platform') == platform
            and all(record.get(key) == value for key, value in asset.items())
            and record.get('url') == 'https://github.com/bazelbuild/bazel/releases/download/' + VERSION + '/' + asset['name']
            and record.get('version') == VERSION and record.get('version_observed') == 'bazel ' + VERSION
            and record.get('release_metadata_sha256') == RELEASE_METADATA_SHA256
            and record.get('binary_rechecked_after_version') is True
            and record.get('bazelisk_used') is False and record.get('caches_enabled') is False
            and record.get('binary_path') and record.get('home_rc'), 'incomplete/wrong fixed Bazel receipt')
    require((folder / 'logs/install-bazel-version.log').read_text().strip() == 'bazel ' + VERSION,
            'Bazel installation version log differs')
    return record
