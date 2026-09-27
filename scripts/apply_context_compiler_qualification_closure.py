#!/usr/bin/env python3
"""Bind qualification to canonical current state and V3 recovery evidence."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one qualification anchor, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


qualification = "scripts/context_compiler_qualification.py"
replace(
    qualification,
    '''MANIFEST = ROOT / "docs/modules/context.compiler/MODULE_MANIFEST.json"
TRUTH_FILES = (
    MANIFEST,
    ROOT / "docs/modules/context.compiler/TECHNICAL.md",
    ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json",
    ROOT / "qualification/module-execution-dossiers/detail/context.compiler.md",
)
SOURCE_EVIDENCE_FILES = (
    ROOT / "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    ROOT / "codex-rs/hepta-context-compiler/src/v2.rs",
    ROOT / "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    ROOT / "codex-rs/ext/hepta-prompt/src/exact_body.rs",
    ROOT / "codex-rs/ext/hepta-prompt/src/lib.rs",
    ROOT / "codex-rs/codex-api/src/encoded_body_observer.rs",
    ROOT / "codex-rs/codex-api/src/endpoint/responses.rs",
    ROOT / "codex-rs/core/src/client.rs",
)
''',
    '''MANIFEST = ROOT / "docs/modules/context.compiler/CURRENT_STATE.json"
TRUTH_FILES = (
    MANIFEST,
    ROOT / "docs/modules/context.compiler/MODULE_MANIFEST.json",
    ROOT / "docs/modules/context.compiler/TECHNICAL.md",
    ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json",
    ROOT / "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md",
    ROOT / "qualification/module-execution-dossiers/detail/context.compiler.md",
)
SOURCE_EVIDENCE_FILES = (
    ROOT / "codex-rs/hepta-context-compiler/src/lib.rs",
    ROOT / "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    ROOT / "codex-rs/hepta-context-compiler/src/v2.rs",
    ROOT / "codex-rs/hepta-context-compiler/src/v2/delivery_evidence.rs",
    ROOT / "codex-rs/hepta-context-compiler/src/v2/preparation_archive.rs",
    ROOT / "codex-rs/hepta-context-compiler/src/v2/recovery.rs",
    ROOT / "codex-rs/hepta-context-compiler/src/v2/redaction.rs",
    ROOT / "codex-rs/hepta-prompt-registry/src/context_authority.rs",
    ROOT / "codex-rs/hepta-intelligence/src/lib.rs",
    ROOT / "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    ROOT / "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery/framing_json.rs",
    ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery/registry_race_tests.rs",
    ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery/runtime_tests.rs",
    ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery/terminal_state.rs",
    ROOT / "codex-rs/hepta-agentd/src/exact_context_delivery/tokenizer_io.rs",
    ROOT / "codex-rs/codex-api/src/context_slot.rs",
    ROOT / "codex-rs/codex-api/src/encoded_body_observer.rs",
    ROOT / "codex-rs/codex-api/src/endpoint/responses.rs",
    ROOT / "codex-rs/core/src/client.rs",
    ROOT / "codex-rs/ext/hepta-prompt/src/exact_body.rs",
)
''',
)
replace(
    qualification,
    '''        "codex-hepta-context-compiler",
        "codex-hepta-intelligence",
        "codex-hepta-prompt-extension",
        "codex-hepta-agentd",
''',
    '''        "codex-hepta-context-compiler",
        "codex-hepta-prompt-registry",
        "codex-hepta-prompt-optimizer",
        "codex-hepta-intelligence",
        "codex-hepta-prompt-extension",
        "codex-hepta-agentd",
''',
)
replace(
    qualification,
    '''        {
            "name": "codex-api-client-tests",
''',
    '''        {
            "name": "legacy-context-compatibility-tests",
            "cwd": CODEX_RS,
            "argv": [
                "cargo", "test", "--locked",
                "-p", "codex-hepta-intelligence",
                "-p", "codex-hepta-agentd",
                "--features", "legacy-prompt-context-v1",
            ],
        },
        {
            "name": "codex-api-client-tests",
''',
)
replace(
    qualification,
    '''                "--all-targets",
                "--",
''',
    '''                "--all-targets",
                "--all-features",
                "--",
''',
)

execution = "scripts/context_compiler_execution.py"
replace(
    execution,
    '''        {"name": "exact-body-regressions", "cwd": legacy.CODEX_RS,
         "argv": ["just", "test", "--locked", "-p", "codex-hepta-prompt-extension", "--lib", "exact_body"],
         "minimumTests": 8},
''',
    '''        {"name": "exact-body-regressions", "cwd": legacy.CODEX_RS,
         "argv": ["just", "test", "--locked", "-p", "codex-hepta-prompt-extension", "--lib", "exact_body"],
         "minimumTests": 8},
        {"name": "v3-product-regressions", "cwd": legacy.CODEX_RS,
         "argv": ["just", "test", "--locked", "-p", "codex-hepta-intelligence", "prompt_product_v3"],
         "minimumTests": 4},
        {"name": "crash-recovery-regressions", "cwd": legacy.CODEX_RS,
         "argv": ["just", "test", "--locked", "-p", "codex-hepta-agentd", "registry_race_tests"],
         "minimumTests": 5},
''',
)
