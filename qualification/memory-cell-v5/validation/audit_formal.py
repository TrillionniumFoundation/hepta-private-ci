"""Independently recount completed V5 joint evidence without executing any model."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unicodedata
import zlib


SEEDS = (1019, 1021, 1031, 1033, 1039)
DOMAINS = ("co2", "temperature", "sunspots", "unemployment")
INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")
ARMS = ("parameter_connected", "parameter_removed", "parameter_permuted",
        "strong_planner", "parameter_oracle", "strong_oracle")
OFFSETS = {"at": [0], "previous": [-1], "change": [-1, 0],
           "mean3": [-2, -1, 0], "range3": [-2, -1, 0], "peak3": [-2, -1, 0]}
REJECT = "__reject__"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": digest(raw)}


def json_file(path):
    return json.loads(Path(path).read_bytes())


def document(path):
    """Independent standard-library decoder for the sealed evidence envelope."""
    path = Path(path)
    item = json_file(path)
    if not isinstance(item, dict) or item.get("schema") != "hepta.memory.v5.compressed-evidence.v1":
        return item
    if set(item) != {"schema", "prefix", "payload"} or item["prefix"] != path.name + ".zlib":
        raise ValueError("bad compressed document envelope")
    record = item["payload"]
    files = record["files"]
    names = [f"{item['prefix']}.part{i:03d}" for i in range(1, len(files) + 1)]
    if not 1 <= len(names) <= 40 or set(names) != set(files):
        raise ValueError("bad evidence part inventory")
    blocks = []
    for name in names:
        part = path.parent / name
        if part.is_symlink() or not 0 < part.stat().st_size <= 480000:
            raise ValueError("bad evidence part file")
        raw = part.read_bytes()
        if {"bytes": len(raw), "sha256": digest(raw)} != files[name]:
            raise ValueError("evidence part hash differs")
        blocks.append(raw)
    encoded = b"".join(blocks)
    if len(encoded) != record["bytes"] or digest(encoded) != record["sha256"]:
        raise ValueError("assembled evidence hash differs")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(encoded, 64000001)
    if len(raw) > 64000000 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("invalid bounded evidence stream")
    if len(raw) != record["uncompressed_bytes"] or digest(raw) != record["uncompressed_sha256"]:
        raise ValueError("decoded evidence hash differs")
    return json.loads(raw)


def exact(actual, target):
    if not isinstance(actual, dict) or target is None:
        return False
    return (set(actual) == {"kind", "value", "support"}
            and actual["kind"] == "number"
            and type(actual["value"]) in (int, float)
            and math.isfinite(actual["value"])
            and actual["value"] == target["value"]
            and actual["support"] == target["support"])


def normalized(request):
    text = unicodedata.normalize("NFKC", request["utterance"]).casefold()
    series = unicodedata.normalize("NFKC", request["series_name"]).casefold()
    return " ".join(text.replace(series, " [series] ").replace(request["date"], " [date] ").split())


def support(domain, date, offsets):
    year, month = map(int, date.split("-"))
    anchor = year * 12 + month - 1
    return [f"{domain}:{(anchor + offset) // 12:04d}-{(anchor + offset) % 12 + 1:02d}" for offset in offsets]


class Audit:
    def __init__(self, project, joint, expected_commit, expected_freeze):
        self.project, self.joint = project, joint
        self.expected_commit, self.expected_freeze = expected_commit, expected_freeze
        self.checks, self.failures, self.failure_count = 0, [], 0
        self.original_project = None
        self.checked_files = {}
        self.domains = []

    def equal(self, actual, expected, label):
        self.checks += 1
        if actual != expected:
            self.failure_count += 1
            if len(self.failures) < 100:
                self.failures.append({"check": label, "actual": actual, "expected": expected})

    def mapped(self, value):
        path = Path(value)
        if self.original_project is not None and path.is_relative_to(self.original_project):
            return self.project / path.relative_to(self.original_project)
        if path.is_relative_to(self.project):
            return path
        raise ValueError("recorded path is outside the original project")

    def inventory(self, files, label):
        for name, identity in files.items():
            path = self.mapped(name)
            if path not in self.checked_files:
                self.checked_files[path] = file_identity(path)
            self.equal(self.checked_files[path], identity, label + ":" + name)

    def fresh(self, folder, mode, seed, domain):
        request_path = folder / f"{mode}-request.json"
        output_path = folder / f"{mode}-output.json"
        request, result = json_file(request_path), document(output_path)
        process = json_file(folder / f"{mode}-process.json")
        label = f"{seed}/{domain}/{mode}"
        if self.original_project is None:
            self.original_project = Path(request["freeze_file"]).parent
        self.equal(process["exit_code"], 0, label + ":exit")
        self.equal(process["request"], file_identity(request_path), label + ":request-file")
        self.equal(process["output_envelope"], file_identity(output_path), label + ":output-file")
        self.equal(result["request_sha256"], digest(canonical(request)), label + ":request-binding")
        self.equal(request["freeze_sha256"], self.expected_freeze, label + ":frozen-request")
        self.equal(result["source_binding"]["freeze_sha256"], self.expected_freeze, label + ":frozen-output")
        self.equal(result["source_binding"]["source_commit"], self.expected_commit, label + ":source")
        for value in (request, result):
            self.equal((value["seed"], value["domain"], value["mode"], value["smoke_only"]), (seed, domain, mode, False), label + ":scope")
        self.equal(len(request["requests"]), 216, label + ":request-count")
        self.equal(len(result["rows"]), 216, label + ":output-count")
        for index, (query, row) in enumerate(zip(request["requests"], result["rows"], strict=True)):
            self.equal(set(query), {"utterance", "series_name", "date"}, label + f":three-fields/{index}")
            self.equal(row["index"], index, label + f":index/{index}")
            self.equal(row["request_sha256"], digest(canonical(query)), label + f":query-hash/{index}")
        self.equal(result["router_parameter_before"], result["router_parameter_after"], label + ":router-immutable")
        self.equal(result["state"]["parameter_identity_before"], result["state"]["parameter_identity_after"], label + ":memory-immutable")
        files = result["serving_file_identities"]
        self.inventory(files, label + ":serving-files")
        self.equal(result["serving_state_bytes"], sum(item["bytes"] for item in files.values()), label + ":state-bytes")
        self.equal(set(result["observed_python_read_opens"]), set(files), label + ":observed-opens")
        if mode == "parameter":
            forbidden = [name for name in files if "/codecs/" in name or "residual" in Path(name).name]
            self.equal(forbidden, [], label + ":parameter-has-no-codec")
        return request, result

    def domain(self, seed, domain):
        folder = self.joint / f"seed-{seed}" / domain
        summary = json_file(folder / "summary.json")
        graders = document(folder / "grader.json")["rows"]
        row_grades = document(folder / "row-grades.json")
        oracle = document(folder / "oracle-control.json")
        prequest, parameter = self.fresh(folder, "parameter", seed, domain)
        srequest, strong = self.fresh(folder, "strong", seed, domain)
        prefix = f"{seed}/{domain}"
        self.equal(prequest["requests"], srequest["requests"], prefix + ":shared-requests")
        decisions = [row["decision"] for row in parameter["rows"]]
        self.equal(decisions, [row["decision"] for row in strong["rows"]], prefix + ":shared-routes")
        self.equal(len(graders), 216, prefix + ":graders")
        self.equal(len(row_grades), 216, prefix + ":row-grades")
        self.equal(len(oracle["rows"]), 216, prefix + ":oracle-rows")
        self.equal(oracle["not_actual_semantic_routing"], True, prefix + ":oracle-label")
        totals = {name: Counter() for name in ARMS}
        confusion, raw_confusion = Counter(), Counter()
        per_intent = {name: Counter() for name in INTENTS}
        known = ood = correct = false_accept = raw_correct = raw_false_accept = composed = 0
        ids, family_counts, labels = set(), Counter(), Counter()
        for index, (grader, query, decision) in enumerate(zip(graders, prequest["requests"], decisions, strict=True)):
            gold, target = grader["gold_intent"], grader["target"]
            ids.add(grader["template_id"])
            labels[gold] += 1
            self.equal(grader["index"], index, prefix + f":grader-index/{index}")
            self.equal(grader["address"], list(map(int, query["date"].split("-"))), prefix + f":address/{index}")
            accepted = decision["accepted_intent"]
            self.equal(accepted in (*INTENTS, None), True, prefix + f":accepted-label/{index}")
            confusion[gold or REJECT, accepted or REJECT] += 1
            raw_confusion[gold or REJECT, decision["raw_label"]] += 1
            if gold is None:
                ood += 1
                false_accept += accepted is not None
                raw_false_accept += decision["raw_label"] in INTENTS
                family_counts[grader["ood_family"]] += 1
                self.equal(target, None, prefix + f":ood-target/{index}")
            else:
                known += 1
                composed += gold != "at"
                correct += accepted == gold
                raw_correct += decision["raw_label"] == gold
                per_intent[gold].update(queries=1, correct_accepted=int(accepted == gold), raw_correct=int(decision["raw_label"] == gold))
                self.equal(grader["authored_expected_provenance_offsets"], OFFSETS[gold], prefix + f":offsets/{index}")
                self.equal(target["support"], support(domain, query["date"], OFFSETS[gold]), prefix + f":target-support/{index}")
            self.equal(oracle["rows"][index]["oracle_intent_supplied_by_grader"], gold, prefix + f":oracle-intent/{index}")
            values = {**parameter["rows"][index]["arms"], **strong["rows"][index]["arms"],
                      "parameter_oracle": oracle["rows"][index]["parameter_oracle"],
                      "strong_oracle": oracle["rows"][index]["strong_oracle"]}
            self.equal(set(values), set(ARMS), prefix + f":arm-inventory/{index}")
            flags = {}
            for name, value in values.items():
                flags[name] = exact(value["actual"], target)
                trace = value["execution"]["trace"]
                self.equal(value["execution"]["calls"], len(trace), prefix + f":hop-count/{name}/{index}")
                expected_reads = sum(item["operation"] in {"c01", "c05"} for item in trace)
                self.equal(value["numeric_read_calls"], expected_reads, prefix + f":read-count/{name}/{index}")
                totals[name].update(known_queries=int(gold is not None), known_exact=int(gold is not None and flags[name]),
                                    composed_queries=int(gold is not None and gold != "at"),
                                    composed_exact=int(gold is not None and gold != "at" and flags[name]),
                                    hop_calls=len(trace), numeric_read_calls=value["numeric_read_calls"],
                                    numeric_coordinates_read=value["numeric_coordinates_read"])
            expected_row = {"index": index, "template_id": grader["template_id"], "gold_intent": gold,
                            "accepted_intent": accepted, "exact_by_arm": flags}
            self.equal(row_grades[index], expected_row, prefix + f":saved-row-grade/{index}")
        self.equal((known, ood, composed, len(ids)), (144, 72, 120, 216), prefix + ":denominators")
        self.equal(labels, Counter({**{name: 24 for name in INTENTS}, None: 72}), prefix + ":label-counts")
        self.equal((len(family_counts), set(family_counts.values())), (12, {6}), prefix + ":ood-families")
        routing = {"known_queries": known, "ood_queries": ood, "known_correct_accepted": correct,
                   "known_correct_accepted_fraction": correct / known, "ood_false_accepted": false_accept,
                   "ood_false_accept_fraction": false_accept / ood, "raw_known_correct": raw_correct,
                   "raw_ood_false_accepted": raw_false_accept, "per_intent": {key: dict(value) for key, value in per_intent.items()},
                   "accepted_confusion": [{"gold": key[0], "prediction": key[1], "count": value} for key, value in sorted(confusion.items())],
                   "raw_confusion": [{"gold": key[0], "prediction": key[1], "count": value} for key, value in sorted(raw_confusion.items())]}
        self.equal(summary["routing"], routing, prefix + ":routing-summary")
        arms = {}
        for name, counts in totals.items():
            arms[name] = {**counts, "known_exact_fraction": counts["known_exact"] / known,
                          "composed_exact_fraction": counts["composed_exact"] / composed}
        self.equal(summary["arms"], arms, prefix + ":arm-summaries")
        removed = totals["parameter_connected"]["composed_exact"] - totals["parameter_removed"]["composed_exact"]
        permuted = totals["parameter_connected"]["composed_exact"] - totals["parameter_permuted"]["composed_exact"]
        checks = {"semantic": correct * 5 >= known * 4 and false_accept * 20 <= ood,
                  "parameter_oracle_exact": totals["parameter_oracle"]["known_exact"] == known,
                  "composed_actual_ablation_gain": min(removed, permuted) * 10 >= composed}
        self.equal(summary["checks"], checks, prefix + ":integer-gates")
        self.equal(summary["all_preregistered_gates_pass"], all(checks.values()), prefix + ":joint-gate")
        self.equal(summary["composed_gain_vs_removed"], removed / composed, prefix + ":removed-gain")
        self.equal(summary["composed_gain_vs_permuted"], permuted / composed, prefix + ":permuted-gain")
        for mode, result, key in (("parameter", parameter, "pure_deployment_files"), ("strong", strong, "strong_deployment_files")):
            self.equal(summary[key], result["serving_file_identities"], prefix + ":deployment-" + mode)
        self.equal(summary["normalized_requests_sha256"], digest(canonical([normalized(row) for row in prequest["requests"]])), prefix + ":normalized-binding")
        self.equal(summary["route_decisions_sha256"], digest(canonical(decisions)), prefix + ":route-binding")
        self.domains.append({"seed": seed, "domain": domain, "known": known, "ood": ood, "composed": composed,
                             "correct_accepted": correct, "false_accepted": false_accept, "checks": checks,
                             "connected_exact": totals["parameter_connected"]["known_exact"],
                             "composed_gain_counts": {"removed": removed, "permuted": permuted}})
        return summary

    def run(self):
        status = json_file(self.joint / "execution-status.json")
        if status.get("execution") != "completed":
            raise ValueError("audit refuses an unfinished formal joint run")
        frozen = json_file(self.project / "FREEZE.json")
        self.equal(file_identity(self.project / "FREEZE.json")["sha256"], self.expected_freeze, "external-freeze-binding")
        self.equal(frozen["source_commit"], self.expected_commit, "external-source-commit")
        self.equal(frozen["frozen"], True, "frozen-state")
        for name, identity in frozen["source_files"].items():
            self.equal(file_identity(self.project / name), identity, "frozen-file:" + name)
            if name.startswith("assets/"):
                self.equal(name, "assets/ASSETS.json", "no-codec-payload-in-source-hash-pass")
        inputs = json_file(self.joint / "evaluation-inputs.json")
        summary = document(self.joint / "summary.json")
        selected_seal_path = self.project / "SELECTED_MODELS.json"
        selected_seal = json_file(selected_seal_path)
        for container in (inputs, summary):
            self.equal(container["source_commit"], self.expected_commit, "summary-source-commit")
            self.equal(container["freeze"], file_identity(self.project / "FREEZE.json"), "summary-freeze-file")
            self.equal(container["selected_models_seal"], file_identity(selected_seal_path), "selected-seal-file")
        self.equal(selected_seal["freeze_sha256"], self.expected_freeze, "selected-seal-freeze")
        self.equal(selected_seal["held_opened"], False, "selected-seal-precedes-held")
        self.equal(summary["seeds"], list(SEEDS), "formal-seed-inventory")
        self.equal(summary["domains"], list(DOMAINS), "formal-domain-inventory")
        self.equal((summary["cases"], summary["actual_route_requests"], summary["additional_strong_control_route_requests"], summary["independent_authored_language_templates"]), (20, 4320, 4320, 216), "global-denominators")
        attempt = json_file(self.joint / "held-access-attempt.json")
        self.equal(attempt["held_access_attempted"], True, "held-access-record")
        self.equal(attempt["expected_seal_sha256"], frozen["held_seal_sha256"], "held-seal-reference")
        for seed_index, seed in enumerate(SEEDS):
            domains = [self.domain(seed, domain) for domain in DOMAINS]
            saved = json_file(self.joint / f"seed-{seed}/summary.json")
            self.equal(saved, summary["results"][seed_index], f"{seed}:nested-summary")
            self.equal(saved["domains"], domains, f"{seed}:nested-domains")
            for source_key, bytes_key, files_key in (("pure_deployment_files", "pure_four_domain_deployment_bytes", "pure_four_domain_deployment_files"), ("strong_deployment_files", "strong_four_domain_deployment_bytes", "strong_four_domain_deployment_files")):
                union = {}
                for row in domains:
                    for name, identity in row[source_key].items():
                        if name in union:
                            self.equal(union[name], identity, f"{seed}:shared-state-identity")
                        union[name] = identity
                self.equal(saved[files_key], union, f"{seed}:state-union")
                self.equal(saved[bytes_key], sum(value["bytes"] for value in union.values()), f"{seed}:state-union-bytes")
            self.equal(len({row["normalized_requests_sha256"] for row in domains}), 1, f"{seed}:normalized-domain-parity")
            self.equal(len({row["route_decisions_sha256"] for row in domains}), 1, f"{seed}:route-domain-parity")
            model = inputs["selected_router_states"][str(seed)]
            directory = self.mapped(model["directory"])
            self.equal({item.name for item in directory.iterdir()}, set(model["files"]), f"{seed}:selected-inventory")
            for name, identity in model["files"].items():
                self.equal(file_identity(directory / name), identity, f"{seed}:selected-file:" + name)
            for key, value in selected_seal["routers"][str(seed)].items():
                self.equal(model[key], value, f"{seed}:selected-sealed-field:" + key)
            training_source = directory.parent.parent / "SOURCE.json"
            candidate = model["candidate"]["name"]
            receipts = {"selection_receipt_sha256": directory.parent / "candidate-diagnostics" / candidate / "RECEIPT.json",
                        "primary_sha256": directory.parent / "PRIMARY.json", "candidates_sha256": directory.parent / "CANDIDATES.json",
                        "training_source_sha256": training_source}
            for key, path in receipts.items():
                self.equal(file_identity(path)["sha256"], model[key], f"{seed}:selection-evidence:" + key)
        for field, check in (("semantic_cases_pass", "semantic"), ("parameter_oracle_cases_pass", "parameter_oracle_exact"), ("composed_cases_pass", "composed_actual_ablation_gain")):
            self.equal(summary[field], sum(row["checks"][check] for row in self.domains), field)
        self.equal(summary["all_preregistered_gates_pass"], all(all(row["checks"].values()) for row in self.domains), "overall-joint-gate")
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--joint", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_source_commit) or not re.fullmatch(r"[0-9a-f]{64}", args.expected_freeze_sha256):
        parser.error("expected identities must be full lowercase hashes")
    project, joint, output = args.project.resolve(), args.joint.resolve(), args.output.absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(joint):
        parser.error("audit output must be a new file outside the joint run")
    audit = Audit(project, joint, args.expected_source_commit, args.expected_freeze_sha256)
    report = {"schema": "hepta.memory.v5.independent-joint-audit.v1", "joint_directory": str(joint),
              "audit_script": file_identity(Path(__file__)), "expected_source_commit": args.expected_source_commit,
              "expected_freeze_sha256": args.expected_freeze_sha256, "models_executed": 0,
              "held_corpus_file_opened": False, "scope": "Independent exact/provenance recount from sealed raw grader and arm outputs, routing/input checks, artifact hashes, and serialized file unions.",
              "limits": ["Numeric gold values are taken from the sealed independent grader; this audit does not independently decode original source archives.", "The audit does not independently attest historical process creation, wall time, training execution, or all operating-system I/O.", "This is an assistant-authored computational audit, not independent human review or a security guarantee.", "No grade_domain, model loader, graph executor, training code, or held corpus loader is imported."]}
    try:
        audit.run()
    except Exception as error:
        audit.failure_count += 1
        audit.failures.append({"exception": type(error).__name__, "message": str(error)})
    report.update(checks=audit.checks, failure_count=audit.failure_count, failures=audit.failures,
                  passed=audit.failure_count == 0, domain_recounts=audit.domains,
                  unique_actual_state_files_hashed=len(audit.checked_files))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, default=lambda value: sorted(value) if isinstance(value, set) else str(value))
        stream.write("\n")
    print(json.dumps({"output": str(output), "passed": report["passed"], "checks": report["checks"], "failures": report["failure_count"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
