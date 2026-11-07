"""Build an inert artifact-only R30 exporter from reviewed exact helpers.

This local generator parses source text; it never imports or executes a native
runner/exporter and never contacts the native environment.
"""
import ast
import difflib
import hashlib
import json
from pathlib import Path

D = Path(__file__).resolve().parent
ROOT = D.parent
old_path = ROOT / "r28-export-preparation/export-r28-closed-template-v2.py"
producer_path = ROOT / "source53-native-gates-preparation/native-run-r30-template-v2.py"
old = old_path.read_text()
producer = producer_path.read_text()
assert hashlib.sha256(old.encode()).hexdigest() == "4568d25b1d122e209ce59d9f1a4015e65ca77246f23b2ece4f86b07a6398d4d8"
assert hashlib.sha256(producer.encode()).hexdigest() == "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b"


def functions(text):
    lines = text.splitlines(keepends=True)
    return {n.name: "".join(lines[n.lineno - 1:n.end_lineno])
            for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


of = functions(old)
pf = functions(producer)
shared = ["require", "sha", "data_pin", "safe_relative", "check_pin",
          "stable_read", "git", "natural_terminal"]
header = '''#!/usr/bin/env python3
"""Inert R30 closed app-server evidence exporter; no gate execution.

Only three future closure maps may be bound after the original job is terminal.
The archive preserves actual originals, including unsuccessful or incomplete
phases, and never fabricates the 19-file successful closure. Archive success is
not engineering qualification or evidence that diagnostic logging repaired a
behavior. The only subprocesses are explicitly allowlisted Git reads.
"""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile

FROZEN = False
TERMINAL_PIN = None
CLOSED_ORIGINAL_PINS = None
CONTROLLER_ORIGINAL_PINS = None

T = Path('/home/alex/work/hepta-cell-unified-20261106-a')
S = T / 'source'
E = T / 'evidence'
PREFIX = 'native-source53-project-r30'
COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TREE = '440d4a8e09af4009e4d9ea067388826308da8803'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
JOB_ID = '1a1b25b399f-fc05-7daa'
JOB_KEY = 'cell-source53-project-r30-20261106-v1'
SOURCE_NAME = 'native-candidate-r30-source.json'
SOURCE_PIN = {'bytes': 56747, 'sha256': '9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda', 'git_blob': 'eea9da2308a920486e1bbfd613745d390cde61de'}
RUNNER_NAME = 'native-run-r30.py'
RUNNER_PIN = {'bytes': 61214, 'sha256': 'b72407252efdaf81d8e3bc5280c3fa7ad9afb36fa398869e8023daaa392ff3c8', 'git_blob': '3c41e24997e2113f0028a58b70f8e646b76ac47e'}
INPUT_PIN = {'bytes': 23866, 'sha256': 'a07c097b1873b65bf86e8b445ceddebc4f994ca0c39bd7900f1a184a0259c81a', 'git_blob': '3e0f823bcd8986fb6b97a5b032b8042405fa221e'}
BASELINE_NAME = 'source53-app-server-r29-baseline.json'
BASELINE_SHA = '92e7ef41b0c2b08b81bb3ad9542f20ec820d86185f80369b4478cb5bd9c20cf1'
BASELINE_COUNT = 1345
PACKAGES = ['codex-app-server']
LOCKS = {'codex-rs/Cargo.lock': '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c', 'MODULE.bazel.lock': 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'}
R26_PRE_PIN = {'bytes': 7651, 'sha256': 'd1b604225a9162ffd3bfc1b4a372dac755f79ce63fe48e8614920d95682ee118', 'git_blob': '9e919e732f041571afe7b9e1c273d6a45b5ca682'}
R28_PRE_PIN = {'bytes': 9513, 'sha256': '741cd5aa598adecb7d2a2c3a4f976e672aac0b6b84697785bfffbdc6a5ed618e'}
NEW_LEAVES = ('codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs', 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs')
COMMANDS = {'strict': ['just', 'clippy', '--locked', '-p', 'codex-app-server', '--', '-D', 'warnings'], 'tests': ['just', 'test', '--locked', '--retries', '0', '-p', 'codex-app-server']}
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
CONTROLLER_PREFIX = 'r30-controller-closed-'
OUT = E / 'checkpoint-r30-closed.tar.gz'
DERIVED = E / 'r30-closed-export'
RESULT = E / 'checkpoint-r30-export.json'
SUCCESS_SUFFIXES = {'-environment.json', '-preconditions.json', '-source-pre-verification.json', '-source-final-verification.json', '-complete.json', '-tests-test-results.json', '-tests-result-review.json'} | {f'-{phase}{suffix}' for phase in COMMANDS for suffix in ('-source-pre-verification.json', '.log', '-resources.txt', '-raw-process-result.json', '-source-post-verification.json', '-receipt.json')}
ALLOWED_SUFFIXES = SUCCESS_SUFFIXES | {'-incomplete.json', '-orchestration-error.json'}
'''
# The inherited guard only changes the exact source identity/count and requires
# the already-frozen diagnostic classification; all byte/index/lock reads remain.
sg = of["source_guard"].replace("source52", "source53").replace("195", "197")
sg = sg.replace("    rows=source['changed_files']", "    require(source['diagnostic_only'] is True and source['behavior_repair_claimed'] is False,'source53 diagnostic classification changed')\n    rows=source['changed_files']")
rg = of["recorded_guard"].replace("195", "197")
text = header + "\n\n" + "\n\n\n".join(of[n] for n in shared)
text += "\n\n\n" + sg + "\n\n\n" + rg
text += "\n\n\n" + pf["clean_lines"] + "\n\n\n" + pf["review_tests"]
text += "\n\n\n" + (D / "export-body.py.txt").read_text()
ast.parse(text)
new = D / "export-r30-closed-template.py"
with new.open("x") as f:
    f.write(text)
nf = functions(text)
assert all(nf[n] == of[n] for n in shared)
assert nf["clean_lines"] == pf["clean_lines"] and nf["review_tests"] == pf["review_tests"]
assignments = {n.targets[0].id: n.value for n in ast.parse(text).body
               if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
assert ast.literal_eval(assignments["FROZEN"]) is False
assert all(ast.literal_eval(assignments[n]) is None for n in ("TERMINAL_PIN", "CLOSED_ORIGINAL_PINS", "CONTROLLER_ORIGINAL_PINS"))
assert len(SUCCESS := {'-environment.json', '-preconditions.json', '-source-pre-verification.json', '-source-final-verification.json', '-complete.json', '-tests-test-results.json', '-tests-result-review.json'} | {f'-{phase}{s}' for phase in ('strict', 'tests') for s in ('-source-pre-verification.json', '.log', '-resources.txt', '-raw-process-result.json', '-source-post-verification.json', '-receipt.json')}) == 19
report = {"schema": "hepta.r30-export-inert-static-build.v1", "template": pin(text.encode()),
          "reference_exporter": {"path": str(old_path.relative_to(ROOT)), **pin(old.encode())},
          "producer": {"path": str(producer_path.relative_to(ROOT)), **pin(producer.encode())},
          "shared_export_helpers_exact": shared, "producer_parsers_exact": ["clean_lines", "review_tests"],
          "ast_parse": "PASS", "inert": True, "unknown_maps": 3,
          "success_original_count": 19, "failure_uses_actual_existing_set": True,
          "runner_imported_or_executed": False, "native_access": False}
with (D / "AST-READBACK.json").open("x") as f:
    json.dump(report, f, indent=2);f.write("\n")
with (D / "r28-v2-to-r30.patch").open("x") as f:
    f.writelines(difflib.unified_diff(old.splitlines(True), text.splitlines(True), fromfile=str(old_path.relative_to(ROOT)), tofile=str(new.relative_to(ROOT))))
print(json.dumps(report))
