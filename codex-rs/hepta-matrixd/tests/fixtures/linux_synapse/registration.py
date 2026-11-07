"""Carry two existing registration sessions outside every artifact directory."""

import json
import os
from pathlib import Path
import stat


NAMES = ("agent-a-session.json", "agent-b-session.json")
USERS = ("@hepta-agent-a:localhost", "@hepta-agent-b:localhost")
RUNTIME_DIRECTORY = "/tmp/hepta-registration-sessions"

# Use the pinned CLI's own nonce, HMAC and single POST. Only retain its otherwise
# discarded success response; never reproduce registration or log response data.
CAPTURE = r"""
import contextlib, json, os, pathlib, re, sys, tempfile, types
from synapse._scripts import register_new_matrix_user as cli

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate response key')
        result[key] = value
    return result

password_path = None
try:
    name, destination = sys.argv[1:]
    if name not in ('hepta-agent-a', 'hepta-agent-b') or not re.fullmatch(
        r'/tmp/hepta-linux-[0-9a-f]{32}-' + re.escape(name) + r'-session.json', destination
    ):
        raise ValueError('invalid registration capability destination')
    password = sys.stdin.buffer.read(258)
    if not re.fullmatch(b'[0-9a-f]{64}\n', password):
        raise ValueError('invalid registration password input')
    fd, password_path = tempfile.mkstemp(prefix='hepta-password-')
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(password)
    original, responses, calls = cli.requests, [], [0, 0]
    url = 'http://127.0.0.1:8008/_synapse/admin/v1/register'
    def get(actual, **kwargs):
        calls[0] += 1
        if actual != url or kwargs or calls != [1, 0]:
            raise ValueError('registration nonce call differs')
        return original.get(actual, **kwargs)
    def post(actual, **kwargs):
        calls[1] += 1
        if actual != url or set(kwargs) != {'json'} or calls != [1, 1]:
            raise ValueError('registration POST differs')
        response = original.post(actual, **kwargs)
        if response.status_code == 200:
            result = response.json(object_pairs_hook=unique)
            session = {key: result[key] for key in ('user_id', 'device_id', 'access_token')}
            if session['user_id'] != '@' + name + ':localhost':
                raise ValueError('registration user differs')
            for key, minimum, maximum in (('device_id', 1, 255), ('access_token', 32, 4096)):
                value = session[key]
                if not isinstance(value, str) or not minimum <= len(value) <= maximum or not all(
                    33 <= ord(char) <= 126 for char in value
                ):
                    raise ValueError('invalid registration session shape')
            responses.append(session)
        return response
    cli.requests = types.SimpleNamespace(get=get, post=post)
    sys.argv = ['register_new_matrix_user', '--config', '/data/homeserver.yaml',
                '--user', name, '--password-file', password_path, '--no-admin',
                'http://127.0.0.1:8008']
    with open(os.devnull, 'w') as silent, contextlib.redirect_stdout(silent), contextlib.redirect_stderr(silent):
        cli.main()
    if calls != [1, 1] or len(responses) != 1:
        raise ValueError('registration did not return exactly one session')
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(responses[0], stream, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
except BaseException:
    sys.stderr.write('Registration session capture failed\n')
    sys.exit(1)
finally:
    if password_path is not None:
        pathlib.Path(password_path).unlink(missing_ok=True)
"""

REMOVE = r"""
import pathlib, re, sys
path = sys.argv[1]
if not re.fullmatch(r'/tmp/hepta-linux-[0-9a-f]{32}-hepta-agent-[ab]-session.json', path):
    raise ValueError('invalid registration capability cleanup path')
pathlib.Path(path).unlink(missing_ok=True)
"""

