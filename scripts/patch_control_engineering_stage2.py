#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, value: str) -> None:
    (ROOT / rel).write_text(value, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    value = read(rel)
    if value.count(old) != 1:
        raise RuntimeError(f"{rel}: expected one marker: {old[:80]!r}")
    write(rel, value.replace(old, new, 1))


def append_once(rel: str, marker: str, body: str) -> None:
    value = read(rel)
    if marker not in value:
        write(rel, value.rstrip() + "\n\n" + textwrap.dedent(body).strip() + "\n")


init = "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
replace_once(
    init,
    "from .external_controls import (\n",
    "from .deployment_evidence import (\n"
    "    BackupRecoveryReceipt,\n"
    "    OperatorAcceptanceReceipt,\n"
    "    ProductionAcceptanceDecision,\n"
    "    RollbackRehearsalReceipt,\n"
    "    TargetDeploymentReceipt,\n"
    "    verify_production_acceptance_evidence,\n"
    ")\n"
    "from .stress_profile import build_stress_profile\n"
    "from .external_controls import (\n",
)
replace_once(
    init,
    '    "AssimilationProposal",\n',
    '    "AssimilationProposal",\n'
    '    "BackupRecoveryReceipt",\n'
    '    "OperatorAcceptanceReceipt",\n'
    '    "ProductionAcceptanceDecision",\n'
    '    "RollbackRehearsalReceipt",\n'
    '    "TargetDeploymentReceipt",\n',
)
replace_once(
    init,
    '    "build_manifest_candidate",\n',
    '    "build_manifest_candidate",\n'
    '    "build_stress_profile",\n',
)
replace_once(
    init,
    '    "verify_distributed_fence",\n',
    '    "verify_production_acceptance_evidence",\n'
    '    "verify_distributed_fence",\n',
)

extensions = "tools/hepta-engineering-control/test_control_engineering_extensions.py"
replace_once(
    extensions,
    "    evaluate_store_capacity,\n",
    "    build_stress_profile,\n    evaluate_store_capacity,\n",
)
replace_once(
    extensions,
    "                self.assertFalse(capacity[\"productionAccepted\"])\n",
    "                self.assertFalse(capacity[\"productionAccepted\"])\n"
    "        profile = build_stress_profile(\n"
    "            records=8, writers=1, reopen_cycles=2\n"
    "        )\n"
    "        self.assertEqual(profile[\"records\"], 8)\n"
    "        self.assertFalse(profile[\"deploymentAccepted\"])\n",
)

map_path = ROOT / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
row = json.loads(map_path.read_text(encoding="utf-8"))
operations = {item.get("operation") for item in row.get("operations", [])}
new_operations = [
    {
        "operation": "verify_production_acceptance_evidence",
        "designOperation": "external_deployment_recovery_rollback_operator_evidence",
        "nativeSymbol": "verify_production_acceptance_evidence",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/deployment_evidence.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [
            {"path": "tools/hepta-engineering-control/test_deployment_evidence.py"}
        ],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
    {
        "operation": "build_stress_profile",
        "designOperation": "sqlite_contention_growth_wal_reopen_profile",
        "nativeSymbol": "build_stress_profile",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/stress_profile.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [
            {"path": "tools/hepta-engineering-control/test_control_engineering_extensions.py"}
        ],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
    {
        "operation": "build_mutation_campaign",
        "designOperation": "real_source_strong_sandbox_mutation_score",
        "nativeSymbol": "build_mutation_campaign",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/qualification_mutation.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [
            {"path": ".github/workflows/hepta-consolidated-source.yml"}
        ],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
]
for operation in new_operations:
    if operation["operation"] not in operations:
        row.setdefault("operations", []).append(operation)

explicit_paths = (
    ".github/workflows/hepta-consolidated-source.yml",
    ".github/workflows/control-engineering-quality.yml",
    ".github/workflows/control-engineering-production-rehearsal.yml",
    "scripts/control_engineering_status.py",
    "scripts/control_engineering_api.py",
    "scripts/test_hepta_exact_blob_squash.py",
)
source_objects = row.setdefault("sourceObjects", [])
known = {entry.get("path") for entry in source_objects if isinstance(entry, dict)}
for path in explicit_paths:
    if path not in known:
        source_objects.append({"path": path, "object": "0" * 40})
map_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")

append_once(
    "docs/modules/control.engineering/IMPLEMENTATION.md",
    "## External target evidence and retained quality gates",
    '''
    ## External target evidence and retained quality gates

    `deployment_evidence.py` verifies separately signed target deployment, backup
    recovery, rollback rehearsal and operator acceptance receipts. All receipts bind
    one target and exact source; signer identities must remain distinct. A successful
    evidence decision still has `production_implementation`, runtime, merge and release
    authority false. Live infrastructure remains external.

    Exact source/merge strong-sandbox lanes retain a real four-mutant package campaign,
    bounded SQLite contention/WAL/reopen profile and host profile. A separate quality
    workflow enforces generated-status/API drift, lint, type checks and branch coverage.
    ''',
)
append_once(
    "docs/modules/control.engineering/OPERATIONS.md",
    "## External target rehearsal workflow",
    '''
    ## External target rehearsal workflow

    `control-engineering-production-rehearsal.yml` runs only on a protected self-hosted
    target labelled `control-engineering-target`. It requires an externally managed
    verifier executable and evidence-bundle mount. Missing runner, verifier, bundle,
    strong sandbox, deployment observation, backup recovery, rollback rehearsal or
    operator acceptance fails closed; the workflow never creates release authority.
    ''',
)

workflow = ".github/workflows/hepta-consolidated-source.yml"
replace_once(
    workflow,
    "      - name: Retain host qualification profile\n",
    "      - name: Run real package mutation campaign\n"
    "        shell: bash\n"
    "        run: |\n"
    "          set -euo pipefail\n"
    "          PYTHONPATH=tools/hepta-engineering-control \\\n"
    "            python3 -m control_engineering_v2.qualification_mutation \\\n"
    "              --repository \"$GITHUB_WORKSPACE\" \\\n"
    "              --output \"$RUNNER_TEMP/control-engineering-mutation.json\"\n"
    "      - name: Measure bounded contention, WAL growth and reopen profile\n"
    "        shell: bash\n"
    "        run: |\n"
    "          set -euo pipefail\n"
    "          PYTHONPATH=tools/hepta-engineering-control \\\n"
    "            python3 -m control_engineering_v2.stress_profile \\\n"
    "              --records 128 --writers 4 --reopen-cycles 8 \\\n"
    "              --output \"$RUNNER_TEMP/control-engineering-stress.json\"\n"
    "      - name: Retain host qualification profile\n",
)
replace_once(
    workflow,
    "          retention-days: 30\n      - name: Retain real command records\n        if: always()\n        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n        with:\n          name: hepta-commands-${{ github.run_id }}-${{ github.run_attempt }}-engineering-${{ matrix.lane }}\n",
    "          retention-days: 30\n"
    "      - name: Retain mutation and stress qualification\n"
    "        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n"
    "        with:\n"
    "          name: control-engineering-quality-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.lane }}\n"
    "          path: |\n"
    "            ${{ runner.temp }}/control-engineering-mutation.json\n"
    "            ${{ runner.temp }}/control-engineering-stress.json\n"
    "          if-no-files-found: error\n"
    "          retention-days: 30\n"
    "      - name: Retain real command records\n"
    "        if: always()\n"
    "        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n"
    "        with:\n"
    "          name: hepta-commands-${{ github.run_id }}-${{ github.run_attempt }}-engineering-${{ matrix.lane }}\n",
)
replace_once(
    workflow,
    "            --output \"$RUNNER_TEMP/control-engineering-product.json\"\n      - name: Retain product execution receipt\n",
    "            --output \"$RUNNER_TEMP/control-engineering-product.json\"\n"
    "      - name: Bind canonical source status to exact tested candidate\n"
    "        shell: bash\n"
    "        run: |\n"
    "          set -euo pipefail\n"
    "          python3 scripts/control_engineering_status.py --check \\\n"
    "            --runtime-output \"$RUNNER_TEMP/control-engineering-status.json\"\n"
    "      - name: Retain product execution receipt\n",
)
replace_once(
    workflow,
    "          path: ${{ runner.temp }}/control-engineering-product.json\n",
    "          path: |\n"
    "            ${{ runner.temp }}/control-engineering-product.json\n"
    "            ${{ runner.temp }}/control-engineering-status.json\n",
)
append_once(
    workflow,
    "  engineering-release-blocker:",
    '''
      engineering-release-blocker:
        name: control.engineering release blocker
        needs:
          - engineering-sandbox
          - engineering-product-gate
          - engineering-product-evidence
        if: always()
        runs-on: ubuntu-latest
        timeout-minutes: 5
        steps:
          - name: Require PR dual-lane evidence or exact-main product evidence
            env:
              EVENT_NAME: ${{ github.event_name }}
              SANDBOX_RESULT: ${{ needs.engineering-sandbox.result }}
              PRODUCT_RESULT: ${{ needs.engineering-product-gate.result }}
              PAIR_RESULT: ${{ needs.engineering-product-evidence.result }}
            shell: bash
            run: |
              set -euo pipefail
              test "$SANDBOX_RESULT" = success
              test "$PRODUCT_RESULT" = success
              if [ "$EVENT_NAME" = pull_request ]; then
                test "$PAIR_RESULT" = success
              else
                test "$PAIR_RESULT" = skipped
              fi
    ''',
)

if SELF.exists():
    SELF.unlink()
