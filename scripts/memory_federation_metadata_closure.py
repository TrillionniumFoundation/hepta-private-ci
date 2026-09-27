#!/usr/bin/env python3
"""Close memory.federation generated metadata inputs."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_generated_runtime_parent() -> None:
    path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime.rs"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\nconst PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs\(2\);\n"
        r"const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;\n"
        r"const PRODUCT_FEDERATION_PURPOSE: &\[u8\] = b\"hepta\.cognitive\.federated-recall\.product\.v2\";\n"
        r"static PRODUCT_FEDERATION_ATTEMPT_SEQUENCE: AtomicU64 = AtomicU64::new\(1\);\n"
    )
    text, count = pattern.subn("\n", text, count=1)
    if count != 1:
        raise SystemExit(f"generated runtime legacy constants drift: {count}")
    path.write_text(text, encoding="utf-8")


def patch_state_sources() -> None:
    path = ROOT / "scripts/hepta-memory-federation-state.py"
    text = path.read_text(encoding="utf-8")
    anchor = '    ".github/workflows/memory-federation-v2-final-verify.yml",\n'
    additions = (
        anchor
        + '    ".github/workflows/memory-federation-full-closure-bootstrap.yml",\n'
        + '    "scripts/memory_federation_core_closure.py",\n'
        + '    "scripts/memory_federation_runtime_closure.py",\n'
        + '    "scripts/memory_federation_metadata_closure.py",\n'
    )
    if additions not in text:
        if text.count(anchor) != 1:
            raise SystemExit("memory federation state source anchor drift")
        text = text.replace(anchor, additions, 1)
    path.write_text(text, encoding="utf-8")


def patch_profile() -> None:
    path = ROOT / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    def visit(value):
        if isinstance(value, dict):
            if value.get("module") == "memory.federation" or value.get("moduleId") == "memory.federation" or value.get("id") == "memory.federation":
                return value
            for child in value.values():
                found = visit(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found is not None:
                    return found
        return None

    profile = visit(data)
    if profile is None:
        raise SystemExit("memory.federation implementation profile not found")
    profile["runtimeDocuments"] = [
        "docs/modules/memory.federation/TECHNICAL.md",
        "docs/modules/memory.federation/V2_HARDENING.md",
        "docs/modules/memory.federation/WIRE_PROTOCOL_V1.md",
        "docs/modules/memory.federation/THREAT_MODEL.md",
        "docs/modules/memory.federation/OPERATIONS.md",
        "docs/modules/memory.federation/sequence.mmd",
    ]
    profile["remainingWork"] = [
        "Physical two-real-host authenticated transport and partition qualification remains external.",
        "Target-host capacity, latency, overload and backpressure qualification remains external.",
        "Independent semantic/security acceptance and operator canary/promotion/release remain external.",
    ]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    patch_generated_runtime_parent()
    patch_state_sources()
    patch_profile()
    print("memory.federation metadata closure applied")


if __name__ == "__main__":
    main()
