#!/usr/bin/env python3
"""Verify Lane B human documents against the machine truth."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
README = ROOT / "qualification/lane-b/README.md"
NATIVE = ROOT / "qualification/lane-b/LANE_B_NATIVE_CLOSURE.md"
COMPOSITION = ROOT / "docs/readiness/LANE_B_RUNTIME_COMPOSITION.md"
FORBIDDEN = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE)
MODULES = ["runtime.supervisor","runtime.fleet","runtime.agentd","runtime.codex","inference.control","inference.worker","automation.taskflow","channel.matrix","browser.servo","ui.control","ui.native"]
COMPOSITION_SECTIONS = [
    "## 1. Purpose and truth boundary", "## 2. Canonical module set",
    "## 3. Runtime and process topology", "## 4. Identity tuple",
    "## 5. Startup order", "## 6. Normal request path",
    "## 7. Automation path", "## 8. Matrix path", "## 9. Browser path",
    "## 10. UI path", "## 11. Cancellation and deadline semantics",
    "## 12. Backpressure and resource exhaustion", "## 13. Fault-state matrix",
    "## 14. Shutdown and rollback order",
    "## 15. Module maturity at the current repository candidate",
    "## 16. Evidence package required for activation", "## 17. Acceptance rule",
]

class Invalid(ValueError): pass

def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out: raise Invalid(f"duplicate JSON key: {key}")
        out[key] = value
    return out

def load(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc: raise Invalid(f"{path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict): raise Invalid(f"{path.relative_to(ROOT)} root object")
    return value

def need(condition: bool, message: str) -> None:
    if not condition: raise Invalid(message)

def render_native(truth: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for row in truth["modules"]:
        for op in row["operations"]: counts[op["state"]] = counts.get(op["state"], 0) + 1
    lines: list[str] = []
    add = lines.append
    add("# Lane B native implementation closure status"); add("")
    add("**Lane:** `LANE-B-RUNTIME`  ")
    add(f"**Lineage anchor:** `{truth['lineageAnchor']['commit']}` / tree `{truth['lineageAnchor']['tree']}`  ")
    add("**Exact candidate:** the clean Git `HEAD` checked by CI; no document embeds its own future commit hash  ")
    add("**Machine truth:** `qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json`  ")
    add("**Test traceability:** `qualification/lane-b/LANE_B_TEST_TRACEABILITY.json`  ")
    add("**Status:** repository-controlled mapping and documentation gaps closed; deployment and independent external evidence remain open")
    add(""); add("## 1. Review model"); add("")
    add("The machine truth is authoritative for module ownership, implementation roots, operation state, native source anchors, delegation, build targets, test identifiers and residual gate class. This Markdown is a generated projection. Each module-specific `IMPLEMENTATION_MAP.json` carries the exact source and test mapping; canonical `TECHNICAL.md` and execution dossiers retain target semantics.")
    add("")
    add("`implemented` means the repository-controlled operation has a current native boundary and executable test surface. `implemented_partial` means a real implementation exists but target deployment or part of the product path remains external. `delegated_partial` means the module deliberately calls another registered owner instead of duplicating it. None of these states proves a remote effect, real model/device execution, deployed UI, target-host timing or independent acceptance.")
    add(""); add("## 2. Closed repository-controlled surface"); add("")
    add(f"- Modules: **{len(truth['modules'])}**; design operations: **{sum(len(row['operations']) for row in truth['modules'])}**.")
    add(f"- `implemented`: **{counts.get('implemented',0)}**; `implemented_partial`: **{counts.get('implemented_partial',0)}**; `delegated_partial`: **{counts.get('delegated_partial',0)}**.")
    add("- `planned`, unclassified and source-inventing operations: **0**.")
    add("- Every operation has a source/delegation disposition, build target and test IDs; every module has a generated implementation map.")
    add(""); add("## 3. Module closure matrix"); add("")
    add("| Module | Maturity | Operation disposition | Current repository boundary |")
    add("|---|---|---|---|")
    for row in truth["modules"]:
        ops = ", ".join(f"`{op['designOperation']}`={op['state']}" for op in row["operations"])
        add(f"| `{row['module']}` | `{row['maturity']}` | {ops} | {row['stateDisposition']} |")
    add(""); add("## 4. Module maps and remaining external gates"); add("")
    for row in truth["modules"]:
        add(f"### `{row['module']}`"); add("")
        add(f"Implementation map: `docs/modules/{row['module']}/IMPLEMENTATION_MAP.json`."); add("")
        add(f"Terminal observer boundary: {row['terminalObserverDisposition']}"); add("")
        for gap in row["residualGaps"]: add(f"- `{gap['class']}` — {gap['gap']}")
        add("")
    add("## 5. Cross-module closure rule"); add("")
    add("Repository-controlled closure requires all 39 operations to be present, every owner entrypoint to resolve inside its registered implementation roots, every delegated callee to name a registered module and real source symbol, every operation to match test traceability, every per-module map to equal its machine projection, and exact-head plus deterministic synthetic-merge governance checks to pass.")
    add("")
    add("Agentd delegation is intentionally represented separately from Codex implementation. Canonical owner roots are not widened merely because Agentd embeds App Server or because the Codex alias resolves to the existing `app-server` and `core` implementation roots.")
    add(""); add("## 6. External gates retained"); add("")
    add("The repository does not self-certify deployed Supervisor/Agentd identities, real host capacity, real provider/model/device use, Matrix homeserver delivery, Servo network effects, deployed Web/native applications, target-host performance or faults, hardware safety, future-window efficacy, operator acceptance, signing, selection, promotion or release. These remain explicit external evidence rather than hidden repository blockers.")
    add(""); add("## 7. Verification"); add(""); add("```bash")
    add("python3 scripts/hepta-lane-b-truth.py self-test")
    add("python3 -m unittest scripts/test_hepta_lane_b_truth.py")
    add("python3 scripts/hepta-lane-b-truth.py verify")
    add("python3 scripts/hepta-lane-b-docs.py verify")
    add("```"); add("")
    add("The commands verify repository structure and mappings at one clean candidate; they issue no external authority.")
    return "\n".join(lines) + "\n"

def verify_readme() -> None:
    text = README.read_text(encoding="utf-8")
    need(text.startswith("# Lane B runtime implementation closure\n"), "README title")
    need(not FORBIDDEN.search(text), "README unresolved marker")
    for name in ("LANE_B_CANDIDATE_MANIFEST.json","LANE_B_IMPLEMENTATION_TRUTH.json","LANE_B_TEST_TRACEABILITY.json","LANE_B_NATIVE_CLOSURE.md","LANE_B_RUNTIME_COMPOSITION.md","IMPLEMENTATION_MAP.json"):
        need(name in text, f"README missing {name}")

def verify_composition(truth: dict[str, Any]) -> None:
    text = COMPOSITION.read_text(encoding="utf-8")
    need(text.startswith("# Lane B runtime composition and failure semantics\n"), "composition title")
    need(not FORBIDDEN.search(text), "composition unresolved marker")
    need(len(text.encode("utf-8")) >= 8_000, "composition too small")
    positions = [text.find(section) for section in COMPOSITION_SECTIONS]
    need(all(position >= 0 for position in positions), "composition missing section")
    need(positions == sorted(positions), "composition section order")
    anchor = truth["lineageAnchor"]
    need(anchor["commit"] in text and anchor["tree"] in text, "composition lineage")
    for row in truth["modules"]:
        need(f"`{row['module']}`" in text, f"composition missing {row['module']}")
        need(f"`{row['module']}` |" in text, f"composition maturity table missing {row['module']}")
    for phrase in ("exact candidate","terminal observer","indeterminate","rollback","independent acceptance","external gates"):
        need(phrase.lower() in text.lower(), f"composition missing {phrase}")

def verify() -> int:
    truth = load(TRUTH)
    need(truth.get("moduleOrder") == MODULES, "truth module order")
    actual = NATIVE.read_text(encoding="utf-8")
    need(actual == render_native(truth), "native closure projection drift")
    need(not FORBIDDEN.search(actual), "native closure unresolved marker")
    verify_readme(); verify_composition(truth)
    print(json.dumps({"status":"PASS_HEPTA_LANE_B_DOCUMENTS","modules":11,"nativeProjectionExact":True,"compositionSections":17,"targetDesignImplementationClosed":False,"productExecutionProved":False}, sort_keys=True))
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=["verify"]); parser.parse_args()
    try: return verify()
    except Invalid as exc: raise SystemExit(f"FAIL_HEPTA_LANE_B_DOCUMENTS: {exc}") from exc

if __name__ == "__main__": raise SystemExit(main())
