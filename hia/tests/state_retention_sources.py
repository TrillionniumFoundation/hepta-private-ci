"""Bind complete original state sources and extract only real date calculations."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from datetime_calendar_oracle.custody import require

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "756f7a31ad4373809a00da65a91ba1ca4571f6cb"
LIB = "codex-rs/state/src/lib.rs"
LOGS = "codex-rs/state/src/runtime/logs.rs"
MEMORIES = "codex-rs/state/src/runtime/memories.rs"
NATIVE = '        #[cfg(feature = "hia-native")]\n'
DEFAULT = '        #[cfg(not(feature = "hia-native"))]\n'


def replace_once(text, old, new=""):
    require(text.count(old) == 1, "missing or repeated admitted source fragment")
    return text.replace(old, new, 1)


def inverse(path, text):
    if path == LIB:
        return replace_once(text, '#[cfg(feature = "hia-native")]\n'
                            '#[path = "../../../hia/datetime_retention.rs"]\n'
                            'mod hia_datetime_retention;\n')
    if path == MEMORIES:
        text = replace_once(text, '#[cfg(not(feature = "hia-native"))]\nuse chrono::Duration;\n',
                            'use chrono::Duration;\n')
        text, count = re.subn(re.escape(NATIVE) + r'        let (?:max_age_cutoff|idle_cutoff|cutoff) = \{\n.*?^        \};\n',
                             '', text, flags=re.M | re.S)
        require(count == 4 and text.count(DEFAULT) == 4, "four memory calculations were not preserved")
        return text.replace(DEFAULT, '')
    if path == LOGS:
        text, count = re.subn(re.escape(NATIVE) + r'        let Some\(cutoff\) = \(\{\n.*?^        \};\n',
                             '', text, flags=re.M | re.S)
        require(count == 1 and text.count(DEFAULT) == 2, "log checked calculation was not preserved")
        text = text.replace(DEFAULT, '')
        text = replace_once(text, NATIVE + '        let cutoff_ts = cutoff.seconds;\n')
        text = replace_once(text, '        let cutoff_ts = cutoff.timestamp();\n')
        return replace_once(text, 'self.delete_logs_before(cutoff_ts).await?;',
                            'self.delete_logs_before(cutoff.timestamp()).await?;')
    return text


def source_custody(original_repo):
    tree = subprocess.check_output(['git', '-C', str(original_repo), 'ls-tree', '-rz', REFERENCE,
                                    '--', 'codex-rs/state/src', 'codex-rs/state/tests'])
    entries = {}
    for line in tree.split(b'\0'):
        if not line:
            continue
        header, name = line.split(b'\t', 1)
        if not name.endswith(b'.rs'):
            continue
        mode, kind, blob = header.decode().split()
        require(mode == '100644' and kind == 'blob', "original Rust source is not a regular file")
        entries[name.decode()] = blob
    current = {str(path.relative_to(ROOT)) for directory in ('src', 'tests')
               for path in (ROOT / 'codex-rs/state' / directory).rglob('*.rs')}
    require(current == set(entries), "complete original state source inventory differs")
    originals, currents, inventory = {}, {}, []
    for path, blob in sorted(entries.items()):
        data = (ROOT / path).read_bytes()
        original = inverse(path, data.decode()).encode()
        actual = hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest()
        require(actual == blob, "complete original state source differs: " + path)
        original_binding = {'bytes': len(original), 'sha256': hashlib.sha256(original).hexdigest()}
        current_binding = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        inventory.append({'path': path, 'original_git_blob': blob,
                          'original': original_binding, 'current': current_binding})
        if path in (LIB, LOGS, MEMORIES):
            originals[path], currents[path] = original.decode(), data.decode()
    return inventory, originals, currents


def calculation(text, method, start, end):
    method_start = text.index(method)
    begin = text.index(start, method_start)
    finish = text.index(end, begin)
    return text[begin:finish]


def generate(originals, currents):
    generated, fragments = [], []
    for label, sources in [('original', originals), ('current', currents)]:
        log_start = NATIVE if label == 'current' else '        let Some(cutoff) =\n'
        logs = calculation(sources[LOGS], 'async fn run_logs_startup_maintenance(',
                           log_start, '        // Startup cleanup')
        log_return = 'self.delete_logs_before(cutoff_ts).await?;' if label == 'current' else \
                     'self.delete_logs_before(cutoff.timestamp()).await?;'
        result = 'cutoff_ts' if label == 'current' else 'cutoff.timestamp()'
        require(logs.count('return Ok(());') == (2 if label == 'current' else 1),
                "log skip-cleanup observation seam changed")
        observed_logs = logs.replace('return Ok(());', 'return None;')
        observed_logs = replace_once(observed_logs, log_return, 'Some([' + result + ', 0])')
        memory = sources[MEMORIES]
        startup = calculation(memory, 'pub async fn claim_stage1_jobs_for_startup(',
                              NATIVE if label == 'current' else '        let max_age_cutoff = ',
                              '        let mut builder')
        prune = calculation(memory, 'pub async fn prune_stage1_outputs_for_retention(',
                            NATIVE if label == 'current' else '        let cutoff = ',
                            '        let rows_affected')
        phase2 = calculation(memory, 'pub async fn get_phase2_input_selection(',
                             NATIVE if label == 'current' else '        let cutoff = ',
                             '        let page_size')
        ttl = re.findall(r'^const LOG_RETENTION_DAYS: i64 = [^\n]+;\n', sources[LOGS], re.M)
        require(len(ttl) == 1, "fixed original log retention changed")
        # Only the date calculations enter this observer. Complete source
        # projection above binds all SQL, early returns, limits and test bodies.
        functions = [('logs', '', logs, observed_logs),
                     ('startup', 'max_age_days: i64, min_rollout_idle_hours: i64', startup,
                      startup + 'Some([max_age_cutoff, idle_cutoff])\n'),
                     ('prune', 'max_unused_days: i64', prune, prune + 'Some([cutoff, 0])\n'),
                     ('phase2', 'max_unused_days: i64', phase2, phase2 + 'Some([cutoff, 0])\n')]
        generated.append('mod ' + label + ' {\nuse super::*;\n' + ttl[0])
        for name, args, actual, observer in functions:
            count = 2 if name == 'startup' else 1
            require(actual.count('Utc::now()') == count * (2 if label == 'current' else 1),
                    "source clock expression count differs")
            fragments.append({'kind': label, 'name': name, 'bytes': len(actual.encode()),
                              'sha256': hashlib.sha256(actual.encode()).hexdigest()})
            generated.append('pub fn ' + name + '(' + args + ') -> Option<[i64; 2]> {\n'
                             + observer.replace('Utc::now()', 'super::read_clock()') + '\n}\n')
        generated.append('}\n')
    return ''.join(generated), fragments


def inventory_sha256(inventory):
    raw = json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()
