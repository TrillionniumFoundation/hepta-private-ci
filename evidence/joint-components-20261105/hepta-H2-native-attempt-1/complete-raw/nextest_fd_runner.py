"""Capture each nextest run image before same-PID fd-exec.

External H2 execution configuration, not repository code or a permission grant.
Discovery is passed through without test credit. This runner never forks,
changes process groups, changes cwd, or writes to stdout. Its work is inside
nextest's original per-test deadline. Runtime outcome comes from libtest logs;
a pre-exec record alone is not execution or test-pass evidence.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import sys
import time

sys.dont_write_bytecode = True


def task(pid):
    fields = (Path('/proc') / str(pid) / 'stat').read_text().rpartition(')')[2].split()
    return int(fields[1]), fields[19]


def descendant(pid, owner):
    seen = set()
    for _ in range(64):
        if pid <= 1 or pid in seen:
            return False
        seen.add(pid)
        parent, ticks = task(pid)
        if pid == owner['pid']:
            return ticks == owner['start_ticks']
        pid = parent
    return False


def image_stat(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def write_record(path, value):
    pending = path.with_suffix('.pending')
    with pending.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def selected(value, config):
    if config['selected_names'] is not None:
        return value in config['selected_names']
    predicate = config['predicate']
    if predicate['kind'] == 'prefix':
        return value.startswith(predicate['value'])
    if predicate['kind'] == 'contains':
        return predicate['value'] in value and '::' in value
    raise ValueError('unsupported selection predicate')


def retain(fd, directory, token):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('test image is not regular')
    image = image_stat(before)
    first = os.read(fd, 4)
    if first != b'\x7fELF':
        raise ValueError('test image is not ELF')
    os.lseek(fd, 0, os.SEEK_SET)
    temporary = directory / (token + '.elf.pending')
    h = hashlib.sha256()
    with temporary.open('xb') as copy:
        while True:
            part = os.read(fd, 1024 * 1024)
            if not part:
                break
            h.update(part)
            copy.write(part)
        copy.flush()
        os.fsync(copy.fileno())
    if image_stat(os.fstat(fd)) != image:
        raise ValueError('opened test ELF changed while retained')
    hexdigest = h.hexdigest()
    final = directory / (hexdigest + '.elf')
    if final.exists():
        # Every completed gate rehashes the retained copy before granting credit.
        # The temporary copy was independently read from this invocation's fd.
        if final.stat().st_size != before.st_size:
            raise ValueError('retained image size differs')
        temporary.unlink()
    else:
        temporary.replace(final)
    os.lseek(fd, 0, os.SEEK_SET)
    return before, hexdigest, final


def main():
    config_path = Path(os.environ['HEPTA_NEXTEST_FD_CAPTURE_CONFIG'])
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    if config['schema'] != 'hepta-nextest-fd-runner-v1':
        raise ValueError('wrong capture configuration schema')
    if str(os.getpid()) != os.readlink('/proc/self'):
        raise ValueError('runner requires the process and /proc to share a PID namespace')
    if os.execve not in os.supports_fd:
        raise ValueError('this platform cannot exec the opened test-image fd')
    if len(sys.argv) < 2 or not Path(sys.argv[1]).is_absolute():
        raise ValueError('nextest must supply an absolute binary path')
    executable = Path(sys.argv[1])
    canonical = executable.resolve(strict=True)
    target = Path(config['target']).resolve(strict=True)
    if canonical != executable or not canonical.is_relative_to(target):
        raise ValueError('test-image path is not canonical within the declared target')
    if not re.fullmatch(re.escape(config['crate']) + r'-[a-f0-9]+', executable.name):
        raise ValueError('unexpected test image name')
    phase = os.environ.get('NEXTEST_TEST_PHASE')
    args = sys.argv[1:]
    pid = os.getpid()
    process = task(pid)
    if not descendant(pid, config['coordinator']):
        raise ValueError('runner is outside the exact coordinator subtree')
    descriptor = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if phase == 'list':
            if '--list' not in args:
                raise ValueError('discovery phase lacks the original list argument')
            os.execve(descriptor, args, os.environ)
            raise AssertionError('execve returned')
        if phase != 'run' or '--exact' not in args or '--list' in args:
            raise ValueError('only exact nextest run invocations receive execution records')
        index = args.index('--exact')
        if index + 1 >= len(args):
            raise ValueError('exact test name is missing')
        name = args[index + 1]
        if not selected(name, config) or sum(selected(value, config) for value in args[1:]) != 1:
            raise ValueError('invocation does not select one expected test')
        directory = Path(config['directory'])
        if not directory.is_dir() or directory.resolve() != directory:
            raise ValueError('capture directory is not canonical')
        token = str(pid) + '-' + process[1]
        before, hexdigest, retained = retain(descriptor, directory, token)
        if task(pid) != process or not descendant(pid, config['coordinator']):
            raise ValueError('runner process identity changed during retention')
        if image_stat(os.stat(executable, follow_symlinks=False)) != image_stat(before):
            raise ValueError('test-image pathname changed during retention')
        record_path = directory / (token + '.json')
        record = {
            'schema': config['schema'], 'status': 'pre_exec_fd_bound',
            'source': config['source'], 'gate': config['gate'],
            'capture_config_sha256': hashlib.sha256(config_raw).hexdigest(),
            'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'actual_executable': str(executable), 'retained_copy': str(retained),
            'sha256': hexdigest, 'bytes': before.st_size, 'device': before.st_dev,
            'inode': before.st_ino, 'mtime_ns': before.st_mtime_ns, 'ctime_ns': before.st_ctime_ns,
            'pid': pid, 'start_ticks': process[1], 'coordinator': config['coordinator'],
            'coordinator_descendant_verified': True, 'pre_exec_fd_identity_verified': True,
            'phase': phase, 'exact_test': name, 'argv': args,
            'observed_selected_tests': [name], 'captured_unix': time.time(),
            'scope': 'opened image bound immediately before same-PID fd-exec; requires matching actual libtest outcome and absence of exec failure',
        }
        write_record(record_path, record)
        if image_stat(os.fstat(descriptor)) != image_stat(before):
            raise ValueError('opened test ELF changed before exec')
        try:
            os.execve(descriptor, args, os.environ)
            raise AssertionError('execve returned')
        except BaseException as error:
            write_record(directory / (token + '.exec-error.json'),
                         {'status': 'exec_failed', 'error': repr(error), 'record': record_path.name})
            raise
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        # Original stderr is preserved. No stdout pollution may corrupt nextest
        # discovery or be mistaken for libtest output.
        print('hepta nextest fd runner refused execution: ' + repr(error), file=sys.stderr)
        raise
