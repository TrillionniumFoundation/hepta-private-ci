"""Preserve every current native gate across three bounded parallel phases.

The immutable 33f source is the conservation reference. Each phase keeps the
original commands and per-test limits, rebuilds its own pinned compiler inputs,
and must execute every assigned gate successfully. A phase result never grants
PASS to the archived serial run or to another source revision.
"""
from __future__ import annotations

import argparse
import gzip
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
_EXECUTED_SOURCE = Path(__file__).resolve().read_bytes()
WORKFLOW = ".github/workflows/codex-hia-native.yml"
BASELINE = "hia/ci/fixtures/native-components-33f5d31b.yml.gz"
BASELINE_SHA256 = "e4fd43764ddcbb530c3710d94ac03dd9c57ae822a1d811aa0a80d1a8112a05af"
PINNED_COMPILER = "0de5657a80f96b138525ac7ee9ce11712a83a10d"
PHASES = ("abi", "owners", "installed")
COMMON = frozenset((2, 3, 4, 5, 6, 7, 54, 80, 115))
ABI = frozenset((*range(8, 54), *range(69, 73), 78, *range(86, 108)))
OWNERS = frozenset((*range(55, 69), *range(73, 78), *range(108, 115)))
INSTALLED = frozenset((79, *range(81, 86)))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate evidence field")
        result[key] = value
    return result


