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


def stage_manifest(source, stage, exact_source_sha):
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
    replaced = original.replace(SOURCE_SPEC, CANDIDATE_SPEC)
    # Syntax and security feature binding are checked before writing.
    candidate = tomllib.loads(replaced)['workspace']['dependencies']['matrix-sdk']
    if (candidate['rev'] != UPSTREAM_GIT_SHA or candidate['version'] != '0.19.1'
            or candidate.get('default-features') is not False
            or set(candidate['features']) != {'e2e-encryption','sqlite'}):
        raise ValueError('unregistered or weakened Matrix dependency candidate')
    target.write_text(replaced,encoding='utf-8')
    return {
        'schema':'hepta.matrix-sdk-cargo-resolution-probe.v1',
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
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    payload=stage_manifest(args.source,args.stage,args.sha)
    args.output.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    sys.exit(main())
