"""Natural OS-process fixtures; no expected result is substituted for the owner."""
from collections import Counter
import os

ENVIRONMENT_KEY = b"CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS"
CASE_COUNT = 994
ENVIRONMENTS = (None, b"", b"1", b"0", b"01", b" 1", b"1\n", b"true",
                "１".encode(), "1\u200b".encode(), "🙂".encode(), b"\xff", b"1\xff")
KINDS = (
    "add", "add-overwrite", "add-nested", "add-directory", "add-symlink",
    "delete", "delete-missing", "delete-directory", "delete-symlink",
    "update", "update-crlf", "update-mixed", "update-cr", "update-no-final-newline",
    "update-missing", "update-directory", "update-invalid-utf8", "update-symlink",
    "move", "move-overwrite", "move-directory", "move-same", "move-symlink",
    "prefix-then-failure", "mixed-success", "empty-patch", "invalid-patch",
    "invalid-hunk", "heredoc", "unicode-name", "nul-content", "absolute-path",
)


def matrix():
    cases = []

    def add(category, **values):
        case = {"id": len(cases), "category": category, "kind": "add", "transport": "arg",
                "argv0_hex": b"apply_patch".hex(), "extra_args_hex": [], "first_arg_hex": None,
                "stdin_mode": "bytes", "stdin_override_hex": None, "environment_hex": None,
                "stdout_mode": "pipe", "stderr_mode": "pipe", "cwd_mode": "normal"}
        case.update(values)
        cases.append(case)

    for kind in KINDS:
        for transport in ("arg", "stdin"):
            for environment in ENVIRONMENTS:
                add("full-main-patch-environment", kind=kind, transport=transport,
                    environment_hex=None if environment is None else environment.hex())
    early = (
        {"transport": "stdin", "stdin_override_hex": ""},
        {"transport": "stdin", "stdin_override_hex": b"\xff".hex()},
        {"transport": "stdin", "stdin_override_hex": b"prefix\xc3".hex()},
        {"transport": "stdin", "stdin_mode": "directory"},
        {"first_arg_hex": "", "stdin_mode": "open-pipe"},
        {"first_arg_hex": b"\xff".hex()},
        {"first_arg_hex": b"\xff".hex(), "extra_args_hex": [b"extra".hex()]},
        {"extra_args_hex": [b"extra".hex()]},
        {"extra_args_hex": [b"\xff".hex()]},
        {"first_arg_hex": "", "extra_args_hex": [b"extra".hex()]},
        {"stdin_mode": "open-pipe"},
        {"stdin_mode": "directory"},
        {"stdin_override_hex": b"\xff".hex()},
        {"argv0_hex": ""},
        {"argv0_hex": b"\xff-apply_patch".hex()},
    )
    for values in early:
        for cwd in ("normal", "removed-after-chdir"):
            for stderr in ("pipe", "closed-pipe"):
                add("argument-stdin-priority", **values, cwd_mode=cwd, stderr_mode=stderr)
    for kind in ("add", "prefix-then-failure", "empty-patch", "invalid-patch", "update-crlf"):
        for transport in ("arg", "stdin"):
            for stdout, stderr in (("closed-pipe", "pipe"), ("pipe", "closed-pipe"), ("closed-pipe", "closed-pipe")):
                for environment in (None, b"1"):
                    add("real-closed-output-pipes", kind=kind, transport=transport,
                        stdout_mode=stdout, stderr_mode=stderr,
                        environment_hex=None if environment is None else environment.hex())
    for cwd in ("unicode", "nonutf8", "removed-after-chdir"):
        for kind in ("add", "update-crlf", "invalid-patch"):
            if cwd == "removed-after-chdir" and kind == "update-crlf":
                continue
            for transport in ("arg", "stdin"):
                add("cwd-byte-and-failure-edges", kind=kind, transport=transport, cwd_mode=cwd)
    for kind in ("heredoc-eof", "heredoc-single-eof", "heredoc-double-eof",
                 "heredoc-unicode-eof", "heredoc-suffix-eof", "heredoc-invalid-quotes"):
        for transport in ("arg", "stdin"):
            for environment in (None, b"1"):
                add("literal-heredoc-boundaries", kind=kind, transport=transport,
                    environment_hex=None if environment is None else environment.hex())
    for environment in (None, b"1"):
        add("large-stdin", kind="large-add", transport="stdin",
            environment_hex=None if environment is None else environment.hex())
    assert len(cases) == CASE_COUNT
    return cases


def categories(cases):
    return dict(Counter(case["category"] for case in cases))