def decode(raw):
    def bad_constant(value):
        raise ValueError("non-finite evidence value: " + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def baseline(root=ROOT):
    raw = gzip.decompress((Path(root) / BASELINE).read_bytes())
    if sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("immutable original native workflow identity differs")
    return raw.decode("utf-8")


def split_workflow(text):
    marker = "  native-components:\n"
    if text.count(marker) != 1:
        raise ValueError("exactly one native-components job is required")
    start = text.index(marker)
    match = re.search(r"^  [A-Za-z0-9_-]+:\n", text[start + len(marker):], re.MULTILINE)
    if match is None:
        raise ValueError("original adjacent jobs are missing")
    end = start + len(marker) + match.start()
    return text[:start], text[start:end], text[end:]


def step_blocks(section):
    matches = list(re.finditer(r"^      - name: (.*)\n", section, re.MULTILINE))
    if not matches:
        raise ValueError("native gate steps are missing")
    header = section[:matches[0].start()]
    blocks = [section[match.start():matches[i + 1].start()
                      if i + 1 < len(matches) else len(section)]
              for i, match in enumerate(matches)]
    return header, blocks


def phase_for(number):
    memberships = [name for name, numbers in (
        ("common", COMMON), ("abi", ABI), ("owners", OWNERS), ("installed", INSTALLED))
        if number in numbers]
    if len(memberships) != 1:
        raise ValueError("original step has missing or overlapping phase allocation")
    return memberships[0]


def expression(value):
    return "$" + "{{ " + value + " }}"


def step_id(number, block):
    matches = re.findall(r"^        id: ([A-Za-z0-9_-]+)\n", block, re.MULTILINE)
    if len(matches) > 1:
        raise ValueError("duplicate step identity")
    return matches[0] if matches else "native_gate_" + str(number).zfill(3)


def transformed_step(number, block):
    identity = step_id(number, block)
    if not re.search(r"^        id: ", block, re.MULTILINE):
        first, rest = block.split("\n", 1)
        block = first + "\n        id: " + identity + "\n" + rest
    selected = phase_for(number)
    if selected != "common":
        condition = "matrix.phase == '" + selected + "'"
        found = re.search(r"^        if: (.*)\n", block, re.MULTILINE)
        if found:
            old = found.group(1)
            if not (old.startswith("$" + "{{ ") and old.endswith(" }}")):
                raise ValueError("original condition must remain an exact expression")
            replacement = expression(condition + " && (" + old[4:-3] + ")")
            block = block[:found.start(1)] + replacement + block[found.end(1):]
        else:
            id_line = "        id: " + identity + "\n"
            block = block.replace(id_line, id_line + "        if: " + expression(condition) + "\n", 1)
    if number == 115:
        old = "          name: codex-hia-current38-results\n"
        if block.count(old) != 1:
            raise ValueError("original artifact name changed")
        block = block.replace(old, "          name: codex-hia-current38-results-" + expression("matrix.phase") + "\n")
        old = "format('{0}/hia-native/build.json"
        if block.count(old) != 1:
            raise ValueError("original artifact paths changed")
        block = block.replace(old, "format('{0}/hia-native-phase-*.json\n            {0}/hia-native/build.json")
    return block


def source_before_step():
    raw = """      - name: Capture exact physical source for this native phase
        id: native_source_before
        run: |
          set -euo pipefail
          python3 -B codex/hia/ci/native_phase_gate.py before \\
            --codex-root "$GITHUB_WORKSPACE/codex" --hepta-root "$HEPTA_SOURCE" \\
            --expected-head "$GITHUB_SHA" --phase "@PHASE@" \\
            --report "$RUNNER_TEMP/hia-native-phase-before.json"

"""
    return raw.replace("@PHASE@", expression("matrix.phase"))


def source_after_step():
    raw = """      - name: Require all assigned gates and unchanged physical phase source
        id: native_phase_terminal
        if: @ALWAYS@
        env:
          HIA_PHASE_STEPS: @STEPS@
        run: |
          set -euo pipefail
          python3 -B codex/hia/ci/native_phase_gate.py after \\
            --codex-root "$GITHUB_WORKSPACE/codex" --hepta-root "$HEPTA_SOURCE" \\
            --expected-head "$GITHUB_SHA" --phase "@PHASE@" \\
            --before "$RUNNER_TEMP/hia-native-phase-before.json" \\
            --report "$RUNNER_TEMP/hia-native-phase-after.json" \\
            --terminal "$RUNNER_TEMP/hia-native-phase-result.json"

"""
    return (raw.replace("@ALWAYS@", expression("always()"))
            .replace("@STEPS@", expression("toJSON(steps)"))
            .replace("@PHASE@", expression("matrix.phase")))


def render(original):
    prefix, section, suffix = split_workflow(original)
    header, blocks = step_blocks(section)
    if len(blocks) != 114 or set(range(2, 116)) != COMMON | ABI | OWNERS | INSTALLED:
        raise ValueError("the complete original 114-step population differs")
    if header.count("    timeout-minutes: 60\n") != 1:
        raise ValueError("the original 60-minute budget differs")
    added = ("    name: Native components (" + expression("matrix.phase") + ")\n"
             "    strategy:\n"
             "      fail-fast: false\n"
             "      matrix:\n"
             "        phase: [abi, owners, installed]\n")
    header = header.replace("  native-components:\n", "  native-components:\n" + added, 1)
    result = []
    for number, block in enumerate(blocks, 2):
        if number == 115:
            result.append(source_after_step())
        result.append(transformed_step(number, block))
        if number == 3:
            result.append(source_before_step())
    return prefix + header + "".join(result) + suffix


def validate_workflow(text, root=ROOT):
    original = baseline(root)
    if text != render(original):
        raise ValueError("native phases changed an original gate, condition, limit, population or unrelated job")
    _, section, _ = split_workflow(original)
    _, blocks = step_blocks(section)
    rows = [{"original_number": n, "name": block.splitlines()[0][14:],
             "id": step_id(n, block), "phase": phase_for(n),
             "original_block_sha256": sha256(block.encode()).hexdigest()}
            for n, block in enumerate(blocks, 2)]
    return rows


def verify_outcomes(steps, phase, rows):
    if phase not in PHASES or type(steps) is not dict:
        raise ValueError("invalid phase or step observations")
    expected = ["native_source_before"] + [
        row["id"] for row in rows
        if row["original_number"] != 115 and row["phase"] in ("common", phase)]
    failed = []
    for identity in expected:
        item = steps.get(identity)
        if (type(item) is not dict or item.get("outcome") != "success"
                or item.get("conclusion") != "success"):
            failed.append({"id": identity, "observation": item})
    if failed:
        raise ValueError("assigned original gate did not complete successfully: " + json.dumps(failed, sort_keys=True))
    return expected


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def file_observation(path, mode, expected_blob):
    before = path.lstat()
    if mode == "120000":
        if not stat.S_ISLNK(before.st_mode):
            raise ValueError("tracked symlink was replaced: " + str(path))
        raw = os.fsencode(os.readlink(path))
        after = path.lstat()
        size = len(raw)
        git_hash = sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest()
        digest = sha256(raw).hexdigest()
    else:
        if mode not in ("100644", "100755") or not stat.S_ISREG(before.st_mode):
            raise ValueError("tracked file type differs: " + str(path))
        if bool(before.st_mode & 0o111) != (mode == "100755"):
            raise ValueError("tracked executable mode differs: " + str(path))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_mode) != (before.st_dev, before.st_ino, before.st_mode):
                raise ValueError("tracked file changed before capture")
            size = opened.st_size
            h1 = sha1(b"blob " + str(size).encode() + b"\0")
            h256 = sha256()
            actual_size = 0
            while True:
                chunk = stream.read(1048576)
                if not chunk:
                    break
                actual_size += len(chunk)
                h1.update(chunk)
                h256.update(chunk)
            after = os.fstat(stream.fileno())
        if actual_size != size:
            raise ValueError("tracked file extent changed")
        git_hash, digest = h1.hexdigest(), h256.hexdigest()
    identity = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in identity):
        raise ValueError("tracked file changed during capture")
    if git_hash != expected_blob:
        raise ValueError("physical bytes differ from the exact Git blob: " + str(path))
    return {"mode": mode, "bytes": size, "git_blob": expected_blob, "sha256": digest}


