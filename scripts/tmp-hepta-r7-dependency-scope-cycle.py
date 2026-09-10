#!/usr/bin/env python3
"""Make r7 dependency inference scope-aware, lexically bounded, and cycle-safe."""

from pathlib import Path

PATH = Path("scripts/hepta-global-finalizer-r7.py")
text = PATH.read_text(encoding="utf-8")
start_marker = "def dependency_names(section: Any, context: str) -> set[str]:\n"
end_marker = "\ndef canonical_hepta_packages(metadata: dict[str, Any]) -> list[str]:\n"

if "def imported_workspace_crates_by_kind(" in text:
    required = (
        "def rust_code_only(",
        "def workspace_dependency_graph(",
        "def dependency_cycle_path(",
        '"skippedCycles"',
        '"dev-dependencies"',
        '"build-dependencies"',
    )
    missing = [fragment for fragment in required if fragment not in text]
    if missing:
        raise SystemExit(f"partial scoped dependency patch: {missing!r}")
    raise SystemExit(0)

if text.count(start_marker) != 1 or text.count(end_marker) != 1:
    raise SystemExit("r7 dependency repair block markers are not unique")
start = text.index(start_marker)
end = text.index(end_marker, start)

new_block = r'''def dependency_names(section: Any, context: str) -> set[str]:
    if section is None:
        return set()
    if not isinstance(section, dict):
        raise RuntimeError(f"{context} must be a TOML table")
    names: set[str] = set()
    for declared_name, declaration in section.items():
        names.add(declared_name)
        if isinstance(declaration, dict):
            package_name = declaration.get("package")
            if package_name is not None:
                if not isinstance(package_name, str) or not package_name:
                    raise RuntimeError(
                        f"{context}.{declared_name}.package must be a non-empty string"
                    )
                names.add(package_name)
    return names


DEPENDENCY_KINDS = (
    "dependencies",
    "dev-dependencies",
    "build-dependencies",
)


def dependency_declarations(text: str) -> dict[str, set[str]]:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(f"cannot inspect invalid Cargo manifest: {error}") from error

    declared = {
        kind: dependency_names(document.get(kind), kind) for kind in DEPENDENCY_KINDS
    }
    targets = document.get("target")
    if targets is None:
        return declared
    if not isinstance(targets, dict):
        raise RuntimeError("target must be a TOML table")
    for target_name, target in targets.items():
        if not isinstance(target, dict):
            raise RuntimeError(f"target.{target_name} must be a TOML table")
        for kind in DEPENDENCY_KINDS:
            declared[kind].update(
                dependency_names(target.get(kind), f"target.{target_name}.{kind}")
            )
    return declared


def dependency_sections(text: str) -> set[str]:
    declared = dependency_declarations(text)
    return set().union(*(declared[kind] for kind in DEPENDENCY_KINDS))


def satisfying_dependency_kinds(kind: str) -> tuple[str, ...]:
    if kind == "dependencies":
        return ("dependencies",)
    if kind == "dev-dependencies":
        return ("dependencies", "dev-dependencies")
    if kind == "build-dependencies":
        return ("build-dependencies",)
    raise RuntimeError(f"unsupported dependency kind: {kind}")


def dependency_is_declared(
    declarations: dict[str, set[str]], dependency: str, kind: str
) -> bool:
    return any(
        dependency in declarations[declared_kind]
        for declared_kind in satisfying_dependency_kinds(kind)
    )


def add_dependency(
    manifest: Path,
    dependency: str,
    dependency_path: Path,
    kind: str = "dependencies",
) -> bool:
    if kind not in DEPENDENCY_KINDS:
        raise RuntimeError(f"unsupported dependency kind: {kind}")
    text = manifest.read_text(encoding="utf-8")
    declarations = dependency_declarations(text)
    if dependency_is_declared(declarations, dependency, kind):
        return False
    try:
        relative = dependency_path.relative_to(manifest.parent).as_posix()
    except ValueError:
        relative = os.path.relpath(dependency_path, manifest.parent).replace(
            os.sep, "/"
        )
    line = f'{dependency} = {{ path = "{relative}" }}\n'
    marker = f"[{kind}]\n"
    if marker in text:
        text = text.replace(marker, marker + line, 1)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n[{kind}]\n{line}"
    manifest.write_text(text, encoding="utf-8")
    return True


def _blank_rust_character(character: str) -> str:
    return "\n" if character == "\n" else " "


def rust_code_only(text: str) -> str:
    """Return Rust code with comments and literal bodies replaced by whitespace."""

    output: list[str] = []
    index = 0
    block_depth = 0
    length = len(text)
    while index < length:
        if block_depth:
            if text.startswith("/*", index):
                output.extend((" ", " "))
                index += 2
                block_depth += 1
                continue
            if text.startswith("*/", index):
                output.extend((" ", " "))
                index += 2
                block_depth -= 1
                continue
            output.append(_blank_rust_character(text[index]))
            index += 1
            continue

        if text.startswith("//", index):
            output.extend((" ", " "))
            index += 2
            while index < length and text[index] != "\n":
                output.append(" ")
                index += 1
            continue
        if text.startswith("/*", index):
            output.extend((" ", " "))
            index += 2
            block_depth = 1
            continue

        if text[index] == "r":
            cursor = index + 1
            while cursor < length and text[cursor] == "#":
                cursor += 1
            if cursor < length and text[cursor] == '"':
                hashes = cursor - index - 1
                terminator = '"' + ("#" * hashes)
                body_end = text.find(terminator, cursor + 1)
                final = length if body_end < 0 else body_end + len(terminator)
                while index < final:
                    output.append(_blank_rust_character(text[index]))
                    index += 1
                continue

        if text[index] == '"':
            output.append(" ")
            index += 1
            escaped = False
            while index < length:
                character = text[index]
                output.append(_blank_rust_character(character))
                index += 1
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    break
            continue

        if text[index] == "'":
            char_end: int | None = None
            if index + 2 < length and text[index + 2] == "'":
                char_end = index + 3
            elif index + 2 < length and text[index + 1] == "\\":
                cursor = index + 2
                while cursor < length and text[cursor] != "\n":
                    if text[cursor] == "'" and text[cursor - 1] != "\\":
                        char_end = cursor + 1
                        break
                    cursor += 1
            if char_end is not None:
                while index < char_end:
                    output.append(_blank_rust_character(text[index]))
                    index += 1
                continue

        output.append(text[index])
        index += 1

    if block_depth:
        raise RuntimeError("unterminated nested Rust block comment during dependency scan")
    return "".join(output)


def source_dependency_kind(package_root: Path, source: Path) -> str:
    relative = source.relative_to(package_root)
    if relative == Path("build.rs"):
        return "build-dependencies"
    if not relative.parts:
        return "dependencies"
    first = relative.parts[0].lower()
    if first in {"tests", "benches", "examples"}:
        return "dev-dependencies"
    if first == "src":
        filename = relative.name.lower()
        parent_parts = {part.lower() for part in relative.parts[1:-1]}
        if (
            filename in {"test.rs", "tests.rs", "test_support.rs"}
            or filename.endswith("_test.rs")
            or filename.endswith("_tests.rs")
            or filename.endswith("_test_support.rs")
            or parent_parts.intersection({"test", "tests"})
        ):
            return "dev-dependencies"
    return "dependencies"


def imported_workspace_crates_by_kind(
    package_root: Path,
) -> dict[str, set[str]]:
    imported = {kind: set() for kind in DEPENDENCY_KINDS}
    pattern = re.compile(r"\b(?:use|extern\s+crate)\s+(?:::)?(codex_[A-Za-z0-9_]+)")
    path_pattern = re.compile(r"\b(codex_[A-Za-z0-9_]+)\s*::")
    sources: set[Path] = set()
    build_script = package_root / "build.rs"
    if build_script.is_file():
        sources.add(build_script)
    for subdir in ("src", "tests", "benches", "examples"):
        source_root = package_root / subdir
        if source_root.exists():
            sources.update(source_root.rglob("*.rs"))
    for source in sorted(sources):
        code = rust_code_only(source.read_text(encoding="utf-8", errors="replace"))
        kind = source_dependency_kind(package_root, source)
        imported[kind].update(pattern.findall(code))
        imported[kind].update(path_pattern.findall(code))
    imported["dev-dependencies"].difference_update(imported["dependencies"])
    return imported


def workspace_dependency_graph(metadata: dict[str, Any]) -> dict[str, set[str]]:
    packages = workspace_package_map(metadata)
    workspace_ids = {row["id"]: name for name, row in packages.items()}
    graph = {name: set() for name in packages}
    resolve = metadata.get("resolve")
    if not isinstance(resolve, dict) or not isinstance(resolve.get("nodes"), list):
        raise RuntimeError("cargo metadata resolve graph is missing")
    for node in resolve["nodes"]:
        if not isinstance(node, dict):
            raise RuntimeError("cargo metadata resolve node must be an object")
        source = workspace_ids.get(node.get("id"))
        if source is None:
            continue
        dependencies = node.get("deps", [])
        if not isinstance(dependencies, list):
            raise RuntimeError(f"cargo metadata deps for {source} must be a list")
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise RuntimeError(f"cargo metadata dependency for {source} must be an object")
            target = workspace_ids.get(dependency.get("pkg"))
            if target is None:
                continue
            kinds = dependency.get("dep_kinds", [])
            if not isinstance(kinds, list):
                raise RuntimeError(
                    f"cargo metadata dep_kinds for {source}->{target} must be a list"
                )
            if not kinds or any(
                not isinstance(kind, dict) or kind.get("kind") != "dev"
                for kind in kinds
            ):
                graph[source].add(target)
    return graph


def dependency_cycle_path(
    graph: dict[str, set[str]], package: str, dependency: str
) -> list[str] | None:
    if package == dependency:
        return [package, package]
    queue: deque[tuple[str, list[str]]] = deque([(dependency, [dependency])])
    visited: set[str] = set()
    while queue:
        current, path = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if current == package:
            return [package, *path]
        for following in sorted(graph.get(current, set())):
            if following not in visited:
                queue.append((following, [*path, following]))
    return None


def repair_missing_local_dependencies(metadata: dict[str, Any]) -> dict[str, Any]:
    packages = workspace_package_map(metadata)
    crate_to_package = {
        package_name.replace("-", "_"): (
            package_name,
            Path(row["manifest_path"]).parent,
        )
        for package_name, row in packages.items()
    }
    graph = workspace_dependency_graph(metadata)
    added: list[dict[str, str]] = []
    skipped_cycles: list[dict[str, Any]] = []
    for package_name, row in sorted(packages.items()):
        manifest = Path(row["manifest_path"])
        package_root = manifest.parent
        declarations = dependency_declarations(manifest.read_text(encoding="utf-8"))
        imports = imported_workspace_crates_by_kind(package_root)
        for kind in DEPENDENCY_KINDS:
            for crate_name in sorted(imports[kind]):
                target = crate_to_package.get(crate_name)
                if target is None:
                    continue
                dependency_name, dependency_path = target
                if dependency_name == package_name or dependency_is_declared(
                    declarations, dependency_name, kind
                ):
                    continue
                if kind in {"dependencies", "build-dependencies"}:
                    cycle = dependency_cycle_path(graph, package_name, dependency_name)
                    if cycle is not None:
                        skipped_cycles.append(
                            {
                                "package": package_name,
                                "dependency": dependency_name,
                                "kind": kind,
                                "manifest": manifest.relative_to(ROOT).as_posix(),
                                "cyclePath": cycle,
                            }
                        )
                        continue
                if add_dependency(manifest, dependency_name, dependency_path, kind):
                    declarations[kind].add(dependency_name)
                    if kind in {"dependencies", "build-dependencies"}:
                        graph[package_name].add(dependency_name)
                    added.append(
                        {
                            "package": package_name,
                            "dependency": dependency_name,
                            "kind": kind,
                            "manifest": manifest.relative_to(ROOT).as_posix(),
                        }
                    )
    return {
        "added": added,
        "count": len(added),
        "skippedCycles": skipped_cycles,
        "skippedCycleCount": len(skipped_cycles),
    }

'''

text = text[:start] + new_block + text[end:]
PATH.write_text(text, encoding="utf-8")