INSTALL = r"""
import json, os, pathlib, sys
root = pathlib.Path('/tmp/hepta-registration-sessions')
names = ('agent-a-session.json', 'agent-b-session.json')
created = False
def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate session key')
        result[key] = value
    return result
try:
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise ValueError('registration sessions exceed bounded input')
    sessions = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(sessions, dict) or set(sessions) != set(names):
        raise ValueError('registration capability set differs')
    os.mkdir(root, 0o700)
    created = True
    os.chmod(root, 0o700)
    for name in names:
        fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(sessions[name], stream, separators=(',', ':'))
            stream.write('\n')
except BaseException:
    if created:
        for name in names:
            (root / name).unlink(missing_ok=True)
        root.rmdir()
    sys.stderr.write('Registration session installation failed\n')
    sys.exit(1)
"""


def register_agent_session(control, server, name, password, private_directory):
    index = ("hepta-agent-a", "hepta-agent-b").index(name)
    remote = f"/tmp/{control.prefix}-{name}-session.json"
    destination = private_directory / NAMES[index]
    if destination.exists() or destination.is_symlink():
        raise ValueError("Registration capability destination already exists")
    try:
        control.commands.run(
            "docker",
            ["exec", "-i", server, "python3", "-c", CAPTURE, name, remote],
            label="register-" + name,
            input_bytes=(password + "\n").encode(),
        )
        control.commands.run(
            "docker",
            ["cp", f"{server}:{remote}", str(destination)],
            label="receive-" + name + "-session",
        )
    finally:
        control.commands.run(
            "docker",
            ["exec", server, "python3", "-c", REMOVE, remote],
            label="remove-" + name + "-server-session",
        )


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate registration session field")
        result[key] = value
    return result


def read_once(path, user):
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        actual = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(actual.st_mode)
            or stat.S_IMODE(actual.st_mode) != 0o600
            or actual.st_uid != os.getuid()
            or actual.st_nlink != 1
            or (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError("Registration capability identity or mode differs")
        raw = stream.read(8193)
        after = path.lstat()
        if any(
            getattr(actual, key) != getattr(after, key)
            for key in (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mode",
                "st_uid",
                "st_nlink",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        ):
            raise ValueError("Registration capability changed during read")
        path.unlink()
    try:
        if len(raw) > 8192:
            raise ValueError("Registration capability exceeds bounded input")
        session = json.loads(raw, object_pairs_hook=unique_object)
        if (
            not isinstance(session, dict)
            or set(session) != {"user_id", "device_id", "access_token"}
            or session["user_id"] != user
        ):
            raise ValueError("Registration session identity differs")
        for key, minimum, maximum in (
            ("device_id", 1, 255),
            ("access_token", 32, 4096),
        ):
            value = session[key]
            if (
                not isinstance(value, str)
                or not minimum <= len(value) <= maximum
                or not all(33 <= ord(char) <= 126 for char in value)
            ):
                raise ValueError("Registration session field shape differs")
        return session
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid private registration session") from None


def install_registration_sessions(control, runtime, private_directory):
    directory = private_directory.lstat()
    if (
        private_directory.parent != Path("/tmp")
        or private_directory.resolve(strict=True) != private_directory
        or not stat.S_ISDIR(directory.st_mode)
        or stat.S_IMODE(directory.st_mode) != 0o700
        or directory.st_uid != os.getuid()
        or sorted(item.name for item in private_directory.iterdir()) != sorted(NAMES)
    ):
        raise ValueError(
            "Registration sessions require a separate private temp directory"
        )
    sessions = {
        name: read_once(private_directory / name, user)
        for name, user in zip(NAMES, USERS, strict=True)
    }
    if any(
        sessions[NAMES[0]][key] == sessions[NAMES[1]][key]
        for key in ("device_id", "access_token")
    ):
        raise ValueError("Registration sessions must use distinct devices and tokens")
    control.commands.run(
        "docker",
        [
            "exec",
            "-i",
            runtime,
            control.contract["tools"]["python3"]["path"],
            "-I",
            "-c",
            INSTALL,
        ],
        label="install-registration-sessions",
        input_bytes=json.dumps(sessions, separators=(",", ":")).encode(),
    )
