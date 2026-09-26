#!/usr/bin/env python3
"""One-shot repository patch for control.engineering P0 identity and status gates."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected exactly one patch anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


replace_once(
    "scripts/hepta-implementation-maps.py",
    '''def checked_identity(value, candidate: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str)
        or not re.fullmatch(r"[0-9a-f]{40}", value[key])
        for key in ("commit", "tree")
    ):
        raise ValueError("source identity requires literal commit/tree SHA-1 values")
    commit, tree = value["commit"], value["tree"]
    if git("cat-file", "-t", commit) != "commit":
        raise ValueError("source identity does not identify a commit")
    if git("rev-parse", f"{commit}^{{tree}}") != tree:
        raise ValueError("source tree mismatch")
    git("merge-base", "--is-ancestor", commit, candidate["commit"])
    return {"commit": commit, "tree": tree}
''',
    '''def checked_identity(
    value,
    candidate: dict[str, str],
    *,
    require_ancestor: bool = True,
) -> dict[str, str]:
    """Validate an exact commit/tree pair and, when required, its lineage.

    Historical integration provenance remains ancestor-bound.  A current-source
    observation for ``exact_blob`` maps may be a squash-equivalent detached
    commit: currentness is then proved by the candidate's exact path/blob
    manifest plus a no-drift comparison over the complete observed path set.
    """
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str)
        or not re.fullmatch(r"[0-9a-f]{40}", value[key])
        for key in ("commit", "tree")
    ):
        raise ValueError("source identity requires literal commit/tree SHA-1 values")
    if type(require_ancestor) is not bool:
        raise ValueError("source identity ancestor policy must be boolean")
    commit, tree = value["commit"], value["tree"]
    if git("cat-file", "-t", commit) != "commit":
        raise ValueError("source identity does not identify a commit")
    if git("rev-parse", f"{commit}^{{tree}}") != tree:
        raise ValueError("source tree mismatch")
    if require_ancestor:
        git("merge-base", "--is-ancestor", commit, candidate["commit"])
    return {"commit": commit, "tree": tree}
''',
)

replace_once(
    "scripts/hepta-implementation-maps.py",
    '''    source = checked_identity(row.get("sourceBase"), candidate)
    mapping_mode = row.get("mappingSourceIdentityMode", "path_only")
    if mapping_mode not in {"path_only", "exact_blob"}:
        raise ValueError(f"unknown mapping source identity mode: {mapping_mode}")
''',
    '''    mapping_mode = row.get("mappingSourceIdentityMode", "path_only")
    if mapping_mode not in {"path_only", "exact_blob"}:
        raise ValueError(f"unknown mapping source identity mode: {mapping_mode}")
    # Integration provenance is never detached from the candidate lineage.
    source = checked_identity(row.get("sourceBase"), candidate)
''',
)

replace_once(
    "scripts/hepta-implementation-maps.py",
    '''    if "observedAtHead" in row:
        observed = checked_identity(row["observedAtHead"], candidate)
''',
    '''    if "observedAtHead" in row:
        observed = checked_identity(
            row["observedAtHead"],
            candidate,
            # Squash changes commit lineage without changing the qualified tree.
            # Only exact-blob maps may use a detached observation, and those maps
            # still prove every mapped HEAD blob plus the complete observed path
            # set below. Path-only observations remain ancestor-bound.
            require_ancestor=(mapping_mode != "exact_blob"),
        )
''',
)

insert_anchor = '''    def test_exact_blob_migration_preserves_provenance_and_rebinds_observation(self):
'''
new_test = '''    def test_exact_blob_observation_survives_squash_equivalent_detached_commit(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        row["mappingSourceIdentityMode"] = "exact_blob"
        row["operations"][0]["sourceBlob"] = self.git(
            "rev-parse", "HEAD:src/alpha/lib.rs"
        )
        detached = self.git(
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            self.git("rev-parse", "HEAD^{tree}"),
            "-m",
            "squash-equivalent detached observation",
        )
        row["observedAtHead"] = {
            "commit": detached,
            "tree": self.git("rev-parse", f"{detached}^{{tree}}"),
        }
        row["observedSourcePaths"] = ["src/alpha"]
        self.change_maps()
        self.verify()

        self.write("src/alpha/lib.rs", "pub fn changed_after_squash() {}\\n")
        self.commit("drift after detached exact observation")
        self.reject()

    def test_path_only_observation_remains_ancestor_bound(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        detached = self.git(
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            self.git("rev-parse", "HEAD^{tree}"),
            "-m",
            "detached path-only observation",
        )
        row["observedAtHead"] = {
            "commit": detached,
            "tree": self.git("rev-parse", f"{detached}^{{tree}}"),
        }
        row["observedSourcePaths"] = ["src/alpha"]
        self.change_maps()
        self.reject()

'''
replace_once(
    "scripts/test_hepta_implementation_maps.py",
    insert_anchor,
    new_test + insert_anchor,
)

replace_once(
    "docs/modules/control.engineering/IMPLEMENTATION_BINDING.md",
    '''`IMPLEMENTATION_MAP.json.sourceBase` is immutable integration provenance, not the
self-referential candidate commit. This module opts into
`mappingSourceIdentityMode=exact_blob`: every mapped operation records the Git blob OID
of its current `sourcePath`; `observedAtHead` covers the complete current source/evidence
set; and the global verifier requires the provenance commit to be an ancestor, recomputes
every `HEAD:<sourcePath>` blob and rejects a missing or stale current observation. A
mapping migration updates the exact blobs and current observation without rewriting
`sourceBase`. Exact candidate commit/tree execution identity remains the responsibility
of source-head and deterministic synthetic-merge execution receipts.
''',
    '''`IMPLEMENTATION_MAP.json.sourceBase` is immutable integration provenance, not the
self-referential candidate commit. This module opts into
`mappingSourceIdentityMode=exact_blob`: every mapped operation records the Git blob OID
of its current `sourcePath`; `observedAtHead` covers the complete current source/evidence
set; and the global verifier keeps `sourceBase` ancestor-bound while permitting an
exact-blob observation to be a squash-equivalent detached commit. A detached observation
is accepted only when its literal commit/tree exists, every candidate `HEAD:<sourcePath>`
blob matches the map, and the complete observed path set has no content drift between the
observation and candidate. Path-only observations remain ancestor-bound. A mapping
migration updates exact blobs and the current observation without rewriting `sourceBase`.
Exact candidate commit/tree execution identity remains the responsibility of source-head,
deterministic synthetic-merge, and post-merge exact-main execution receipts.
''',
)

replace_once(
    ".github/workflows/hepta-consolidated-source.yml",
    '''      - "scripts/hepta-gap-closure.py"
      - "scripts/verify_cargo_lock.py"
''',
    '''      - "scripts/hepta-gap-closure.py"
      - "scripts/hepta-implementation-maps.py"
      - "scripts/test_hepta_implementation_maps.py"
      - "scripts/control_engineering_status.py"
      - "docs/modules/control.engineering/**"
      - ".github/workflows/control-engineering-*.yml"
      - "scripts/verify_cargo_lock.py"
''',
)

status_script = r'''#!/usr/bin/env python3
"""Generate and verify the non-self-certifying control.engineering status view."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
STATUS = ROOT / "docs/modules/control.engineering/STATUS.json"
AUTHORITY_KEYS = (
    "runtimeAuthority",
    "mergeAuthority",
    "activationAuthority",
    "promotionAuthority",
    "releaseAuthority",
    "externalEffectAuthority",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def static_projection() -> dict:
    row = load(MAP)
    boundary = row["claimBoundary"]
    return {
        "schema": "hepta.control-engineering-status.v1",
        "schemaVersion": 1,
        "module": "control.engineering",
        "generatedFrom": "docs/modules/control.engineering/IMPLEMENTATION_MAP.json",
        "sourceIdentityPolicy": {
            "mappingMode": row.get("mappingSourceIdentityMode"),
            "provenance": row.get("sourceBase"),
            "currentObservation": row.get("observedAtHead"),
            "executionIdentity": "ci_receipt_only_not_tracked_status",
        },
        "source": {
            "rootPresent": bool(row["sourceRootPresent"]),
            "nativeMappingComplete": bool(boundary["nativeSourceMappingComplete"]),
            "implementedOperationMappingComplete": bool(
                boundary["implementedOperationMappingComplete"]
            ),
            "productCallerState": row["productCallerState"],
            "productionWriterState": row["productionWriterState"],
        },
        "claims": {
            "productionImplementation": bool(row["productionImplementation"]),
            "productExecutionProved": bool(boundary["productExecutionProved"]),
            "independentAcceptance": bool(boundary["independentAcceptance"]),
            "activation": bool(boundary["activation"]),
            "release": bool(boundary["release"]),
        },
        "repositoryControlledGaps": row.get("repositoryControlledGaps", []),
        "externalEvidenceGates": row.get("externalEvidenceGates", []),
        "runtimeEvidence": {
            "tracked": False,
            "reason": "exact source, synthetic merge, post-merge main, host and product receipts are generated by CI for one immutable run",
        },
        "authority": {key: False for key in AUTHORITY_KEYS},
    }


def render(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def git(*args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
    )
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def runtime_projection(output: Path, lane: str, product_receipt: Path | None) -> None:
    if lane not in {"source-head", "base-merge", "post-merge-main"}:
        raise SystemExit("invalid runtime lane")
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    receipt = None
    if product_receipt is not None:
        receipt = load(product_receipt)
        if receipt.get("sourceCommit") not in {None, head} and receipt.get("testedCommit") != head:
            raise SystemExit("product receipt is not bound to current HEAD")
    value = {
        "schema": "hepta.control-engineering-runtime-status.v1",
        "schemaVersion": 1,
        "module": "control.engineering",
        "lane": lane,
        "candidate": {"commit": head, "tree": tree},
        "staticStatus": static_projection(),
        "productReceipt": receipt,
        "authority": {key: False for key in AUTHORITY_KEYS},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("write")
    sub.add_parser("verify")
    runtime = sub.add_parser("runtime")
    runtime.add_argument("--output", required=True, type=Path)
    runtime.add_argument("--lane", required=True)
    runtime.add_argument("--product-receipt", type=Path)
    args = parser.parse_args()
    expected = render(static_projection())
    if args.command == "write":
        STATUS.write_text(expected, encoding="utf-8")
        return 0
    if args.command == "verify":
        if not STATUS.is_file() or STATUS.read_text(encoding="utf-8") != expected:
            raise SystemExit("FAIL_CONTROL_ENGINEERING_STATUS_DRIFT")
        return 0
    runtime_projection(args.output, args.lane, args.product_receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
write("scripts/control_engineering_status.py", status_script)

quality_workflow = r'''name: control.engineering focused quality

on:
  pull_request:
    paths:
      - "tools/hepta-engineering-control/**"
      - "scripts/hepta-implementation-maps.py"
      - "scripts/test_hepta_implementation_maps.py"
      - "scripts/control_engineering_status.py"
      - "docs/modules/control.engineering/**"
      - ".github/workflows/control-engineering-quality.yml"
      - ".github/workflows/hepta-consolidated-source.yml"
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: control-engineering-quality-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  identity-and-status:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Verify implementation-map regressions
        run: python3 -m unittest -v scripts/test_hepta_implementation_maps.py
      - name: Verify generated control.engineering status
        run: python3 scripts/control_engineering_status.py verify
      - name: Compile Python owner and status tooling
        run: |
          python3 -m compileall -q tools/hepta-engineering-control/control_engineering_v2
          python3 -m py_compile scripts/hepta-implementation-maps.py scripts/control_engineering_status.py
      - name: Retain exact focused status
        shell: bash
        run: |
          set -euo pipefail
          lane=post-merge-main
          if [ "${{ github.event_name }}" = pull_request ]; then lane=source-head; fi
          python3 scripts/control_engineering_status.py runtime \
            --lane "$lane" \
            --output "$RUNNER_TEMP/control-engineering-status.json"
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: control-engineering-status-${{ github.run_id }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/control-engineering-status.json
          if-no-files-found: error
          retention-days: 30
'''
write(".github/workflows/control-engineering-quality.yml", quality_workflow)

# Generate the tracked static status only after the generator and map are in place.
subprocess.run(
    ["python3", "scripts/control_engineering_status.py", "write"],
    cwd=ROOT,
    check=True,
)

# The bootstrap files are deliberately absent from the resulting product commit.
for relative in (
    "scripts/bootstrap_control_engineering_phase1.py",
    ".github/workflows/bootstrap-control-engineering-phase1.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()
