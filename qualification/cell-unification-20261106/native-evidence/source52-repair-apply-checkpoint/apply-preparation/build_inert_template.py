"""Build an inert source52 apply-only derivative; never imports/executes it."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

D = Path(__file__).resolve().parent
t = (D / "references/native-source51-apply-template.py").read_text()
assert hashlib.sha256(t.encode()).hexdigest() == "743a9f7ff2c4992b91aab39aa22298b6599c169c15089360e7dbcfbff4cf0f8e"
# Rename source roles simultaneously; historical lock provenance is corrected
# explicitly below because source50 remains the original successful lock run.
t = t.replace("SOURCE51", "__TARGET_UPPER__").replace("SOURCE50", "SOURCE51").replace("__TARGET_UPPER__", "SOURCE52")
t = t.replace("source51", "__target_lower__").replace("source50", "source51").replace("__target_lower__", "source52")
t = t.replace("source50 -> source51", "source51 -> source52")
t = t.replace("r26-source", "r28-source").replace("r24", "r26").replace("R24", "R26")
replacements = {
    '"1fdd647b0ecb235530e8b88bbea45b3d3762906f"': '"e28b0f385ee882f842911044958b2810f62f6379"',
    '"ea48acf562499192a25e05ae28926a32632dee62"': '"763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"',
    '"bytes": 53832': '"bytes": 55418',
    '"ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0"': '"74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a"',
    '"2b6988709adfd80084a846688453ceafd3f4accf"': '"09ad6990ac2eeec1eb7d21689eef7733a531f75b"',
    '"644e58b095e57c8b037cb282aa1da04f50501cb04b7c3f472d18e48272cda14f"': '"c7f2154976a0df45dc721e6fefcfc5089f98c048c3755549464a257d11a1033a"',
    '"bec33f505f774d6ed6056df873bb2dbf4b751c43"': '"cd46317153095ebe99011d47a57ebeefb5136386"',
    '"1a1b17f112c-fc05-792a"': '"1a1b1b739ee-fc05-7a70"',
    '    "codex-rs/exec-server/tests/common/fake_bwrap.rs",\n    "codex-rs/network-proxy/src/http_proxy.rs",':
        '    "codex-rs/network-proxy/src/runtime.rs",',
    '"two reviewed candidate bindings required"': '"one reviewed existing repository leaf binding required"',
    '"patch does not cover exactly two reviewed Rust paths"': '"patch does not cover exactly the single reviewed existing Rust leaf"',
    '"source52 count unbound"': '"source52 count unbound"',
}
for old, new in replacements.items():
    assert old in t, old
    t = t.replace(old, new)
t = t.replace('require(type(EXPECTED_CHANGED_COUNT) is int and EXPECTED_CHANGED_COUNT > 0, "source52 count unbound")',
              'require(type(EXPECTED_CHANGED_COUNT) is int and EXPECTED_CHANGED_COUNT == SOURCE51_COUNT + 1, "source52 count must be the prior194 plus exactly one existing repository leaf")')
t = t.replace('for expected in (SOURCE51_MANIFEST_PIN, R26_TERMINAL_PIN, SOURCE52_MANIFEST_PIN, DELTA_MANIFEST_PIN):',
              'for expected in (SOURCE51_MANIFEST_PIN, R26_TERMINAL_PIN, SOURCE52_MANIFEST_PIN, DELTA_MANIFEST_PIN, EXISTING_BASELINE_LEAF_PIN):')
t = t.replace('    for name in (INPUT_NAME, SOURCE51_MANIFEST_NAME, SOURCE52_MANIFEST_OUTPUT_NAME, R26_TERMINAL_NAME):',
              '    for expected in R26_FAILURE_PINS.values():\n        validate_pin(expected)\n    require(set(R26_FAILURE_PINS) == {\n        R26_TERMINAL_NAME, R26_PREFIX + "-tests-raw-process-result.json",\n        R26_PREFIX + "-tests-receipt.json", R26_PREFIX + "-tests-source-post-verification.json",\n    }, "four actual failed r26 originals are required")\n    for name in (INPUT_NAME, SOURCE51_MANIFEST_NAME, SOURCE52_MANIFEST_OUTPUT_NAME, *R26_FAILURE_PINS):')
t = t.replace('report["actual_tree"] == expected_tree\n            and len(files)',
              'report["actual_tree"] == expected_tree\n            and report["native_head"] == FRAMEWORK_PARENT\n            and len(files)')
t = t.replace('    except Exception as error:\n        report["error"] = repr(error)\n    return report\n\n\ndef replay_patch',
              '        if expected_tree == SOURCE51_TREE:\n            report["existing_repo_leaf_outside_prior_changed_manifest"] = existing_baseline_leaf_guard()\n    except Exception as error:\n        report["error"] = repr(error)\n        report["pass"] = False\n    return report\n\n\ndef replay_patch')
constants = '''
EXISTING_BASELINE_LEAF_PIN = {
    "bytes": 75473,
    "sha256": "3214446d85796e5d1c4a308ba53aab3bf7098fc18cd38cfc6f97a1cbb14d2e4f",
    "git_blob": "1a449a44381fafa4a5d6a5d0e08753f425f339fc",
}
R26_PREFIX = "native-source51-project-r26"
R26_FAILURE_PINS = {
    R26_TERMINAL_NAME: R26_TERMINAL_PIN,
    R26_PREFIX + "-tests-raw-process-result.json": {
        "bytes": 635, "sha256": "ac2729d6bd5424bc5744baa7625aa64daccd429b90f7e172e2f17c764fb112c2",
        "git_blob": "cd43196eab2604fb62ff32895786bc672ae2770e",
    },
    R26_PREFIX + "-tests-receipt.json": {
        "bytes": 2312, "sha256": "dd6e5fa8629a57f90774282d70a1a81fe641faaec7ca0e0a89590522bfdf7cf3",
        "git_blob": "313af0ac2a088dd2b35c8a6973c8239297814002",
    },
    R26_PREFIX + "-tests-source-post-verification.json": {
        "bytes": 633, "sha256": "f94acb64e0b875228625feac0a9485efbd3bf68d2058447130abcb1e4c15ea4b",
        "git_blob": "7bee7921a263922dde356745c807f338ef1f6231",
    },
}
'''
t = t.replace('\n\ndef require(value, message):', '\n' + constants + '\n\ndef require(value, message):', 1)
new_load = (D / "new_load_inputs.py.txt").read_text().strip() + "\n\n\n"
a = t.index("def load_inputs():")
b = t.index("def run_git_phase(", a)
t = t[:a] + new_load + t[b:]
t = t.replace('"inherited_lock_boundary": "Source50 lock success is retained only for identical dependency inputs and unchanged raw locks; this is not a new lock invocation or Rust qualification.",',
              '"inherited_lock_boundary": "The original source50 lock success is retained only for identical dependency inputs and unchanged raw locks through source51 and source52; this is not a new lock invocation or Rust qualification.",')
t = t.replace('            "actual_changed_file_count": post["actual_changed_file_count"],',
              '            "prior_changed_file_count": SOURCE51_COUNT,\n            "before_existing_repo_leaf_not_in_prior_changed_manifest": True,\n            "source51_original_changed_manifest_rows_unchanged": True,\n            "actual_changed_file_count": post["actual_changed_file_count"],')
t = t.replace('        post["changed_from_source51_paths"] = delta_paths',
              '        post["changed_from_source51_paths"] = delta_paths\n        post["prior_changed_file_count"] = SOURCE51_COUNT\n        post["before_existing_repo_leaf_not_in_prior_changed_manifest"] = True\n        post["source51_original_changed_manifest_rows_unchanged"] = True')
t = t.replace('        prestage["index_tree"] = git("write-tree").decode().strip()',
              '        prestage["index_tree"] = git("write-tree").decode().strip()\n        prestage["native_head"] = git("rev-parse", "HEAD").decode().strip()')
t = t.replace('            prestage["index_tree"] == SOURCE51_TREE and set(prestage["unstaged_paths"]) == set(ALLOWED_PATHS)',
              '            prestage["index_tree"] == SOURCE51_TREE and prestage["native_head"] == FRAMEWORK_PARENT\n            and set(prestage["unstaged_paths"]) == set(ALLOWED_PATHS)')
ast.parse(t)
out = D / "native-source52-apply-template.py"
out.write_text(t)
old = (D / "references/native-source51-apply-template.py").read_text()
patch = "".join(difflib.unified_diff(old.splitlines(keepends=True), t.splitlines(keepends=True),
                                  fromfile="reviewed/source51-apply-template.py",
                                  tofile="inert/source52-apply-template.py"))
(D / "source51-to-source52-template.patch").write_text(patch)
print(json.dumps({"bytes":len(t.encode()), "sha256":hashlib.sha256(t.encode()).hexdigest(),
                  "ast_parse_pass":True, "frozen":False, "native_executed":False}))
