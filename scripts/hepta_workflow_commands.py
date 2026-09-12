"""Inspect declared executable workflow scalars, not prose; not a CI pass receipt.

Only plain/literal/folded run scalars and repository-local composite actions are
supported. Remote actions are opaque. Runtime conditions are not evaluated here.
"""

from pathlib import Path
import re
import shlex


def _workflow_scalars(text: str):
    """Visit declarations once, never reinterpret block-scalar content as YAML.

    This is the repository's restricted declaration profile, not a YAML or
    shell evaluator. The key column includes a sequence marker, so sibling
    name/env fields cannot be swallowed by a ``- run: |`` block.
    """
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = re.fullmatch(
            r" *(?:- +)?(?P<key>[A-Za-z_][\w.-]*):\s*(?P<value>.*)", lines[index]
        )
        index += 1
        if not match:
            continue
        key, scalar = match.group("key", "value")
        block_header = re.fullmatch(
            r"([|>])(?:[1-9][-+]?|[-+][1-9]?)? *(?:#.*)?", scalar
        )
        if block_header:
            block = []
            while index < len(lines):
                line = lines[index]
                if line.strip() and len(line) - len(line.lstrip()) <= match.start("key"):
                    break
                block.append(line.strip())
                index += 1
            scalar = (" " if block_header[1] == ">" else "\n").join(block)
        yield key, scalar


def _shell_commands(scalar: str) -> list[list[str]]:
    commands = []
    for line in scalar.replace("\\\n", " ").splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if tokens:
            commands.append(tokens)
    return commands


def workflow_commands(text: str) -> list[list[str]]:
    """Read declared run scalars, not comments, labels or examples in prose."""
    return [
        command
        for key, scalar in _workflow_scalars(text)
        if key == "run"
        for command in _shell_commands(scalar)
    ]


def declared_commands(
    text: str, root: Path, stack: tuple[Path, ...] = ()
) -> list[list[str]]:
    """Expand local actions outside scalar bodies; reject cycles and escapes."""
    if len(stack) >= 16:
        raise ValueError("local action nesting limit")
    commands = []
    for key, scalar in _workflow_scalars(text):
        if key == "run":
            commands.extend(_shell_commands(scalar))
            continue
        if key != "uses":
            continue
        use = shlex.split(scalar, comments=True)
        if not use or not use[0].startswith("./"):
            continue  # Remote actions remain opaque.
        if len(use) != 1:
            raise ValueError("unsupported local action reference")
        directory = (root / use[0]).resolve()
        if not directory.is_relative_to(root.resolve()):
            raise ValueError("local action outside repository")
        candidates = [directory / name for name in ("action.yml", "action.yaml")]
        present = [path for path in candidates if path.is_file()]
        if len(present) != 1:
            raise ValueError("local action missing or ambiguous")
        path = present[0].resolve()
        if not path.is_relative_to(root.resolve()) or path in stack:
            raise ValueError("local action cycle or path escape")
        action = path.read_text(encoding="utf-8")
        if not any(
            key == "using" and shlex.split(value, comments=True) == ["composite"]
            for key, value in _workflow_scalars(action)
        ):
            raise ValueError("unsupported local action execution profile")
        commands.extend(declared_commands(action, root, (*stack, path)))
    return commands


def verify_synthetic_merge(text: str, root: Path) -> None:
    """Resolve the shared action before checking actual merge-construction commands."""
    commands = declared_commands(text, root)
    # These are declared shell invocations; comments, names and echo output are
    # not executable evidence. Behavioral tests exercise the shared action.
    lines = [
        " ".join(command)
        for command in commands
        if command[0] not in {"echo", "printf", "true"}
    ]
    merge_tree = any(
        re.match(
            r"(?:git |[A-Z_][A-Z0-9_]*=\$\(git )merge-tree --write-tree(?: |$)", line
        )
        for line in lines
    )
    commit_tree = any(
        line.startswith("git commit-tree ")
        or re.match(r"[A-Z_][A-Z0-9_]*=\$\(printf .* \| git commit-tree ", line)
        for line in lines
    )
    if not merge_tree or not commit_tree:
        raise ValueError("missing executable merge-tree/commit-tree construction")
