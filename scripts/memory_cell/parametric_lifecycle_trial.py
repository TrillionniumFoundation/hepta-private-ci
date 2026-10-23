"""Real adapter correction, descendant withdrawal and clean-base replay trial."""

from pathlib import Path

from parametric_cohort import fact, questions, score, TEST_TEMPLATE, VALUES
from parametric_owner import Frontier, ParametricOwner


def run_lifecycle(
    cell,
    *,
    model,
    parent_dir,
    parent_sha,
    facts,
    output,
    steps,
    learning_rate,
    templates,
    derived_cells,
    read_worker,
    write_json,
):
    output = Path(output)
    output.mkdir()
    (output / "reader-cwd").mkdir()
    scope = facts[0]["scope"]
    original_roots = {f["source_digest"] for f in facts}
    view = Frontier(scope)
    owner_path = output / "owner.sqlite3"
    owner = ParametricOwner(owner_path)
    current = owner.activate(
        "memory",
        parent_dir,
        parent_sha,
        scope=scope,
        expected_current=None,
        generation=0,
        provider=lambda: view,
        allowed_roots=original_roots,
    )
    descendants = []
    for index, derived in enumerate(derived_cells):
        derived_roots = set(derived["roots"])
        if not original_roots <= derived_roots:
            raise ValueError("derived adapter omitted inherited source roots")
        key = f"derived-{index}"
        owner.activate(
            key,
            derived["directory"],
            derived["manifest_sha256"],
            scope=scope,
            expected_current=None,
            generation=0,
            provider=lambda: view,
            allowed_roots=derived_roots,
        )
        descendants.append(key)

    cell.load(
        parent_dir,
        expected_manifest_sha256=parent_sha,
        scope=scope,
        allowed_roots=original_roots,
        revoked=set(),
    )
    corrected = [dict(f) for f in facts]
    for index in (0, 1):
        old = facts[index]
        corrected[index] = fact(
            scope,
            old["entity"],
            VALUES[(VALUES.index(old["value"]) + 1) % len(VALUES)],
            revision=1,
        )
    correction_receipt = cell.fit_sources(corrected, steps, learning_rate, templates)
    write_json(output / "correction-write.json", correction_receipt)
    corrected_dir = output / "corrected-cell"
    corrected_sha = cell.save(corrected_dir)
    corrected_roots = set(cell.reader.roots)
    owner.activate(
        "memory",
        corrected_dir,
        corrected_sha,
        scope=scope,
        expected_current=current.manifest_sha256,
        generation=1,
        parent_manifest_sha256=current.manifest_sha256,
        provider=lambda: view,
        allowed_roots=corrected_roots,
    )
    corrected_journal = owner.invoke(
        "memory",
        scope,
        lambda: view,
        lambda active: read_worker(
            model,
            active.directory,
            active.manifest_sha256,
            scope,
            active.roots,
            questions(corrected, TEST_TEMPLATE),
            output,
            "corrected",
        ),
    )
    correction_scores = dict(
        all=score(corrected_journal["rows"], corrected),
        revised=score(corrected_journal["rows"][:2], corrected[:2]),
        retained=score(corrected_journal["rows"][2:], corrected[2:]),
    )

    revoked = {facts[0]["source_digest"], corrected[0]["source_digest"]}
    view = Frontier(scope, epoch=1, revoked=tuple(sorted(revoked)))
    forward_calls = []

    def forbidden(_):
        forward_calls.append(True)
        raise AssertionError("revoked cell reached model execution")

    rejected = []
    for key in ["memory", *descendants]:
        try:
            owner.invoke(key, scope, lambda: view, forbidden)
        except ValueError as error:
            rejected.append(dict(cell=key, error=str(error)))
        else:
            raise AssertionError("withdrawn learned ancestor remained available")
    restarted = ParametricOwner(owner_path)
    try:
        restarted.invoke("memory", scope, lambda: Frontier(scope), forbidden)
    except ValueError as error:
        restart_rejection = str(error)
    else:
        raise AssertionError("restart forgot the observed withdrawal frontier")

    remaining = corrected[1:]
    cell.reset(scope)
    rebuilt_receipt = cell.fit_sources(remaining, steps, learning_rate, templates)
    if (
        rebuilt_receipt["initialization"] != "frozen_base"
        or rebuilt_receipt["learned_parent_manifest_sha256"] is not None
        or rebuilt_receipt["inherited_roots"]
        or set(rebuilt_receipt["roots"]) != {f["source_digest"] for f in remaining}
    ):
        raise ValueError(
            "delete recovery must replay from clean base with exact allowed roots"
        )
    write_json(output / "clean-replay-write.json", rebuilt_receipt)
    rebuilt_dir = output / "rebuilt-cell"
    rebuilt_sha = cell.save(rebuilt_dir)
    restarted.activate(
        "memory",
        rebuilt_dir,
        rebuilt_sha,
        scope=scope,
        expected_current=corrected_sha,
        generation=2,
        parent_manifest_sha256=corrected_sha,
        provider=lambda: view,
        allowed_roots=set(rebuilt_receipt["roots"]),
    )
    restored_journal = restarted.invoke(
        "memory",
        scope,
        lambda: view,
        lambda active: read_worker(
            model,
            active.directory,
            active.manifest_sha256,
            scope,
            active.roots,
            questions(remaining, TEST_TEMPLATE),
            output,
            "rebuilt",
        ),
    )
    try:
        restarted.invoke(
            "memory",
            scope,
            lambda: view,
            forbidden,
            query_roots=(facts[0]["source_digest"],),
        )
    except ValueError as error:
        query_rejection = str(error)
    else:
        raise AssertionError("deleted source query remained available")
    # Raw model behavior on unknown keys is measured, not claimed as certified erasure.
    unknown_journal = read_worker(
        model,
        rebuilt_dir,
        rebuilt_sha,
        scope,
        rebuilt_receipt["roots"],
        [questions(facts[:1], TEST_TEMPLATE)[0], "Which color did we assign to Zelda?"],
        output,
        "unknown-diagnostic",
    )
    result = dict(
        schema="hepta.parametric-memory.lifecycle-trial.v1",
        correction=correction_scores,
        clean_replay_recall=score(restored_journal["rows"], remaining),
        withdrawal_rejections=rejected,
        forward_calls_on_revoked=len(forward_calls),
        restart_frontier_rejection=restart_rejection,
        deleted_query_rejection=query_rejection,
        clean_base_replay_verified=True,
        exact_replayed_roots=rebuilt_receipt["roots"],
        deleted_roots=sorted(revoked),
        unknown_raw_answers=[r["text"] for r in unknown_journal["rows"]],
        parameter_unlearning_statistically_proven=False,
        provider_authenticated=False,
        current_manifest_sha256=rebuilt_sha,
        current_generation=2,
        production_accepted=False,
    )
    write_json(output / "result.json", result)
    return result
