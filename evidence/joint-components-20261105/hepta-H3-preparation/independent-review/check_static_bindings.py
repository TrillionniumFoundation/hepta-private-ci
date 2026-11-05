#!/usr/bin/env python3
"""Independent static H3 bindings; no Rust, native, formatter, or model execution."""
import ast
import hashlib
import json
from pathlib import Path
import re

import yaml

WORKSPACE = Path(__file__).resolve().parents[2]
SOURCE = WORKSPACE / "model_storage/h3-preparation"
OUTPUT = Path(__file__).resolve().parent
PATCH_SHA = "938124f6dffe9127463e5bf93b473d6f58e07567aa5a78ff90b07ee38b9f7fb8"
MANIFEST_SHA = "94e38205ffc44e2a4af1571fee1d70d379737e1d403af756f812fee61476d257"


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def evaluate(node, env):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [evaluate(item, env) for item in node.elts]
        return set(values) if isinstance(node, ast.Set) else values
    if isinstance(node, ast.Dict):
        return {evaluate(key, env): evaluate(value, env) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.BitOr)):
        left, right = evaluate(node.left, env), evaluate(node.right, env)
        return left + right if isinstance(node.op, ast.Add) else left | right
    if isinstance(node, ast.SetComp):
        require(len(node.generators) == 1, "one static set generator")
        generator = node.generators[0]
        require(isinstance(generator.target, ast.Name) and not generator.ifs and not generator.is_async,
                "static set generator only")
        return {evaluate(node.elt, dict(env, **{generator.target.id: value}))
                for value in evaluate(generator.iter, env)}
    raise ValueError("unexpected expected-name expression " + ast.dump(node))


def guard(step):
    lines = step["run"].splitlines()
    require(lines[0].endswith("<<'PY'") and lines[-1] == "PY", "known guard heredoc")
    tree = ast.parse("\n".join(lines[1:-1]))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets))
    names = evaluate(assignment.value, {"prefix": "authbus_dispatch::tests::"})
    tree.body.remove(assignment)
    return names, ast.dump(tree, include_attributes=False)


