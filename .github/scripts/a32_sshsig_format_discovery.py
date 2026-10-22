"""Pre-resolution native formatter discovery; changed source is always HOLD, never qualified."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from a32_sshsig_controls_nokill import wait_owned
from a32_sshsig_format_boundaries import boundary, git, inventory, snapshot, tree_hash
from a32_sshsig_guard import LOCKS, PACKAGES, digest, require, save


class Discovery:
    def __init__(self, root, evidence, source_sha, source_tree, manifest, admit):
        require(__debug__, 'formatter boundary asserts require non-optimized Python')
        self.root, self.out = root, evidence / 'format-discovery'
        require(not self.out.exists(), 'formatter evidence must be fresh')
        self.out.mkdir()
        self.live = Path(tempfile.mkdtemp(prefix='a32-format-live-', dir=evidence.parent))
        require(not self.live.is_relative_to(evidence), 'formatter live logs must be outside uploaded evidence')
        self.sha, self.tree, self.manifest, self.admit = source_sha, source_tree, manifest, admit
        self.receipt = {'schema': 'a32.sshsig-format-discovery.v1', 'source_sha': source_sha,
                        'source_tree': source_tree, 'product_tree': manifest['expected_product_tree'],
                        'locks_generated': False, 'pins_refreshed': False, 'native_functional_qualification': False,
                        'input_format_passed': False, 'complete': False, 'hold': True,
                        'live_logs_not_uploaded': str(self.live), 'commands': [], 'child_unsettled': False}
        save(self.out / 'receipt.json', self.receipt)

    def command(self, name, argv):
        self.admit()
        require(not self.receipt['child_unsettled'], 'unsettled formatter: no further command')
        live = self.live / (name + '.log')
        record = {'name': name, 'argv': argv, 'status': 'running', 'signals_sent': False,
                  'started_unix': time.time(), 'live_log_not_uploaded': str(live)}
        self.receipt['commands'].append(record)
        self.receipt['child_unsettled'] = True  # Persist before spawn; abrupt host interruption remains unknown.
        save(self.out / 'receipt.json', self.receipt)
        process = None; first_error = None
        try:
            with live.open('xb') as stream:
                env = dict(os.environ, RUSTUP_TOOLCHAIN='1.95.0', CARGO_NET_OFFLINE='true', CARGO_TERM_COLOR='never')
                process = subprocess.Popen(argv, cwd=self.root / 'codex-rs', env=env,
                                           stdout=stream, stderr=subprocess.STDOUT)
                self.receipt['child_unsettled'] = True
                def observe(event):
                    record.setdefault('deferred_events', []).append(event)
                    save(self.out / 'receipt.json', self.receipt)
                code = wait_owned(process, observe)
            self.receipt['child_unsettled'] = False
            record.update(status='terminal', exit_code=code)
            data = live.read_bytes()
            (self.out / (name + '.log')).write_bytes(data)
            record.update(log_sha256=digest(data), log_bytes=len(data), log_complete=True)
            return code, data
        except BaseException as error:
            first_error = error
            settled = process is not None and process.returncode is not None
            self.receipt['child_unsettled'] = not settled
            record.update(status='interrupted-or-failed', exception_type=type(error).__name__,
                          actual_exit=process.returncode if process else None)
            # Only an immutable diagnostic prefix, never a live formatter source snapshot.
            try:
                if live.exists():
                    with live.open('rb') as stream:
                        size = min(os.fstat(stream.fileno()).st_size, 64 * 1024 * 1024)
                        prefix = stream.read(size)
                    (self.out / (name + '.partial.log')).write_bytes(prefix)
                    record.update(log_sha256=digest(prefix), log_bytes=len(prefix), log_complete=False)
            except BaseException as secondary:
                error.add_note('partial-log capture failed: ' + repr(secondary))
            raise
        finally:
            try:
                save(self.out / 'receipt.json', self.receipt)
            except BaseException as secondary:
                if first_error is None:
                    raise
                first_error.add_note('formatter receipt write failed: ' + repr(secondary))

    def run(self):
        entries = inventory(self.root, self.sha, self.tree)
        boundary(self.root, self.sha, self.tree, entries)
        before = snapshot(self.root, entries)
        require(all(before[path]['blob'] == item['blob'] and before[path]['mode'] == item['mode']
                    for path, item in entries.items()), 'full raw checkout differs from frozen input')
        locks = {path: before[path] for path in LOCKS}
        self.receipt['input_locks'] = locks
        save(self.out / 'input-files.json', before)
        cargo = ['cargo', 'fmt']
        for package in PACKAGES:
            cargo += ['--package', package]
        trailing = ['--', '--config', 'imports_granularity=Item']
        check = [*cargo, *trailing, '--check']
        first_error = None
        try:
            version_code, version = self.command('rustfmt-version', ['rustfmt', '--version'])
            require(version_code == 0 and version.startswith(b'rustfmt '), 'native rustfmt version unavailable')
            boundary(self.root, self.sha, self.tree, entries)
            require(snapshot(self.root, entries) == before, 'version query changed source')
            code, output = self.command('input-format-check', check)
            boundary(self.root, self.sha, self.tree, entries)
            require(snapshot(self.root, entries) == before, 'formatter check changed source')
            self.receipt['input_format_check_exit'] = code
            if code == 0:
                self.receipt.update(input_format_passed=True, complete=True, hold=False, changed_files=[])
                return True
            require(code == 1 and re.search(rb'(?m)^Diff in ', output),
                    'format check failed without genuine style diff; no automatic formatter invocation')
            code, _ = self.command('generate-format-only', [*cargo, *trailing])
            boundary(self.root, self.sha, self.tree, entries)
            after = snapshot(self.root, entries)
            changed = sorted(path for path in entries if before[path] != after[path])
            self.receipt['changed_files'] = [{'path': path, 'before': before[path], 'after': after[path]} for path in changed]
            self.receipt['generation_exit'] = code
            patch = git(self.root, 'diff', '--binary', '--full-index', '--no-ext-diff', '--no-textconv', self.sha, '--')
            (self.out / 'native-rustfmt.patch').write_bytes(patch)
            # Raw output is preserved before rejecting any out-of-scope generated path.
            for path in changed:
                target = self.out / 'postimages' / path; target.parent.mkdir(parents=True, exist_ok=True)
                current = self.root / path
                target.write_bytes(os.fsencode(os.readlink(current)) if current.is_symlink() else current.read_bytes())
            save(self.out / 'observed-generated-files.json', after)
            self.receipt.update(generated_patch_sha256=digest(patch), generated_tree=tree_hash(after),
                                generated_artifacts_require_independent_review=True)
            roots = ('codex-rs/utils/path-utils/', 'codex-rs/state/', 'codex-rs/hepta-memory/', 'codex-rs/hepta-operator-acceptance/')
            allowed = {x['path'] for x in self.manifest['files'] if x['path'].endswith('.rs') and x['path'].startswith(roots)}
            require(set(changed) <= allowed and all(before[path]['mode'] == after[path]['mode'] for path in changed),
                    'formatter changed unreviewed paths or modes; preserved raw artifacts remain HOLD')
            require({path: after[path] for path in LOCKS} == locks, 'formatter altered locks')
            require(code == 0, 'formatter failed; raw artifacts remain HOLD')
            final_code, _ = self.command('generated-format-check', check)
            boundary(self.root, self.sha, self.tree, entries)
            require(snapshot(self.root, entries) == after, 'final check changed generated source')
            self.receipt.update(generated_check_exit=final_code, locks_unchanged=True, complete=final_code == 0)
            require(final_code == 0, 'generated format check failed; raw artifacts remain HOLD')
            return False  # Even genuine, complete formatting output never qualifies a changed source tree.
        except BaseException as error:
            first_error = error
            self.receipt.update(error=str(error), error_type=type(error).__name__, hold=True)
            raise
        finally:
            try:
                save(self.out / 'receipt.json', self.receipt)
            except BaseException as secondary:
                if first_error is None:
                    raise
                first_error.add_note('formatter final receipt write failed: ' + repr(secondary))
