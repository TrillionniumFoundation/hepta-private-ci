"""Bind qualification subprocesses and read optional observer measurements.

The shared file reader bounds a GNU time usage snapshot to 16 KiB and rejects
observed replacement, nonregular files and symlinks. Unavailable usage remains
None, never zero, and cannot overwrite the child failure recorded by its owner.
The original Python probe command/environment and 30-second budget are retained;
its two pipes now share the existing process owner with separate 16 KiB caps.
Neither file snapshots nor a probe's reported versions attest execution identity,
physical resource limits, independent operation, model benefit or public TPS.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


# Reuse the owner that bounds output, elapsed time and process-group cleanup.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'formal/pon-nakamoto-v1'))
from bounded_process import run_bounded
from ci.read_native_cache_observation import read_bounded, strict_json

GNU_TIME_EXECUTABLE_LIMIT = 16 * 1024 * 1024
GNU_TIME_PROBE_LIMIT = 16 * 1024
GNU_TIME_USAGE_LIMIT = 16 * 1024
PYTHON_RUNTIME_PROBE_LIMIT = 16 * 1024


def gnu_time_sha256(executable):
    """Hash a bounded regular file without allocating its full contents."""
    descriptor = os.open(executable, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('GNU_TIME_REGULAR_FILE_REQUIRED')
        if info.st_size > GNU_TIME_EXECUTABLE_LIMIT:
            raise ValueError('GNU_TIME_EXECUTABLE_LIMIT')
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = stream.read(min(65536, GNU_TIME_EXECUTABLE_LIMIT - size + 1))
            if not chunk:
                return digest.hexdigest()
            size += len(chunk)
            if size > GNU_TIME_EXECUTABLE_LIMIT:
                raise ValueError('GNU_TIME_EXECUTABLE_LIMIT')
            digest.update(chunk)


def verify_gnu_time(observer):
    """Software file observation only; not race-free execution attestation."""
    if gnu_time_sha256(observer['executable']) != observer['sha256']:
        raise ValueError('GNU_TIME_EXECUTABLE_CHANGED')


def bind_gnu_time(environment):
    """Select a real GNU time executable, without shell or implicit PATH fallback.

    TRNM_GNU_TIME may name an absolute executable path (for example an official
    package extracted into a writable workspace). The default is /usr/bin/time.
    A bounded identity probe must succeed; absence or another implementation is
    an error, never an unmeasured successful qualification. Preserve this one
    explicit observer selection when sanitizing TRNM_* for nested runners.
    """
    environment = dict(environment)
    selected = environment.get('TRNM_GNU_TIME', '/usr/bin/time')
    if not Path(selected).is_absolute():
        raise ValueError('GNU_TIME_ABSOLUTE_PATH_REQUIRED')
    executable = Path(selected).resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('GNU_TIME_EXECUTABLE_REQUIRED')
    digest = gnu_time_sha256(executable)
    probe = run_bounded([str(executable), '--version'], b'', timeout=5,
                        stdout_limit=GNU_TIME_PROBE_LIMIT, stderr_limit=GNU_TIME_PROBE_LIMIT)
    if probe.returncode:
        raise ValueError('GNU_TIME_PROBE_FAILED')
    identity = probe.stdout.decode('utf-8').strip()
    if not re.match(r'^time \(GNU [Tt]ime\)', identity):
        raise ValueError('GNU_TIME_IDENTITY_REQUIRED')
    if gnu_time_sha256(executable) != digest:
        raise ValueError('GNU_TIME_CHANGED_DURING_PROBE')
    environment['TRNM_GNU_TIME'] = str(executable)
    return environment, dict(executable=str(executable), sha256=digest,
                             identity=identity, observation='software-file-snapshot-not-execution-attestation')


def read_gnu_time_peak_rss(usage):
    """Return recorded GNU time RSS, or None when its measurement is unavailable.

    Killing the whole subprocess group can kill GNU time before it writes a
    summary. Missing, empty or malformed output must not hide the child's actual
    exit status or timeout. Zero is returned only when the file records zero.
    """
    try:
        lines = read_bounded(usage, GNU_TIME_USAGE_LIMIT).decode('utf-8').splitlines()
        if not lines:
            return None
        values = lines[-1].split()
        if (len(values) != 3 or not re.fullmatch(r'[0-9]+', values[0])
                or any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value)
                       for value in values[1:])):
            return None
        return int(values[0])
    except (OSError, UnicodeError, ValueError):
        return None


def bind_python_runtime(environment):
    # Preserve the venv path: resolving its interpreter symlink selects system Python.
    environment = dict(environment)
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment.get('PATH', '')
    command = [
        'python3', '-c',
        'import sys,platform,json,numpy,cryptography; '
        'print(json.dumps(dict(executable=sys.executable,python=platform.python_version(),'
        'numpy=numpy.__version__,cryptography=cryptography.__version__)))',
    ]
    probe = run_bounded(command, b'', env=environment, timeout=30,
                        stdout_limit=PYTHON_RUNTIME_PROBE_LIMIT,
                        stderr_limit=PYTHON_RUNTIME_PROBE_LIMIT)
    if probe.returncode:
        raise subprocess.CalledProcessError(probe.returncode, command,
                                            output=probe.stdout, stderr=probe.stderr)
    observation = strict_json(probe.stdout.decode('utf-8'))
    fields = {'executable', 'python', 'numpy', 'cryptography'}
    if (type(observation) is not dict or set(observation) != fields
            or any(type(value) is not str or not value for value in observation.values())):
        raise ValueError('PYTHON_RUNTIME_IDENTITY_REQUIRED')
    return environment, observation
