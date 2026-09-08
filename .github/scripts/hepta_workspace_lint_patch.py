#!/usr/bin/env python3
"""Remove stale dead-code lint formalism without weakening workspace lints."""

from __future__ import annotations

from pathlib import Path


REGISTRY = Path("codex-rs/core/src/tools/registry.rs")
BEDROCK = Path(
    "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs"
)


def replace_exact(text: str, old: str, new: str, *, label: str, count: int = 1) -> str:
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{label}: expected {count} exact matches, found {actual}")
    return text.replace(old, new, count)


def patch_registry() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        '    #[expect(dead_code, reason = "retained tool cancellation metadata query")]\n',
        "",
        label="trait cancellation lint expectation",
    )
    wrapper = '''
    pub(crate) fn waits_for_runtime_cancellation(&self, name: &ToolName) -> Option<bool> {
        let tool = self.tool(name)?;
        Some(tool.waits_for_runtime_cancellation())
    }
'''
    text = replace_exact(
        text,
        wrapper,
        "",
        label="unused ToolRegistry cancellation wrapper",
    )
    REGISTRY.write_text(text, encoding="utf-8")


def patch_bedrock() -> None:
    text = BEDROCK.read_text(encoding="utf-8")
    top_level_expect = '''#[expect(
    dead_code,
    reason = "Bedrock account endpoints are not yet routed by the stable protocol"
)]
'''
    text = replace_exact(
        text,
        top_level_expect,
        "",
        label="top-level Bedrock lint expectations",
        count=4,
    )
    BEDROCK.write_text(text, encoding="utf-8")


def main() -> None:
    patch_registry()
    patch_bedrock()


if __name__ == "__main__":
    main()
