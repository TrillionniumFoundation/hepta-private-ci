#!/usr/bin/env python3
"""Opt-in SDK-only diagnostic bootstrap. Fail closed; never tune host security."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request

CONTRACT_SHA256 = "055ec2aaa3498af8952fa7ead62067119764d11c85e9d3cab01f8d0e5cf1d9fa"
TOOLS_SHA256 = "394c568da25bffe4a98e20bf07910a3add13aa9ff3a4ca28acd5f496280881e0"


class Hold(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Hold(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_bytes(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), f"not a regular file: {path}")
        return stream.read()


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
    return subprocess.check_output(
        ["/usr/bin/git", "-C", str(repo), "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args], env=env
    )


def tree(repo, ref):
    entries = {}
    for item in git(repo, "ls-tree", "-rz", "--full-tree", ref).split(b"\0"):
        if item:
            meta, path = item.split(b"\t", 1)
            mode, kind, sha = meta.decode().split()
            require(kind == "blob" and mode in {"100644", "100755", "120000"}, "unsupported tree entry")
            entries[os.fsdecode(path)] = (mode, sha)
    return entries


def source_guard(repo, contract, env, final=False):
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None and env.get("GITHUB_SHA") == head, "checkout/event SHA mismatch")
    require(env.get("GITHUB_REPOSITORY") == contract["repository"], "unexpected repository")
    require(env.get("GITHUB_EVENT_NAME") == "push" and env.get("GITHUB_REF") == contract["branch"], "unexpected event/ref")
    parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").decode().split()[1:]
    require(parents == [contract["source_commit"]], "diagnostic must be one direct child of approved source")
    require(git(repo, "rev-parse", f"{parents[0]}^{{tree}}").decode().strip() == contract["source_tree"], "source tree mismatch")
    baseline, current = tree(repo, parents[0]), tree(repo, "HEAD")
    require(contract.get("schema") == 2, "unsupported source contract")
    added = set(contract["added_paths"])
    require(len(added) == 4 and not added.intersection(baseline), "invalid diagnostic path roster")
    require(set(current) == set(baseline) | added, "unexpected added/deleted paths")
    repairs = contract.get("modified_paths", {})
    require(isinstance(repairs, dict) and set(repairs) == {".github/workflows/sdk.yml"}, "invalid approved repair roster")
    repair = repairs[".github/workflows/sdk.yml"]
    require(isinstance(repair, dict) and set(repair) == {"before", "after"}, "invalid repair identity")
    before, after = repair["before"], repair["after"]
    require(all(isinstance(value, list) and len(value) == 2 and value[0] == "100644"
                and isinstance(value[1], str) and re.fullmatch(r"[0-9a-f]{40}", value[1])
                for value in (before, after)), "invalid repair blob/mode")
    require(before != after and baseline[".github/workflows/sdk.yml"] == tuple(before), "repair baseline differs")
    expected = dict(baseline)
    expected[".github/workflows/sdk.yml"] = tuple(after)
    require(all(current[p] == value for p, value in expected.items()), "production source differs from approved source and SDK repair")
    require(all(current[p][0] == "100644" for p in added), "diagnostic helpers must be regular non-executable files")
    index = {}
    for item in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
        if item:
            meta, path = item.split(b"\t", 1)
            mode, sha, stage = meta.decode().split()
            require(stage == "0", "unmerged index")
            index[os.fsdecode(path)] = (mode, sha)
    require(index == current, "index differs from committed source")
    for switch in ("-v", "-f"):
        require(all(x[:2] == b"H " for x in git(repo, "ls-files", switch, "-z").split(b"\0") if x), "hidden index flags are not allowed")
    for path, (mode, sha) in current.items():
        file = repo / path
        info = file.lstat()
        if mode == "120000":
            require(stat.S_ISLNK(info.st_mode), f"expected symlink: {path}")
            raw = os.fsencode(os.readlink(file))
        else:
            require(stat.S_ISREG(info.st_mode), f"expected regular file: {path}")
            require(bool(info.st_mode & 0o111) == (mode == "100755"), f"mode differs: {path}")
            raw = regular_bytes(file)
        actual = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        require(actual == sha, f"raw bytes differ: {path}")
    others = ["--others", "--exclude-standard"] if final else ["--others"]
    require(not git(repo, "ls-files", *others, "-z"), "unexpected untracked input/output")
    require(not os.path.lexists(repo / "user.bazelrc"), "optional user.bazelrc is not permitted")
    require(regular_bytes(repo / ".bazelversion").decode().strip() == contract["bazel_version"], "Bazel version differs")
    return head


def environment_guard(env):
    require(env.get("RUNNER_OS") == "Linux" and env.get("RUNNER_ARCH") == "X64", "Linux x64 runner required")
    require(platform.system() == "Linux" and platform.machine() == "x86_64", "unexpected native platform")
    for key in ("BUILDBUDDY_API_KEY", "BAZELRC", "BAZEL_OPTS", "BAZEL_STARTUP_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "LD_PRELOAD", "BASH_ENV", "ENV"):
        require(not env.get(key), f"unexpected override: {key}")


def policy_receipt(read_text=lambda p: Path(p).read_text(), uid=os.geteuid):
    """Observe policy only; neither a capability probe nor a qualification claim."""
    ordinary_uid = uid()
    require(ordinary_uid != 0, "policy receipt must run as ordinary job user")
    policies = {}
    paths = {
        "unprivileged_userns_clone": "/proc/sys/kernel/unprivileged_userns_clone",
        "max_user_namespaces": "/proc/sys/user/max_user_namespaces",
        "apparmor_restrict_unprivileged_userns": "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
    }
    for name, path in paths.items():
        try:
            policies[name] = {"status": "present", "value": read_text(path).strip()}
        except FileNotFoundError:
            policies[name] = {"status": "missing"}
        except (OSError, UnicodeError) as error:
            policies[name] = {"status": "unreadable", "error_type": type(error).__name__}
    return {"ordinary_uid": ordinary_uid, "policies": policies}


def output_receipt(repo):
    """Read staged artifacts, without executing them or asserting test success."""
    outputs = {}
    for name in ("codex", "codex-code-mode-host"):
        path = repo / ".tmp/sdk-ci" / name
        try:
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode), "staged output is not regular")
                checksum = hashlib.sha256()
                size = 0
                while chunk := stream.read(1024 * 1024):
                    checksum.update(chunk)
                    size += len(chunk)
                after = os.fstat(stream.fileno())
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)
            if identity(before) != identity(after) or size != after.st_size:
                outputs[name] = {"status": "changed_during_read"}
            else:
                outputs[name] = {"status": "present", "bytes": size, "sha256": checksum.hexdigest(), "mode": oct(stat.S_IMODE(after.st_mode))}
        except FileNotFoundError:
            outputs[name] = {"status": "missing"}
        except (OSError, Hold) as error:
            outputs[name] = {"status": "unreadable", "error_type": type(error).__name__}
    return {"outputs": outputs, "qualification": "unknown; consult original step and test outcomes"}


def project_rc(raw, optional_line):
    """Only the original keyless Linux SDK's active, non-configured defaults."""
    output = []
    imports = 0
    dangerous = ("--remote_executor", "--remote_cache=", "--remote_header", "--bes_backend", "--bes_results_url", "--experimental_remote_downloader", "--credential_helper", "--config", "--strategy=", "--spawn_strategy=")
    for line in raw.decode().splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        if tokens[0].startswith(("import", "try-import")):
            require(line.strip() == optional_line, "unexpected rc import")
            imports += 1
            continue
        selector = tokens[0]
        if ":" in selector:
            base, config = selector.split(":", 1)
            if config != "linux":
                continue
            require(base in {"startup", "common", "build"}, "unsupported Linux rc selector")
            selector = base
        if selector not in {"startup", "common", "build"}:
            raise Hold("unsupported unconditional rc selector")
        require(len(tokens) >= 2 and all(t.startswith("--") for t in tokens[1:]), "unsupported rc grammar")
        require(not any(t.startswith(dangerous) for t in tokens[1:]), "remote/config/strategy setting in active rc")
        output.append(" ".join([selector, *(shlex.quote(t) for t in tokens[1:])]))
    require(imports == 1, "expected exactly the reviewed optional user rc import")
    return ("\n".join(output) + "\n").encode()


class HTTPSReleaseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlparse(newurl)
        require(url.scheme == "https" and url.hostname in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"} and url.username is None and url.password is None and url.port in {None, 443}, "unexpected release redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_payload(tool, opener=None):
    require(re.fullmatch(r"https://github\.com/(facebook/dotslash|casey/just|bazelbuild/bazel)/releases/download/[^/]+/[^/?#]+", tool["url"]) is not None, "unapproved release URL")
    require(re.fullmatch(r"[0-9a-f]{64}", tool["sha256"]) is not None, "invalid payload digest")
    require(0 < tool["size"] <= 100_000_000, "payload size outside bound")
    opener = opener or urllib.request.build_opener(HTTPSReleaseRedirects()).open
    with opener(tool["url"], timeout=60) as stream:
        raw = stream.read(tool["size"] + 1)
    require(len(raw) == tool["size"] and digest(raw) == tool["sha256"], "tool payload size/hash mismatch")
    return raw


def executable_payload(tool, raw):
    require(len(raw) == tool["size"] and digest(raw) == tool["sha256"], "unverified payload")
    if tool["format"] == "raw":
        require(tool["name"] == "bazel" and raw.startswith(b"\x7fELF"), "unexpected raw tool")
        return raw
    require(tool["format"] == "tar.gz" and tool["member"] == tool["name"], "unsupported archive contract")
    found = []
    count = total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|gz") as archive:
        for member in archive:
            count += 1
            total += member.size
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in member.name, "unsafe archive path")
            require(member.isfile() or member.isdir(), "archive link/device is forbidden")
            require(not member.mode & 0o7000, "special archive mode is forbidden")
            require(count <= 1000 and total <= 128 * 1024 * 1024, "archive expansion exceeds bound")
            if str(path) == tool["member"]:
                require(member.isfile() and member.size <= 32 * 1024 * 1024, "invalid executable member")
                with archive.extractfile(member) as stream:
                    found.append(stream.read())
    require(len(found) == 1 and found[0].startswith(b"\x7fELF"), "missing/duplicate/non-ELF executable")
    return found[0]


