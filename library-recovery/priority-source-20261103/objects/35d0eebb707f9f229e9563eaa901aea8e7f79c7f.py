from pathlib import Path
import hashlib, json, subprocess
root=Path('/workspace/shared/focused-candidate-ci-proposals')
def write(kind, branch, extraenv, steps):
 p=root/kind/'candidate/.github/workflows'/f'{kind}-diagnostic.yml';p.parent.mkdir(parents=True,exist_ok=True)
 s='''# Fixed source-head diagnostic only; never main/base-merge qualification.
name: KIND source diagnostic
on:
  push:
    branches: [BRANCH]
permissions:
  contents: read
concurrency:
  group: KIND-diagnostic-${{ github.ref }}
  cancel-in-progress: false
jobs:
  diagnostic:
    if: github.event_name == 'push' && github.ref == 'refs/heads/BRANCH'
    runs-on: ubuntu-24.04
    timeout-minutes: TIMEOUT
    env:
      SOURCE_SHA: ${{ github.sha }}
      TESTED_SHA: ${{ github.sha }}
      HEPTA_CI_LANE: source-head
EXTRAENV    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ github.sha }}
          persist-credentials: false
      - name: Verify clean exact candidate source
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          test -z "$(git status --porcelain --untracked-files=normal)"
          mkdir -p "$RUNNER_TEMP/KIND-records"
STEPS      - name: Verify source remains unchanged
        if: always()
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          test -z "$(git status --porcelain --untracked-files=normal)"
      - name: Retain diagnostic receipts only
        if: always()
        timeout-minutes: 3
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: KIND-diagnostic-${{ github.sha }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/KIND-records/
          if-no-files-found: error
          retention-days: 7
'''.replace('KIND',kind).replace('BRANCH',branch).replace('TIMEOUT','60' if kind=='taskflow-pending-cap' else '10').replace('EXTRAENV',extraenv).replace('STEPS',steps)
 p.write_text(s)
 patch=root/f'{kind}-ci.patch'; patch.write_text('diff --git a/'+str(p.relative_to(root/kind/'candidate'))+' b/'+str(p.relative_to(root/kind/'candidate'))+'\nnew file mode 100644\n--- /dev/null\n+++ b/'+str(p.relative_to(root/kind/'candidate'))+'\n@@ -0,0 +1,'+str(len(s.splitlines()))+' @@\n'+''.join('+'+l+'\n' for l in s.splitlines()))
 return p
write('taskflow-pending-cap','diagnostic/taskflow-pending-cap', '''      RUSTUP_TOOLCHAIN: 1.96.0
      CARGO_BUILD_JOBS: 2
      CARGO_INCREMENTAL: 0
      CARGO_PROFILE_DEV_DEBUG: 0
      CARGO_TARGET_DIR: ${{ runner.temp }}/taskflow-pending-cap-target
''','''      - name: Install pinned native prerequisites
        shell: bash
        run: |
          set -euo pipefail
          sudo apt-get update
          sudo apt-get install -y build-essential libcap-dev pkg-config
          rustup toolchain install 1.96.0 --profile minimal
      - uses: taiki-e/install-action@44c6d64aa62cd779e873306675c7a58e86d6d532
        with:
          tool: just@1.51.0,nextest@0.9.103
      - name: Resolve existing verified V8 inputs
        env:
          CODEX_REPO_ROOT: ${{ github.workspace }}
          PYTHONPATH: scripts
        run: python3 scripts/hepta_ci_v8.py
      - name: Test actual-worker pending capacity
        run: python3 scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/taskflow-pending-cap-records/pending.json" --minimum-tests 3 --timeout-seconds 2700 -- just test --locked -p codex-app-server-client --lib -E 'test(remote::pending_capacity_tests)'
      - name: Test existing owned-client lifetime in same lib build
        if: ${{ !cancelled() && steps.pending.outcome != 'skipped' }}
        run: python3 scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/taskflow-pending-cap-records/lifetime.json" --minimum-tests 3 --timeout-seconds 2700 -- just test --locked -p codex-app-server-client --lib -E 'test(remote::shutdown_lifetime_tests)'
'''.replace('      - name: Test actual-worker pending capacity\n','      - name: Test actual-worker pending capacity\n        id: pending\n'))
write('ui-license-identity','diagnostic/ui-license-identity','', '''      - uses: actions/setup-node@53b83947a5a98c8d113130e565377fae1a50d02f
        with:
          node-version: 22
      - name: Run only license identity regressions on Node 22
        shell: bash
        run: |
          set -euo pipefail
          test "$(node -p 'process.versions.node.split(".")[0]')" = 22
          python3 scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/ui-license-identity-records/command.json" --timeout-seconds 120 -- node --test --test-reporter=junit --test-reporter-destination="$RUNNER_TEMP/ui-license-identity-records/tests.xml" apps/hepta-control-ui/test/robrix-source-identity.test.mjs
      - name: Require exactly three passing tests and retain counts
        if: always()
        shell: bash
        run: |
          set -euo pipefail
          python3 - <<'PYCOUNT'
          import json, os
          from pathlib import Path
          import xml.etree.ElementTree as ET
          root = Path(os.environ['RUNNER_TEMP']) / 'ui-license-identity-records'
          record = json.loads((root / 'command.json').read_text())
          cases = list(ET.parse(root / 'tests.xml').getroot().iter('testcase'))
          counts = {'tests': len(cases), 'failed': sum(c.find('failure') is not None or c.find('error') is not None for c in cases), 'skipped': sum(c.find('skipped') is not None for c in cases)}
          counts.update(source_sha=record['source_sha'], before=record['before'], after=record['after'], qualification=False)
          (root / 'counts.json').write_text(json.dumps(counts, indent=2) + '\\n')
          assert record['status'] == 'passed' and record['exit_code'] == 0, record
          assert counts['tests'] == 3 and counts['failed'] == 0 and counts['skipped'] == 0, counts
          assert record['before'] == record['after'] and record['source_sha'] == os.environ['SOURCE_SHA'], record
          PYCOUNT
''')
