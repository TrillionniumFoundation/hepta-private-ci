from pathlib import Path
import ast
import difflib
import hashlib
import json


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
CONTROL = ".github/scripts/run_b11_acl_identity_counterfactual.py"
HELPER = ".github/scripts/run_b11_read_acl_readiness.py"
WORKFLOW = ".github/workflows/hepta-windows-token-mechanism-probe.yml"
ORIGINALS = {
    CONTROL: ("architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v3/candidate/" + CONTROL,
              "3680db31233e47ba7fad99f31a7019c4536288bb"),
    HELPER: ("research-audit/b11-read-readiness-20261105/execution-candidate-v2/candidate/" + HELPER,
             "6010ce9cc6da2eca95aac9ba453581f68770bbe6"),
    WORKFLOW: ("research-audit/b11-read-readiness-20261105/execution-candidate-v2/candidate/" + WORKFLOW,
               "89d2eaf4bb9900f7476d49476e2657effa68327a"),
}


def identity(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


before = {}
for path, (original, expected) in ORIGINALS.items():
    body = (WORKSPACE / original).read_bytes()
    assert identity(body)["git_blob"] == expected
    target = ROOT / "source" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    before[path] = body.decode()

validator = '''def git_bash_record(path):
    require(os.name == "nt", "the explicit Git Bash executable requires native Windows")
    require(path.is_absolute() and path.name.casefold() == "bash.exe",
            "Git Bash must be an explicit absolute Windows bash.exe path")
    require(path.is_file(), "the workflow's explicit Git Bash executable does not exist")
    return {"path": str(path), **digest(path.read_bytes())}


'''
control = replace_once(before[CONTROL], "def save(directory, name, value):", validator + "def save(directory, name, value):")
control = replace_once(control, '    parser.add_argument("--evidence", type=Path, required=True)\n',
                       '    parser.add_argument("--evidence", type=Path, required=True)\n'
                       '    parser.add_argument("--bash-executable", type=Path, required=True)\n')
control = replace_once(control, '    try:\n        entry = source_guard(root, head, POSITIVE, False)\n',
                       '    try:\n        bash = git_bash_record(args.bash_executable)\n'
                       '        save(evidence, "git-bash-executable.json", bash)\n'
                       '        entry = source_guard(root, head, POSITIVE, False)\n')
control = replace_once(control, '            positive_argv = ["bash",', '            positive_argv = [bash["path"],')
control = replace_once(control, '        argv = ["bash",', '        argv = [bash["path"],')
control_blob = identity(control.encode())["git_blob"]

helper = replace_once(before[HELPER], 'CONTROL_BLOB = "3680db31233e47ba7fad99f31a7019c4536288bb"',
                      f'CONTROL_BLOB = "{control_blob}"')
helper = replace_once(helper, '    parser.add_argument("--evidence", type=Path, required=True)\n',
                      '    parser.add_argument("--evidence", type=Path, required=True)\n'
                      '    parser.add_argument("--bash-executable", type=Path, required=True)\n')
helper = replace_once(helper, '    try:\n        previous = original / "acl-identity-counterfactual"\n',
                      '    try:\n        bash = control.git_bash_record(args.bash_executable)\n'
                      '        control.save(evidence, "git-bash-executable.json", bash)\n'
                      '        previous = original / "acl-identity-counterfactual"\n')
helper = replace_once(helper, '        argv = ["bash",', '        argv = [bash["path"],')

workflow = before[WORKFLOW]
shell_capture = '''          bash_executable="$BASH"
          if [[ "$bash_executable" != *.exe ]]; then
            bash_executable="${bash_executable}.exe"
          fi
          test -f "$bash_executable"
'''
for script in ("run_b11_acl_identity_counterfactual.py", "run_b11_read_acl_readiness.py"):
    old = f'          python3 .github/scripts/{script} \\\n            --evidence "$(cygpath -w "$evidence")"'
    new = shell_capture + old + ' \\\n            --bash-executable "$(cygpath -aw "$bash_executable")"'
    workflow = replace_once(workflow, old, new)
after = {CONTROL: control, HELPER: helper, WORKFLOW: workflow}

patches = []
rows = []
for path, text in after.items():
    target = ROOT / "candidate" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    pre, post = identity(before[path].encode()), identity(text.encode())
    patches.append(f'diff --git a/{path} b/{path}\nindex {pre["git_blob"]}..{post["git_blob"]} 100644\n'
                   + ''.join(difflib.unified_diff(before[path].splitlines(keepends=True), text.splitlines(keepends=True),
                                                 fromfile="a/" + path, tofile="b/" + path)))
    rows.append({"path": path, "preimage": pre, "postimage": post,
                 "preimage_file": str(ROOT / "source" / path), "postimage_file": str(target)})
(ROOT / "full.patch").write_text("".join(patches))
(ROOT / "source-map.json").write_text(json.dumps(rows, indent=2) + "\n")

# Compare complete unchanged function bodies, complete runtime predicates, and
# full argv tails without invoking either CLI or any process under test.
preserved_functions = {}
for path in (CONTROL, HELPER):
    pre_ast, post_ast = ast.parse(before[path]), ast.parse(after[path])
    pre_defs = {node.name: ast.get_source_segment(before[path], node) for node in pre_ast.body if isinstance(node, ast.FunctionDef)}
    post_defs = {node.name: ast.get_source_segment(after[path], node) for node in post_ast.body if isinstance(node, ast.FunctionDef)}
    for name, body in pre_defs.items():
        if name != "main":
            assert post_defs[name] == body, name
    preserved_functions[path] = sorted(name for name in pre_defs if name != "main")
    old_lists = [node.value for node in ast.walk(pre_ast) if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.List) and node.value.elts
                 and isinstance(node.value.elts[0], ast.Constant) and node.value.elts[0].value == "bash"]
    new_lists = [node.value for node in ast.walk(post_ast) if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.List) and node.value.elts
                 and ast.dump(node.value.elts[0]) == ast.dump(ast.parse('bash["path"]', mode="eval").body)]
    assert len(old_lists) == len(new_lists) == (2 if path == CONTROL else 1)
    for old, new in zip(old_lists, new_lists):
        assert [ast.dump(node) for node in old.elts[1:]] == [ast.dump(node) for node in new.elts[1:]]
    compile(after[path], path, "exec")

