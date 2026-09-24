#!/usr/bin/env python3
"""Materialize reviewed #830 changes on one current-source candidate branch.

Preparation is committed before qualification. This tool never mutates main,
branch protection, signing credentials, or release state.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / 'apps/hepta-native'
BASE = '7ddbfac88525196e7a4b31387ceae194958275f5'
BRANCH = 'work/ui-native-current-source-20260925'


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected one source anchor, got {text.count(old)}')
    return text.replace(old, new, 1)


def prepare():
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    if branch != BRANCH:
        raise RuntimeError('preparation is restricted to the named native candidate branch')
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=ROOT, check=True)
    if (APP / 'CURRENT_SOURCE.json').exists():
        fingerprint(False)
        return
    changes = {}
    path = APP / 'src/journal.rs'
    text = path.read_text()
    text = replace_once(text, 'use std::fs::File;\n',
        'use std::collections::HashSet;\nuse std::fs::File;\nuse std::io::Read as _;\n', 'bounded journal imports')
    text = replace_once(text, 'struct JournalFile {',
        '#[serde(deny_unknown_fields)]\nstruct JournalFile {', 'closed journal schema')
    text = replace_once(text, '    _lock: File,',
        '    failed: bool,\n    _lock: File,', 'journal owner poison')
    text = replace_once(text, '                _lock: lock,',
        '                failed: false,\n                _lock: lock,', 'new journal health')
    text = replace_once(text, '            _lock: lock,\n        })',
        '            failed: false,\n            _lock: lock,\n        })', 'reopened journal health')
    text = replace_once(text, '        let bytes = std::fs::read(&path)?;',
        '''        let mut bytes = Vec::new();
        File::open(&path)?.take(MAX_JOURNAL_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_JOURNAL_BYTES {
            return Err(ShellError::State("operation journal read exceeded byte limit".to_owned()));
        }''', 'bounded journal read')
    text = replace_once(text, '        for operation in &state.operations {\n            operation.validate()?;\n        }',
        '''        let mut keys = HashSet::with_capacity(state.operations.len());
        for operation in &state.operations {
            operation.validate()?;
            if !keys.insert(operation.key.clone()) {
                return Err(ShellError::State("duplicate operation identity in journal".to_owned()));
            }
        }''', 'reject duplicate recovered keys')
    text = replace_once(text, '    pub fn upsert(&mut self, record: OperationRecord) -> Result<(), ShellError> {\n',
        '''    /// Failed persistence requires reopen and reconciliation, never replay.
    pub fn ensure_healthy(&self) -> Result<(), ShellError> {
        if self.failed {
            return Err(ShellError::State("journal persistence is indeterminate; reopen and reconcile".to_owned()));
        }
        Ok(())
    }

    pub fn upsert(&mut self, record: OperationRecord) -> Result<(), ShellError> {
        self.ensure_healthy()?;
''', 'fail closed after uncertain persistence')
    text = replace_once(text, '            if existing.subject_id != record.subject_id',
        '            if existing.endpoint_id != record.endpoint_id\n                || existing.subject_id != record.subject_id', 'journal endpoint binding')
    text = replace_once(text, '            if !phase_transition_allowed(existing.phase, record.phase) {',
        '''            if existing.phase == OperationPhase::Terminal && existing != &record {
                return Err(ShellError::State("terminal operation observation is immutable".to_owned()));
            }
            if !phase_transition_allowed(existing.phase, record.phase) {''', 'immutable terminal observation')
    start = text.index('    pub fn compact_terminal(')
    end = text.index('    fn persist(', start)
    text = text[:start] + '''    pub fn compact_terminal(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        self.ensure_healthy()?;
        let terminal_count = self.operations.iter()
            .filter(|record| record.phase == OperationPhase::Terminal).count();
        if terminal_count > keep_latest {
            return Err(ShellError::State(
                "terminal retirement requires a durable deduplication frontier".to_owned(),
            ));
        }
        Ok(())
    }

''' + text[end:]
    text = replace_once(text, '        self.persist(&next)?;',
        '''        if let Err(error) = self.persist(&next) {
            self.failed = true;
            return Err(error);
        }''', 'poison on uncertain journal write')
    changes[path] = text
    path = APP / 'src/qualification.rs'
    changes[path] = replace_once(path.read_text(), 'use crate::model::sha256_bytes;\n', '', 'unused qualification import')
    path = APP / 'src/security.rs'
    changes[path] = replace_once(path.read_text(),
        '.with_verified_use(permit.token, &permit.binding, consumer)',
        '.with_verified_effect(permit.token, &permit.binding, consumer)',
        'current kernel synchronous-effect fence')
    path = APP / 'src/runtime.rs'
    text = path.read_text()
    text = replace_once(text, '        manifest.validate()?;\n',
        '        self.journal.ensure_healthy()?;\n        manifest.validate()?;\n', 'connect owner health')
    text = replace_once(text,
        '        let session = self.require_session()?.clone();\n        let view = self.require_view()?.clone();',
        '        self.journal.ensure_healthy()?;\n        let session = self.require_session()?.clone();\n        let view = self.require_view()?.clone();', 'dispatch owner health')
    text = replace_once(text, '            if existing.subject_id != request.subject_id\n',
        '            if existing.endpoint_id != session.endpoint_id\n                || existing.subject_id != request.subject_id\n', 'endpoint replay fencing')
    text = replace_once(text, '        let pending: Vec<OperationRecord> = self.journal.pending().cloned().collect();',
        '        self.journal.ensure_healthy()?;\n        let pending: Vec<OperationRecord> = self.journal.pending().cloned().collect();', 'reconciliation owner health')
    changes[path] = text
    path = APP / 'src/updater.rs'
    text = path.read_text()
    for signature in [
        '    ) -> Result<PendingUpdateV1, ShellError> {\n        manifest.validate',
        '    pub fn rollback_unconfirmed(&self) -> Result<bool, ShellError> {\n',
        '    pub fn confirm_current_digest(&self, running_binary: &Path) -> Result<bool, ShellError> {\n',
    ]:
        if signature.endswith('manifest.validate'):
            replacement = signature.replace('        manifest.validate',
                '        let _lock = lock_update_root(&self.root)?;\n        manifest.validate')
        else:
            replacement = signature + '        let _lock = lock_update_root(&self.root)?;\n'
        text = replace_once(text, signature, replacement, 'updater writer fence')
    text = text.replace('self.clear_pending()?;', 'self.clear_pending_locked()?;')
    text = replace_once(text, '    pub fn clear_pending(&self) -> Result<(), ShellError> {\n',
        '''    pub fn clear_pending(&self) -> Result<(), ShellError> {
        let _lock = lock_update_root(&self.root)?;
        if self.load_pending()?.is_some_and(|pending| !matches!(
            pending.status, PendingUpdateStatus::Staged | PendingUpdateStatus::RolledBack
        )) {
            return Err(ShellError::Update(
                "cannot erase unresolved activation or recovery state".to_owned(),
            ));
        }
        self.clear_pending_locked()
    }

    fn clear_pending_locked(&self) -> Result<(), ShellError> {
''', 'no erasure of uncertain updates')
    text = replace_once(text, '        validate_pending(&pending)?;\n        Ok(Some(pending))',
        '''        validate_pending(&pending)?;
        // Expired admitted requests may recover, but cannot freshly activate.
        self.trusted_keys.verify_message(
            &pending.manifest.key_id,
            &pending.manifest.signature_base64,
            pending.manifest.signing_message().as_bytes(),
        )?;
        Ok(Some(pending))''', 'authenticated recovery manifest')
    text = replace_once(text, '        if let Err(error) = copy_and_sync(&backup, &target) {',
        '''        let current_digest = match digest_file(&target) {
            Ok(digest) => digest,
            Err(_) => return recovery_required(
                &self.pending_path(), &mut pending,
                "cannot identify installed binary before rollback",
            ),
        };
        if current_digest != pending.manifest.package_digest
            && current_digest != pending.manifest.predecessor_digest
        {
            return recovery_required(
                &self.pending_path(), &mut pending,
                "rollback refused: installed binary is neither candidate nor predecessor",
            );
        }
        if let Err(error) = copy_and_sync(&backup, &target) {''', 'rollback predecessor CAS')
    text = replace_once(text, '        if digest_file(running_binary)? != pending.manifest.package_digest {',
        '''        let target = pending.target_path.as_ref().ok_or_else(||
            ShellError::Update("pending activation lacks target identity".to_owned())
        )?;
        if std::fs::canonicalize(running_binary)? != std::fs::canonicalize(target)? {
            return Err(ShellError::Update("confirmation binary is not the installed target".to_owned()));
        }
        if digest_file(running_binary)? != pending.manifest.package_digest {''', 'confirmation physical target')
    text = replace_once(text, '    let mut pending: PendingUpdateV1 = serde_json::from_slice(&std::fs::read(pending_path)?)?;',
        '''    let root = pending_path.parent().ok_or_else(||
        ShellError::Update("pending update has no parent directory".to_owned())
    )?;
    let _lock = lock_update_root(root)?;
    let mut pending: PendingUpdateV1 = serde_json::from_slice(&std::fs::read(pending_path)?)?;''', 'helper and GUI writer lock')
    text += '''

// Shared by GUI transitions and the updater helper; never held across GUI life.
fn lock_update_root(root: &Path) -> Result<File, ShellError> {
    let path = root.join("update-owner.lock");
    match std::fs::symlink_metadata(&path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Err(ShellError::Security("update owner lock is not a regular file".to_owned()));
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let mut options = std::fs::OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    file.try_lock().map_err(|_| ShellError::Update(
        "another native update transition is in progress".to_owned(),
    ))?;
    Ok(file)
}
'''
    changes[path] = text
    for path, text in changes.items():
        path.write_text(text)
        print(path.relative_to(ROOT))


def fingerprint(write):
    path = APP / 'CURRENT_SOURCE.json'
    names = sorted(p for p in APP.rglob('*') if p.is_file()
        and not any(part in {'target', '__pycache__'} for part in p.relative_to(APP).parts)
        and p.name != 'CURRENT_SOURCE.json')
    observed = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in names}
    if write:
        path.write_text(json.dumps({
            'schema': 'hepta.ui.native.current-source.v1',
            'baselineCommit': BASE,
            'historicalSourceCommit': '3198549d80d6c59887b82e2c50018ab818217c53',
            'canonicalBranch': BRANCH,
            'files': observed,
            'productionQualified': False,
            'releaseAuthorized': False,
        }, indent=2) + '\n')
    else:
        expected = json.loads(path.read_text())['files']
        if observed != expected:
            raise RuntimeError('native source/lock/document fingerprints do not match candidate')
        print(f'verified {len(observed)} native source identities')


def sync_metadata():
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
    path = ROOT / 'docs/modules/ui.native/IMPLEMENTATION_MAP.json'
    data = json.loads(path.read_text())
    entries = {
        'connect_runtime': ('runtime.rs', 'pub fn connect_runtime(', 'tests/runtime.rs'),
        'render_runtime_view': ('runtime.rs', 'pub fn refresh_runtime_view(', 'tests/backend.rs'),
        'request_platform_capability': ('runtime.rs', 'pub fn request_platform_capability(', 'tests/runtime.rs'),
        'apply_shell_update': ('updater.rs', 'pub fn verify_and_stage(', 'tests/security_updater.rs'),
    }
    data['sourceBase'] = {'commit': source, 'tree': tree}
    for op in data['operations']:
        filename, symbol, test = entries[op['designOperation']]
        source_path = f'apps/hepta-native/src/{filename}'
        op['ownerEntrypoint'].update(path=source_path, symbol=symbol, buildTarget='hepta-native')
        op['nativeSymbol'] = symbol
        op['sourcePath'] = source_path
        op['sourcePathExists'] = True
        op['tests'] = [{'path': f'apps/hepta-native/{test}', 'kind': 'rust_integration',
            'command': 'cargo test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets'}]
    data['repositoryControlledGaps'] = [
        'Current main gateway authentication is not yet composed with the restored native backend.',
        'Current kernel authority store does not establish non-Unix durable final-use qualification.',
        'Strict exact-head and merge tests require actual execution on the committed locked candidate.',
        'Bounded OS launcher waits, UI thread responsiveness, and durable retirement remain unqualified.',
        'Physical package, accessibility, IME, multi-monitor DPI and performance acceptance remain unproved.',
    ]
    data['externalEvidenceGates'] = [
        'Independent platform signing/notarization and release-channel custody.',
        'Independent physical target-host and operator acceptance.',
    ]
    for key in ['repositoryControlledSourceBoundaryGapsClosed', 'productExecutionComplete',
                'deploymentQualificationComplete', 'independentAcceptanceComplete',
                'productionImplementation', 'productExecutionProved', 'independentAcceptance',
                'activation', 'release']:
        data['claimBoundary'][key] = False
    data['productionImplementation'] = False
    data['productCallerState'] = 'not_composed'
    data['stateOwnerDisposition'] = ('Rust shell owns its bounded local operation journal; '
        'kernel.authority retains final-use authority. Local persistence is not domain-write authority.')
    path.write_text(json.dumps(data, indent=2) + '\n')
    path = ROOT / 'qualification/module-execution-dossiers/NATIVE_BINDINGS.json'
    bindings = json.loads(path.read_text())
    changed = []
    def visit(value):
        if isinstance(value, dict):
            if value.get('module') == 'ui.native' and 'blobSha' in value:
                native = 'apps/hepta-native/src/runtime.rs'
                value['path'] = native
                value['blobSha'] = subprocess.check_output(['git', 'hash-object', native], cwd=ROOT, text=True).strip()
                value['exports'] = ['NativeShellRuntime', 'connect_runtime', 'refresh_runtime_view',
                                    'request_platform_capability', 'reconcile_pending']
                changed.append(native)
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(bindings)
    if len(changed) != 1:
        raise RuntimeError(f'expected exactly one native source binding, found {len(changed)}')
    path.write_text(json.dumps(bindings, indent=2) + '\n')
    print('bound native mapping to committed source', source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--write-fingerprints', action='store_true')
    parser.add_argument('--sync-metadata', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.write_fingerprints:
        fingerprint(True)
    elif args.sync_metadata:
        sync_metadata()
    else:
        fingerprint(False)
