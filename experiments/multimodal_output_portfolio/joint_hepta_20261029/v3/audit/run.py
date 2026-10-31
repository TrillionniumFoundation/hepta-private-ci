"""Run the independent, read-only final evidence audit from the repository root."""

import argparse
import json
from pathlib import Path
import resource
import time
import traceback

import torch

from .core import Audit, sha
from . import matrix, diagnostic, adjacent


def run(output, *, partial=False, sections=("matrix", "diagnostic", "text", "native"),
        rustc, model_directory, tokenizer_python):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    v3 = Path(__file__).resolve().parent.parent
    selected = v3/"evidence/matrix_frozen_20261030/seed-17-width-32/dual.joint.dynamic/MODEL.pt"
    torch.set_num_threads(1)
    started = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_SELF)
    results = {}
    with (output/"TRAJECTORY_AUDIT.jsonl").open("w") as log:
        audit = Audit(v3, log)
        runners = {
            "matrix": lambda: matrix.run(audit, v3, partial=partial),
            "diagnostic": lambda: diagnostic.run(audit, v3, selected),
            "text": lambda: adjacent.text_run(audit, v3, selected, model_directory=model_directory, tokenizer_python=tokenizer_python),
            "native": lambda: adjacent.native_run(audit, v3, selected, rustc=rustc),
        }
        for section in sections:
            try:
                results[section] = runners[section]()
            except Exception as error:
                audit.errors.append({"check": "section_execution", "section": section,
                                     "error": repr(error), "traceback": traceback.format_exc()})
            log.flush()
            progress = {"completed_sections": list(results), "checks": sum(audit.counts.values()),
                        "trajectories": audit.counts["trajectories"], "errors": len(audit.errors),
                        "wall_seconds": time.perf_counter()-started}
            (output/"PROGRESS.json").write_text(json.dumps(progress, indent=2)+"\n")
            print(json.dumps({"section": section, **progress}), flush=True)
        roles = sorted(audit.identities)
        overlap = {}
        for index, left in enumerate(roles):
            for right in roles[index+1:]:
                identities = audit.identities[left] & audit.identities[right]
                inputs = audit.inputs[left] & audit.inputs[right]
                overlap[left+"__"+right] = {"source_overlap": len(identities), "public_input_overlap": len(inputs)}
                audit.check(not identities and not inputs, "source_and_input_roles_disjoint", left+"__"+right)
        after = resource.getrusage(resource.RUSAGE_SELF)
        report = {"schema": "hepta.v3.independent-evidence-audit.v1", "passed": not audit.errors,
                  "partial": partial, "sections_requested": list(sections), "sections": results,
                  "audit_source_sha256": {p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                  "checks_by_kind": dict(audit.counts), "errors": audit.errors,
                  "source_roles": {role: {"sources": len(audit.identities[role]), "inputs": len(audit.inputs[role]),
                                         "namespaces": sorted({x[0] for x in audit.identities[role]})} for role in roles},
                  "role_overlaps": overlap, "max_independent_utility_absolute_error": audit.max_utility_error,
                  "trajectory_audit_sha256": sha(output/"TRAJECTORY_AUDIT.jsonl"),
                  "wall_seconds": time.perf_counter()-started,
                  "self_cpu_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                  "scope": "read-only retained-data/weight/source reconciliation; independently decoded media and utility arithmetic",
                  "limitations": ["No claim that physical CPU/wall timings are exogenous or have a modelled direct gradient.",
                                  "Recorded counters are reconciled; external physical time measurement is not independently reconstructed.",
                                  "Training and optimizer updates are not replayed; actual final parameter groups and retained rollout identities are checked.",
                                  "Synthetic namespaces and public document module roles are disjoint; foundation-model pretraining may overlap.",
                                  "No general NDU optimum, natural four-modality qualification, human semantic rating or production-owner integration is certified.",
                                  "Native replay checks local declared profile; no automatic external witness service or hardware power-loss qualification."]}
        (output/"AUDIT.json").write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+"\n")
        lines = ["# Independent final evidence audit", "", f"Result: {'PASS' if report['passed'] else 'FAIL'}.", "",
                 f"Retained trajectories reopened: {audit.counts['trajectories']}; failures retained: {audit.counts['failures_retained']}.",
                 f"Maximum independent media utility absolute difference: {audit.max_utility_error:.12g} (tolerance 2e-7).", "",
                 "The final return is reconstructed from TRAJECTORY events plus SEAL_COST, then checked against evaluation/diagnostic rows.",
                 "Actual PNG/WAV/GIF/text files are decoded independently; source namespace/id reconstructs the registered target.", "",
                 "## Sections", ""]
        lines += [f"- {name}: " + json.dumps(value, sort_keys=True) for name, value in results.items()]
        lines += ["", "## Limits", ""] + ["- "+limit for limit in report["limitations"]]
        if audit.errors:
            lines += ["", "## Errors", "", "```json", json.dumps(audit.errors, indent=2), "```"]
        (output/"AUDIT.md").write_text("\n".join(lines)+"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--sections", nargs="+", choices=("matrix", "diagnostic", "text", "native"),
                        default=("matrix", "diagnostic", "text", "native"))
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--tokenizer-python", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output, partial=args.partial, sections=args.sections, rustc=args.rustc,
                 model_directory=args.model_directory, tokenizer_python=args.tokenizer_python)
    print(json.dumps({"audit_passed": result["passed"], "errors": len(result["errors"])}))
    raise SystemExit(0 if result["passed"] else 1)
