"""Fit only a pre-existing Circuit's router from one original A correction."""

import argparse
import fcntl
import os
from pathlib import Path
import sys
import tempfile

from . import adoption, chat_protocol, coding_sft, data, paired_cold, paired_consumer_circuit
from . import paired_consumer_run, paired_freeze, paired_intake, paired_source, paired_source_train
from . import prospective_exposure
from .online_v4 import circuit_bundle as circuit, circuit_router

require = adoption.require
POLICY = "hepta.paired-learning.router-only.v1"
d = data.digest
read = adoption.read_json
keep = paired_source_train.agree_or_write


def source_hash():
    paths = [Path(__file__), *(Path(m.__file__) for m in (
        paired_source, paired_source_train, paired_intake, paired_freeze, paired_cold,
        paired_consumer_circuit, paired_consumer_run, prospective_exposure))]
    return d([circuit.execution_binding(), {p.name: coding_sft.file_hash(p) for p in paths}])


def check_plan(plan):
    require(set(plan) == {"schema", "study", "delivery", "failure", "correction", "parent",
                          "retention", "trainer_source_sha256", "timeout_seconds"}
            and plan["schema"] == POLICY and plan["failure"] != plan["correction"]
            and type(plan["timeout_seconds"]) is int and 0 < plan["timeout_seconds"] <= 7200,
            "expected one original correction and one fixed router-only plan")
    for key in ("study", "delivery", "failure", "correction", "parent", "retention", "trainer_source_sha256"):
        paired_source.sha(plan[key])
    require(plan["trainer_source_sha256"] == source_hash(), "router trainer changed")


def inspect_node(model, node, root):
    task, pred = node["request"], node["output"]
    tok = paired_cold.frozen_tokenizer(model, root)
    rendered = coding_sft.prompt_text(task["input"], tok, model["runtime"]["message_protocol"], task.get("messages"))
    return paired_consumer_run.inspect_cell(model, task, pred, tok, rendered, tok.encode(rendered, add_special_tokens=False))


def review_search(root, folder, parent, example):
    """Replay the original scored topologies, relays and actual slot tokenizations."""
    search, plan, raw = (read(folder / name) for name in ("SEARCH.json", "PLAN.json", "BUNDLE.json"))
    router, cells, budget = circuit._components(parent)
    rows = search["observations"]
    graphs = [circuit._graph(g) for g in parent["router"]["graphs"]]
    require(raw["models"] == parent["models"] and raw["budget"] == parent["budget"]
            and raw["parent"] == d(parent) and raw["router"]["graphs"] == parent["router"]["graphs"]
            and raw["router"]["plan"] == parent["router"]["plan"]
            and raw["router"]["training_record_digests"] == plan["record_digests"] == [d(example)]
            and raw["router"]["training_plan_digest"] == search["plan_digest"] == d(plan)
            and read(folder / "ROUTER.json") == raw["router"]
            and search["router_digest"] == raw["router_sha256"] == d(raw["router"])
            and len(rows) == len(graphs), "original router study or retained Cells differ")
    verified = []
    for g, row in zip(graphs, rows, strict=True):
        require(row["graph_id"] == g.graph_id and row["task_id"] == example["task_id"]
                and row["result_path"] == f"task-0000/{g.graph_id}/RESULT.json", "search graph differs")
        result = paired_source.read_bound(folder / row["result_path"], row["result_digest"])
        task, nodes = circuit._task(paired_cold.visible_task(example)), result["nodes"]
        require(len(nodes) == len(g.path), "missing search node")
        for i, (key, node) in enumerate(zip(g.path, nodes, strict=True)):
            require(node["cell_id"] == key and node["slot"] == i
                    and node["request"] == circuit._request(task, g, i, nodes, budget), "search relay differs")
            inspect_node(parent["models"][key], node, root)
        score = data.verify_answer(example, nodes[-1]["output"]["answer"])
        require(d(score) == d(result["outcome"]) and score["success"] is result["success"] is row["success"]
                and result["cost"] == row["cost"] == dict(circuit._cost(nodes), verifier_calls=1),
                "search scoring or prices differ")
        verified.append((row, result))
    return raw, verified


