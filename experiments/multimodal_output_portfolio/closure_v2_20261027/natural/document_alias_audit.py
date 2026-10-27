"""Freeze source-only merchant aliases, then run explicitly posthoc sensitivity."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np


PHYSICAL_GROUPS = [
    (["X51005705759", "X51005705760"], "Both headers name MYDIN / TRI SHAAS / MYDIN MART SRI MUDA; same full store address, phone 03-51217970 and GST 000429166592."),
    (["X51005711401", "X51005711451", "X51006389898"], "WAN SHENG / truncated WAN SHE; same full address, company 002043319-W and GST 001335787520; no differing outlet in source words."),
    (["X51005724552", "X51005724623"], "KEDAI PAPAN YEW CHUAN spelling loss; same LOT 276 location, phone/fax 03-87686092 and GST 000781500416."),
    (["X51005361906", "X51005361908"], "Both source-word headers print TEO HENG; same full address, company 001451637-M, GST 000689913856 and phone/fax."),
    (["X51005433518", "X51007846397"], "Both source-word headers print UNIHAKKA INTERNATIONAL; company 867388-U, GST 000656195584 and outlet BAR WANG RICE@PERMAS JAYA match."),
    (["X51005453801", "X51006350750"], "GL HANDICRAFT TAIL/TAII annotation; same full store address, company 75495-W and GST 001948532736; no differing outlet in source words."),
    (["X51006327978", "X51006335552"], "Y/YONG SOON FATT truncation; same full store address, company 81497-P, GST 000788250624 and phone 016-2014209."),
]

CORPORATE_OR_FAMILY_GROUPS = [
    (["X51005757220", "X51006414600"], "Same AEON company 126926-H / GST 002017394688 and registered address, but footer outlets BANDAR PUCHONG and TEBRAU CITY differ. Corporate/template overlap, not the same physical store."),
    (["X51005230616", "X51006619507"], "GERBANG ALAF explicitly prints formerly GOLDEN ARCHES; same company 65351-M / GST 000504664064. McDonald outlets PETRONAS TAMAN MELATI DT and DATARAN PAHLAWAN 2 differ."),
    (["X00016469620", "X00016469623", "X51005719914", "X51005568884"], "MR DIY group and registered address recur; TESCO TERBAU, TESCO PUTRA NILAI, TESCO MENJALARA KEPONG and CHERAS LEISURE MALL are distinct outlets, with different company/GST identifiers. Conservative shared-family/template grouping only."),
]


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_new(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def normalized(value):
    return re.sub("[^A-Z0-9]", "", (value or "").upper())


def metadata(row, cohort):
    text = " ".join(row.get("reference_words", [])).upper()
    phones = []
    pattern = r"(?:\bTEL(?:EPHONE)?|\bPHONE|\bFAX|H/P)\s*(?:NO[.]?)?\s*[:.]*\s*([+()0-9][+()0-9\s-]{5,24})"
    for match in re.finditer(pattern, text):
        digits = re.sub("[^0-9]", "", match.group(1))
        if 8 <= len(digits) <= 13:
            phones.append(digits)
    gst = re.findall(r"\bGST\s*(?:REG(?:ISTRATION)?\.?\s*)?(?:ID|NO)?\s*(?:NO\.?\s*)?[:#.]?\s*([0-9]{12})\b", text)
    company = row["reference"]["company"]
    core = re.sub(r"\b(SDN|BHD|SENDIRIAN|BERHAD|MALAYSIA|COMPANY|CO)\b", " ", company.upper())
    return {"id": row["id"], "cohort": cohort, "role": row.get("role"),
        "company": company, "address": row["reference"]["address"],
        "core_name": normalized(core), "normalized_address": normalized(row["reference"]["address"]),
        "phones": sorted(set(phones)), "company_identifier_candidates": sorted(set(re.findall(r"\b[0-9]{5,9}-[A-Z]\b", text[:900]))),
        "GST_identifiers": sorted(set(gst)), "full_reference_words": text,
        "source_image_sha256": row["sha256"], "source_image_path": row["path"]}


def partition(records, groups):
    parent = {r["id"]: r["id"] for r in records}

    def find(identity):
        while parent[identity] != identity:
            identity = parent[identity]
        return identity

    for members, _ in groups:
        if any(identity not in parent for identity in members):
            raise ValueError("Reviewed alias source is absent")
        anchor = min(find(identity) for identity in members)
        for identity in members:
            parent[find(identity)] = anchor
    return {identity: find(identity) for identity in sorted(parent)}


def freeze(workspace, output):
    code = Path(__file__).resolve().parent
    manifests = [
        ("historical", code.parents[1] / "repair_20261026/natural/document/evidence/SOURCE_MANIFEST.json"),
        ("continuation", workspace / "natural-continuation-assets/document/MANIFEST.json"),
        ("first", workspace / "natural-v2-assets/document/MANIFEST.json"),
        ("replication", workspace / "natural-v2-assets/document-replication/MANIFEST.json"),
    ]
    records = [metadata(row, cohort) for cohort, path in manifests for row in load(path)["documents"]]
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Repeated source identity in reviewed universe")
    candidates = []
    for index, first in enumerate(records):
        for second in records[index + 1:]:
            name_ratio = difflib.SequenceMatcher(None, first["core_name"], second["core_name"]).ratio()
            address_ratio = difflib.SequenceMatcher(None, first["normalized_address"], second["normalized_address"]).ratio()
            shared = {key: sorted(set(first[key]) & set(second[key])) for key in ("phones", "company_identifier_candidates", "GST_identifiers")}
            equal_address = bool(first["normalized_address"]) and first["normalized_address"] == second["normalized_address"]
            if equal_address or name_ratio >= .65 and address_ratio >= .7 or name_ratio >= .92 and address_ratio >= .45 or any(shared.values()):
                candidates.append({"ids": [first["id"], second["id"]], "name_ratio": name_ratio,
                    "address_ratio": address_ratio, "exact_normalized_address": equal_address, "shared_identifiers": shared})
    physical = partition(records, PHYSICAL_GROUPS)
    conservative = partition(records, PHYSICAL_GROUPS + CORPORATE_OR_FAMILY_GROUPS)
    counts = {}
    for cohort, role in sorted({(r["cohort"], r["role"]) for r in records}):
        selected = [r["id"] for r in records if r["cohort"] == cohort and r["role"] == role]
        counts[cohort + "/" + role] = {"documents": len(selected),
            "confirmed_physical_components": len({physical[i] for i in selected}),
            "conservative_corporate_family_components": len({conservative[i] for i in selected})}
    prior = {r["id"] for r in records if r["cohort"] != "replication"}
    replication = {r["id"] for r in records if r["cohort"] == "replication"}
    exclusions = {}
    for kind, mapping in (("physical", physical), ("corporate_family", conservative)):
        previous = {mapping[i] for i in prior}
        exclusions[kind] = sorted(i for i in replication if mapping[i] in previous)
    result = {"schema": "hepta.ndu.closure-v2.natural.document-alias-source-seal.v1", "sealed_ns": time.time_ns(),
        "source_only_audit": True, "model_outputs_read_by_this_freeze": False,
        "postqualification_aggregate_results_already_known": True,
        "mapping_basis": "All four source manifests; company/address similarity, phone/company/GST equality candidates and manual review of complete source reference_words; no per-source rewards used to form or choose components.",
        "candidate_rule": "Exact nonempty normalized address OR core-name ratio>=.65 and address ratio>=.70 OR name ratio>=.92 and address ratio>=.45 OR shared extracted phone/company/GST identifier. SequenceMatcher comparisons on source metadata only.",
        "limitations": "Reference-word annotations are evidence, not an independent company/store registry; unflagged aliases and shared templates may remain. A common registered address does not prove a common physical outlet. Confirmed components are an audited partition under available annotations, not a theorem that all remaining entities are independent.",
        "source_manifests": [{"cohort": cohort, "path": str(path), "sha256": sha(path)} for cohort, path in manifests],
        "source_rows": records, "source_count": len(records), "unique_exact_image_hashes": len({r["source_image_sha256"] for r in records}),
        "candidate_pairs": candidates,
        "confirmed_physical_groups": [{"members": ids, "source_only_reason": reason} for ids, reason in PHYSICAL_GROUPS],
        "additional_corporate_or_family_groups": [{"members": ids, "source_only_reason": reason} for ids, reason in CORPORATE_OR_FAMILY_GROUPS],
        "physical_component": physical, "corporate_family_component": conservative,
        "cohort_counts": counts, "replication_with_prior_source_overlap": exclusions,
        "total_confirmed_physical_components": len(set(physical.values())),
        "total_conservative_corporate_family_components": len(set(conservative.values())),
        "bootstrap_frozen_before_sensitivity": {"draws": 5000, "seed": 2844, "interval_quantiles": [.0125, .9875],
            "metrics": ["quality", "field_exact", "cpu_seconds", "wall_seconds", "cost_adjusted_return"],
            "primary_original_gate_unchanged": True,
            "partitions": ["first_all_physical", "replication_all_physical", "replication_no_prior_physical", "replication_no_prior_corporate_family"],
            "estimands": ["equal_weight_per_audited_entity", "original_document_weight_with_entity_resampling"]},
        "auditor_source_sha256": sha(__file__)}
    save_new(output, result)
    print({"source_only_seal": str(output), "sha256": sha(output), "source_rows": len(records),
        "candidate_pairs": len(candidates), "cohort_counts": counts, "replication_prior_overlap": exclusions}, flush=True)


def sensitivity(rows, allowed, mapping, specification):
    metrics = specification["metrics"]
    difference = {}
    for identity in sorted(allowed):
        chosen = [row for row in rows if row["id"] == identity]
        paired = {}
        for arm in ("original_rules", "rule_residual"):
            observations = [row for row in chosen if row["arm"] == arm]
            if len(observations) != 2:
                raise ValueError("Incomplete paired actual output")
            paired[arm] = np.mean([[row[key] for key in metrics] for row in observations], axis=0)
        difference[identity] = paired["rule_residual"] - paired["original_rules"]
    components = sorted({mapping[identity] for identity in allowed})
    groups = [np.asarray([difference[identity] for identity in sorted(allowed) if mapping[identity] == component]) for component in components]
    means = np.asarray([group.mean(0) for group in groups])
    totals = np.asarray([group.sum(0) for group in groups])
    counts = np.asarray([len(group) for group in groups])
    rng = np.random.default_rng(specification["seed"])
    indices = rng.integers(len(groups), size=(specification["draws"], len(groups)))
    bootstraps = {"equal_weight_per_audited_entity": means[indices].mean(1),
        "original_document_weight_with_entity_resampling": totals[indices].sum(1) / counts[indices].sum(1)[:, None]}
    points = {"equal_weight_per_audited_entity": means.mean(0),
        "original_document_weight_with_entity_resampling": totals.sum(0) / counts.sum()}
    summaries = {}
    for estimand, bootstrap in bootstraps.items():
        interval = np.quantile(bootstrap, specification["interval_quantiles"], axis=0)
        summaries[estimand] = {key: {"difference": float(points[estimand][index]),
            "CI97_5": interval[:, index].tolist()} for index, key in enumerate(metrics)}
    return {"documents": len(allowed), "audited_entity_components": len(components),
        "ordered_component_ids": components, "estimands": summaries}


def analyze(workspace, seal_path, output):
    seal = load(seal_path)
    if sha(__file__) != seal["auditor_source_sha256"]:
        raise ValueError("Alias decision or analysis code changed after source-only seal")
    for manifest in seal["source_manifests"]:
        if sha(manifest["path"]) != manifest["sha256"]:
            raise ValueError("Source metadata changed after alias review")
    physical, corporate = seal["physical_component"], seal["corporate_family_component"]
    first = {r["id"] for r in seal["source_rows"] if r["cohort"] == "first"}
    replication = {r["id"] for r in seal["source_rows"] if r["cohort"] == "replication"}
    rows = {key: load(workspace / "natural-v2-runs" / study / "ROWS.json")
        for key, study in (("first", "document-qualification-001"), ("replication", "document-replication-001"))}
    partitions = {"first_all_physical": ("first", first, physical),
        "replication_all_physical": ("replication", replication, physical),
        "replication_no_prior_physical": ("replication", replication - set(seal["replication_with_prior_source_overlap"]["physical"]), physical),
        "replication_no_prior_corporate_family": ("replication", replication - set(seal["replication_with_prior_source_overlap"]["corporate_family"]), corporate)}
    result = {"schema": "hepta.ndu.closure-v2.natural.document-alias-sensitivity.v1",
        "analyzed_ns": time.time_ns(), "source_only_seal_sha256": sha(seal_path),
        "posthoc_diagnostic_not_new_qualification": True, "original_protocol_model_and_results_unchanged": True,
        "new_model_generation_or_fitting": False,
        "result": {name: sensitivity(rows[key], allowed, mapping, seal["bootstrap_frozen_before_sensitivity"])
            for name, (key, allowed, mapping) in partitions.items()},
        "interpretation": "The original 128 normalized-name experiment is reproducible, but it does not establish 128 independent previously unseen physical merchants. Removing source-only identified overlaps is a diagnostic using existing outputs, not a fresh confirmatory qualification. Strict prospective entity-resolved source isolation remains a separate boundary."}
    save_new(output, result)
    print({"sensitivity": str(output), "posthoc_only": True,
        "partitions": {key: {"documents": row["documents"], "entities": row["audited_entity_components"],
            "quality": row["estimands"]["equal_weight_per_audited_entity"]["quality"],
            "cost_adjusted_return": row["estimands"]["equal_weight_per_audited_entity"]["cost_adjusted_return"]} for key, row in result["result"].items()}}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "analyze"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seal", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze(args.workspace, args.output)
    elif args.seal is None:
        raise ValueError("The source-only seal is required before sensitivity analysis")
    else:
        analyze(args.workspace, args.seal, args.output)