def capture_repo(root, expected_commit):
    root = Path(root).resolve(strict=True)
    if type(expected_commit) is not str or re.fullmatch("[0-9a-f]{40}", expected_commit) is None:
        raise ValueError("an exact commit is required")
    if git(root, "rev-parse", "HEAD").decode().strip() != expected_commit:
        raise ValueError("checkout commit differs from this run")
    tree = git(root, "rev-parse", expected_commit + "^{tree}").decode().strip()
    records = {}
    for row in git(root, "ls-tree", "-r", "-z", expected_commit).split(b"\0"):
        if not row:
            continue
        metadata, raw_name = row.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        name = raw_name.decode("utf-8")
        if (kind != "blob" or name.startswith("/") or ".." in Path(name).parts
                or name in records):
            raise ValueError("unsupported or duplicate tracked source entry")
        path = root / name
        if path.parent.resolve(strict=True) != path.parent:
            raise ValueError("tracked source has a symlinked parent")
        records[name] = file_observation(path, mode, blob)
    if not records or git(root, "rev-parse", "HEAD").decode().strip() != expected_commit:
        raise ValueError("checkout source set or commit changed")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked authoring source or index changed")
    return {"head": expected_commit, "tree": tree, "files": records}


def physical_source(args):
    if args.phase not in PHASES:
        raise ValueError("unknown native gate phase")
    if Path(__file__).resolve().read_bytes() != _EXECUTED_SOURCE:
        raise ValueError("executing phase reader source changed after import")
    codex = Path(args.codex_root).resolve(strict=True)
    if (codex / "hia/ci/native_phase_gate.py").read_bytes() != _EXECUTED_SOURCE:
        raise ValueError("phase reader does not belong to the captured checkout")
    rows = validate_workflow((codex / WORKFLOW).read_text(), codex)
    captured = {"schema": "codex.hia.native-phase-source.v1",
                "phase": args.phase, "codex": capture_repo(codex, args.expected_head),
                "compiler": capture_repo(args.hepta_root, PINNED_COMPILER)}
    if Path(__file__).resolve().read_bytes() != _EXECUTED_SOURCE:
        raise ValueError("executing phase reader changed during capture")
    return captured, rows


def compare_source(prior, captured):
    if canonical(prior) != canonical(captured):
        raise ValueError("phase physical sources or exact types changed")


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("before", "after"))
    parser.add_argument("--codex-root", type=Path, required=True)
    parser.add_argument("--hepta-root", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--terminal", type=Path)
    args = parser.parse_args()
    result = {"schema": "codex.hia.native-phase-terminal.v1", "phase": args.phase,
              "head": args.expected_head, "passed": False, "all_phases_passed": False,
              "serial_original_run_passed": False, "job_budget_minutes": 60}
    try:
        captured, rows = physical_source(args)
        write_new(args.report, captured)
        if args.operation == "before":
            print("Captured exact physical source", args.phase, args.expected_head)
            return
        if args.before is None or args.terminal is None:
            raise ValueError("terminal admission requires original source capture and terminal output")
        prior = decode(args.before.read_bytes())
        compare_source(prior, captured)
        required = verify_outcomes(decode(os.environ["HIA_PHASE_STEPS"]), args.phase, rows)
        result.update(passed=True, source_unchanged=True, completed_step_ids=required,
                      original_step_count=len(rows),
                      conservation_sha256=sha256(canonical(rows)).hexdigest())
        print("PASS phase=" + args.phase + " assigned_original_steps=" + str(len(required) - 1)
              + " source=" + args.expected_head + " budget_minutes=60")
    except BaseException as exc:
        result["failure"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        if args.operation == "after" and args.terminal is not None:
            write_new(args.terminal, result)


if __name__ == "__main__":
    main()