tail = '    except Exception as exc:\n        error = repr(exc)\n    finally:\n'
assert before[CONTROL].split(tail)[1] == after[CONTROL].split(tail)[1]
assert before[HELPER].split(tail)[1] == after[HELPER].split(tail)[1]
start = '      - name: Run the original outer Windows sandbox unit target\n'
end = '      - name: Check the ACL identity counterfactual and restore its source\n'
assert before[WORKFLOW].split(start)[1].split(end)[0] == after[WORKFLOW].split(start)[1].split(end)[0]
assert before[WORKFLOW].split('      # The unchanged wrapper')[1] == after[WORKFLOW].split('      # The unchanged wrapper')[1]
assert 'CONTROL_SCRIPT: CONTROL_BLOB' in helper
assert f'CONTROL_BLOB = "{control_blob}"' in helper
assert before[HELPER].split('PINS = {')[1].split('REQUIRED_CASES')[0] == helper.split('PINS = {')[1].split('REQUIRED_CASES')[0]
assert before[CONTROL].split('def require(')[0] == control.split('def require(')[0]
(ROOT / "static-verification.json").write_text(json.dumps({
    "role": "SOURCE_ONLY_NOT_WINDOWS_EXECUTION", "source_maps": rows,
    "complete_existing_non_main_functions_unchanged": preserved_functions,
    "all_three_original_argv_tails_AST_equal": True,
    "counterfactual_and_helper_finally_tails_byte_equal": True,
    "original_whole_workflow_step_and_upload_cleanup_tail_byte_equal": True,
    "all_original_case_names_flags_scope_budgets_and_oracles_preserved": True,
    "helper_CONTROL_BLOB_equals_actual_counterfactual_postimage": control_blob,
    "original_ten_non_control_pins_unchanged": True,
    "python_compilation_only_no_module_main_executed": True,
    "native_or_ref_actions": False,
}, indent=2) + "\n")
print(json.dumps({"source_map": rows, "patch": identity((ROOT / "full.patch").read_bytes())}, indent=2))
