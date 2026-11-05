"""One bounded existing-identity ls-remote; never emit an origin URL or secrets."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

SOURCE = Path('/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf/source-h3')
EXPECTED_COMMIT = '6db78eca53a5acdda0d96873d3f4cd65863426f0'
EXPECTED_TREE = 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
EXPECTED_REF = 'refs/heads/evidence/joint-components-20261105-93bfc'
EXPECTED_HEAD = '571c3da959bcbcca6639a5882d49aebadd00bff2'
CONFIGS = {
 '/home/qian-qi/work/hepta-audit-ledger-fixture-fix-20261103/.git/config': '24452f7031356ffbc08ab7fb9657efa5b67fb0b16b2a2ce704ec99d1514267b8',
 '/home/qian-qi/work/hepta-audit-ledger-fixture-fix-20261103/.git/worktrees/hepta-audit-provider-recovery-fix-20261103/config.worktree': 'bfefdfeb2bf56f4a5282c172fe3a69b4075e13fe3bf3cd54f6611bafa461c276',
 '/home/qian-qi/work/hepta-audit-ledger-fixture-fix-20261103/.git/worktrees/source1/config.worktree': '443a5f645c23c3d0c0aa09f634b2ad111d46ef61946b598a2fb311678ab47454',
 '/home/qian-qi/work/hepta-audit-ledger-fixture-fix-20261103/.git/worktrees/source-h2/config.worktree': '443a5f645c23c3d0c0aa09f634b2ad111d46ef61946b598a2fb311678ab47454',
 '/home/qian-qi/work/hepta-audit-ledger-fixture-fix-20261103/.git/worktrees/source-h3/config.worktree': '443a5f645c23c3d0c0aa09f634b2ad111d46ef61946b598a2fb311678ab47454',
}
ENV = dict(os.environ)
for name in tuple(ENV):
    if name.startswith('GIT_TRACE') or name in ('GIT_CURL_VERBOSE',):
        ENV.pop(name)
ENV['GIT_TERMINAL_PROMPT'] = '0'
ENV['GIT_OPTIONAL_LOCKS'] = '0'


def config_hashes():
    result = {}
    for path in CONFIGS:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024:
                raise ValueError('regular bounded configuration required')
            raw = stream.read(1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != before.st_size:
            raise ValueError('configuration changed during hash-only read')
        result[path] = hashlib.sha256(raw).hexdigest()
    return result


def local_git(arguments):
    result = subprocess.run(['git', '-C', str(SOURCE), *arguments], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV, timeout=5)
    if result.returncode != 0:
        raise ValueError('local Git inspection failed; raw streams withheld')
    return result.stdout


def source_identity():
    head = local_git(['rev-parse', 'HEAD']).decode('ascii').strip()
    tree = local_git(['rev-parse', 'HEAD^{tree}']).decode('ascii').strip()
    status = local_git(['status', '--porcelain=v1', '--untracked-files=no'])
    if not re.fullmatch('[0-9a-f]{40}', head) or not re.fullmatch('[0-9a-f]{40}', tree):
        raise ValueError('unexpected source identity')
    return {'commit':head, 'tree':tree, 'tracked_clean':not status,
            'tracked_status_bytes':len(status), 'tracked_status_sha256':hashlib.sha256(status).hexdigest()}


def expected_origin(raw):
    value = raw.decode('utf-8').strip()
    if '\n' in value or '\r' in value:
        return False
    if '://' in value:
        parsed = urlsplit(value)
        host, path = parsed.hostname, parsed.path.lstrip('/')
        if parsed.query or parsed.fragment or parsed.scheme not in ('https', 'ssh'):
            return False
    else:
        match = re.fullmatch(r'(?:[^@/:]+@)?([^/:]+):(.+)', value)
        if not match:
            return False
        host, path = match.groups()
    if path.endswith('.git'):
        path = path[:-4]
    return host == 'github.com' and path == 'TrillionniumFoundation/hepta-private-ci'


def safe_error_classification(stderr):
    value = stderr.lower()
    if b'suspended' in value:
        return 'existing_identity_suspended'
    if b'authentication failed' in value or b'could not read username' in value or b'permission denied' in value or b'403' in value or b'401' in value:
        return 'existing_identity_or_access_denied'
    if b'could not resolve' in value or b'failed to connect' in value or b'connection' in value or b'timed out' in value:
        return 'network_or_transport_error'
    return 'unclassified_nonzero_git_error_raw_withheld'


started = time.monotonic()
report = {'schema':'existing-git-readonly-capability-probe-v1',
    'repository':'TrillionniumFoundation/hepta-private-ci', 'source_path':str(SOURCE),
    'expected_ref':EXPECTED_REF, 'expected_head':EXPECTED_HEAD,
    'ls_remote_timeout_seconds':60, 'ls_remote_attempts':0,
    'origin_url_emitted_or_saved':False, 'credential_material_emitted_or_saved':False,
    'credential_helper_modified':False, 'new_account_or_login_attempted':False,
    'clone_push_upload_or_branch_mutation':False,
    'stderr_policy':'Raw Git stderr is held only in memory and omitted from all durable/user output to prevent origin credentials being disclosed; classification and byte length only.',
    'failures':[]}
try:
    report['configurations_before'] = config_hashes()
    if report['configurations_before'] != CONFIGS:
        raise ValueError('protected configurations differ before probe')
    report['source_before'] = source_identity()
    if report['source_before']['commit'] != EXPECTED_COMMIT or report['source_before']['tree'] != EXPECTED_TREE or not report['source_before']['tracked_clean']:
        raise ValueError('exact clean existing source required')
    report['origin_matches_expected_repository'] = expected_origin(local_git(['remote','get-url','origin']))
    if not report['origin_matches_expected_repository']:
        raise ValueError('existing origin is not the exact authorized repository')
    report['ls_remote_attempts'] = 1
    call_started = time.monotonic()
    try:
        response = subprocess.run(['git','-C',str(SOURCE),'ls-remote','--heads','origin',EXPECTED_REF],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, env=ENV)
        report['ls_remote_elapsed_seconds'] = time.monotonic() - call_started
        report['ls_remote_returncode'] = response.returncode
        report['ls_remote_timed_out'] = False
        report['git_stderr_bytes'] = len(response.stderr)
        if response.returncode == 0:
            records = []
            for line in response.stdout.splitlines():
                match = re.fullmatch(rb'([0-9a-f]{40})\t' + re.escape(EXPECTED_REF.encode()), line)
                if match is None:
                    raise ValueError('unexpected ls-remote output; raw output withheld')
                records.append({'sha':match.group(1).decode('ascii'), 'ref':EXPECTED_REF})
            report['actual_refs'] = records
            report['expected_head_matches'] = records == [{'sha':EXPECTED_HEAD,'ref':EXPECTED_REF}]
            report['existing_git_read_access'] = len(records) == 1
            if not report['expected_head_matches']:
                report['failures'].append('expected evidence ref/head did not match')
        else:
            report['existing_git_read_access'] = False
            report['git_error_classification'] = safe_error_classification(response.stderr)
            report['failures'].append('existing Git ls-remote returned nonzero; no fallback attempted')
    except subprocess.TimeoutExpired:
        report['ls_remote_elapsed_seconds'] = time.monotonic() - call_started
        report['ls_remote_timed_out'] = True
        report['existing_git_read_access'] = False
        report['failures'].append('original 60-second ls-remote timeout; no retry attempted')
except Exception as error:
    report['failures'].append('safe probe exception type: ' + type(error).__name__)
finally:
    try:
        report['configurations_after'] = config_hashes()
        report['configurations_unchanged'] = report.get('configurations_before') == report['configurations_after'] == CONFIGS
        report['source_after'] = source_identity()
        report['source_unchanged'] = report.get('source_before') == report['source_after']
        if not report['configurations_unchanged'] or not report['source_unchanged']:
            report['failures'].append('protected source/configuration changed')
    except Exception as error:
        report['failures'].append('post-probe verification exception type: ' + type(error).__name__)
    report['elapsed_seconds'] = time.monotonic() - started
    report['status'] = 'READ_ONLY_PROBE_PASSED' if not report['failures'] else 'READ_ONLY_PROBE_NOT_PASSED'
    sys.stdout.write(json.dumps(report,sort_keys=True,indent=2)+'\n')
    sys.stdout.flush()
sys.exit(0 if not report['failures'] else 1)
