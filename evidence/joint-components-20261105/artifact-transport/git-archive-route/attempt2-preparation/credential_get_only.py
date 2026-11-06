"""Read an existing credential; never approve/store/erase or log its contents."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

SOURCE = '/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf/source-h3'
REPO = 'TrillionniumFoundation/hepta-private-ci'


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('get', 'store', 'erase'):
        return 1
    request = sys.stdin.buffer.read(16385)
    if len(request) > 16384:
        return 1
    if sys.argv[1] != 'get':
        return 0
    fields = {}
    for line in request.decode('utf-8').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in fields:
                return 1
            fields[key] = value
    if fields.get('protocol') != 'https' or fields.get('host') != 'github.com':
        return 1
    if fields.get('path', '').removesuffix('.git') != REPO:
        return 1
    origin = os.environ['HEPTA_TRANSPORT_ORIGIN']
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or parsed.hostname != 'github.com'
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.path.lstrip('/').removesuffix('.git') != REPO
            or parsed.query or parsed.fragment):
        return 1
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith('GIT_CONFIG_') or key.startswith('HEPTA_TRANSPORT_'):
            env.pop(key)
    original = json.loads(os.environ['HEPTA_TRANSPORT_ORIGINAL_GIT_CONFIG_ENV'])
    if any(not key.startswith('GIT_CONFIG_') for key in original):
        return 1
    env.update(original)
    env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0',
               GIT_ASKPASS='/bin/false', SSH_ASKPASS='/bin/false', GCM_INTERACTIVE='Never')
    response = subprocess.run(['git', '-C', SOURCE, 'credential', 'fill'],
                              input=('url=' + origin + '\n\n').encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, timeout=15)
    if response.returncode or len(response.stdout) > 16384:
        return 1
    values = {}
    for line in response.stdout.splitlines():
        if b'=' in line:
            key, value = line.split(b'=', 1)
            if key in (b'username', b'password'):
                if key in values or not value:
                    return 1
                values[key] = value
    if set(values) != {b'username', b'password'}:
        return 1
    sys.stdout.buffer.write(b'username=' + values[b'username'] + b'\npassword=' + values[b'password'] + b'\n\n')
    sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        code = 1
    sys.exit(code)
