"""Post hoc descriptive readout joins; never a confirmation efficacy gate.

Only standard-library modules are imported. Raw JSON arrays are streamed one
episode at a time. The join rule was previously reported on DEV: exact task
successor continuity, no completion/failure, unchanged fitted teacher belief,
and a recorded fresh event or recovery. No model is loaded or changed.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import time


STUDY = Path(__file__).resolve().parents[1]
REPO = STUDY.parents[2]
CANDIDATES = tuple(f"{family}__{mode}" for family in (
    "ordinary_bank", "clocked_bank", "first_passage_bank")
    for mode in ("structured_on", "impulse_on"))
KINDS = ("event", "recovery")
SPLITS = ("iid", "ood")
SCOPE = ("Post hoc descriptive trained-readout audit. Event, elapsed time, task flags, "
         "bank features and selected trajectories can change together. This is not "
         "maximum recoverable information, a randomized event/reset intervention, "
         "an independent task-utility contrast or an efficacy gate.")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


def episodes(path):
    """Read the complete gzip JSON array without retaining unrelated episodes."""
    decoder, buffer, eof, state = json.JSONDecoder(), "", False, "open"
    with gzip.open(path, "rt") as stream:
        while True:
            buffer = buffer.lstrip()
            if not buffer:
                if eof:
                    if state == "done":
                        return
                    raise ValueError("incomplete raw episode array")
                buffer, eof = stream.read(1 << 17), False
                eof = not buffer
                continue
            if state == "done":
                raise ValueError("trailing content after raw episode array")
            if state == "open":
                if buffer[0] != "[":
                    raise ValueError("raw episodes must be a JSON array")
                buffer, state = buffer[1:], "first"
                continue
            if state in ("first", "separator") and buffer[0] == "]":
                buffer, state = buffer[1:], "done"
                continue
            if state == "separator":
                if buffer[0] != ",":
                    raise ValueError("missing episode separator")
                buffer, state = buffer[1:], "item"
                continue
            try:
                episode, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                extra = stream.read(1 << 17)
                if not extra:
                    raise
                buffer += extra
                continue
            if not isinstance(episode, dict):
                raise ValueError("episode is not an object")
            buffer, state = buffer[end:], "separator"
            yield episode


def summarize(pairs):
    n = len(pairs)
    before = math.fsum(p["before_squared_error"] for p in pairs)
    after = math.fsum(p["after_squared_error"] for p in pairs)
    change = math.fsum(p["after_squared_error"] - p["before_squared_error"] for p in pairs)
    return dict(pairs=n, before_mse=before / n if n else None,
                after_mse=after / n if n else None,
                paired_change=change / n if n else None,
                sum_before_squared_error=before, sum_after_squared_error=after,
                sum_paired_change=change)


def audit_split(path, fit, split, worlds):
    groups = {(candidate, kind): [] for candidate in CANDIDATES for kind in KINDS}
    counts = {key: Counter() for key in groups}
    seen = {candidate: set() for candidate in CANDIDATES}
    raw_count = 0
    for episode in episodes(path):
        raw_count += 1
        if episode["fit"] != fit or episode["split"] != split:
            raise ValueError("raw episode belongs to a different fit/split")
        candidate = episode["candidate"]
        if candidate not in seen or episode["controller"] != "value":
            continue
        if episode["world"] in seen[candidate]:
            raise ValueError("duplicated selected episode")
        seen[candidate].add(episode["world"])
        decisions = episode["decisions"]
        for position, before in enumerate(decisions):
            event = before["event"]
            if event["event"] and event["recovery"]:
                raise ValueError("simultaneous fresh event and recovery")
            for kind in KINDS:
                if not event[kind]:
                    continue
                count = counts[candidate, kind]
                count["recorded_transitions"] += 1
                expected = (before["latent_index"] < 15 <= before["latent_after"] if kind == "event"
                            else before["latent_after"] < 15 <= before["latent_index"])
                if not expected:
                    raise ValueError("event/recovery flag disagrees with latent transition")
                if position + 1 == len(decisions):
                    count["no_next_decision"] += 1
                    continue
                after = decisions[position + 1]
                failed = []
                if before["after"] != after["state"]:
                    failed.append("task_state_discontinuity")
                if before["completion"] is not None or (before["content"] is not None
                                                         and "failure" in before["content"]):
                    failed.append("completion_or_failure")
                if before["teacher_belief"] != after["teacher_belief"]:
                    failed.append("teacher_belief_changed")
                if failed:
                    count["excluded_pairs"] += 1
                    count.update(failed)
                    continue
                if before["latent_after"] != after["latent_index"]:
                    raise ValueError("joined decisions have discontinuous latent state")
                teacher = before["teacher_belief"]
                predictions = [r["scores"]["belief"] for r in (before, after)]
                if not all(math.isfinite(p) and 0 <= p <= 1 for p in [teacher, *predictions]):
                    raise ValueError("invalid belief")
                errors = [(p - teacher) ** 2 for p in predictions]
                if any(abs(e - r["belief_squared_error"]) > 1e-15
                       for e, r in zip(errors, (before, after))):
                    raise ValueError("readout error differs from recorded diagnostic")
                groups[candidate, kind].append(dict(world=episode["world"], decision=position,
                    teacher_belief=teacher, before_belief=predictions[0], after_belief=predictions[1],
                    before_squared_error=errors[0], after_squared_error=errors[1],
                    action=before["action"], latent_before=before["latent_index"],
                    latent_after=before["latent_after"],
                    elapsed_change=after["state"]["elapsed"] - before["state"]["elapsed"],
                    changed_task_fields=sorted(k for k in before["state"]
                                              if before["state"][k] != after["state"][k])))
    if any(len(v) != worlds for v in seen.values()) or len({tuple(sorted(v)) for v in seen.values()}) != 1:
        raise ValueError("missing or mismatched selected candidate worlds")
    rows, retained = [], []
    for (candidate, kind), pairs in groups.items():
        if candidate.startswith("ordinary_") and counts[candidate, kind]["recorded_transitions"]:
            raise ValueError("ordinary comparator recorded an event/recovery")
        row = dict(fit=fit, split=split, candidate=candidate, transition=kind,
                   episodes=worlds, **summarize(pairs), join_counts=dict(counts[candidate, kind]),
                   actions=dict(Counter(str(p["action"]) for p in pairs)),
                   changed_task_fields=dict(Counter(k for p in pairs for k in p["changed_task_fields"])))
        rows.append(row)
        retained.extend(dict(candidate=candidate, split=split, transition=kind, **p) for p in pairs)
    return dict(raw_episodes_streamed=raw_count, selected_episodes=worlds * len(CANDIDATES),
                rows=rows, joined_pairs=retained)


def collect_fit(root, output, fit, seal, seal_sha, source_sha):
    folder = root / f"fit_{fit}"
    paths = [folder / "STARTED.json", folder / "FINISHED.json",
             root / "process_receipts" / f"fit_{fit}.json",
             *(folder / f"{split}_episodes.json.gz" for split in SPLITS)]
    if not paths[1].exists() or not paths[2].exists():
        return None
    hashes = {str(p.resolve()): sha(p) for p in paths}
    started, finished, process = [json.loads(p.read_text()) for p in paths[:3]]
    if (any(r["fit"] != fit for r in (started, finished, process)) or process["returncode"] != 0
            or process["stage"] != "confirm" or started["model_freeze_sha256"] != seal_sha):
        raise ValueError("successful confirmation receipt and matching sealed models required")
    target = output / f"fit_{fit}.json"
    if target.exists():
        result = json.loads(target.read_text())
        if result["input_sha256"] != hashes or result["script_sha256"] != source_sha:
            raise ValueError("cached audit input or source changed")
        return result
    cpu, wall = time.process_time(), time.perf_counter()
    result = dict(fit=fit, script_sha256=source_sha, model_seal_sha256=seal_sha,
                  input_sha256=hashes, rows=[], joined_pairs=[], raw_episodes_streamed=0,
                  selected_episodes=0)
    for split, path in zip(SPLITS, paths[3:]):
        part = audit_split(path, fit, split, seal["protocol"][f"{split}_worlds"])
        for key in ("rows", "joined_pairs"):
            result[key].extend(part[key])
        for key in ("raw_episodes_streamed", "selected_episodes"):
            result[key] += part[key]
    if hashes != {str(p.resolve()): sha(p) for p in paths}:
        raise ValueError("confirmation inputs changed during audit")
    result.update(analysis_cpu_seconds=time.process_time()-cpu,
                  analysis_wall_seconds=time.perf_counter()-wall,
                  finished_utc=datetime.now(timezone.utc).isoformat())
    write_json(target, result)
    print(json.dumps(dict(fit=fit, joined_pairs=len(result["joined_pairs"]),
                         selected_episodes=result["selected_episodes"])), flush=True)
    return result


def finalize(results, output, evidence, seal, seal_sha, source_sha):
    if [r["fit"] for r in results] != seal["fits"]:
        raise ValueError("final report requires all registered fits with successful receipts")
    rows = [row for result in results for row in result["rows"]]
    pooled = []
    for split in SPLITS:
        for candidate in CANDIDATES:
            for kind in KINDS:
                group = [r for r in rows if (r["split"], r["candidate"], r["transition"]) ==
                         (split, candidate, kind)]
                n = sum(r["pairs"] for r in group)
                nonempty = [r for r in group if r["pairs"]]
                row = dict(split=split, candidate=candidate, transition=kind,
                           pairs=n, contributing_fits=len(nonempty), registered_fits=len(group),
                           episodes=sum(r["episodes"] for r in group),
                           per_fit_counts={str(r["fit"]): r["pairs"] for r in group})
                for field, total in (("before_mse", "sum_before_squared_error"),
                                     ("after_mse", "sum_after_squared_error"),
                                     ("paired_change", "sum_paired_change")):
                    row[field] = math.fsum(r[total] for r in group) / n if n else None
                    row["equal_nonempty_fit_" + field] = statistics.fmean(r[field] for r in nonempty) if nonempty else None
                row["between_nonempty_fit_change_sd"] = statistics.stdev(r["paired_change"] for r in nonempty) if len(nonempty) > 1 else None
                pooled.append(row)
    report = dict(schema="digital-actual-readout-descriptive-audit-v1", scope=SCOPE,
                  declared_after_confirmation_started=True, no_new_significance_or_efficacy_gates=True,
                  completed_fits=seal["fits"], candidates=CANDIDATES, splits=SPLITS, controller="value",
                  script_sha256=source_sha, model_seal_sha256=seal_sha,
                  main_sources_sha256=seal["source_sha256"],
                  rule="Exact after==next.state; completion is None and no content failure; exact unchanged teacher belief; recorded event/recovery; latent continuity asserted.",
                  exclusion_counts_are_nonexclusive=True,
                  selected_episodes=sum(r["selected_episodes"] for r in results),
                  raw_episodes_streamed=sum(r["raw_episodes_streamed"] for r in results),
                  raw_input_sha256={k:v for result in results for k,v in result["input_sha256"].items()},
                  per_fit_audit_files={str(r["fit"]): dict(path=str(output / f"fit_{r['fit']}.json"),
                      sha256=sha(output / f"fit_{r['fit']}.json")) for r in results},
                  pooled=pooled, per_fit=rows)
    evidence.mkdir(parents=True, exist_ok=True)
    json_path = evidence / "ACTUAL_READOUT_REVIEW.json"
    write_json(json_path, report)
    lines = ["# Actual-task before/after trained-readout audit", "", SCOPE, "",
        "All 16 registered fits have successful confirmation process and FINISHED receipts. "
        "The audit covers both splits, all six non-CPU cell candidates and the value controller. "
        "It retains per-fit counts and paired observations; no model, primary contrast, threshold or protocol was changed.", "",
        "## Join and estimand", "",
        "Consecutive decisions are joined only when the complete successor task state exactly equals "
        "the next state, the transition has no READ completion or failure, fitted teacher belief is "
        "exactly unchanged, and the recorded transition is a fresh event or recovery. Latent-state "
        "continuity and stored squared errors are checked. Before/after squared error uses the same "
        "teacher belief. Positive paired change means worse readout error after the transition.", "",
        "The main table pools transition pairs, matching the DEV descriptive join. These observations "
        "are dependent within episodes and fits. The separate equal-fit mean includes only fits with "
        "eligible pairs; empty fits stay explicitly empty, not zero-error. No significance tests are performed.", "",
        "## First-passage brief table", "",
        "| Split | Drive | Transition | Pairs | Contributing fits | MSE before | MSE after | Paired change | Equal-fit change |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    def number(value):
        return "—" if value is None else f"{value:.6f}"
    for row in pooled:
        if row["candidate"].startswith("first_passage_"):
            drive = "impulse" if row["candidate"].endswith("impulse_on") else "sustained"
            lines.append(f"| {row['split']} | {drive} | {row['transition']} | {row['pairs']} | "
                         f"{row['contributing_fits']}/16 | {number(row['before_mse'])} | "
                         f"{number(row['after_mse'])} | {number(row['paired_change'])} | "
                         f"{number(row['equal_nonempty_fit_paired_change'])} |")
    lines += ["", "## Complete candidate table", "",
        "| Split | Candidate | Transition | Pairs | Contributing fits | MSE before | MSE after | Paired change |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in pooled:
        lines.append(f"| {row['split']} | {row['candidate']} | {row['transition']} | {row['pairs']} | "
                     f"{row['contributing_fits']}/16 | {number(row['before_mse'])} | "
                     f"{number(row['after_mse'])} | {number(row['paired_change'])} |")
    lines += ["", "Ordinary candidates have no recorded event or recovery in any fit; their empty "
        "MSE entries are undefined, not successful zero-error observations.", "",
        "## Per-fit first-passage pair counts and changes", "",
        "| Fit | Split | Sustained event n / ΔMSE | Sustained recovery n / ΔMSE | Impulse event n / ΔMSE | Impulse recovery n / ΔMSE |",
        "| ---: | --- | ---: | ---: | ---: | ---: |"]
    for fit in seal["fits"]:
        for split in SPLITS:
            values = []
            for mode in ("structured_on", "impulse_on"):
                for kind in KINDS:
                    row = next(r for r in rows if (r["fit"],r["split"],r["candidate"],r["transition"]) ==
                               (fit,split,f"first_passage_bank__{mode}",kind))
                    values.append(f"{row['pairs']} / {number(row['paired_change'])}")
            lines.append(f"| {fit} | {split} | " + " | ".join(values) + " |")
    lines += ["", "## Interpretation limits and reproducibility", "",
        "Elapsed time, action costs, pending/broken flags, time-indexed bank features and trajectory "
        "selection can change across the joined decisions. Different candidates can select different "
        "world/state populations. A constant teacher target removes new-observation changes in that "
        "target; it does not make event or recovery causal. This is the existing learned readout, not "
        "an independently fitted optimal decoder or maximal available information.", "",
        "The controlled trained-cell retention probe remains separate. In the actual task, impulse "
        "changes both drift and bank future-driver features; this audit cannot separate those effects. "
        "The actual head retains public last-observation and time inputs, so cell-only information "
        "loss cannot be inferred from a readout-error increase.", "",
        f"Selected episodes: **{report['selected_episodes']:,}**; streamed raw episodes: **{report['raw_episodes_streamed']:,}**. "
        "The JSON retains every fit × split × candidate × transition row, nonexclusive exclusion "
        "counts, raw SHA-256 identities and per-fit audit hashes. Per-fit audit files additionally "
        "retain each included pair's world/decision ID, beliefs, latent indices, elapsed change and "
        "changed task fields. Main source bytes and the model-seal identity were verified before "
        "and after analysis; the successful confirmation receipts link these outcomes to that seal.", "",
        f"Audit script SHA-256: `{source_sha}`.", "",
        f"Model seal SHA-256: `{seal_sha}`.", "",
        f"Companion JSON SHA-256: `{sha(json_path)}`.", "",
        "Whole-process costs are recorded by the published external wait4 supervisor in the "
        "audit output process_receipts directory; per-fit inner analysis costs are nested, not additive.", ""]
    with (evidence / "ACTUAL_READOUT_REVIEW.md").open("x") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("collect", "finalize"))
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-seal", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=STUDY / "evidence")
    args = parser.parse_args()
    seal, seal_sha, source_sha = json.loads(args.model_seal.read_text()), sha(args.model_seal), sha(__file__)
    if len(seal["fits"]) != 16 or seal["fits"] != seal["protocol"]["fits"]:
        raise ValueError("complete registered 16-fit seal required")
    frozen = {path: sha(REPO / path) for path in seal["source_sha256"]}
    if frozen != seal["source_sha256"]:
        raise ValueError("main scientific source changed")
    args.output.mkdir(parents=True, exist_ok=True)
    results = [result for fit in seal["fits"] if (result := collect_fit(
        args.confirmation, args.output, fit, seal, seal_sha, source_sha)) is not None]
    if args.stage == "finalize":
        finalize(results, args.output, args.evidence, seal, seal_sha, source_sha)
    if (frozen != {path: sha(REPO / path) for path in frozen} or sha(__file__) != source_sha
            or sha(args.model_seal) != seal_sha):
        raise ValueError("source or seal changed during audit")
    print(json.dumps(dict(stage=args.stage, completed_fits=[r["fit"] for r in results],
                         missing_fits=[f for f in seal["fits"] if f not in {r["fit"] for r in results}],
                         script_sha256=source_sha)), flush=True)


if __name__ == "__main__":
    main()
