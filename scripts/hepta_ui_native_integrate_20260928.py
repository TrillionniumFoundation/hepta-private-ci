#!/usr/bin/env python3
"""One-shot, exact-preimage source edits for the authorized native candidate.

This is transport, not qualification. The executor commits real source, then
its inventory, then the inventory-inclusive source map, and removes itself.
"""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'work/ui-native-qualified-integration-20260928'

def replace(path, old, new, count=1):
    file = ROOT / path
    text = file.read_text(encoding='utf-8')
    if text.count(old) != count:
        raise RuntimeError(f'preimage mismatch in {path}: expected {count}, got {text.count(old)}')
    file.write_text(text.replace(old, new), encoding='utf-8')

def main():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise RuntimeError('refusing dirty input')
    config = json.loads((ROOT / 'apps/hepta-native/CANDIDATE.json').read_text())
    if config['canonicalBranch'] != BRANCH or config['releaseAuthorized'] is not False:
        raise RuntimeError('wrong non-promoting candidate')
    for path, count in [('apps/hepta-native/src/ui.rs', 2),
                        ('apps/hepta-native/src/ui/operations_view.rs', 3),
                        ('apps/hepta-native/src/ui/shutdown.rs', 1)]:
        replace(path, 'let mut runtime = lock_runtime(&runtime)?;',
                'let mut runtime = admission\n                    .wait_lock(&runtime, Duration::from_secs(30))\n                    .map_err(|message| ShellError::State(message.to_owned()))?;', count)
    replace('apps/hepta-native/src/ui/shutdown.rs',
            'self.runtime_closed && self.update_requested && self.failure.is_none()',
            'self.requested() && self.runtime_closed && self.update_requested && self.failure.is_none()')
    replace('apps/hepta-native/src/ui/shutdown_tests.rs',
            '    shutdown.runtime_closed = true;\n    assert!(shutdown.activation_allowed());',
            '    shutdown.runtime_closed = true;\n    assert!(!shutdown.activation_allowed());\n    shutdown.request(Instant::now());\n    assert!(shutdown.activation_allowed());')
    old = '''            if let Some(previous) = self.record_digests.get(&identity) {
                if previous != &digest {
                    return Err(ShellError::State(
                        "retired observation is immutable".to_owned(),
                    ));
                }
            }'''
    new = '''            // An identity-only tombstone is not an empty receipt slot. In a
            // mixed batch, attaching its record only in memory fabricates an
            // uncommitted receipt that disappears on restart.
            if self.contains(&identity) && !self.record_digests.contains_key(&identity) {
                return Err(ShellError::State(
                    "retired identity-only tombstone cannot acquire an archived receipt".to_owned(),
                ));
            }
            if let Some(previous) = self.record_digests.get(&identity)
                && previous != &digest
            {
                return Err(ShellError::State(
                    "retired observation is immutable".to_owned(),
                ));
            }'''
    replace('apps/hepta-native/src/retirement.rs', old, new)
    file = ROOT / 'apps/hepta-native/src/retirement.rs'
    file.write_text(file.read_text() + '\n#[cfg(test)]\n#[path = "retirement_claim_tests.rs"]\nmod claim_tests;\n')
    file = ROOT / 'apps/hepta-native/src/ui/task_supervisor_tests.rs'
    file.write_text(file.read_text() + '''
#[test]
fn cancelled_lock_waiter_finishes_while_owner_is_still_locked() {
    let owner = Arc::new(std::sync::Mutex::new(0));
    let held = owner.lock().unwrap();
    let worker_owner = Arc::clone(&owner);
    let (entered, waiting) = mpsc::channel();
    let mut task = SupervisedTask::spawn("cancel-contended-lock", || {}, move |admission| {
        entered.send(()).unwrap();
        admission.wait_lock(&worker_owner, Duration::from_secs(3)).map(|_| ())?;
        admission.begin()
    }).unwrap();
    waiting.recv_timeout(Duration::from_secs(5)).unwrap();
    task.cancel_before_admission();
    assert_eq!(finish(&mut task), Ok(Err("native task cancelled before runtime admission")));
    drop(held);
}

#[test]
fn timed_out_lock_waiter_never_enters_the_owner() {
    let owner = Arc::new(std::sync::Mutex::new(0));
    let held = owner.lock().unwrap();
    let worker_owner = Arc::clone(&owner);
    let mut task = SupervisedTask::spawn("bounded-lock-wait", || {}, move |admission| {
        admission.wait_lock(&worker_owner, Duration::from_millis(5)).map(|_| ())?;
        admission.begin()
    }).unwrap();
    assert_eq!(finish(&mut task), Ok(Err("native runtime lock deadline exceeded before admission")));
    drop(held);
}
''')
    path = 'apps/hepta-native/tools/prepare_current_source.py'
    replace(path, 'BRANCH = "work/ui-native-acceptance-repair-20260927"', '''CANDIDATE = json.loads((APP / "CANDIDATE.json").read_text(encoding="utf-8"))
if (CANDIDATE.get("schema") != "hepta.ui.native.candidate.v1"
        or not re.fullmatch(r"work/ui-native-[a-z0-9-]+", CANDIDATE.get("canonicalBranch", ""))
        or not re.fullmatch(r"[0-9a-f]{40}", CANDIDATE.get("pinnedBase", ""))
        or CANDIDATE.get("pinnedBase") == "0" * 40
        or CANDIDATE.get("productionQualified") is not False
        or CANDIDATE.get("releaseAuthorized") is not False):
    raise RuntimeError("invalid non-promoting native candidate definition")
BRANCH = CANDIDATE["canonicalBranch"]''')
    file = ROOT / path
    file.write_text(re.sub(r'^WRITE_BRANCHES = .*$', 'WRITE_BRANCHES = {BRANCH}', file.read_text(), flags=re.M))
    replace(path, '        if source_path.read_bytes() != committed:',
            '        committed_oid = git("rev-parse", f"HEAD:{relative}")\n        worktree_oid = git("hash-object", f"--path={relative}", relative)\n        if worktree_oid != committed_oid:')
    replace(path, '                    "canonicalBranch": BRANCH,',
            '                    "canonicalBranch": BRANCH,\n                    "pinnedBase": CANDIDATE["pinnedBase"],')
    replace(path, 'or manifest.get("canonicalBranch") != BRANCH\n',
            'or manifest.get("canonicalBranch") != BRANCH\n                or manifest.get("pinnedBase") != CANDIDATE["pinnedBase"]\n')
    replace(path, '''    source = git("log", "-1", "--format=%H", "--", *SOURCE_LOG_PATHS)
    if not source:
        raise RuntimeError("unable to resolve the committed native source candidate")''',
            '''    # CURRENT_SOURCE.json is part of the mapped app root. Commit the
    # fingerprint first; observe that complete root rather than an older tree.
    fingerprint(False)
    source = git("rev-parse", "HEAD")''')
    replace(path, '    data["sourceBase"] = {"commit": source, "tree": tree}',
            '    data["canonicalBranch"] = BRANCH\n    data["pinnedBase"] = CANDIDATE["pinnedBase"]\n    data["sourceBase"] = {"commit": source, "tree": tree}')
    file = ROOT / 'scripts/test_hepta_ui_native_source.py'
    file.write_text(file.read_text().replace("'work/ui-native-closure-20260927'", 'source.BRANCH'))
    replace('scripts/test_hepta_ui_native_source.py', '    def test_wrong_current_branch_refused(self):', '''    def test_superseded_write_branch_refused(self):
        for branch in source.CANDIDATE["supersededCandidates"]:
            with patch.dict(os.environ, HEPTA_UI_NATIVE_WRITE_BRANCH=branch):
                with self.assertRaises(RuntimeError):
                    source.require_branch()

    def test_stale_pinned_base_refused(self):
        path = self.app / "CURRENT_SOURCE.json"
        data = json.loads(path.read_text())
        data["pinnedBase"] = "f" * 40
        path.write_text(json.dumps(data))
        with self.assertRaises(RuntimeError):
            self.check()

    def test_wrong_current_branch_refused(self):''')
    for path in ['docs/modules/ui.native/TECHNICAL.md', 'apps/hepta-native/DEVELOPMENT.md']:
        file = ROOT / path
        text = file.read_text()
        for old_branch in ['work/ui-native-acceptance-repair-20260927', 'work/ui-native-verified-closure-20260927']:
            text = text.replace(old_branch, BRANCH)
        text += '\n## Current integration status\n\nCANDIDATE.json owns the candidate and pinned base. The qualified-integration ledger dated 2026-09-28 supersedes earlier completion ledgers; inherited protocol details remain historical evidence, not a current pass. Worker mutex waiting is cancellation-aware and bounded to 30 seconds. The shutdown deadline denies update activation but never detaches or replays admitted work. Retirement disk indexing and physical/signed-product qualification remain open.\n'
        file.write_text(text)
    replace('docs/modules/kernel.authority/TECHNICAL.md',
            '](../../../codex-rs/hepta-private-state)', '](../../../codex-rs/hepta-private-state/Cargo.toml)')
    file = ROOT / 'docs/modules/ui.native/CURRENT_SOURCE.json'
    data = json.loads(file.read_text())
    data['canonicalCandidate'] = 'apps/hepta-native/CANDIDATE.json'
    data['currentLedger'] = 'docs/modules/ui.native/QUALIFIED-INTEGRATION-20260928.md'
    file.write_text(json.dumps(data, indent=2) + '\n')
    for path in ['.github/workflows/hepta-ui-native-remediation.yml', '.github/workflows/hepta-ui-native-remediation-format.yml']:
        file = ROOT / path
        text = re.sub(r'branches: \[[^\n]+\]', 'branches: [' + BRANCH + ']', file.read_text(), count=1)
        text = text.replace('base=a126987b84737dbc2ee2592442a314117bddb4a2', 'base=$(python3 -c \'import json; print(json.load(open("apps/hepta-native/CANDIDATE.json"))["pinnedBase"])\')')
        if path.endswith('remediation.yml'):
            text = text.replace('          check registry python3 scripts/test_hepta_module_registry.py', '          check registry python3 scripts/test_hepta_module_registry.py\n          python3 scripts/hepta-module-docs.py verify\n          python3 scripts/hepta-module-docs.py refresh-derived --check\n          python3 scripts/hepta-module-docs.py refresh-indexes --check')
        file.write_text(text)
    # The executor is not a second product source or a permanent branch writer.
    (ROOT / '.github/workflows/hepta-ui-native-integrate-20260928.yml').unlink()
    Path(__file__).unlink()
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)

if __name__ == '__main__':
    main()