def exposure(parent, records, example, verified, root):
    prompts, tokens = paired_consumer_circuit.training_inputs(parent, root)
    keys, catalogs = set(), {}
    for manifest in (parent, *parent["models"].values()):
        prior = manifest.get("paired_source_exposure", {})
        prompts.update(prior.get("known_prompt_hashes", []))
        tokens.update(prior.get("input_ids_sha256", []))
        keys.update(prior.get("source_keys", []))
        direct = prospective_exposure.catalog_for(manifest)
        for cat in [*prior.get("registered_catalogs", []), *([direct] if direct else [])]:
            catalogs[d(cat)] = cat
            tokens.update(r["input_ids_sha256"] for r in cat["known_inputs"])
            prompts.update(r["prompt_sha256"] for r in cat["known_inputs"])
    tokens.update(row["input_ids_sha256"] for row in parent["router_training_inputs"])
    current_keys = set.union(*(paired_source.known_source_keys(r) for r in records))
    prompt = paired_source.text_sha(example["task"]["input"])
    current_tokens = {node["output"]["input_ids_sha256"] for _, result in verified for node in result["nodes"]}
    return dict(schema="hepta.paired-learning.source-exposure.v1", record_digests=[d(r) for r in records],
                prompt_sha256=prompt, known_prompt_hashes=sorted(prompts | {prompt}),
                input_ids_sha256=sorted(tokens | current_tokens), source_keys=sorted(keys | current_keys),
                registered_catalogs=[catalogs[k] for k in sorted(catalogs)],
                current_source_keys=sorted(current_keys), current_input_ids=sorted(current_tokens))


