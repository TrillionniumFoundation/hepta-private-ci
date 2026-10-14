"""Read-only replay of a specific NEGATIVE shared-Stem confirmation profile.

No model import, fitting, label-driven selection, or production owner.
A verified archive digest confirms bytes, NOT authorship, task independence or truth.
The negative historical gate is intentional: this is not a generic future model
selection algorithm. Reuse it to audit archived development evidence unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import stat
from zipfile import ZipFile

PREFIX = "hepta-fresh-confirmation/"
NAMES = ("candidate-lock.json", "cohort.json", "predictions.json",
         "confirmation.json", "report.json")
MAX_MEMBER = 16 * 1024 * 1024
ARMS = {"bank", "shared", "linear_distilled", "residual_corrected"}


class AuditError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise AuditError("duplicate JSON field")
            value[key] = item
        return value

    def nonfinite(_):
        raise AuditError("nonfinite JSON token")

    return json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)


def require(ok, message):
    if not ok:
        raise AuditError(message)


class Input:
    """Allow only the original closed file inventory in a checked source tree."""
    def __init__(self, path, expected_zip_sha256=None):
        self.path = Path(path)
        self.archive_sha256 = None
        self.archive = None
        if self.path.is_file():
            data = self.path.read_bytes()
            self.archive_sha256 = digest(data)
            require(expected_zip_sha256 == self.archive_sha256,
                    "archive differs from externally pinned SHA256")
            self.archive = ZipFile(self.path)
            entries = self.archive.infolist()
            require(len(entries) <= 2048 and
                    len({x.filename for x in entries}) == len(entries) and
                    all(x.file_size <= MAX_MEMBER and not x.filename.startswith("/")
                        and ".." not in Path(x.filename).parts and
                        not stat.S_ISLNK((x.external_attr >> 16) & 0o170000)
                        for x in entries), "unsafe ZIP member inventory")
            require(self.archive.testzip() is None, "corrupt ZIP member")
        else:
            require(self.path.is_dir() and expected_zip_sha256 is None,
                    "existing directory or pinned original archive required")

    def read(self, member):
        require(member in tuple(PREFIX + name for name in NAMES),
                "unregistered source member")
        if self.archive:
            require(member in self.archive.namelist(), "missing archive member")
            data = self.archive.read(member)
        else:
            p = self.path / member
            require(not any(x.is_symlink() for x in (p, *p.parents)) and
                    p.is_file() and p.stat().st_size <= MAX_MEMBER,
                    "missing, linked or oversized source")
            data = p.read_bytes()
        require(len(data) <= MAX_MEMBER, "oversized source bytes")
        return data


def score(rows, labels, cells, classes):
    require(len(rows) == len(labels) == len(cells) and len(rows) > 0,
            "unpaired observation/label/Cell rows")
    require(type(classes) is int and 2 <= classes <= 256,
            "invalid fixed classification dimension")
    counts, nll, per_cell, flags = 0, 0.0, {}, []
    for row, label, cell in zip(rows, labels, cells, strict=True):
        require(type(label) is int and 0 <= label < classes and
                type(cell) is int and cell in (0, 1), "invalid outcome identity")
        require(isinstance(row, list) and len(row) == classes and
                all(type(p) in (float, int) and math.isfinite(p) and
                    0 <= p <= 1 for p in row) and
                abs(math.fsum(row) - 1.0) <= 1e-5 and row[label] > 0,
                "invalid probability vector")
        hit = max(range(classes), key=lambda j: row[j]) == label
        flags.append(hit)
        counts += int(hit)
        nll -= math.log(row[label])
        group = per_cell.setdefault(cell, {"cell": cell, "cases": 0, "correct": 0})
        group["cases"] += 1
        group["correct"] += int(hit)
    return {"cases": len(rows), "correct": counts, "accuracy": counts / len(rows),
            "nll": nll / len(rows),
            "per_cell": [per_cell[k] for k in sorted(per_cell)]}, flags


def audit(path, expected_zip_sha256=None):
    inp = Input(path, expected_zip_sha256)
    raw = {name: inp.read(PREFIX + name) for name in NAMES}
    parsed = {name[:-5]: strict_json(data) for name, data in raw.items()}
    lock, cohort, predictions, confirmation, report = (
        parsed[k] for k in ("candidate-lock", "cohort", "predictions",
                           "confirmation", "report"))
    require(type(cohort) is list and len(cohort) == 1024 and
            all(type(x) is dict for x in (lock, predictions, confirmation, report)),
            "unexpected registered historical profile")
    for key, file, record in (
        ("candidate_lock_sha256", "candidate-lock.json", predictions),
        ("cohort_sha256", "cohort.json", report),
        ("predictions_sha256", "predictions.json", report),
        ("confirmation_sha256", "confirmation.json", report)):
        require(record.get(key) == digest(raw[file]),
                "source hash not bound to recorded original bytes: " + key)
    require(confirmation.get("candidate_lock_sha256") ==
            digest(raw["candidate-lock.json"]) and
            confirmation.get("predictions_sha256") ==
            digest(raw["predictions.json"]) and
            confirmation.get("proposed") == lock.get("selected") and
            confirmation.get("chosen") == report.get("chosen") and
            confirmation.get("new_model_selected_on_confirmation") is False and
            confirmation.get("production_accepted") is False and
            report.get("schema") == "hepta.fresh-confirmation-executed.v1" and
            report.get("cohort_sha256") == predictions.get("cohort_sha256") and
            report.get("proposed") == lock.get("selected") ==
            predictions.get("selected"),
            "frozen candidate, cohort or profile mismatch")
    case_ids = [c["case_id"] for c in cohort]
    require(len(set(case_ids)) == 1024 and
            predictions.get("case_ids") == case_ids,
            "original prediction/cohort identity or ordering changed")
    index = {phase: [i for i, c in enumerate(cohort) if c["split"] == phase]
             for phase in ("confirmation", "evaluation")}
    require(all(len(index[phase]) == 512 and
                Counter(cohort[i]["cell"] for i in index[phase]) ==
                {0: 256, 1: 256} for phase in index) and
            sum(map(len, index.values())) == len(cohort),
            "independent stage cardinality, Cell assignment or split changed")
    for stage, obj in (("confirmation", confirmation), ("evaluation", report)):
        require(obj.get(stage + "_ids") ==
                [case_ids[i] for i in index[stage]] and
                len(obj.get(stage + "_labels", [])) == 512,
                "stage labels or case bindings incomplete")
    probs = predictions.get("predictions")
    require(type(probs) is dict and set(probs) == ARMS,
            "missing or substituted original model arms")
    scores, flags = {}, {}
    for phase in index:
        indices = index[phase]
        owner = confirmation if phase == "confirmation" else report
        labels = owner[phase + "_labels"]
        cells = [cohort[i]["cell"] for i in indices]
        scores[phase], flags[phase] = {}, {}
        for arm, rows in probs.items():
            require(type(rows) is list and len(rows) == 1024,
                    "incomplete original prediction arm")
            observed, verdicts = score([rows[i] for i in indices], labels,
                                       cells, lock["profile"]["classes"])
            scores[phase][arm], flags[phase][arm] = observed, verdicts
            if phase == "evaluation":
                claimed = report["scores"][arm]
                require(claimed["cases"] == observed["cases"] and
                        claimed["correct"] == observed["correct"] and
                        claimed["per_cell"] == observed["per_cell"] and
                        abs(claimed["accuracy"] - observed["accuracy"]) < 1e-12 and
                        abs(claimed["nll"] - observed["nll"]) < 1e-5,
                        "original evaluator diverges from sealed probabilities: " + arm)
    pairs = []
    for cell in (0, 1):
        which = [j for j, position in enumerate(index["confirmation"])
                 if cohort[position]["cell"] == cell]
        base = [flags["confirmation"]["bank"][j] for j in which]
        candidate = [flags["confirmation"][report["proposed"]][j] for j in which]
        gain = sum(c and not b for b, c in zip(base, candidate))
        loss = sum(b and not c for b, c in zip(base, candidate))
        recorded = confirmation["bound"]["per_cell"][cell]
        require(recorded["cell"] == cell and recorded["cases"] == 256 and
                recorded["bank_correct"] == sum(base) and
                recorded["candidate_correct"] == sum(candidate) and
                recorded["gains"] == gain and recorded["losses"] == loss and
                recorded["nonregression_supported_under_iid"] is False,
                "original paired gains/losses or failed nonregression gate changed")
        pairs.append({"cell": cell, "cases": 256, "gains": gain, "losses": loss})
    # Compute every disjoint outcome transition from UNMODIFIED raw probabilities.
    # These are descriptive counts, not post-hoc selection or iid confidence.
    paired_deltas = {}
    for phase in ("confirmation", "evaluation"):
        paired_deltas[phase] = {}
        for arm in sorted(ARMS - {"bank"}):
            records = []
            for cell in (0, 1):
                idx = [j for j, row_index in enumerate(index[phase])
                       if cohort[row_index]["cell"] == cell]
                b = [flags[phase]["bank"][j] for j in idx]
                c = [flags[phase][arm][j] for j in idx]
                wins = sum(candidate and not baseline
                           for baseline, candidate in zip(b, c))
                losses = sum(baseline and not candidate
                             for baseline, candidate in zip(b, c))
                records.append({"cell": cell, "cases": len(idx),
                                "gains": wins, "losses": losses,
                                "net_correct": wins - losses})
            paired_deltas[phase][arm] = records
    require(confirmation["bound"]["supported_under_iid"] is False and
            confirmation["chosen"] == report["chosen"] == "bank" and
            report["chosen_score"] == report["scores"]["bank"] and
            report["retention_certified"] is False and
            report["assumptions_verified"] is False and
            report["pretraining_clean"] is False and
            report["production_accepted"] is False and
            lock["independent_source_families_verified"] is False,
            "negative historical result must never be relabeled positive")
    return {"schema": "hepta.stem-historical-postseal-replay.v1",
            "zip_sha256": inp.archive_sha256,
            "members": {k: digest(raw[k]) for k in NAMES},
            "cohort_sizes": {k: len(v) for k, v in index.items()},
            "scores": scores, "confirmation_pairs": pairs,
            "descriptive_paired_deltas": paired_deltas,
            "candidate": report["proposed"], "chosen": report["chosen"],
            "flops_observed": report["encoding"].get("active_flops") is not None,
            "energy_observed": report["encoding"].get("energy_joules") is not None,
            "independent_source_families_verified": False,
            "retention_certified": False, "production_accepted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--zip-sha256", help="external original SHA256 (mandatory for ZIP)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.zip_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as sink:
        json.dump(result, sink, indent=2, sort_keys=True, allow_nan=False)
        sink.write("\n")
    print(json.dumps({"chosen": result["chosen"], "production_accepted": False,
                      "evaluation_correct": {name: row["correct"] for name, row in
                                             result["scores"]["evaluation"].items()}},
                     sort_keys=True))


if __name__ == "__main__":
    main()
