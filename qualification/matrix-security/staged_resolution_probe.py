#!/usr/bin/env python3
"""Prepare a Git-pinned Matrix SDK dependency-resolution experiment in a disposable worktree.

Only rewrites a *temporary* Cargo.toml on a detached worktree. The real PR
source, lock, and deny.toml never change. A successful Cargo graph resolution
is NOT license/security/E2EE/SQLite WAL acceptance.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from upstream_source_probe import UPSTREAM_GIT_SHA

SOURCE_SPEC = 'matrix-sdk = { version = "0.18.0", default-features = false, features = ["e2e-encryption", "sqlite"] }'
CANDIDATE_SPEC = (f'matrix-sdk = {{ git = "https://github.com/matrix-org/matrix-rust-sdk", '
                  f'rev = "{UPSTREAM_GIT_SHA}", version = "0.19.1", '
                  f'default-features = false, features = ["e2e-encryption", "sqlite"] }}')
# Two independent, disposable dependency-resolution arms. The real repo's
# patched SDK SQLite (0.18) remains unchanged throughout both experiments.
SQLITE_PATCH_SPEC = 'matrix-sdk-sqlite = { path = "third_party/matrix-sdk-sqlite-0.18.0" }'
SQLITE_ARMS = ('retain_legacy_sqlite_patch', 'use_upstream_sqlite')


def stage_manifest(source, stage, exact_source_sha, *, sqlite_arm='retain_legacy_sqlite_patch'):
    if sqlite_arm not in SQLITE_ARMS:
        raise ValueError('unknown or unregistered SQLite resolver arm')
    source = source.resolve()
    stage = stage.resolve()
    if stage == source or source in stage.parents or stage in source.parents:
        raise ValueError('candidate stage must be an independent Git worktree outside source')
    if not re.fullmatch(r'[0-9a-f]{40}', exact_source_sha):
        raise ValueError('candidate must use exact Git source SHA')
    expected = subprocess.run(['git','-C',str(stage),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if expected != exact_source_sha:
        raise ValueError('disposable worktree is not the exact requested SHA')
    target = stage/'codex-rs/Cargo.toml'
    original = target.read_text(encoding='utf-8')
    if original.count(SOURCE_SPEC) != 1:
        raise ValueError('workspace SDK dependency no longer matches frozen baseline')
    # The retention arm must really retain an audited 0.18 SQLite patch;
    # otherwise two diagnostically distinct arms could silently be identical.
    original_patch = tomllib.loads(original).get('patch', {}).get('crates-io', {}).get('matrix-sdk-sqlite')
    if (original.count(SQLITE_PATCH_SPEC) != 1
            or original_patch != {'path': 'third_party/matrix-sdk-sqlite-0.18.0'}):
        raise ValueError('the legacy SQLite patch is not the exact pinned source')
    replaced = original.replace(SOURCE_SPEC, CANDIDATE_SPEC)
    # A pinned SDK 0.19 cannot safely inherit the 0.18 SQLite source patch.
    # Only an isolated resolver arm may test its removal; this does not change
    # the actual workspace or waive any dependency-security rule.
    if sqlite_arm == 'use_upstream_sqlite':
        replaced = replaced.replace(SQLITE_PATCH_SPEC + '\n', '', 1)
        if SQLITE_PATCH_SPEC in replaced:
            raise ValueError('SQLite patch removal incomplete')
    # Syntax and security feature binding are checked before writing.
    candidate = tomllib.loads(replaced)['workspace']['dependencies']['matrix-sdk']
    if (candidate['rev'] != UPSTREAM_GIT_SHA or candidate['version'] != '0.19.1'
            or candidate.get('default-features') is not False
            or set(candidate['features']) != {'e2e-encryption','sqlite'}):
        raise ValueError('unregistered or weakened Matrix dependency candidate')
    staged_patch = tomllib.loads(replaced).get('patch',{}).get('crates-io',{}).get('matrix-sdk-sqlite')
    if sqlite_arm == 'use_upstream_sqlite' and staged_patch is not None:
        raise ValueError('old SQLite patch remains in disposable source')
    if sqlite_arm == 'retain_legacy_sqlite_patch' and staged_patch != original_patch:
        raise ValueError('retained SQLite patch changed in disposable source')
    target.write_text(replaced,encoding='utf-8')
    return {
        'schema':'hepta.matrix-sdk-cargo-resolution-probe.v2',
        'sqlite_arm':sqlite_arm,
        'legacy_sqlite_patch_preserved':sqlite_arm == 'retain_legacy_sqlite_patch',
        'source_sha':exact_source_sha,
        'candidate_git_sha':UPSTREAM_GIT_SHA,
        'source_manifest_sha256':sha256(original.encode()).hexdigest(),
        'staged_manifest_sha256':sha256(replaced.encode()).hexdigest(),
        'preserved_e2ee_and_sqlite':True,
        'affected_workspace_files':['codex-rs/Cargo.toml'],
        'upstream_source_reviewed':False,
        'cargo_graph_resolution_passed':False,
        'cargo_deny_passed':False,
        'e2ee_crash_recovery_passed':False,
        'production_authorized':False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--sha',required=True)
    parser.add_argument('--sqlite-arm',choices=SQLITE_ARMS,default='retain_legacy_sqlite_patch')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    payload=stage_manifest(args.source,args.stage,args.sha,sqlite_arm=args.sqlite_arm)
    args.output.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    sys.exit(main())
