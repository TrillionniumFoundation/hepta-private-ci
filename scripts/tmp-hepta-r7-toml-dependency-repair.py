#!/usr/bin/env python3
"""Make r7 dependency discovery TOML-structural and idempotent."""

from pathlib import Path

path = Path("scripts/hepta-global-finalizer-r7.py")
text = path.read_text(encoding="utf-8")

old_import = "import time\nfrom collections import defaultdict, deque\n"
new_import = "import time\nimport tomllib\nfrom collections import defaultdict, deque\n"
if old_import in text and new_import not in text:
    if text.count(old_import) != 1:
        raise SystemExit("unexpected r7 import marker count")
    text = text.replace(old_import, new_import, 1)
elif new_import not in text:
    raise SystemExit("r7 tomllib import state is unexpected")

old_function = '''def dependency_sections(text: str) -> set[str]:
    declared: set[str] = set()
    current = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line
            continue
        if current not in {
            "[dependencies]",
            "[dev-dependencies]",
            "[build-dependencies]",
        }:
            continue
        match = re.match(r"([A-Za-z0-9_-]+)\\s*=", line)
        if match:
            declared.add(match.group(1))
    return declared
'''

new_function = '''def dependency_names(section: Any, context: str) -> set[str]:
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


def dependency_sections(text: str) -> set[str]:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(f"cannot inspect invalid Cargo manifest: {error}") from error

    declared: set[str] = set()
    dependency_kinds = (
        "dependencies",
        "dev-dependencies",
        "build-dependencies",
    )
    for kind in dependency_kinds:
        declared.update(dependency_names(document.get(kind), kind))

    targets = document.get("target")
    if targets is None:
        return declared
    if not isinstance(targets, dict):
        raise RuntimeError("target must be a TOML table")
    for target_name, target in targets.items():
        if not isinstance(target, dict):
            raise RuntimeError(f"target.{target_name} must be a TOML table")
        for kind in dependency_kinds:
            declared.update(
                dependency_names(target.get(kind), f"target.{target_name}.{kind}")
            )
    return declared
'''

if old_function in text and new_function not in text:
    if text.count(old_function) != 1:
        raise SystemExit("unexpected dependency_sections marker count")
    text = text.replace(old_function, new_function, 1)
elif new_function not in text:
    raise SystemExit("r7 dependency parser state is unexpected")

path.write_text(text, encoding="utf-8")
