"""Install a verified, fixed Rust toolchain under this task directory only."""
import hashlib
import json
import argparse
from pathlib import Path
import subprocess
import tarfile
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parent
VERSION = '1.95.0'
TARGET = 'x86_64-unknown-linux-gnu'
MANIFEST_URL = f'https://static.rust-lang.org/dist/channel-rust-{VERSION}.toml'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', nargs='+', default=['rustc', 'rust-std', 'cargo', 'rustfmt-preview'])
    args = parser.parse_args()
    tools = ROOT / 'toolchain'
    staging = ROOT / 'toolchain_downloads'
    staging.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MANIFEST_URL, timeout=30) as response:
        manifest_bytes = response.read()
    manifest = tomllib.loads(manifest_bytes.decode())
    previous = ROOT / 'rust_toolchain_provenance.json'
    existing = json.loads(previous.read_text()).get('components', []) if previous.exists() else []
    provenance = {'version': VERSION, 'target': TARGET, 'manifest_url': MANIFEST_URL,
                  'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                  'manifest_date': manifest['date'], 'components': existing}
    for component in args.components:
        entry = manifest['pkg'][component]['target'][TARGET]
        url, expected = entry['xz_url'], entry['xz_hash']
        archive = staging / url.rsplit('/', 1)[1]
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'Official component hash mismatch: {component}')
        with tarfile.open(archive, 'r:xz') as package:
            members = package.getmembers()
            top = members[0].name.split('/')[0]
            package.extractall(staging, filter='data')
            # Verify large members too: the executor's filesystem once yielded
            # a short extracted LLVM library despite a valid archive checksum.
            for member in members:
                target = staging / member.name
                if member.isfile() and target.stat().st_size != member.size:
                    with package.extractfile(member) as source, target.open('wb') as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
                    if target.stat().st_size != member.size:
                        raise RuntimeError(f'Incomplete extraction: {member.name}')
        subprocess.run([str(staging / top / 'install.sh'), '--prefix=' + str(tools),
                        '--disable-ldconfig'], check=True, capture_output=True, text=True)
        provenance['components'] = [item for item in provenance['components'] if item['component'] != component]
        provenance['components'].append({'component': component, 'url': url,
                                        'sha256': actual, 'archive_bytes': archive.stat().st_size})
        print(json.dumps({'installed': component, 'verified_sha256': actual}), flush=True)
    provenance['rustc_version'] = subprocess.check_output([str(tools / 'bin/rustc'), '--version'], text=True).strip()
    provenance['cargo_version'] = subprocess.check_output([str(tools / 'bin/cargo'), '--version'], text=True).strip()
    (ROOT / 'rust_toolchain_provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps({'rustc': provenance['rustc_version'], 'cargo': provenance['cargo_version']}))


if __name__ == '__main__':
    main()