def materialize(case, root):
    """Create only this fresh owned fixture, then return exact execve inputs."""
    root.mkdir()
    raw_root = os.fsencode(root)
    cwd_name = {"normal": b"cwd", "unicode": "cwd-é🙂".encode(),
                "nonutf8": b"cwd-\xff", "removed-after-chdir": b"cwd"}[case["cwd_mode"]]
    cwd = raw_root + b"/" + cwd_name
    os.mkdir(cwd)

    def path(relative):
        encoded = relative if isinstance(relative, bytes) else relative.encode()
        assert encoded and not encoded.startswith(b"/") and b".." not in encoded.split(b"/")
        return cwd + b"/" + encoded

    def file(relative, data):
        filename = path(relative)
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "xb") as stream:
            stream.write(data)
        os.chmod(filename, 0o644)

    def directory(relative):
        os.makedirs(path(relative), exist_ok=True)

    kind = case["kind"]
    name = "target.txt"
    body = "*** Add File: target.txt\n+new\n"
    if kind.startswith("add"):
        if kind == "add-overwrite":
            file(name, b"old\n")
        elif kind == "add-nested":
            body = "*** Add File: nested/deep/target.txt\n+new\n"
        elif kind == "add-directory":
            directory(name)
        elif kind == "add-symlink":
            file("real.txt", b"old\n")
            os.symlink(b"real.txt", path(name))
    elif kind.startswith("delete"):
        body = "*** Delete File: target.txt\n"
        if kind == "delete-directory":
            directory(name)
        elif kind == "delete-symlink":
            file("real.txt", b"old\n")
            os.symlink(b"real.txt", path(name))
        elif kind != "delete-missing":
            file(name, b"old\n")
    elif kind.startswith("update"):
        old = {"update-crlf": b"one\r\ntwo\r\n", "update-mixed": b"one\r\ntwo\n",
               "update-cr": b"one\rtwo\r", "update-no-final-newline": b"one\ntwo",
               "update-invalid-utf8": b"one\n\xff\n"}.get(kind, b"one\ntwo\n")
        body = "*** Update File: target.txt\n@@\n-one\n-two\n+ONE\n+TWO\n"
        if kind == "update-directory":
            directory(name)
        elif kind == "update-symlink":
            file("real.txt", old)
            os.symlink(b"real.txt", path(name))
        elif kind != "update-missing":
            file(name, old)
    elif kind.startswith("move"):
        file(name, b"one\ntwo\n")
        destination = "target.txt" if kind == "move-same" else "moved.txt"
        body = "*** Update File: target.txt\n*** Move to: " + destination + "\n@@\n-one\n+ONE\n two\n"
        if kind == "move-overwrite":
            file(destination, b"overwritten\n")
        elif kind == "move-directory":
            directory(destination)
        elif kind == "move-symlink":
            file("real.txt", b"overwritten\n")
            os.symlink(b"real.txt", path(destination))
    elif kind == "prefix-then-failure":
        body += "*** Delete File: missing.txt\n"
    elif kind == "mixed-success":
        file("old.txt", b"old\n")
        file("update.txt", b"old\n")
        body += "*** Delete File: old.txt\n*** Update File: update.txt\n@@\n-old\n+changed\n"
    elif kind == "empty-patch":
        body = ""
    elif kind == "invalid-hunk":
        body = "*** Update File: target.txt\nthis is not a chunk\n"
    elif kind == "unicode-name":
        body = "*** Add File: 汉🙂.txt\n+é\n"
    elif kind == "nul-content":
        body = "*** Add File: target.txt\n+nul\x00byte\n"
    elif kind == "absolute-path":
        body = "*** Add File: " + os.fsdecode(path(name)) + "\n+new\n"
    elif kind == "large-add":
        body = "*** Add File: target.txt\n+" + "x" * (256 * 1024 + 7) + "\n"
    elif not kind.startswith("heredoc") and kind != "invalid-patch":
        raise AssertionError("unknown fixed fixture")
    patch = ("*** Begin Patch\n" + body + "*** End Patch\n").encode()
    if kind == "invalid-patch":
        patch = b"not a patch\n"
    elif kind.startswith("heredoc"):
        wrappers = {
            "heredoc": (b"<<'PATCH'\n", b"PATCH\n"),
            "heredoc-eof": (b"<<EOF\n", b"EOF\n"),
            "heredoc-single-eof": (b"<<'EOF'\n", b"EOF\n"),
            "heredoc-double-eof": (b'<<"EOF"\n', b"EOF\n"),
            "heredoc-unicode-eof": ("\u2003<<'EOF'\n".encode(), "EOF\n\u3000".encode()),
            "heredoc-suffix-eof": (b"<<EOF\n", b"prefix-EOF\n"),
            "heredoc-invalid-quotes": (b'<<"EOF\'\n', b"EOF\n"),
        }
        first, last = wrappers[kind]
        patch = first + patch + last
    args = [] if case["transport"] == "stdin" else [patch]
    if case["first_arg_hex"] is not None:
        assert args
        args[0] = bytes.fromhex(case["first_arg_hex"])
    args.extend(bytes.fromhex(value) for value in case["extra_args_hex"])
    stdin = patch if case["transport"] == "stdin" else b""
    if case["stdin_override_hex"] is not None:
        stdin = bytes.fromhex(case["stdin_override_hex"])
    if case["stdin_mode"] == "open-pipe":
        assert args, "an intentionally unclosed stdin is only used when an argument is supplied"
    if kind == "nul-content" and case["transport"] == "arg":
        # NUL is not legal in execve arguments. Keep an actual argv case with a
        # normal patch and the NUL input ignored on stdin; the stdin case passes
        # the full NUL-containing patch to the real original program.
        args[0] = b"*** Begin Patch\n*** Add File: target.txt\n+new\n*** End Patch\n"
        stdin = patch
    assert all(b"\0" not in value for value in args)
    environment = {b"PATH": os.fsencode(os.defpath), b"LANG": b"C.UTF-8",
                   b"LC_ALL": b"C.UTF-8", b"TZ": b"UTC", b"RUST_BACKTRACE": b"0"}
    if case["environment_hex"] is not None:
        environment[ENVIRONMENT_KEY] = bytes.fromhex(case["environment_hex"])
    assert all(b"\0" not in key + value for key, value in environment.items())
    if case["stdin_mode"] == "directory":
        os.mkdir(raw_root + b"/stdin-directory")
    # Cwd removal is confined to a fresh empty directory before exec. No case
    # that requires a preexisting file may select this failure mechanism.
    if case["cwd_mode"] == "removed-after-chdir":
        assert not os.listdir(cwd), "removed cwd fixture must be empty"
    return {"argv": [bytes.fromhex(case["argv0_hex"]), *args], "stdin": stdin,
            "cwd": cwd, "environment": environment, "patch": patch}