def write_new(path, raw, mode=0o600):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode), "wb") as stream:
        stream.write(raw)


def append_values(path, values):
    for key, value in values.items():
        require("\n" not in str(value) and "\r" not in str(value), "invalid workflow environment value")
    with open(path, "a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def bootstrap(repo, contract, env):
    source_guard(repo, contract, env)
    environment_guard(env)
    print("Read-only namespace policy (not capability): " + json.dumps(policy_receipt(), sort_keys=True))
    root = Path(tempfile.mkdtemp(prefix="a32-sdk-diagnostic-", dir=env["RUNNER_TEMP"]))
    cache = Path(env["HOME"]) / ".cache/codex-ci/bazel-repository-cache"
    for path in (root / "bin", root / "o", root / "b", root / "contents", root / "cargo-target", root / "tmp", cache):
        path.mkdir(parents=True, exist_ok=True)
        require(not path.is_symlink(), "symlinked build/cache directory")
    tools_raw = regular_bytes(repo / ".github/sdk-diagnostic/tools.json")
    require(digest(tools_raw) == TOOLS_SHA256, "tool manifest is not the reviewed release-metadata pin set")
    tools = json.loads(tools_raw)
    require(tools["schema"] == 1 and tools["os"] == "Linux" and tools["arch"] == "x86_64", "unexpected tool manifest")
    require([t["name"] for t in tools["tools"]] == ["dotslash", "just", "bazel"], "unexpected tool roster")
    require(tools["tools"][2]["version"] == contract["bazel_version"], "tool/source Bazel version mismatch")
    hashes = {}
    for tool in tools["tools"]:
        binary = executable_payload(tool, fetch_payload(tool))
        destination = root / "bin" / ("bazel-real" if tool["name"] == "bazel" else tool["name"])
        write_new(destination, binary, 0o700)
        hashes[str(destination)] = digest(binary)
        print(f"Verified official payload {tool['name']} {tool['version']} sha256:{tool['sha256']}", flush=True)
    rc = root / "sdk.bazelrc"
    write_new(rc, project_rc(regular_bytes(repo / ".bazelrc"), contract["optional_rc_line"]))
    hashes[str(rc)] = digest(regular_bytes(rc))
    critical = [".bazelrc", ".bazelversion", ".github/scripts/run-bazel-ci.sh", ".github/scripts/run_bazel_with_buildbuddy.py", ".github/scripts/sdk_diagnostic.py", ".github/sdk-diagnostic/source.json", ".github/sdk-diagnostic/tools.json"]
    hashes.update({str(repo / p): digest(regular_bytes(repo / p)) for p in critical})
    shim = root / "bin/bazel"
    write_new(shim, ("#!/bin/sh\nexec /usr/bin/python3 " + shlex.quote(str(repo / ".github/scripts/sdk_diagnostic.py")) + ' bazel "$@"\n').encode(), 0o700)
    hashes[str(shim)] = digest(regular_bytes(shim))
    state = {"root": str(root), "repository": str(repo), "cache": str(cache), "head": env["GITHUB_SHA"], "hashes": hashes}
    state_path = root / "state.json"
    raw = json.dumps(state, sort_keys=True).encode()
    write_new(state_path, raw, 0o400)
    append_values(env["GITHUB_ENV"], {"SDK_DIAGNOSTIC_STATE": str(state_path), "SDK_DIAGNOSTIC_STATE_SHA256": digest(raw), "CODEX_REPO_ROOT": str(repo), "CI_BUILD_ROOT": str(root), "BAZEL_OUTPUT_BASE": str(root / "o"), "BAZEL_OUTPUT_USER_ROOT": str(root / "b"), "BAZEL_REPOSITORY_CACHE": str(cache), "BAZEL_REPO_CONTENTS_CACHE": str(root / "contents"), "CARGO_TARGET_DIR": str(root / "cargo-target"), "TEMP": str(root / "tmp"), "TMP": str(root / "tmp"), "CARGO_NET_GIT_FETCH_WITH_CLI": "true", "CODEX_BAZEL_BIN": str(shim), "BUILDBUDDY_API_KEY": ""})
    append_values(env["GITHUB_OUTPUT"], {"repository-cache-path": str(cache), "bazel-output-base": str(root / "o"), "cargo-target-dir": str(root / "cargo-target")})
    with open(env["GITHUB_PATH"], "a", encoding="utf-8") as stream:
        stream.write(str(root / "bin") + "\n")


def expected_arguments(state):
    root = Path(state["root"])
    start = [f"--output_user_root={root / 'b'}", "--noexperimental_remote_repo_contents_cache"]
    caches = [f"--repo_contents_cache={root / 'contents'}", f"--repository_cache={state['cache']}"]
    targets = ["//codex-rs/cli:codex", "//codex-rs/code-mode-host:codex-code-mode-host"]
    return [start + ["build", f"--build_metadata=COMMIT_SHA={state['head']}", "--build_metadata=TAG_job=sdk", "--remote_download_toplevel"] + caches + ["--"] + targets,
            *[start + ["cquery", "--output=files"] + caches + ["--", target] for target in targets]]


def guarded_bazel_command(args, state):
    require(args in expected_arguments(state), "unexpected Bazel command/flag/order/target; no remote override permitted")
    root = Path(state["root"])
    return [str(root / "bin/bazel-real"), "--nosystem_rc", "--nohome_rc", "--noworkspace_rc", f"--bazelrc={root / 'sdk.bazelrc'}", "--bazelrc=/dev/null", f"--output_base={root / 'o'}", *args]


def run_bazel(args, env):
    environment_guard(env)
    raw = regular_bytes(Path(env["SDK_DIAGNOSTIC_STATE"]))
    require(digest(raw) == env["SDK_DIAGNOSTIC_STATE_SHA256"], "bootstrap state changed")
    state = json.loads(raw)
    require(env.get("GITHUB_SHA") == state["head"] and Path.cwd() == Path(state["repository"]), "Bazel source context changed")
    for path, expected in state["hashes"].items():
        require(digest(regular_bytes(Path(path))) == expected, f"bootstrap/source/tool bytes changed: {path}")
    require(not os.path.lexists(Path(state["repository"]) / "user.bazelrc"), "unexpected workspace user rc")
    command = guarded_bazel_command(args, state)
    print("Diagnostic Bazel: sealed local rc; no environment/system/home/workspace rc; exact original SDK argv", file=sys.stderr)
    print("Diagnostic Bazel invocation (strategy/outcome not yet observed): " + json.dumps({"argv": command, "rc_sha256": state["hashes"][str(Path(state["root"]) / "sdk.bazelrc")]}, sort_keys=True), file=sys.stderr, flush=True)
    os.execve(command[0], command, dict(env))


def main():
    require(len(sys.argv) >= 2, "subcommand required")
    mode = sys.argv[1]
    if mode == "bazel":
        run_bazel(sys.argv[2:], os.environ)
        return
    require(mode in {"preflight", "preflight-sdk", "bootstrap", "final"} and len(sys.argv) == 2, "unexpected subcommand")
    repo = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    contract_raw = regular_bytes(repo / ".github/sdk-diagnostic/source.json")
    require(digest(contract_raw) == CONTRACT_SHA256, "source contract is not the reviewed snapshot")
    contract = json.loads(contract_raw)
    environment_guard(os.environ)
    source_guard(repo, contract, os.environ, final=mode == "final")
    if mode == "preflight-sdk":
        print("Read-only namespace policy (not capability): " + json.dumps(policy_receipt(), sort_keys=True))
    if mode == "final":
        print("Staged output identity (not test success): " + json.dumps(output_receipt(repo), sort_keys=True))
    if mode == "bootstrap":
        bootstrap(repo, contract, os.environ)
    print(f"SDK diagnostic {mode}: passed scoped guard; not a native test-pass claim")


if __name__ == "__main__":
    try:
        main()
    except (Hold, OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(f"::error::HOLD: {error}", file=sys.stderr)
        raise SystemExit(1)