def main():
    patch = (SOURCE / "h3-repair-v1.patch").read_bytes()
    manifest_raw = (SOURCE / "h3-repair-v1-manifest.json").read_bytes()
    require(sha(patch) == PATCH_SHA and sha(manifest_raw) == MANIFEST_SHA, "frozen candidate changed")
    manifest = json.loads(manifest_raw)
    inventories = []
    for row in manifest["files"]:
        candidate = (SOURCE / "candidate" / row["path"]).read_bytes()
        require((len(candidate), sha(candidate), blob(candidate)) ==
                (row["new_bytes"], row["new_sha256"], row["new_git_blob"]), "candidate bytes " + row["path"])
        if row["base_git_blob"] is not None:
            base = (SOURCE / "base" / row["path"]).read_bytes()
            require((len(base), sha(base), blob(base)) ==
                    (row["base_bytes"], row["base_sha256"], row["base_git_blob"]), "base bytes " + row["path"])
        inventories.append(row)
    workflow = ".github/workflows/hepta-pq-policy-renewal.yml"
    old = yaml.safe_load((SOURCE / "base" / workflow).read_text())
    new = yaml.safe_load((SOURCE / "candidate" / workflow).read_text())
    require({k: v for k, v in old.items() if k != "jobs"} ==
            {k: v for k, v in new.items() if k != "jobs"}, "workflow triggers/permissions altered")
    old_job, new_job = old["jobs"]["policy-renewal"], new["jobs"]["policy-renewal"]
    require({k: v for k, v in old_job.items() if k != "steps"} ==
            {k: v for k, v in new_job.items() if k != "steps"}, "matrix/resource/job budget/environment altered")
    old_steps, new_steps = old_job["steps"], new_job["steps"]
    def step_key(step):
        if "name" in step:
            return step["name"]
        if "id" in step:
            return "id:" + step["id"]
        if "uses" in step:
            return "uses:" + step["uses"]
        return "anonymous:" + sha(json.dumps(step, sort_keys=True).encode())
    old_names = [step_key(step) for step in old_steps]
    new_names = [step_key(step) for step in new_steps]
    require(len(set(old_names)) == len(old_names) and len(set(new_names)) == len(new_names), "unique step names")
    require([name for name in new_names if name in old_names] == old_names, "old step relative order changed")
    added = [step for step in new_steps if step_key(step) not in old_names]
    require(len(added) == 1 and added[0]["name"] ==
            "Run explicit runtime input and qualification-before-runtime controls", "one explicit new step")
    by_name = {step_key(step): step for step in new_steps}
    changed = [step_key(step) for step in old_steps if step != by_name[step_key(step)]]
    guard_name = "Require every selected test by name with no selected skip"
    product_names = [name for name in changed if name != guard_name]
    require(len(product_names) == 1 and "process" in product_names[0].lower(), "only product and exact-name guard changed")
    product_name = product_names[0]
    prior_product = next(step for step in old_steps if step_key(step) == product_name)
    product = by_name[product_name]
    require({k: v for k, v in prior_product.items() if k != "run"} ==
            {k: v for k, v in product.items() if k != "run"}, "product env/condition changed")
    expected_product = prior_product["run"].replace("--minimum-tests 1", "--minimum-tests 2").replace(
        "test(=pq_effect_survives_owned_agentd_kill_after_provider_fsync_without_resend)'",
        "test(=pq_effect_survives_owned_agentd_kill_after_provider_fsync_without_resend) | test(=binary::held_daemon_image_reuse_refuses_wrong_changed_or_missing_files)'")
    require(product["run"] == expected_product, "product command differs outside required selector/minimum")
    before_names, before_ast = guard(next(step for step in old_steps if step_key(step) == guard_name))
    after_names, after_ast = guard(by_name[guard_name])
    require(before_ast == after_ast and all(names <= after_names.get(key, set()) for key, names in before_names.items()),
            "prior exact-name guard algorithm or cases altered")
    additions = {key: sorted(names - before_names.get(key, set())) for key, names in after_names.items()
                 if names - before_names.get(key, set())}
    require(sum(map(len, before_names.values())) == 71 and sum(map(len, after_names.values())) == 74,
            "selected exact totals")
    require(additions == {
        "effect-pq-product": ["binary::held_daemon_image_reuse_refuses_wrong_changed_or_missing_files"],
        "neural-runtime-input": ["native_comparison_input_requires_v2_and_independently_pinned_snapshot",
                                 "ordinary_native_composition_rejects_untrusted_qualification_before_inference_owners"]},
        "new exact names")
    new_step = added[0]
    require(new_step["if"] == product["if"] and new_step["env"] == {"CARGO_NET_OFFLINE": "true"}, "new control env")
    require("--minimum-tests 2 --timeout-seconds 600 -- just test --locked -p codex-hepta-agentd" in new_step["run"]
            and "--no-capture --retries 0 --test-threads=1" in new_step["run"], "new original-profile control invocation")
    require(set(re.findall(r"test\(=([^)]*)\)", new_step["run"])) == after_names["neural-runtime-input"],
            "new selectors exactly match guard")
    source_map = {
        "binary::held_daemon_image_reuse_refuses_wrong_changed_or_missing_files": "tests/support/automation_effect_binary.rs",
        "native_comparison_input_requires_v2_and_independently_pinned_snapshot": "tests/neural_comparison_native.rs",
        "ordinary_native_composition_rejects_untrusted_qualification_before_inference_owners": "tests/neural_cognitive_bootstrap.rs"}
    for name, relative in source_map.items():
        text = (SOURCE / "candidate/codex-rs/hepta-agentd" / relative).read_text()
        require(re.search(r"#\[test\]\s*(?:async\s+)?fn\s+" + re.escape(name.split("::")[-1]) + r"\s*\(", text)
                or re.search(r"#\[tokio::test[^\n]*\]\s*async fn\s+" + re.escape(name.split("::")[-1]) + r"\s*\(", text),
                "new selected name must be a real nonignored test: " + name)
    owner = (SOURCE / "candidate/codex-rs/hepta-agentd/tests/support/neural_native_owner.rs").read_text()
    paths = re.findall(r'"([^"]+)"', owner.split("for relative in [", 1)[1].split("] {", 1)[0])
    profile = (SOURCE / "reference/codex-rs/hepta-infer-worker-host/src/smollm_neural_profile.rs").read_text()
    required = re.findall(r'"([^"]+)"', profile.split("let required = [", 1)[1].split("];", 1)[0])
    require(len(paths) == 13 and sorted(Path(path).name for path in paths) == required, "exact profile source pins")
    base_product = (SOURCE / "base/codex-rs/hepta-agentd/tests/automation_effect_pq_product.rs").read_text()
    new_product = (SOURCE / "candidate/codex-rs/hepta-agentd/tests/automation_effect_pq_product.rs").read_text()
    require(base_product[base_product.index('checkpoint(&evidence, "second-process.json"'):]
            == new_product[new_product.index('checkpoint(&evidence, "second-process.json"'):],
            "all pending recovery assertions after second capture must remain exact")
    value = dict(schema="h3-independent-static-bindings-v1", status="PASS_STATIC_ONLY", base_commit=manifest["base_commit"],
                 patch_sha256=PATCH_SHA, manifest_sha256=MANIFEST_SHA, files=inventories,
                 workflow=dict(original_selected=71, new_selected=74, additions=additions,
                               original_step_relative_order_unchanged=True, changed_original_steps=changed,
                               matrix_resources_environment_unchanged=True, job_timeout_seconds=5400,
                               original_product_timeout_seconds=1800, added_runtime_control_timeout_seconds=600,
                               exact_guard_algorithm_ast_unchanged=True, original_commands_other_than_product_unchanged=True),
                 complete_profile_source_pins=paths, later_process_assertions_byte_identical=True,
                 desktop_actions=0, cargo_executions=0, formatter_executions=0, native_tests_run=0,
                 qualification_credit=False)
    (OUTPUT / "static-bindings.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(dict(status=value["status"], files=len(inventories), old_cases=71, new_cases=74,
                          source_pins=len(paths), native_tests_run=0)))


if __name__ == "__main__":
    main()
