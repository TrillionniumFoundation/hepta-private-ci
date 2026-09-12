"""Inspect declared executable workflow scalars, not prose; not a CI pass receipt.

Only plain/literal/folded run scalars and repository-local composite actions are
supported. Remote actions are opaque. Runtime conditions are not evaluated here.
"""

from pathlib import Path
import re
import shlex


def workflow_commands(text: str) -> list[list[str]]:
    """Read executable run scalars used by this workflow, not comments or labels.

    This deliberately supports the workflow's plain, literal and folded run
    forms. It does not interpret arbitrary shell/YAML programs as proof of tests.
    """
    lines = text.splitlines()
    commands = []
    index = 0
    while index < len(lines):
        match = re.fullmatch(r"(\s*)(?:-\s+)?run:\s*(.*)", lines[index])
        index += 1
        if not match:
            continue
        indent, scalar = match.groups()
        if scalar in ("|", "|-", "|+", ">", ">-", ">+"):
            block = []
            while index < len(lines):
                line = lines[index]
                if line.strip() and len(line) - len(line.lstrip()) <= len(indent):
                    break
                block.append(line.strip())
                index += 1
            scalar = (" " if scalar.startswith(">") else "\n").join(block)
        for line in scalar.replace("\\\n", " ").splitlines():
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            if tokens:
                commands.append(tokens)
    return commands


def declared_commands(
    text: str, root: Path, stack: tuple[Path, ...] = ()
) -> list[list[str]]:
    """Expand local actions outside run scalars; reject cycles and path escapes."""
    if len(stack) >= 16:
        raise ValueError("local action nesting limit")
    commands = workflow_commands(text)
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        run = re.fullmatch(r"(\s*)(?:-\s+)?run:\s*([|>][-+]?)", line)
        if run:
            while index < len(lines):
                child = lines[index]
                if child.strip() and len(child) - len(child.lstrip()) <= len(run[1]):
                    break
                index += 1
            continue
        use = re.fullmatch(r"\s*(?:-\s+)?uses:\s*(\./[^\s#]+)\s*(?:#.*)?", line)
        if not use:
            continue
        directory = (root / use[1]).resolve()
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
        if not re.search(r"^\s+using:\s*composite\s*$", action, re.M):
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
