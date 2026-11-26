"""Project only proven unrelated Cargo metadata out of V8 canary inputs.

Unknown module, lockfile and toolchain inputs stay in the comparison. Parse
errors abort metadata instead of silently suppressing the build matrix.
"""

import ast
import json
import re
import tomllib


def v8_dependency_closure(cargo_lock: bytes) -> list[dict]:
    packages = tomllib.loads(cargo_lock.decode())["package"]
    by_name: dict[str, list[dict]] = {}
    for package in packages:
        by_name.setdefault(package["name"], []).append(package)
    roots = by_name.get("v8", [])
    if len(roots) != 1:
        raise ValueError("expected exactly one resolved v8 package")
    pending = roots[:]
    seen = {}
    while pending:
        package = pending.pop()
        identity = (package["name"], package["version"], package.get("source", ""))
        if identity in seen:
            continue
        seen[identity] = package
        for dependency in package.get("dependencies", []):
            parts = dependency.split(" ", 2)
            candidates = by_name.get(parts[0], [])
            if len(parts) >= 2:
                candidates = [p for p in candidates if p["version"] == parts[1]]
            if len(parts) == 3:
                candidates = [
                    p for p in candidates if p.get("source") == parts[2].strip("()")
                ]
            if len(candidates) != 1:
                raise ValueError(f"unresolved or ambiguous V8 dependency: {dependency}")
            pending.extend(candidates)
    # Keep complete package records, including checksum, source and dependency
    # edges. Same-version source substitutions must not skip coverage.
    return [seen[key] for key in sorted(seen)]


def cargo_manifest_inputs(contents: bytes, closure: list[dict]) -> dict:
    manifest = tomllib.loads(contents.decode())
    workspace = manifest["workspace"]
    names = {package["name"] for package in closure}
    dependencies = {
        name: value
        for name, value in workspace.get("dependencies", {}).items()
        if name in names or isinstance(value, dict) and value.get("package") in names
    }
    workspace["dependencies"] = dependencies
    workspace["members"] = [
        name
        for name in workspace.get("members", [])
        if "v8" in name or any(symbol in name for symbol in "*?[")
    ]
    # Preserve all other known and future workspace/compiler configuration,
    # including edition, rust-version, profiles, patches and replacements.
    return manifest


def bazel_module_inputs(contents: bytes, closure: list[dict]) -> str:
    module = ast.parse(contents.decode())
    names = {package["name"] for package in closure}
    retained = []
    for statement in module.body:
        call = statement.value if isinstance(statement, ast.Expr) else None
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "crate"
            and call.func.attr == "annotation"
        ):
            targets = [field.value for field in call.keywords if field.arg == "crate"]
            if (
                len(targets) == 1
                and isinstance(targets[0], ast.Constant)
                and isinstance(targets[0].value, str)
                and re.fullmatch(r"[A-Za-z0-9_-]+", targets[0].value)
                and targets[0].value not in names
            ):
                continue
        retained.append(statement)
    module.body = retained
    return ast.dump(module, include_attributes=False)


def bazel_lock_inputs(contents: bytes, closure: list[dict]) -> dict:
    lock = json.loads(contents)
    identities = {f"{p['name']}_{p['version']}" for p in closure}
    for extension, facts in lock.get("facts", {}).items():
        if extension.endswith("//rs:extensions.bzl%crate"):
            if not isinstance(facts, dict):
                raise ValueError("unknown Cargo facts lockfile schema")
            lock["facts"][extension] = {
                identity: value
                for identity, value in facts.items()
                if identity in identities
                or not re.fullmatch(r"[A-Za-z0-9_-]+_\d+\.\d+\.\d+[^\s]*", identity)
            }
    # All registry hashes, other extension facts and platform/toolchain data
    # remain significant. This is not a second Bazel dependency resolver.
    return lock


SCOPED_INPUTS = {
    "codex-rs/Cargo.toml": cargo_manifest_inputs,
    "MODULE.bazel": bazel_module_inputs,
    "MODULE.bazel.lock": bazel_lock_inputs,
}
