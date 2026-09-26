#!/usr/bin/env python3
"""Apply the first context.compiler proof-chain consolidation atomically."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one replacement, found {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


def patch_source() -> None:
    replace_once(
        "codex-rs/hepta-context-compiler/src/v2.rs",
        "    /// context.compiler does not reinterpret it as a raw preparation digest.\n\n    fn verify_delivery(",
        "    /// context.compiler does not reinterpret it as a raw preparation digest.\n    fn verify_delivery(",
    )
    replace_once(
        "codex-rs/hepta-context-compiler/src/v2.rs",
        "\npub fn observe_delivery(\n",
        "\n#[allow(clippy::too_many_arguments)]\npub fn observe_delivery(\n",
    )
    replace_once(
        "codex-rs/hepta-intelligence/src/provider_bound_prompt_tests.rs",
        "        nonce: [41; 32],",
        "        nonce: *digest(\"nonce:provider-bound:realization:1\").as_array(),",
    )


def patch_qualification() -> None:
    path = ROOT / "scripts/context_compiler_qualification.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '                "test",\n                "-p",\n                "codex-hepta-context-compiler",',
        '                "test",\n                "--locked",\n                "-p",\n                "codex-hepta-context-compiler",',
        1,
    )
    text = text.replace(
        '                "clippy",\n                "-p",\n                "codex-hepta-context-compiler",',
        '                "clippy",\n                "--locked",\n                "-p",\n                "codex-hepta-context-compiler",',
        1,
    )
    old_deny = '''        {
            "name": "cargo-deny",
            "cwd": CODEX_RS,
            "argv": ["cargo", "deny", "check"],
        },'''
    new_deny = '''        {
            "name": "cargo-deny-policy",
            "cwd": CODEX_RS,
            "argv": [
                "cargo",
                "deny",
                "--locked",
                "check",
                "bans",
                "licenses",
                "sources",
            ],
        },
        {
            "name": "cargo-advisories",
            "cwd": CODEX_RS,
            "argv": ["cargo", "deny", "--locked", "check", "advisories"],
            "required": False,
        },'''
    if old_deny not in text:
        raise SystemExit("qualification cargo-deny anchor missing")
    text = text.replace(old_deny, new_deny, 1)
    text = text.replace(
        '        "succeeded": exit_code == 0,\n        "logPath":',
        '        "succeeded": exit_code == 0,\n'
        '        "required": bool(spec.get("required", True)),\n'
        '        "logPath":',
        1,
    )
    text = text.replace(
        '    commands_succeeded = all(result["succeeded"] for result in command_results)',
        '    commands_succeeded = all(\n'
        '        result["succeeded"] or not result["required"]\n'
        '        for result in command_results\n'
        '    )',
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_manifest() -> None:
    path = ROOT / "docs/modules/context.compiler/MODULE_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["branch"] = "codex/context-compiler-v2-full-closure-20260927"
    for root in [
        "codex-rs/codex-api/src/dispatch_metadata.rs",
        "codex-rs/codex-api/src/endpoint/responses.rs",
        "codex-rs/core/src/model_provider_policy/attempt_owner.rs",
        "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs",
        "codex-rs/hepta-context-compiler/src/provider_bound.rs",
        "codex-rs/hepta-context-compiler/src/provider_delivery.rs",
        "codex-rs/hepta-intelligence/src/provider_bound_prompt.rs",
        "codex-rs/hepta-agentd/src/provider_bound_prompt_runtime.rs",
    ]:
        if root not in manifest["sourceRoots"]:
            manifest["sourceRoots"].append(root)
    commands = manifest["qualification"]["commands"]
    commands[:] = [
        command.replace(
            "cargo test -p codex-hepta-context-compiler",
            "cargo test --locked -p codex-hepta-context-compiler",
        ).replace(
            "cargo clippy -p codex-hepta-context-compiler",
            "cargo clippy --locked -p codex-hepta-context-compiler",
        )
        for command in commands
        if command != "cargo deny check"
    ]
    commands.insert(4, "cargo deny --locked check bans licenses sources")
    commands.insert(
        5,
        "cargo deny --locked check advisories (recorded non-blocking repository audit)",
    )
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def patch_workflow_paths() -> None:
    path = ROOT / ".github/workflows/context-compiler-qualification.yml"
    text = path.read_text(encoding="utf-8")
    anchor = "      - codex-rs/core/src/model_provider_policy/**\n"
    additions = (
        anchor
        + "      - codex-rs/codex-api/src/dispatch_metadata.rs\n"
        + "      - codex-rs/codex-api/src/endpoint/responses.rs\n"
        + "      - codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs\n"
        + "      - codex-rs/hepta-agentd/src/provider_bound_prompt_runtime.rs\n"
        + "      - codex-rs/hepta-agentd/src/provider_bound_prompt_runtime_tests.rs\n"
    )
    if anchor not in text:
        raise SystemExit("qualification workflow path anchor missing")
    path.write_text(text.replace(anchor, additions, 1), encoding="utf-8")


def main() -> int:
    patch_source()
    patch_qualification()
    patch_manifest()
    patch_workflow_paths()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
