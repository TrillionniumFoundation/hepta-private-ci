#!/usr/bin/env python3
"""Fail-closed structural qualification for the immutable ui.native candidate."""

from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")

FORBIDDEN_WORKFLOWS = {
    "hepta-ui-native-acceptance-proposal.yml",
    "hepta-ui-native-current-source.yml",
    "hepta-ui-native-fix-materializer.yml",
    "hepta-ui-native-integrate-20260928.yml",
    "hepta-ui-native-operational-materialize.yml",
    "hepta-ui-native-projections.yml",
    "hepta-ui-native-qualified-integration.yml",
    "hepta-ui-native-remediation-format.yml",
    "hepta-ui-native-remediation.yml",
    "hepta-ui-native-slim-materializer.yml",
    "hepta-ui-native-source-integrity.yml",
    "ui-native-direct-apply-once.yml",
    "ui-native-remediation-apply-once.yml",
    "ui-native-source-export-pr.yml",
    "ui-native-wal-index-apply-once.yml",
    "ui-native-wal-index-export-pr.yml",
}
ALLOWED_WORKFLOW = "ui-native-qualification.yml"
READ_ONLY_WORKFLOWS = frozenset(
    {
        ALLOWED_WORKFLOW,
        "ui-native-lifecycle-source.yml",
        "ui-native-robrix-preview.yml",
    }
)

STATE_FILES = (
    "apps/hepta-native/CURRENT_SOURCE.json",
    "apps/hepta-native/CANDIDATE.json",
    "apps/hepta-native/STORAGE_BUDGETS.json",
    "docs/modules/ui.native/CURRENT_SOURCE.json",
    "docs/modules/ui.native/CURRENT_DELIVERY.json",
    "docs/modules/ui.native/IMPLEMENTATION_MAP.json",
    "docs/modules/ui.native/QUALIFICATION_MANIFEST.json",
)

