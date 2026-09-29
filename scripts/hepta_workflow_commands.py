"""Inspect declared executable workflow scalars, not prose; not a CI pass receipt.

Only plain/literal/folded run scalars and repository-local composite actions are
supported. Remote actions are opaque. Runtime conditions are not evaluated here.
"""

from pathlib import Path
import json
import re
import shlex


def run_scalar_commands(scalar: str) -> list[list[str]]:
    """Tokenize executable lines from one already-parsed ``run`` scalar."""
    commands: list[list[str]] = []
    for line in scalar.replace(chr(92) + "\n", " ").splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if tokens:
            commands.append(tokens)
    return commands


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
        commands.extend(run_scalar_commands(scalar))
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


def verify_owner_self_tests(registries: list[dict], root: Path) -> None:
    """Each subordinate self-test must run in its owner workflow, not twice globally."""
    for registry in registries:
        validator = shlex.split(registry["validator"])
        if (
            len(validator) != 3
            or validator[0] != "python3"
            or validator[-1] != "verify"
        ):
            raise ValueError("unsupported subordinate validator command")
        path = (root / registry["workflow"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("subordinate workflow missing or outside repository")
        expected = [*validator[:-1], "self-test"]
        commands = declared_commands(path.read_text(encoding="utf-8"), root)
        if expected not in commands:
            raise ValueError(
                f"owner workflow {registry['workflow']} must invoke {' '.join(expected)}"
            )


def load_workflow(text: str) -> dict:
    """Parse workflow data without YAML key coercion, duplicate keys or recursion.

    Parsing is not approval of arbitrary commands. Callers separately validate
    event, credential and runner envelopes; normal source review still applies.
    """
    import yaml

    if len(text.encode("utf-8")) > 262144:
        raise ValueError("workflow input exceeds 256 KiB")
    try:
        node = yaml.compose(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid workflow YAML: {error}") from error
    budget = 16384
    active = set()

    def convert(value, depth=0):
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 64 or id(value) in active:
            raise ValueError("workflow nesting or alias expansion exceeds bounds")
        active.add(id(value))
        try:
            if isinstance(value, yaml.ScalarNode):
                if value.tag not in {
                    "tag:yaml.org,2002:str",
                    "tag:yaml.org,2002:null",
                    "tag:yaml.org,2002:bool",
                    "tag:yaml.org,2002:int",
                }:
                    raise ValueError("unsupported workflow scalar tag")
                return value.value
            if isinstance(value, yaml.SequenceNode):
                return [convert(item, depth + 1) for item in value.value]
            if isinstance(value, yaml.MappingNode):
                result = {}
                for key, item in value.value:
                    key = convert(key, depth + 1)
                    if not isinstance(key, str) or key in result or key == "<<":
                        raise ValueError("duplicate or ambiguous workflow key")
                    result[key] = convert(item, depth + 1)
                return result
            raise ValueError("invalid workflow node")
        finally:
            active.remove(id(value))

    result = convert(node)
    if not isinstance(result, dict):
        raise ValueError("workflow must be an object")
    return result


def workflow_events(document: dict) -> set[str]:
    value = document.get("on")
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, (dict, list)) and all(isinstance(item, str) for item in value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate workflow event")
        return set(value)
    raise ValueError("invalid workflow event declaration")


def workflow_jobs(document: dict) -> dict[str, dict]:
    """Return validated executable jobs from an already parsed workflow."""
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError("workflow jobs must be a nonempty object")
    if any(
        not isinstance(name, str) or not isinstance(job, dict)
        for name, job in jobs.items()
    ):
        raise ValueError("workflow job entries must be named objects")
    return jobs


def workflow_job(document: dict, name: str) -> dict:
    try:
        return workflow_jobs(document)[name]
    except KeyError as error:
        raise ValueError(f"missing workflow job: {name}") from error


def workflow_steps(document: dict, job_name: str) -> list[dict]:
    steps = workflow_job(document, job_name).get("steps")
    if (
        not isinstance(steps, list)
        or not steps
        or any(not isinstance(step, dict) for step in steps)
    ):
        raise ValueError(f"workflow job {job_name} must contain object steps")
    return steps


def _unique_step(document: dict, job_name: str, key: str, value: str) -> dict:
    matches = [
        step for step in workflow_steps(document, job_name) if step.get(key) == value
    ]
    if len(matches) != 1:
        raise ValueError(
            f"workflow job {job_name} requires one step with {key}={value!r}"
        )
    return matches[0]


def workflow_step(document: dict, job_name: str, name: str) -> dict:
    return _unique_step(document, job_name, "name", name)


def workflow_step_by_id(document: dict, job_name: str, step_id: str) -> dict:
    return _unique_step(document, job_name, "id", step_id)


def workflow_run(step: dict) -> str:
    value = step.get("run")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("workflow step has no executable run scalar")
    return value if value.endswith("\n") else value + "\n"


def workflow_needs(job: dict) -> set[str]:
    value = job.get("needs", [])
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    raise ValueError("workflow needs must be a string or string list")


def workflow_contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            workflow_contains_key(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return any(workflow_contains_key(item, key) for item in value)
    return False


def workflow_expression_functions(value: object) -> set[str]:
    """Return function calls from GitHub expression bodies, ignoring quoted text."""
    functions: set[str] = set()
    if not isinstance(value, str):
        return functions
    expressions = re.findall(r"\$\{\{(.*?)\}\}", value, flags=re.S) or [value]
    for expression in expressions:
        expression = re.sub(r"'(?:[^']|'')*'", "''", expression)
        expression = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expression)
        functions.update(
            re.findall(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)\s*\(", expression)
        )
    return functions


def workflow_expression_references(
    value: object, *, implicit: bool = False
) -> set[str]:
    """Return data-flow references from GitHub expressions in parsed YAML.

    Plain prose, labels, shell text outside ``${{ ... }}``, and quoted literals
    are ignored.  This checks declared workflow wiring, not expression truth.
    """
    references: set[str] = set()
    roots = "needs|steps|matrix|github|inputs|env|vars|runner|strategy|job"

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            expressions = re.findall(r"\$\{\{(.*?)\}\}", item, flags=re.S)
            if implicit and not expressions:
                expressions = [item]
            for expression in expressions:
                expression = re.sub(r"'(?:[^']|'')*'", "''", expression)
                expression = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expression)
                references.update(
                    re.findall(
                        rf"(?<![\w.])(?:{roots})(?:\.[A-Za-z0-9_-]+)*",
                        expression,
                    )
                )

    visit(value)
    return references


def workflow_literal_collection_values(value: object) -> set[str]:
    """Collect static string members from a list or JSON literals in expressions.

    This supports direct YAML sequences and ``fromJSON`` expressions without
    requiring one exact whitespace, quoting, or conditional spelling.
    """
    values: set[str] = set()
    if isinstance(value, list):
        if all(isinstance(item, str) and "${{" not in item for item in value):
            return set(value)
        return set()
    if not isinstance(value, str):
        return set()
    for match in re.finditer(r"'(?:[^']|'')*'|\"(?:[^\"\\]|\\.)*\"", value):
        token = match.group(0)
        try:
            decoded = (
                token[1:-1].replace("''", "'")
                if token.startswith("'")
                else json.loads(token)
            )
            candidate = json.loads(decoded)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, list) and all(
            isinstance(item, str) for item in candidate
        ):
            values.update(candidate)
    return values


def validate_manual_workflow(text: str, maximum_minutes: int) -> None:
    """Admit a bounded, credential-free hosted manual diagnostic envelope.

    Automatic events, privileged runners and secret-bearing workflows require
    the existing reviewed integration path; no filename can authorize them.
    """
    document = load_workflow(text)
    events = workflow_events(document)
    if not events or not events <= {"workflow_dispatch", "workflow_call"}:
        raise ValueError("new automatic workflow requires integration review")

    def permissions(value):
        if not isinstance(value, dict) or any(
            not isinstance(item, str) or item not in {"read", "none"}
            for item in value.values()
        ):
            raise ValueError(
                "manual diagnostic requires explicit read-only permissions"
            )

    permissions(document.get("permissions"))
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not 1 <= len(jobs) <= 16:
        raise ValueError("manual diagnostic requires bounded jobs")

    def credentials(value):
        if isinstance(value, dict):
            if any(
                key in value
                for key in ("secrets", "environment", "container", "services")
            ):
                raise ValueError(
                    "manual diagnostic cannot acquire deployment credentials"
                )
            for item in value.values():
                credentials(item)
        elif isinstance(value, list):
            for item in value:
                credentials(item)
        elif isinstance(value, str):
            for expression in re.findall(r"\$\{\{(.*?)\}\}", value, flags=re.S):
                # Ignore quoted text, not identifiers: toJSON(secrets) is as
                # credential-bearing as secrets.KEY or secrets['KEY'].
                expression = re.sub(r"'(?:[^']|'')*'", "''", expression)
                if re.search(r"(?<![\w.])secrets\b", expression, flags=re.I):
                    raise ValueError("manual diagnostic cannot reference secrets")

    credentials(document)

    def job_bound(job):
        strategy = job.get("strategy", {})
        if not isinstance(strategy, dict):
            raise ValueError("manual diagnostic requires a static strategy")
        if "matrix" not in strategy:
            return 1
        matrix = strategy["matrix"]
        if not isinstance(matrix, dict) or not matrix:
            raise ValueError("manual diagnostic requires a finite static matrix")

        def literal(value):
            if isinstance(value, dict):
                return all(literal(item) for item in value.values())
            if isinstance(value, list):
                return all(literal(item) for item in value)
            return isinstance(value, str) and "${{" not in value

        if not literal(matrix):
            raise ValueError("dynamic matrix requires integration review")
        axes = {
            key: value
            for key, value in matrix.items()
            if key not in {"include", "exclude"}
        }
        combinations = 1 if axes else 0
        for values in axes.values():
            if not isinstance(values, list) or not values:
                raise ValueError("matrix dimensions require nonempty static lists")
            combinations *= len(values)
            if combinations > 16:
                raise ValueError("manual diagnostic exceeds expanded job budget")
        includes = matrix.get("include", [])
        excludes = matrix.get("exclude", [])
        for entries in (includes, excludes):
            if not isinstance(entries, list) or not all(
                isinstance(item, dict) for item in entries
            ):
                raise ValueError("matrix include/exclude must be static objects")
        # Upper bound: exclusions do not buy extra budget. Include-only rows may
        # add jobs; metadata-only includes on existing axes cannot add a new job.
        combinations += sum(
            not axes or bool(excludes) or bool(set(row) & set(axes)) for row in includes
        )
        if not 1 <= combinations <= 16:
            raise ValueError("manual diagnostic exceeds expanded job budget")
        return combinations

    expanded_jobs = 0
    for job in jobs.values():
        if not isinstance(job, dict) or "uses" in job:
            raise ValueError("opaque reusable job requires integration review")
        expanded_jobs += job_bound(job)
        if expanded_jobs > 16:
            raise ValueError("manual diagnostic exceeds expanded job budget")
        permissions(job.get("permissions", document["permissions"]))
        runner = job.get("runs-on")
        if not isinstance(runner, str) or not re.fullmatch(
            r"(?:ubuntu|windows|macos)-(?:latest|[0-9.]+)", runner
        ):
            raise ValueError("manual diagnostic requires a static hosted runner")
        minutes = job.get("timeout-minutes", "")
        if (
            not isinstance(minutes, str)
            or not minutes.isdecimal()
            or not 1 <= int(minutes) <= maximum_minutes
        ):
            raise ValueError(
                "manual diagnostic needs a timeout within the reviewed cost budget"
            )
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("manual diagnostic needs executable steps")
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("invalid diagnostic step")
            use = step.get("uses")
            if use is not None and (
                not isinstance(use, str)
                or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}", use
                )
            ):
                raise ValueError(
                    "diagnostic actions must be pinned; opaque local actions require review"
                )
            if isinstance(use, str) and use.startswith("actions/checkout@"):
                if step.get("with", {}).get("persist-credentials") != "false":
                    raise ValueError("diagnostic checkout must not persist credentials")
