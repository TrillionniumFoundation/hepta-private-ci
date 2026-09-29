#!/usr/bin/env python3
"""Materialize a diagnostic Cargo closure of unchanged on-disk Rust sources.

This is not the product workspace, an alternate executor, or target-host
qualification. It compiles the real owner, mailbox, port and Unix vault files
with their real core implementation. The generated manifests and lockfile are
retained with CI artifacts so dependency/feature scope cannot be hidden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def materialize(output: Path) -> None:
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("diagnostic inputs must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    packages = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())["package"]

    def version(name: str, prefix: str = "") -> str:
        matches = [p["version"] for p in packages if p["name"] == name and p["version"].startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"ambiguous locked dependency {name}: {matches}")
        return "=" + matches[0]

    def dependency(name: str, prefix: str = "", features: tuple = ()) -> str:
        return f'{name} = {{ version = {json.dumps(version(name, prefix))}, features = {json.dumps(features)} }}\n'

    def path(value: Path) -> str:
        return json.dumps(str(value))

    core = ROOT / "codex-rs/hepta-infer-core"
    host = ROOT / "codex-rs/hepta-infer-worker-host"
    header = '[package]\nversion = "0.0.0"\nedition = "2024"\npublish = false\nautotests = false\nautobins = false\n'
    core_manifest = header + 'name = "codex-hepta-infer-core"\n[lib]\nname = "codex_hepta_infer_core"\ndoctest = false\npath = ' + path(core / "src/lib.rs") + '\n[dependencies]\n'
    core_manifest += 'codex-hepta-types = { path = ' + path(ROOT / "codex-rs/hepta-types") + ' }\n'
    core_manifest += dependency('serde', features=('derive', 'rc')) + dependency('serde_json') + dependency('sha2', '0.10.') + dependency('ed25519-dalek')
    for source in sorted((core / "tests").glob('*.rs')):
        core_manifest += '\n[[test]]\nname = ' + json.dumps(source.stem) + '\npath = ' + path(source) + '\n'
    for source in sorted((core / "src/bin").glob('*.rs')):
        core_manifest += '\n[[bin]]\nname = ' + json.dumps(source.stem) + '\npath = ' + path(source) + '\n'
    (output / 'core').mkdir()
    (output / 'core/Cargo.toml').write_text(core_manifest)
    modules = ['actor_latency', 'actor_mailbox', 'actor_policy', 'actor_observation',
               'control_actor', 'control_port', 'output_protection', 'unix_output_protector']
    wrapper = '#![forbid(unsafe_code)]\n' + ''.join(f'#[path = {path(host / "src" / (name + ".rs"))}]\npub mod {name};\n' for name in modules)
    wrapper += 'pub use control_actor::{NativeJournalWriterActor, NativeControlActorError};\n'
    (output / 'host').mkdir()
    (output / 'host/lib.rs').write_text(wrapper)
    host_manifest = header + 'name = "codex-hepta-infer-worker-host"\n[lib]\nname = "codex_hepta_infer_worker_host"\ndoctest = false\npath = "lib.rs"\n[dependencies]\n'
    host_manifest += 'codex-hepta-infer-core = { path = "../core" }\n'
    host_manifest += dependency('serde', features=('derive', 'rc')) + dependency('serde_json') + dependency('sha2', '0.10.')
    host_manifest += dependency('async-trait') + dependency('libc') + dependency('rustix', '1.', ('process', 'net'))
    host_manifest += dependency('tokio', features=('io-util', 'macros', 'net', 'rt-multi-thread', 'sync', 'time'))
    host_manifest += '[dev-dependencies]\n' + dependency('tempfile') + dependency('ed25519-dalek')
    host_manifest += '\n[[test]]\nname = "production_actor"\npath = ' + path(host / 'tests/control_actor.rs') + '\n'
    (output / 'host/Cargo.toml').write_text(host_manifest)
    (output / 'Cargo.toml').write_text('[workspace]\nmembers = ["core", "host"]\nresolver = "2"\n')
    source_files = sorted(set(core.rglob('*.rs')) | set(host.rglob('*.rs')))
    identity = {
        'schema': 'hepta.inference-control-boundary-diagnostic.v1',
        'scope': 'original-selected-sources-minimal-dependency-closure',
        'sourceSha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'sourceTree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip(),
        'sourceFileSha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        'claims': {'productWorkspaceQualified': False, 'targetHostQualified': False, 'release': False},
    }
    (output / 'source-scope.json').write_text(json.dumps(identity, indent=2) + '\n')
    print(json.dumps({'diagnosticManifest': str(output / 'Cargo.toml'), 'scope': identity['scope']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    materialize(args.output)
