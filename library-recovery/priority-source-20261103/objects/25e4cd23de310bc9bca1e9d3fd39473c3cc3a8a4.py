from pathlib import Path
import difflib
r=Path(__file__).resolve().parent
p=r/'taskflow-pending-cap/candidate/.github/workflows/taskflow-pending-cap-diagnostic.yml'
s=p.read_text().replace('      CARGO_PROFILE_DEV_DEBUG: 0\n','      CARGO_PROFILE_DEV_DEBUG: 0\n      CARGO_PROFILE_TEST_DEBUG: 0\n')
s=s.replace('    steps:\n','''    steps:
      - name: Bound setup and both test commands together
        shell: bash
        run: echo "NATIVE_DEADLINE=$(( $(date +%s) + 3000 ))" >> "$GITHUB_ENV"
''',1)
s=s.replace('      - uses: actions/checkout@','      - timeout-minutes: 5\n        uses: actions/checkout@')
s=s.replace('      - name: Install pinned native prerequisites\n','      - name: Install pinned native prerequisites\n        timeout-minutes: 10\n')
s=s.replace('      - uses: taiki-e/install-action@','      - timeout-minutes: 5\n        uses: taiki-e/install-action@')
s=s.replace('      - name: Resolve existing verified V8 inputs\n','      - name: Resolve existing verified V8 inputs\n        timeout-minutes: 10\n')
s=s.replace('        run: python3 scripts/hepta_ci_exec.py --output', '''        shell: bash
        run: |
          set -euo pipefail
          remaining=$(( NATIVE_DEADLINE - $(date +%s) ))
          test "$remaining" -ge 30
          budget=$(( remaining < 2700 ? remaining : 2700 ))
          python3 scripts/hepta_ci_exec.py --output''').replace('--timeout-seconds 2700','--timeout-seconds "$budget"')
s=s.replace('      - name: Test existing owned-client lifetime in same lib build\n','''      - name: Retain pending receipt before the second command
        if: always()
        timeout-minutes: 3
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: taskflow-pending-cap-first-${{ github.sha }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/taskflow-pending-cap-records/pending.json*
          if-no-files-found: error
          retention-days: 7
      - name: Test existing owned-client lifetime in same lib build
''')
p.write_text(s)
p=r/'ui-license-identity/candidate/.github/workflows/ui-license-identity-diagnostic.yml'
s=p.read_text().replace("          counts = {'tests':", "          names = [case.get('name') for case in cases]\n          counts = {'names': names, 'tests':")
s=s.replace("          assert counts['tests'] == 3", """          assert sorted(names) == sorted([
              'editing a shipped license invalidates source identity and restoring it recovers identity',
              'adding and removing nested shipped licenses changes the complete source inventory',
              'missing shipped-license directory fails closed',
          ]), names
          assert counts['tests'] == 3""")
p.write_text(s)
for kind in ['taskflow-pending-cap','ui-license-identity']:
 p=r/kind/'candidate/.github/workflows'/f'{kind}-diagnostic.yml';s=p.read_text(); name=p.relative_to(r/kind/'candidate').as_posix()
 (r/f'{kind}-ci.patch').write_text(f'diff --git a/{name} b/{name}\nnew file mode 100644\n'+''.join(difflib.unified_diff([],s.splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+name)))
p=r/'test_static_routing.py'
s=p.read_text().replace('--timeout-seconds 2700 -- just', '--timeout-seconds \\"$budget\\" -- just')
p.write_text(s)