IMPLEMENTATION_PATHS = (
    ".gitattributes",
    "apps/hepta-native/.gitattributes",
    "apps/hepta-native/src",
    "apps/hepta-native/tests",
    "apps/hepta-native/Cargo.toml",
    "apps/hepta-native/Cargo.lock",
    "apps/hepta-native/build.rs",
    "apps/hepta-native/rust-toolchain.toml",
    "apps/hepta-native/portal",
    "apps/hepta-native/packaging",
    "apps/hepta-native/tools/package_unsigned.py",
    "apps/hepta-native/tools/archive_safety.py",
    "codex-rs/hepta-native-gateway",
    "codex-rs/hepta-private-state",
    "codex-rs/keyring-store",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/hepta-contracts",
    ".cargo",
    "codex-rs/.cargo",
    "apps/hepta-native/.cargo",
)
QUALIFIED_MANIFESTS = (
    "apps/hepta-native/Cargo.toml",
    "codex-rs/hepta-native-gateway/Cargo.toml",
    "codex-rs/hepta-contracts/Cargo.toml",
    "codex-rs/hepta-private-state/Cargo.toml",
    "codex-rs/utils/private-state/Cargo.toml",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_json(path: str) -> dict[str, Any]:
    value = json.loads(_read(path))
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def _walk(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="strict"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_success(*args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _cargo_manifest(path: Path) -> dict[str, Any]:
    _require(
        path.is_file() and not path.is_symlink(),
        f"unsafe or missing Cargo manifest: {path}",
    )
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _repository_path(path: Path) -> str:
    root = ROOT.resolve(strict=True)
    try:
        lexical_relative = path.relative_to(ROOT)
    except ValueError:
        try:
            lexical_relative = path.relative_to(root)
        except ValueError as error:
            raise RuntimeError(
                f"local Cargo dependency escapes the repository: {path}"
            ) from error
    # Canonicalize only the trusted root alias (macOS /var, Windows short paths).
    # Keep dependency components intact so resolving them cannot hide a link.
    depth = 0
    for part in lexical_relative.parts:
        depth += -1 if part == ".." else 1
        _require(depth >= 0, f"local Cargo dependency escapes the repository: {path}")
    checked = root / lexical_relative
    resolved = checked.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise RuntimeError(
            f"local Cargo dependency escapes the repository: {path}"
        ) from error
    for parent in (checked, *checked.parents):
        if not parent.is_relative_to(root):
            continue
        metadata = parent.lstat()
        _require(
            not (
                stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ),
            f"local Cargo dependency uses a symlink or reparse point: {path}",
        )
    return relative.as_posix()


def _workspace_manifest(path: Path, manifest: dict[str, Any]) -> Path | None:
    if "workspace" in manifest:
        return path
    explicit = manifest.get("package", {}).get("workspace")
    if explicit is not None:
        _require(isinstance(explicit, str), "Cargo package.workspace must be a path")
        workspace = path.parent / explicit / "Cargo.toml"
        _repository_path(workspace)
        _require(
            "workspace" in _cargo_manifest(workspace),
            "explicit Cargo workspace is missing",
        )
        return workspace
    for parent in path.parent.parents:
        try:
            parent.relative_to(ROOT.resolve(strict=True))
        except ValueError:
            break
        candidate = parent / "Cargo.toml"
        if candidate.is_file() and "workspace" in _cargo_manifest(candidate):
            return candidate
    return None


def local_cargo_dependency_paths() -> tuple[str, ...]:
    """Resolve local paths for the exact app and owner Cargo subjects.

    Dev dependencies enter only for packages tested with --all-targets. Every
    target's normal/build dependencies and optional dependencies are included,
    because qualification uses all features and all three operating systems.
    """
    seeds = {
        ROOT / relative
        for relative in QUALIFIED_MANIFESTS
        if (ROOT / relative).is_file()
    }
    queue = [(path, True) for path in seeds]
    visited: dict[Path, bool] = {}
    paths: set[str] = set()
    while queue:
        path, include_dev = queue.pop()
        _repository_path(path)
        path = path.resolve(strict=True)
        if path in visited and (visited[path] or not include_dev):
            continue
        visited[path] = include_dev
        paths.add(_repository_path(path.parent))
        manifest = _cargo_manifest(path)
        workspace_path = _workspace_manifest(path, manifest)
        workspace = (
            _cargo_manifest(workspace_path) if workspace_path is not None else {}
        )
        if workspace_path is not None:
            paths.add(_repository_path(workspace_path))
        sections = ("dependencies", "build-dependencies") + (
            ("dev-dependencies",) if include_dev else ()
        )
        for table in [manifest, *manifest.get("target", {}).values()]:
            for section in sections:
                for name, specification in table.get(section, {}).items():
                    if not isinstance(specification, dict):
                        continue
                    base = path.parent
                    if specification.get("workspace") is True:
                        _require(
                            workspace_path is not None,
                            f"{path}: dependency {name} has no workspace",
                        )
                        inherited = (
                            workspace.get("workspace", {})
                            .get("dependencies", {})
                            .get(name)
                        )
                        _require(
                            inherited is not None,
                            f"{path}: workspace dependency {name} is missing",
                        )
                        specification = inherited
                        base = workspace_path.parent
                    if isinstance(specification, dict) and "path" in specification:
                        dependency = base / specification["path"]
                        _repository_path(dependency)
                        queue.append(
                            (
                                dependency / "Cargo.toml",
                                dependency / "Cargo.toml" in seeds,
                            )
                        )
        # Local registry/git overrides may influence any qualified root. Freeze
        # every declared local override, even when it currently resolves unused.
        for owner_path, owner in ((path, manifest), (workspace_path, workspace)):
            if owner_path is None:
                continue
            for override in [
                *owner.get("patch", {}).values(),
                owner.get("replace", {}),
            ]:
                for specification in override.values():
                    if isinstance(specification, dict) and "path" in specification:
                        dependency = owner_path.parent / specification["path"]
                        _repository_path(dependency)
                        queue.append((dependency / "Cargo.toml", False))
    return tuple(sorted(paths))


def implementation_paths() -> tuple[str, ...]:
    # The standalone app permits evidence/navigation continuations beside its
    # product source, so retain its explicit operational paths above.
    dependencies = set(local_cargo_dependency_paths()) - {"apps/hepta-native"}
    return tuple(sorted(set(IMPLEMENTATION_PATHS) | dependencies))


def check_dependency_workflow_filters(workflow: str) -> None:
    _require("    paths:\n" in workflow, "qualification path filters are missing")
    filters = workflow.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
    patterns = {
        line.strip().removeprefix("- ").strip("\"'")
        for line in filters.splitlines()
        if line.strip().startswith("- ")
    }
    dependencies = (
        *local_cargo_dependency_paths(),
        "tools/ui-native-projections",
        ".cargo",
        "codex-rs/.cargo",
        ".gitattributes",
        "apps/hepta-native/.gitattributes",
    )
    for path in dependencies:
        expected = (
            path if path.endswith(("Cargo.toml", ".gitattributes")) else f"{path}/**"
        )
        parent_patterns = {
            f"{parent.as_posix()}/**"
            for parent in Path(path).parents
            if parent.as_posix() != "."
        }
        _require(
            expected in patterns
            or bool(parent_patterns & patterns)
            or "**" in patterns,
            f"qualification workflow does not trigger for dependency {path}",
        )


def check_frozen_implementation(implementation: str) -> None:
    paths = implementation_paths()
    _require(
        _git_success("diff", "--quiet", implementation, "HEAD", "--", *paths),
        "metadata continuation changes product implementation after the frozen source",
    )
    _require(
        _git_success("diff", "--quiet", "HEAD", "--", *paths),
        "product implementation has staged or working-tree drift",
    )
    untracked = _git_value("ls-files", "--others", "--exclude-standard", "--", *paths)
    _require(untracked == "", "product implementation has untracked source files")
    check_frozen_storage_budgets(implementation)


def check_job_environment_contexts(workflow: str) -> None:
    """Check job env expressions before GitHub schedules a runner.

    This workflow uses two-space mapping indentation. Runner, step and env
    contexts are available inside steps, but not in job-level env values.
    """
    allowed = {"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"}
    in_jobs = False
    job = None
    environment: list[str] = []
    in_environment = False

    def validate() -> None:
        pattern = r"\$\{\{((?:'(?:[^']|'')*'|[^'}]|\}(?!\}))*?)\}\}"
        for match in re.finditer(pattern, "\n".join(environment), re.DOTALL):
            # Expressions use single-quoted string literals, with doubled
            # quotes for escaping. Text in a literal names no context.
            expression = re.sub(r"'(?:[^']|'')*'", "", match.group(1))
            for token in re.finditer(r"[A-Za-z_][A-Za-z0-9_-]*", expression):
                before = expression[: token.start()].rstrip()
                after = expression[token.end() :].lstrip()
                name = token.group().lower()
                if (
                    before.endswith(".")
                    or after.startswith("(")
                    or name in {"true", "false", "null"}
                ):
                    continue
                _require(
                    name in allowed,
                    f"job {job} env uses unavailable context {token.group()!r}",
                )

    for line in workflow.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indentation = len(line) - len(stripped)
        if in_environment and indentation <= 4:
            validate()
            environment = []
            in_environment = False
        if indentation == 0:
            # A trailing YAML comment or whitespace does not change this
            # block mapping header. Quoted inline scalar values are not headers.
            in_jobs = re.fullmatch(r"jobs:(?:[ \t]+(?:#.*)?)?", stripped) is not None
            job = None
        elif in_jobs and indentation == 2:
            job = stripped.split(":", 1)[0]
        elif (
            in_jobs
            and job is not None
            and indentation == 4
            and stripped.startswith("env:")
        ):
            in_environment = True
            environment.append(stripped[4:])
        elif in_environment:
            environment.append(stripped)
    if in_environment:
        validate()


def check_frozen_storage_budgets(implementation: str) -> None:
    # This JSON is embedded by include_str! in the qualification executable.
    # Only the two source-navigation anchors may continue after its source freeze.
    relative = "apps/hepta-native/STORAGE_BUDGETS.json"
    path = ROOT / relative
    frozen_exists = _git_success("cat-file", "-e", f"{implementation}:{relative}")
    if not frozen_exists and not path.exists():
        return  # Small isolated source fixtures need not define storage budgets.
    _require(
        frozen_exists and path.is_file() and not path.is_symlink(),
        "storage budget contract is missing from the frozen or current source",
    )
    frozen = json.loads(_git_value("show", f"{implementation}:{relative}") or "null")
    current = _load_json(relative)
    _require(
        isinstance(frozen, dict), "frozen storage budget contract is not an object"
    )
    navigation = {"implementationSourceSha", "implementationSourceTree"}
    _require(
        {key: value for key, value in frozen.items() if key not in navigation}
        == {key: value for key, value in current.items() if key not in navigation},
        "storage budget contract changed after the frozen source",
    )


def check_native_platform_contracts() -> None:
    """Check declared Rust adapter wiring, not runtime or physical acceptance.

    These lexical checks replace the retired absolute interpreter-launcher
    checks. Actual bounds, identity, cancellation and terminality still require
    the Rust behavioral tests and installed-platform evidence. This scope does
    not declare the separate picker/installer/UI modules fully Rust-only.
    """
    contracts = {
        "apps/hepta-native/src/platform.rs": {
            "verified open resource": "fn open_verified_resource(",
            "final-symlink rejection": "OFlags::NOFOLLOW",
            "retained descriptor transport": "Fd::from(file.as_fd())",
            "bounded native portal handoff": "RESOURCE_HANDOFF_TIMEOUT",
            "uncertain external effects": "PlatformObservation::indeterminate()",
            "bounded adapter slots": "LauncherSlot::acquire(active)?",
            "cleared helper environment": "command.env_clear();",
            "Rust notification helper dispatch": "notification_helper::launch(",
        },
        "apps/hepta-native/src/native_portal.rs": {
            "pinned portal owner": ".sender(owner.as_str())",
            "exact request path": ".path(path.as_str())",
            "bounded response queue": "MessageStream::for_match_rule(rule, &connection, Some(4))",
            "request handle verification": "returned.as_str() != path",
            "bounded response bytes": "body.len() > MAX_RESPONSE_BYTES",
            "bounded request cleanup": "CLOSE_TIMEOUT",
        },
        "apps/hepta-native/src/platform_linux.rs": {
            "native notification method": '"Notify"',
            "notification deadline": "super::NOTIFICATION_TIMEOUT",
        },
        "apps/hepta-native/src/platform_notification_helper.rs": {
            "same executable": "std::env::current_exe()?",
            "running image identity": "running_binary_digest()?",
            "launcher image identity": "digest_file(&executable)? != expected_digest",
            "child readiness identity": "ready.binary_digest != expected_digest",
            "request identity": "self.nonce != nonce",
            "bounded request bytes": "MAX_REQUEST_BYTES + 1",
            "model payload validation": "PlatformPayload::Notify",
            "closed request schema": "#[serde(deny_unknown_fields)]",
            "inherited request pipe": ".stdin(Stdio::piped())",
            "inherited readiness pipe": ".stdout(Stdio::piped())",
            "child deadline": "super::NOTIFICATION_TIMEOUT",
            "child termination": "child.kill()",
            "child retirement": "child.wait()",
            "nonblocking readiness reader": "crate::native_pipe::prepare_reader(&stdout)?",
            "nonblocking request writer": "crate::native_pipe::prepare_writer(&stdin)?",
            "polled readiness": "crate::native_pipe::read_available(",
            "partial request writes": "writer.write(&request[written..])",
        },
        "apps/hepta-native/src/native_pipe.rs": {
            "Unix nonblocking pipe mode": "OFlags::NONBLOCK",
            "Windows available-byte reader": "hepta_native_platform::pipe::read_available(",
            "Windows nonblocking pipe writer": "hepta_native_platform::pipe::configure_writer(",
        },
        "apps/hepta-native/platform-adapters/src/pipe.rs": {
            "Windows nonblocking pipe mode": "PIPE_NOWAIT",
            "Windows pipe availability observation": "PeekNamedPipe",
            "empty open pipe is not EOF": "if available == 0",
            "bounded available-byte read": "bytes.len().min(available as usize)",
        },
        "apps/hepta-native/src/platform_notify_macos.rs": {
            "installed bundle identity": '"org.trillionnium.hepta.native"',
            "native notification API": "UNUserNotificationCenter",
            "literal notification title": "NSString::from_str(title)",
        },
        "apps/hepta-native/src/platform_notify_windows.rs": {
            "registered identity gate": "notification_supported()",
            "literal notification text": "CreateTextNode",
            "registered native notifier": "CreateToastNotifierWithId",
        },
    }
    for relative, required in contracts.items():
        path = ROOT / relative
        _require(
            path.is_file() and not path.is_symlink(),
            f"missing or unsafe Rust platform source: {relative}",
        )
        source = _read(relative)
        _require(
            re.search(
                r"\b(?:python3?|powershell|osascript|notify-send)(?:\.exe)?\b",
                source,
                re.IGNORECASE,
            )
            is None,
            f"retired interpreter/launcher reference in Rust platform source: {relative}",
        )
        _require(
            re.search(
                r"include_(?:str|bytes)!\s*\([^)]*\.(?:py|ps1|js|ts|sh)[\"']", source
            )
            is None,
            f"embedded executable script in Rust platform source: {relative}",
        )
        for label, token in required.items():
            _require(
                token in source, f"missing Rust platform contract {label}: {relative}"
            )
    main = _read("apps/hepta-native/src/main.rs")
    _require(
        'raw_args == ["--native-notification-helper"]' in main
        and "hepta_native::platform::run_notification_helper()?" in main,
        "notification helper does not have its exact no-argument entrypoint",
    )


def check_read_only_workflow_registration(workflows: dict[str, str]) -> None:
    """Register reviewed subjects without granting writer or release authority."""
    _require(
        set(workflows) == READ_ONLY_WORKFLOWS,
        f"unexpected ui.native workflow set: {sorted(workflows)}",
    )
    for name, workflow in workflows.items():
        # Reject job overrides, inline mappings, aliases and write-all. These
        # reviewed workflows deliberately use one explicit read-only root grant.
        active = "\n".join(
            line for line in workflow.splitlines() if not line.lstrip().startswith("#")
        )
        # Escaped quoted keys can spell permissions/uses differently while
        # YAML decodes them to the same key. This deliberately literal format
        # rejects that syntax rather than guessing at YAML escape semantics.
        quoted_keys = re.findall(r'"(?:[^"\\\n]|\\.)*"[ \t]*:', active)
        quoted_actions = re.findall(
            r'(?:uses|["\']uses["\']):\s*"(?:[^"\\\n]|\\.)*"', active
        )
        _require(
            not any("\\" in value for value in quoted_keys + quoted_actions),
            f"{name}: escaped workflow keys or action values are unsupported",
        )
        _require(
            re.search(r"(?m)^\s*-\s*\{", active) is None,
            f"{name}: inline workflow steps are unsupported",
        )
        # Keep action/input declarations in the reviewed plain block subset.
        # Block scalars, aliases and duplicate quoted keys are not interpreted.
        _require(
            re.search(
                r"(?m)^\s*(?:-\s*)?(?:[\"'](?:uses|with)[\"']\s*:|<<\s*:|(?:[\w-]+:\s*)?[&*][\w-]+)",
                active,
            )
            is None,
            f"{name}: unsupported workflow action or input syntax",
        )
        _require(
            re.search(r"(?m)^\s*(?:-\s*)?(?:uses|with)[ \t]+:", active) is None,
            f"{name}: action/input keys require canonical colon spacing",
        )
        action_lines = re.findall(r"(?m)^\s*(?:-\s*)?uses:[^\n]*", active)
        _require(
            all(
                re.fullmatch(
                    r"\s*(?:-\s*)?uses: [A-Za-z0-9_./@-]+(?:[ \t]+#[^\n]*)?", line
                )
                for line in action_lines
            ),
            f"{name}: action values must use plain single-line syntax",
        )
        keys = re.findall(r"(?:\bpermissions|[\"']permissions[\"'])[ \t]*:", active)
        _require(len(keys) == 1, f"{name}: nested or ambiguous workflow permissions")
        declarations = re.findall(
            r"(?m)^([ \t]*)permissions[ \t]*:[ \t]*([^\n]*)$", active
        )
        _require(declarations == [("", "")], f"{name}: ambiguous workflow permissions")
        grant = re.search(r"(?m)^permissions:\n((?:[ \t]+[^\n]*\n|\n)+)", workflow)
        lines = (
            [
                line.strip()
                for line in grant.group(1).splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if grant
            else []
        )
        _require(lines == ["contents: read"], f"{name}: workflow is not read-only")
        _require(
            re.search(r"\bgit[ \t]+(?:-[^\n;]*?[ \t]+)?(?:push|commit|apply)\b", active)
            is None,
            f"{name}: unsafe workflow Git operation",
        )
        _require(
            re.search(r"\bsecrets\s*(?:\.|\[)", active) is None,
            f"{name}: read-only workflow must not request external credentials",
        )
        checkout = re.findall(
            r"(?:\bpersist-credentials|[\"']persist-credentials[\"'])[ \t]*:[ \t]*([^,}\n]+)",
            active,
        )
        _require(
            bool(checkout)
            and all(value.strip().strip("\"'") == "false" for value in checkout),
            f"{name}: checkout credentials must not persist",
        )
        # Each checkout has its own default. A safe declaration on one step
        # cannot cover an added checkout which silently persists credentials.
        lines = active.splitlines()
        checkouts = 0
        for index, line in enumerate(lines):
            use = re.match(
                r"^([ \t]*)(-\s+)?(?:uses|[\"']uses[\"']):\s*[\"']?actions/checkout@",
                line,
            )
            if use is None:
                continue
            checkouts += 1
            step_indent = len(use[1]) - (0 if use[2] else 2)
            end = index + 1
            while end < len(lines):
                child = lines[end]
                if child.strip() and len(child) - len(child.lstrip()) <= step_indent:
                    break
                end += 1
            block = lines[index:end]
            input_indent = step_indent + 2
            with_headers = [
                offset
                for offset, child in enumerate(block)
                if re.fullmatch(r" " * input_indent + r"with:\s*", child)
            ]
            _require(
                len(with_headers) == 1,
                f"{name}: checkout requires one explicit with mapping",
            )
            start = with_headers[0] + 1
            stop = start
            while stop < len(block):
                child = block[stop]
                if child.strip() and len(child) - len(child.lstrip()) <= input_indent:
                    break
                stop += 1
            settings = [
                child.strip()
                for child in block[start:stop]
                if re.match(r" " * (input_indent + 2) + r"persist-credentials:", child)
            ]
            _require(
                settings == ["persist-credentials: false"],
                f"{name}: every checkout requires explicit non-persistent credentials in with",
            )
        _require(checkouts > 0, f"{name}: source checkout is missing")
        _require(
            "cancel-in-progress: false" in workflow
            and "cancel-in-progress: true" not in workflow,
            f"{name}: exact-source run may be cancelled",
        )
        check_job_environment_contexts(workflow)


def check_repository() -> dict[str, Any]:
    workflows = ROOT / ".github" / "workflows"
    for name in FORBIDDEN_WORKFLOWS:
        _require(
            not (workflows / name).exists(), f"retired writer workflow remains: {name}"
        )

    ui_native_workflows = sorted(
        path.name
        for suffix in ("yml", "yaml")
        for path in workflows.glob(f"*ui-native*.{suffix}")
    )
    check_read_only_workflow_registration(
        {name: _read(f".github/workflows/{name}") for name in ui_native_workflows}
    )
    workflow = _read(f".github/workflows/{ALLOWED_WORKFLOW}")
    check_job_environment_contexts(workflow)
    check_dependency_workflow_filters(workflow)
    for forbidden in ("contents: write", "git push", "git commit", "git apply"):
        _require(
            forbidden not in workflow, f"qualification workflow contains {forbidden!r}"
        )
    _require(
        "persist-credentials: false" in workflow, "checkout credentials are persisted"
    )
    _require(
        "cancel-in-progress: false" in workflow, "exact-source run may be cancelled"
    )
    _require("exact head" in workflow, "exact-head platform subjects are missing")
    _require(
        "ordered-parent merge" in workflow, "ordered-parent merge subjects are missing"
    )

    ci_root = ROOT / ".ci"
    if ci_root.exists():
        capsules = sorted(
            str(path.relative_to(ROOT)) for path in ci_root.glob("ui-native*")
        )
        _require(not capsules, f"ui.native patch capsules remain: {capsules}")

    journal = _read("apps/hepta-native/src/journal.rs")
    storage = _read("apps/hepta-native/src/journal_storage.rs")
    retirement = _read("apps/hepta-native/src/retirement.rs")
    source_contracts = {
        "journal-v7": 'const JOURNAL_SCHEMA_V7: &str = "hepta.native-operation-journal.v7";',
        "wal-v1": 'const WAL_SCHEMA: &str = "hepta.native-operation-wal.v1";',
        "active-index": "operation_index: HashMap<OperationKey, usize>",
        "wal-magic": 'const WAL_MAGIC: &[u8; 8] = b"HPTNWAL1";',
        "retirement-v3": 'const HEAD_SCHEMA: &str = "hepta.native-retirement.v3";',
        "retirement-index-v1": 'const INDEX_SCHEMA: &str = "hepta.native-retirement-index.v1";',
        "retirement-bucket-v1": 'const BUCKET_SCHEMA: &str = "hepta.native-retirement-index-bucket.v1";',
    }
    joined = "\n".join((journal, storage, retirement))
    for name, token in source_contracts.items():
        _require(token in joined, f"missing source contract {name}: {token}")

    budgets = _load_json("apps/hepta-native/STORAGE_BUDGETS.json")
    structural = budgets.get("structural")
    _require(isinstance(structural, dict), "storage structural budgets are missing")
    _require(
        budgets.get("status") == "provisional-unqualified",
        "budgets claim qualification",
    )
    _require(
        budgets.get("measurements") is None, "unreviewed measurements are embedded"
    )
    exact_constants = {
        "maxActiveRecords": "const MAX_OPERATION_RECORDS: usize = 4096;",
        "maxSnapshotBytes": "const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;",
        "maxWalBytes": "const MAX_WAL_BYTES: u64 = 4 * 1024 * 1024;",
        "maxWalFrameBytes": "const MAX_WAL_FRAME_BYTES: u64 = 128 * 1024;",
        "checkpointWalEntries": "const WAL_CHECKPOINT_ENTRIES: usize = 128;",
        "retirementSegmentEntries": "const SEGMENT_ENTRIES: usize = 1024;",
        "retirementSegmentBytes": "const SEGMENT_BYTES: u64 = 512 * 1024;",
        "retirementRecordBytes": "const RECORD_BYTES: u64 = 32 * 1024;",
        "retirementIndexBucketEntries": "const MAX_INDEX_BUCKET_ENTRIES: usize = 65_536;",
        "retirementIndexCacheEntries": "const MAX_INDEX_CACHE_ENTRIES: usize = 65_536;",
    }
    for key, token in exact_constants.items():
        _require(key in structural, f"storage budget {key} is missing")
        _require(token in joined, f"source constant for {key} drifted")

    check_native_platform_contracts()

    anchors: dict[str, str] = {}
    trees: dict[str, str] = {}
    for relative in STATE_FILES:
        state = _load_json(relative)
        anchor = state.get("implementationSourceSha")
        tree = state.get("implementationSourceTree")
        _require(
            isinstance(anchor, str) and SHA1_RE.fullmatch(anchor) is not None,
            f"{relative} lacks a valid implementationSourceSha",
        )
        _require(
            isinstance(tree, str) and SHA1_RE.fullmatch(tree) is not None,
            f"{relative} lacks a valid implementationSourceTree",
        )
        anchors[relative] = anchor
        trees[relative] = tree
        for key, value in _walk(state):
            if key in {
                "productionQualified",
                "deploymentQualified",
                "releaseAuthorized",
            }:
                _require(value is False, f"{relative} falsely sets {key}={value!r}")

    unique_anchors = sorted(set(anchors.values()))
    unique_trees = sorted(set(trees.values()))
    _require(len(unique_anchors) == 1, f"state anchors disagree: {anchors}")
    _require(len(unique_trees) == 1, f"state trees disagree: {trees}")
    implementation = unique_anchors[0]
    implementation_tree = unique_trees[0]
    _require(
        _git_success("cat-file", "-e", f"{implementation}^{{commit}}"),
        "implementation source commit is unavailable",
    )
    _require(
        _git_value("rev-parse", f"{implementation}^{{tree}}") == implementation_tree,
        "implementation source tree does not match its commit",
    )
    check_frozen_implementation(implementation)

    head = _git_value("rev-parse", "HEAD")
    tree = _git_value("rev-parse", "HEAD^{tree}")
    parents = (_git_value("show", "-s", "--format=%P", "HEAD") or "").split()
    return {
        "schema": "hepta.ui-native-source-evidence.v1",
        "status": "structural-pass",
        "implementationSourceSha": implementation,
        "implementationSourceTree": implementation_tree,
        "repositoryHead": head,
        "repositoryTree": tree,
        "orderedParents": parents,
        "workflow": ALLOWED_WORKFLOW,
        "readOnlyWorkflows": sorted(READ_ONLY_WORKFLOWS),
        "retiredWorkflowCount": len(FORBIDDEN_WORKFLOWS),
        "sourceContracts": sorted(source_contracts),
        "localCargoDependencyPaths": list(local_cargo_dependency_paths()),
        "limitations": [
            "structural evidence is not physical-platform acceptance",
            "performance budgets remain unqualified until measured artifacts are attached",
            "release flags remain false pending independent review",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit", type=Path)
    args = parser.parse_args()
    evidence = check_repository()
    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.emit is not None:
        args.emit.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
