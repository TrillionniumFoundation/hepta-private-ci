"""Live-owner admitted batch reads; gold and source values stay in the parent."""

from dataclasses import asdict

from retention_common import digest, remaining_timeout, require, retain
from longitudinal_scoring import questions, score_round
from model_process import run_decoder


def read_panels(
    service, request, snapshot, previous, panels, directory, timeout, deadline
):
    binding = service.parameter_binding()
    require(
        binding is not None and service.snapshot() == snapshot,
        "live published source snapshot required for decoder admission",
    )
    for fact in snapshot["facts"]:
        require(
            service.read(fact["entity"], fact["relation"]).status.value == "answered",
            "all panel keys must be current and unconflicted",
        )
    train_questions = questions(snapshot, panels["train_templates"])
    heldout_questions = questions(snapshot, panels["heldout_templates"])
    cwd = directory / "reader-cwd"
    cwd.mkdir(exist_ok=False)
    results, journals = {}, {}
    for control in ("adapter", "base", "shuffled"):
        chosen = (
            train_questions + heldout_questions
            if control == "adapter"
            else heldout_questions
        )
        read_request = dict(
            model=request["base"],
            snapshot=binding["active"].directory,
            manifest_sha256=binding["active"].manifest_sha256,
            scope=snapshot["scope"],
            allowed_roots=list(binding["active"].roots),
            questions=chosen,
            rank=request["rank"],
            seed=request["seed"],
            control=control,
        )
        retain(directory / f"{control}.request.json", read_request)
        require(not list(cwd.iterdir()), "decoder working directory must be empty")

        def invoke(active):
            require(
                active == binding["active"] and service.snapshot() == snapshot,
                "source or selected adapter changed before batch dispatch",
            )
            return run_decoder(
                read_request,
                timeout=remaining_timeout(deadline, timeout),
                cwd=cwd,
                receipt_dir=directory / "processes",
            )

        journal = service.owner.invoke(
            service.store.cell_id, service.store.scope, service.authority_view, invoke
        )
        require(
            service.parameter_binding() == binding and service.snapshot() == snapshot,
            "source or selected adapter changed during batch inference",
        )
        require(
            not list(cwd.iterdir()),
            "decoder unexpectedly wrote in its working directory",
        )
        retain(directory / f"{control}.journal.json", journal)
        journals[control] = journal
        heldout = journal
        if control == "adapter":
            training = journal | {"rows": journal["rows"][: len(train_questions)]}
            results["training_diagnostic"] = score_round(
                snapshot, previous, [], training, panels["train_templates"]
            )
            heldout = journal | {"rows": journal["rows"][len(train_questions) :]}
        results[control] = score_round(
            snapshot,
            previous,
            panels["final_events"],
            heldout,
            panels["heldout_templates"],
        )
    reference = journals["adapter"]["rows"][-len(heldout_questions) :]
    for control in ("base", "shuffled"):
        require(
            [r["prompt_token_ids"] for r in journals[control]["rows"]]
            == [r["prompt_token_ids"] for r in reference],
            "controls used different prompts",
        )
        require(
            journals[control]["admitted_adapter_state_sha256"]
            == journals["adapter"]["admitted_adapter_state_sha256"],
            "controls loaded a different trained adapter",
        )
    require(
        journals["shuffled"]["consumed_adapter_state_sha256"]
        != journals["adapter"]["consumed_adapter_state_sha256"],
        "shuffle control did not change weights",
    )
    all_rows = [r for journal in journals.values() for r in journal["rows"]]
    results["decoder_cost"] = dict(
        queries=len(all_rows),
        input_tokens=sum(r["input_tokens"] for r in all_rows),
        generated_tokens=sum(r["generated_tokens"] for r in all_rows),
        generation_seconds=sum(r["seconds"] for r in all_rows),
        fresh_processes=len(journals),
        process_ids=[j["decoder_process"]["pid"] for j in journals.values()],
        child_wall_seconds=sum(
            j["decoder_process"]["wall_seconds"] for j in journals.values()
        ),
    )
    return results


def withdrawal_probe(service, snapshot):
    source = next(s for s in snapshot["sources"] if s["source_id"] == "long_00")
    receipt = service.revoke(source["source_id"], source["revision"])
    calls, reads = [], []
    for entity in ("long_00", "long_01"):
        response = service.invoke_parameter(
            entity,
            "color",
            f"Return the retained color for {entity}.",
            lambda *_: calls.append(entity),
        )
        reads.append(dict(entity=entity, result=response))
    require(
        not calls
        and [r["result"]["status"] for r in reads] == ["revoked", "unavailable"],
        "withdrawal allowed a stale decoder callback",
    )
    require(
        service.parameter_binding() is None, "withdrawal left old parameters current"
    )
    return dict(
        receipt=asdict(receipt),
        reads=reads,
        decoder_callbacks=len(calls),
        source_snapshot_after_sha256=digest(service.snapshot()),
        physical_parameter_erasure_claim=False,
    )


def summarize(protocol, trials):
    ranking = []
    for arm in protocol["tie_order"]:
        rows = [t for t in trials if t["arm"] == arm]
        complete = len(rows) == len(protocol["seeds"]) and all(
            t["status"] == "complete" for t in rows
        )
        scores = (
            [
                min(
                    t["scores"]["adapter"][name]["accuracy"]
                    for name in ("source_both_wordings", "unchanged_retention")
                )
                for t in rows
            ]
            if complete
            else []
        )
        quality = complete and all(
            t["scores"]["adapter"]["source_both_wordings"]["accuracy"] >= 0.9
            and t["scores"]["adapter"]["unchanged_retention"]["accuracy"] >= 0.9
            and t["scores"]["adapter"]["corrected_sources"]["all_exact"]
            and all(
                t["scores"]["adapter"]["source_both_wordings"]["accuracy"]
                > t["scores"][c]["source_both_wordings"]["accuracy"]
                for c in ("base", "shuffled")
            )
            for t in rows
        )
        ranking.append(
            dict(
                arm=arm,
                complete=complete,
                worst_seed=min(scores) if scores else None,
                mean_seed=sum(scores) / len(scores) if scores else None,
                exposed_development_quality_gate=quality,
            )
        )
    eligible = [r for r in ranking if r["complete"]]
    eligible.sort(
        key=lambda r: (
            -r["worst_seed"],
            -r["mean_seed"],
            protocol["tie_order"].index(r["arm"]),
        )
    )
    return dict(
        arms=ranking,
        selected_arm=eligible[0]["arm"] if len(eligible) == len(ranking) else None,
        selection_is_development_only=True,
        future_gate_satisfied=False,
        retrieval_superiority_established=False,
        production_accepted=False,
    )