def _fit(root, plan, owner, *, engineering=False):
    check_plan(plan)
    require(engineering == (owner.get("schema") == "engineering_fixture"), "owner or fixture scope differs")
    if not engineering:
        from . import paired_people
        require(owner["use"] == "train" and owner["study_sha256"] == plan["study"]
                and owner["delivery_id"] == plan["delivery"], "source grant differs")
        paired_people.check_training_statement(owner, dict(failure_sha256=plan["failure"], correction_sha256=plan["correction"], study_sha256=plan["study"]))
    root = Path(root)
    parent = paired_source.read_bound(root / "parent.json", plan["parent"])
    circuit.checked_bundle(parent, root)
    paired_consumer_circuit.training_inputs(parent, root)
    panel = paired_source.read_bound(root / "retention.json", plan["retention"])
    paired_cold.checked_panels({"retention": panel}, parent["runtime"])
    records = [paired_source.read_bound(root / (k + ".json"), plan[k]) for k in ("failure", "correction")]
    example = paired_source.derive(*records, root / "originals")
    source_keys = set.union(*(paired_source.known_source_keys(r) for r in records))
    require(all(r["split"] != "train" and r["authorization"]["training_allowed"] is False
                and not source_keys.intersection(paired_source.known_source_keys(r)) for r in panel),
            "old panel overlaps A or permits training")
    tokenizer = paired_cold.frozen_tokenizer(parent, root)
    def input_ids(row):
        task = row["task"]
        text = coding_sft.prompt_text(task["input"], tokenizer, parent["runtime"]["message_protocol"], task.get("messages"))
        ids = tokenizer.encode(text, add_special_tokens=False)
        require(0 < len(ids) <= parent["runtime"]["max_input_tokens"], "source input outside parent budget")
        return ids
    require(all(input_ids(r) != input_ids(example) for r in panel), "source and retention share token IDs")
    op = root / "paired-training" / d([plan["study"], plan["failure"], plan["correction"]])
    op.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (op / "lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        keep(op / "PLAN.json", plan)
        keep(op / "OWNER.json", owner)
        search = op / "router-search"
        if not search.exists():
            with tempfile.TemporaryDirectory(dir=op) as tmp:
                staged = Path(tmp) / "search"
                circuit.fit_bundle([example], parent["models"], [circuit._graph(g) for g in parent["router"]["graphs"]],
                                   circuit.Budget(**parent["budget"]), root, staged, parent=d(parent))
                os.rename(staged, search)
                paired_source.sync_directory(op)
        raw, verified = review_search(root, search, parent, example)
        scope = "engineering_fixture" if engineering else "owner_intake"
        receipt = dict(schema=POLICY, study_sha256=plan["study"], scope=scope, source_plan_sha256=d(plan),
                       owner_receipt_sha256=d(owner), failure_sha256=plan["failure"], correction_sha256=plan["correction"],
                       derived_record_sha256=d(example), parent_sha256=d(parent), topology_source="original_parent_router",
                       search_sha256=d(read(search / "SEARCH.json")), cell_manifests={k:d(v) for k,v in parent["models"].items()},
                       scores=[{"graph":r["graph_id"],"success":r["success"],"raw_result_sha256":r["result_digest"]} for r,_ in verified],
                       future_records_consumed=0, cell_parameters_updated=0, payment_authorized=False)
        keep(op / "ROUTER-FIT.json", receipt)
        scores = {r["success"] for r,_ in verified}
        if len(scores) < 2 or raw["router"]["weights"] == parent["router"]["weights"]:
            result = dict(receipt, decision="no_update_no_distinct_graph_success" if len(scores) < 2 else "no_update_unchanged_router")
            keep(op / "NO_UPDATE.json", result)
            return result, op
        candidate = dict(raw, paired_source_exposure=exposure(parent, records, example, verified, root))
        # Retain prior adapted Cells' original material bindings verbatim.
        if "consumer_cell_training_receipts" in parent:
            candidate["consumer_cell_training_receipts"] = parent["consumer_cell_training_receipts"]
        require(paired_cold.checked_models(parent, candidate) == dict(changed_cell_weights=[], router_weights_changed=True),
                "expected exactly a router change")
        spec = dict(parent=parent, candidate=candidate, retention=panel, timeout_seconds=plan["timeout_seconds"])
        keep(op / "freeze-spec.json", spec)
        snapshot = dict(schema=paired_freeze.FREEZE_SCHEMA, **spec)
        if not (op / "FROZEN.json").exists():
            paired_freeze.freeze(op / "freeze-spec.json", root, op / "FROZEN.json")
        paired_source.read_bound(op / "FROZEN.json", d(snapshot))
        completed = dict(schema="hepta.paired-learning.source-completion.v1", update_scope=POLICY, scope=scope,
                         study_sha256=plan["study"], source_plan_sha256=d(plan), owner_receipt_sha256=d(owner),
                         failure_sha256=plan["failure"], correction_sha256=plan["correction"], parent_sha256=d(parent),
                         candidate_sha256=d(candidate), freeze_sha256=d(snapshot), training_receipt_sha256=d(receipt),
                         future_records_consumed=0, independent_human_identity_established=False)
        keep(op / "COMPLETED.json", completed)
        return completed, op


def verify_originals(folder, snapshot, completed):
    """Rebuild the router-source bindings from original A and per-topology receipts."""
    root = folder.parent.parent
    plan = paired_source.read_bound(folder / "PLAN.json", completed["source_plan_sha256"])
    check_plan(plan)
    parent = paired_source.read_bound(root / "parent.json", plan["parent"])
    require(parent == snapshot["parent"] and d(snapshot["retention"]) == plan["retention"], "wrong source graph or panel")
    records = [paired_source.read_bound(root / (key + ".json"), plan[key]) for key in ("failure", "correction")]
    example = paired_source.derive(*records, root / "originals")
    raw, verified = review_search(root, folder / "router-search", parent, example)
    expected = dict(raw, paired_source_exposure=exposure(parent, records, example, verified, root))
    if "consumer_cell_training_receipts" in parent:
        expected["consumer_cell_training_receipts"] = parent["consumer_cell_training_receipts"]
    receipt = paired_source.read_bound(folder / "ROUTER-FIT.json", completed["training_receipt_sha256"])
    require(snapshot["candidate"] == expected and {r["success"] for r, _ in verified} == {False, True}
            and receipt["search_sha256"] == d(read(folder / "router-search/SEARCH.json"))
            and receipt["derived_record_sha256"] == d(example) and receipt["owner_receipt_sha256"] == completed["owner_receipt_sha256"]
            and receipt["failure_sha256"] == completed["failure_sha256"] == plan["failure"]
            and receipt["correction_sha256"] == completed["correction_sha256"] == plan["correction"],
            "original router fit, retained exposures or grants differ")


def main():
    from . import paired_source_gate
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("materials", "spec", "spec_sha", "consent_binary", "binary_sha", "root_pid", "sqlite_home", "route"):
        p.add_argument(arg)
    a = p.parse_args()
    os.fstat(3)
    os.fstat(4)
    plan = paired_source.read_bound(a.spec, a.spec_sha)
    check_plan(plan)
    with open(a.consent_binary, "rb") as f:
        require(f.read(4) == b"\x7fELF", "registered Linux native consent binary required")
    try:
        grant = paired_intake.verify_live(a.consent_binary, a.binary_sha, plan["study"], plan["delivery"],
                                        dict(use="train", failure=plan["failure"], correction=plan["correction"]),
                                        (a.root_pid, a.sqlite_home, a.route))
    finally:
        os.close(3)
        os.close(4)
    result, op = _fit(a.materials, plan, grant)
    if "freeze_sha256" in result:
        result = paired_source_gate.gate(Path(a.materials), op)
    print(data.canonical(result).decode())


if __name__ == "__main__":
    main()
