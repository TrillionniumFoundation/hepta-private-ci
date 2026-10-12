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
    workspace=manifest['workspace']['dependencies']
    sysversion=workspace['libsqlite3-sys']['version']
    local_sdk=workspace['matrix-sdk']
    current=local_sdk['version']
    patches=manifest.get('patch',{}).get('crates-io',{})
    sqlite_patch=patches.get('matrix-sdk-sqlite')
    sdk_patch=patches.get('matrix-sdk')
    issues=[]
    if version(rust) < version(upstream['rust_msr_version']):
        issues.append('LOCAL_RUST_TOOLCHAIN_BELOW_PINNED_UPSTREAM_MSRV')
    if version(sysversion)[:2] != (0,38):
        issues.append('LIBSQLITE3_SYS_037_VS_UPSTREAM_RUSQLITE_040_LINKS_038')
    if version(current) != version(upstream['sdk_version']):
        issues.append('HEPTA_MATRIX_SDK_RELEASE_NEEDS_MIGRATION')
    if (version(current) >= (0,19,0) and
            current != f"={upstream['sdk_version']}"):
        issues.append('HEPTA_MATRIX_SDK_REQUIREMENT_NOT_EXACT')
    features=set(local_sdk.get('features',[]))
    if (local_sdk.get('default-features') is not False or
            not {'e2e-encryption','sqlite'}.issubset(features)):
        issues.append('HEPTA_E2EE_SQLITE_FEATURES_MISSING')
    # Modern SDK 0.19.1 intentionally uses its reviewed native SQLite crate,
    # not Hepta's *obsolete* 0.18 patch. A missing sqlite patch is not an
    # excuse to accept an unpinned SDK source or disabled WAL recovery.
    if sqlite_patch is not None:
        patch=sqlite_patch.get('path') if isinstance(sqlite_patch,dict) else None
        if patch == 'third_party/matrix-sdk-sqlite-0.18.0':
            issues.append('HEPTA_SQLITE_PATCH_STILL_018')
        elif patch != f"third_party/matrix-sdk-sqlite-{upstream['sqlite_version']}":
            issues.append('HEPTA_SQLITE_PATCH_NOT_SAME_PINNED_RELEASE')
        sqlite_mode='version_pinned_local_sqlite_patch'
    elif version(current) >= (0,19,0):
        sqlite_mode='pinned_sdk_native_sqlite_requires_wal_qualification'
        if not (isinstance(sdk_patch,dict) and
                sdk_patch.get('path') ==
                f"third_party/matrix-sdk-{upstream['sdk_version']}"):
            issues.append('HEPTA_NATIVE_SQLITE_UPSTREAM_SDK_SOURCE_UNBOUND')
    else:
        sqlite_mode='unreviewed_missing_legacy_patch'
        issues.append('HEPTA_SQLITE_PATCH_STILL_018')
    return {**upstream,
        'local_rust':rust,
        'local_libsqlite3_sys':sysversion,
        'local_matrix_sdk_version':current,
        'local_sqlite_source_mode':sqlite_mode,
        'migration_blockers':sorted(set(issues)),
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
    # A successful offline source read is NOT a release gate, but known local
    # migration incompatibilities must not pass the prerequisite job.
    return 0 if report['upstream_manifest_shape_ok'] and not report['migration_blockers'] else 3


if __name__=='__main__':
    sys.exit(main())
