#!/usr/bin/env python3
"""Read-only offline qualification of an EXACT upstream Matrix SDK git commit.

Inspect manifests only. This neither compiles or executes upstream code nor
confers trust/production authorization. Keeping Git SHA pin verification
separate from Cargo dependency resolution prevents source-substitution claims.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tomllib

from matrix_dependency_gate import version

UPSTREAM_GIT_SHA = 'b3c07ea6ba6e8e46e30811c0500b04505c4be9f9'
EXPECTED_SDK_VERSION = '0.19.1'


def inspect_upstream(source, expected_sha, *, source_head=None):
    if len(expected_sha) != 40 or any(x not in '0123456789abcdef' for x in expected_sha):
        raise ValueError('unverified expected Git SHA')
    if source_head != expected_sha:
        raise ValueError('upstream checkout not at exact, approved commit')
    root = tomllib.loads((source/'Cargo.toml').read_text(encoding='utf-8'))
    sdk = tomllib.loads((source/'crates/matrix-sdk/Cargo.toml').read_text(encoding='utf-8'))
    crypto = tomllib.loads((source/'crates/matrix-sdk-crypto/Cargo.toml').read_text(encoding='utf-8'))
    sqlite = tomllib.loads((source/'crates/matrix-sdk-sqlite/Cargo.toml').read_text(encoding='utf-8'))
    rust = root['workspace']['package']['rust-version']
    sdk_version = sdk['package']['version']
    crypto_version = crypto['package']['version']
    sqlite_version = sqlite['package']['version']
    rusqlite = sqlite['dependencies']['rusqlite']['version']
    deps = sdk.get('dependencies',{})
    blockers = []
    if sdk_version != EXPECTED_SDK_VERSION:
        blockers.append('UPSTREAM_SDK_VERSION_CHANGED')
    if version(crypto_version) < (0,19,0):
        blockers.append('UPSTREAM_CRYPTO_UNPATCHED')
    if 'anymap2' in deps or 'anymap3' not in deps:
        blockers.append('UPSTREAM_ANYMAP3_MIGRATION_MISSING')
    if sqlite_version != sdk_version:
        blockers.append('UPSTREAM_SQLITE_VERSION_SKEW')
    if version(rust) < (1,96,0):
        blockers.append('UPSTREAM_RUST_MSRV_UNEXPECTED')
    return {
        'schema':'hepta.matrix-sdk-source-probe.v1',
        'exact_upstream_sha': source_head,
        'sdk_version':sdk_version,
        'crypto_version':crypto_version,
        'sqlite_version':sqlite_version,
        'rust_msr_version':rust,
        'anymap2_direct': 'anymap2' in deps,
        'anymap3_direct': 'anymap3' in deps,
        'rusqlite_version':rusqlite,
        'manifest_errors':blockers,
        'upstream_manifest_shape_ok': not blockers,
        'cargo_resolution_verified':False,
        'hepta_sdk_api_compatible':False,
        'sqlite_wal_recovery_verified':False,
        'production_authorized':False,
    }


def compare_local(upstream, local_root):
    manifest=tomllib.loads((local_root/'codex-rs/Cargo.toml').read_text(encoding='utf-8'))
    toolchain=tomllib.loads((local_root/'codex-rs/rust-toolchain.toml').read_text(encoding='utf-8'))
    rust=toolchain['toolchain']['channel']
    sysversion=manifest['workspace']['dependencies']['libsqlite3-sys']['version']
    current=manifest['workspace']['dependencies']['matrix-sdk']['version']
    patch=manifest['patch']['crates-io']['matrix-sdk-sqlite']['path']
    issues=[]
    if version(rust) < version(upstream['rust_msr_version']):
        issues.append('LOCAL_RUST_TOOLCHAIN_BELOW_PINNED_UPSTREAM_MSRV')
    if version(sysversion)[:2] != (0,38):
        issues.append('LIBSQLITE3_SYS_037_VS_UPSTREAM_RUSQLITE_040_LINKS_038')
    if current != upstream['sdk_version']:
        issues.append('HEPTA_MATRIX_SDK_RELEASE_NEEDS_MIGRATION')
    if 'matrix-sdk-sqlite-0.18.0' in patch:
        issues.append('HEPTA_SQLITE_PATCH_STILL_018')
    return {**upstream,
        'local_rust':rust,
        'local_libsqlite3_sys':sysversion,
        'local_matrix_sdk_version':current,
        'migration_blockers':issues,
        'migration_ready':False,
        'upstream_source_reviewed':False,
        'full_E2EE_restoration_verified':False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    observed=subprocess.run(['git','-C',str(args.upstream),'rev-parse','HEAD'],
                            capture_output=True,text=True,check=True).stdout.strip()
    report=compare_local(inspect_upstream(args.upstream,args.expected_sha,source_head=observed),args.root)
    args.output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,sort_keys=True,indent=2))
    return 0 if report['upstream_manifest_shape_ok'] else 3


if __name__=='__main__':
    sys.exit(main())
