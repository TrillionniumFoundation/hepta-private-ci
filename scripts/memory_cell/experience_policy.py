"""Small source-supervised read policy for the controlled event experiment.

This is not a natural-language extractor or a production authority. The public
lookup grammar supplies entities/paths, never gold values. Ten weights are learned
from calibration-scope event relations; test questions and answers are absent.
"""

from dataclasses import asdict
import math
import re
import time

from event_projection import EventProjection, Lookup
from event_revision_closure import select_current
from native import digest

PROFILE = "hepta.controlled-event.learned-read.v1"
INITIAL = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
STEPS = 192


def lookup_from_question(query):
    """Parse only the existing explicit controlled-task grammar, not gold labels."""
    match = re.fullmatch(
        r"For ([a-zA-Z0-9_-]{1,96}) at logical revision ([0-9]{1,5}), what is "
        r"(the location|the location of the assigned component|"
        r"the mode that actually succeeded for the assigned component)\? "
        r"Reply with only the single recorded site_ or mode_ identifier followed by supporting "
        r"\[E1\], \[E2\] labels, without other words\. "
        r"Respect explicit supersedes events; later effective revisions do not apply\.",
        query.content,
    )
    if not match:
        raise ValueError("outside the public controlled lookup grammar")
    path = {
        "the location": ("location",),
        "the location of the assigned component": ("component", "location"),
        "the mode that actually succeeded for the assigned component": (
            "component", "successful_mode"
        ),
    }[match[3]]
    lookup = Lookup(match[1], path, int(match[2]))
    lookup.validate()
    return lookup


def candidate_features(projection, lookup, candidates, selected, *, revoked):
    projection.select(lookup, candidates, mode="hybrid", revoked=revoked, limit=8)
    if len(selected) >= len(lookup.path) or any(k not in candidates for k in selected):
        raise ValueError("invalid sequential selection state")
    depth = len(selected)
    entity = projection.facts[selected[-1]]["value"] if selected else lookup.entity
    retired = {
        old for row in projection.facts.values() if row["revision"] <= lookup.revision
        for old in row["supersedes"]
    }
    ids, features = [], []
    for rank, key in enumerate(candidates):
        if key in selected:
            continue
        row = projection.facts[key]
        entity_match = row["entity"] == entity
        attribute_match = row["attribute"] == lookup.path[depth]
        visible = row["revision"] <= lookup.revision
        current = visible and key not in retired
        features.append((
            float(entity_match), float(attribute_match),
            float(entity_match and attribute_match), float(current),
            float(not visible), float(key in retired),
            float(entity_match and attribute_match and current),
            1.0 / (rank + 1), float(depth > 0), 1.0,
        ))
        ids.append(key)
    return tuple(ids), tuple(features)


def choose(projection, lookup, candidates, weights=INITIAL, *, revoked):
    """Rank each next event without injecting facts from outside the same pool."""
    if len(weights) != len(INITIAL) or any(
        type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100
        for v in weights
    ):
        raise ValueError("invalid read-policy weights")
    selected, decisions = [], []
    for _ in lookup.path:
        ids, vectors = candidate_features(
            projection, lookup, candidates, selected, revoked=revoked
        )
        if not ids:
            break
        scores = [sum(a * b for a, b in zip(weights, x, strict=True)) for x in vectors]
        winner = min(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
        selected.append(ids[winner])
        decisions.append(dict(
            candidates=ids, feature_digest=digest(vectors),
            scores=scores, selected=ids[winner],
        ))
    return tuple(selected), dict(
        profile=PROFILE, decisions=decisions, weights_digest=digest(weights),
        source_event_reads=len(projection.facts) * len(decisions),
        scored_candidates=sum(len(d["candidates"]) for d in decisions),
        injected_out_of_pool_sources=0, independent_semantic_review=False,
    )


def fit_policy(documents, training_scopes, *, revision, reader_identity, revoked):
    """Source-only TRAIN projection; integer revisions are not calendar windows."""
    import torch

    write_started = time.perf_counter()
    scopes = tuple(sorted(training_scopes))
    if (
        not 1 <= len(scopes) <= 64 or len(scopes) != len(set(scopes))
        or not 1 <= len(documents) <= 2048
        or len({d.identity for d in documents}) != len(documents)
        or type(revision) is not int or not 0 <= revision <= 10000
        or not re.fullmatch(r"[a-f0-9]{64}", reader_identity)
        or not set(scopes).issubset({d.scope for d in documents})
    ):
        raise ValueError("bounded exact policy training admission required")
    train = tuple(d for d in documents if d.scope in scopes)
    if {d.root for d in train}.intersection(revoked):
        raise ValueError("withdrawn training source")
    prepared, dispositions = {}, []
    for scope in scopes:
        projection = EventProjection(tuple(d for d in train if d.scope == scope))
        pool = tuple(sorted(projection.facts))
        keys = sorted({(r["entity"], r["attribute"]) for r in projection.facts.values()})
        examples = []
        for entity, attribute in keys:
            paths = {(attribute,)}
            for row in projection.facts.values():
                if row["entity"] == entity and row["attribute"] == attribute:
                    paths.update((attribute, r["attribute"]) for r in projection.facts.values()
                                 if r["entity"] == row["value"])
            for path in sorted(paths):
                lookup = Lookup(entity, path, revision)
                selected, info = select_current(
                    projection, lookup, pool, revoked=revoked, limit=8
                )
                if info["incomplete"] or info["conflicts"] or len(selected) != len(path):
                    dispositions.append(dict(scope=scope, entity=entity, path=path,
                                             disposition="unknown_not_a_negative"))
                    continue
                # Traverse the source-defined path; source sorting is not path order.
                cursor, ordered = entity, []
                for attr in path:
                    matching = [k for k in selected
                                if (projection.facts[k]["entity"], projection.facts[k]["attribute"])
                                == (cursor, attr)]
                    if len(matching) != 1:
                        break
                    ordered.append(matching[0])
                    cursor = projection.facts[matching[0]]["value"]
                if len(ordered) == len(path):
                    examples.append((lookup, tuple(ordered)))
        if not examples:
            raise ValueError("no supported calibration paths in scope")
        prepared[scope] = (projection, pool, examples)
    count = sum(len(v[2]) for v in prepared.values())
    if count > 1024:
        raise ValueError("policy training projection exceeds budget")
    weight = torch.nn.Parameter(torch.tensor(INITIAL, dtype=torch.float64))
    before = weight.detach().clone()
    optimizer = torch.optim.AdamW([weight], lr=0.03)
    losses, operations = [], 0
    started = time.perf_counter()
    for step in range(STEPS):
        projection, original_pool, examples = prepared[scopes[step % len(scopes)]]
        lookup, targets = examples[(step // len(scopes)) % len(examples)]
        # Input ordering varies without using target labels to place candidates.
        pool = tuple(sorted(original_pool, key=lambda key: digest((step, key))))
        prefix, loss = [], weight.sum() * 0
        for target in targets:
            ids, x = candidate_features(projection, lookup, pool, prefix, revoked=revoked)
            features = torch.tensor(x, dtype=torch.float64)
            logits = features @ weight
            loss = loss + torch.logsumexp(logits, 0) - logits[ids.index(target)]
            operations += features.numel() * 6
            prefix.append(target)
        loss = loss / len(targets) + 0.001 * (weight - before).square().sum()
        if not torch.isfinite(loss):
            raise ValueError("nonfinite learned read objective")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_([weight], 1.0, error_if_nonfinite=True)
        optimizer.step()
        if not torch.isfinite(weight).all() or weight.abs().max() > 100:
            raise ValueError("unbounded read policy update")
        losses.append(float(loss.detach()))
    delta = float((weight.detach() - before).square().sum())
    if not delta > 0:
        raise ValueError("no actual learned policy update")
    return dict(
        schema=PROFILE, weights=weight.detach().tolist(), initial=INITIAL,
        training_scopes=scopes, roots=sorted({d.root for d in train}), revision=revision,
        source_digest=digest([asdict(d) for d in train]), reader_identity=reader_identity,
        steps=STEPS, parameters=len(INITIAL), examples=count, losses=losses,
        dispositions=dispositions, delta_squared_norm=delta, operation_estimate=operations,
        training_seconds=time.perf_counter() - started,
        write_seconds=time.perf_counter() - write_started,
        retained_training_source_bytes=sum(len(d.content.encode()) for d in train),
        test_queries_consumed=False, supervision="controlled-source-relations-not-human-review",
        independent_review=False, production_accepted=False,
    )


def validate_policy(value, documents, *, reader_identity, test_scopes, revoked):
    if (
        value["schema"] != PROFILE or value["reader_identity"] != reader_identity
        or value["test_queries_consumed"] is not False
        or value["production_accepted"] is not False
        or type(value["revision"]) is not int
        or not 0 <= value["revision"] <= 10000
        or len(value["weights"]) != len(INITIAL)
        or tuple(value["initial"]) != INITIAL
        or not value["training_scopes"]
        or len(set(value["training_scopes"])) != len(value["training_scopes"])
        or set(value["training_scopes"]) & set(test_scopes)
        or any(type(w) not in (int, float) or not math.isfinite(w) or abs(w) > 100
               for w in value["weights"])
    ):
        raise ValueError("incompatible or test-overlapping learned policy")
    train = tuple(d for d in documents if d.scope in value["training_scopes"])
    test = tuple(d for d in documents if d.scope in test_scopes)
    roots = {d.root for d in train}
    if (
        roots != set(value["roots"]) or roots.intersection(revoked)
        or roots.intersection(d.root for d in test)
        or set(value["training_scopes"]) != {d.scope for d in train}
        or digest([asdict(d) for d in train]) != value["source_digest"]
    ):
        raise ValueError("policy ancestry/source drift or cross-task source sharing")
    return tuple(value["weights"])


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from bundle_trial import write
    from event_memory_trial import read
    from experience_write_trial import original_documents

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "scopes", "output"):
        parser.add_argument(name, type=Path)
    for name in ("source-sha", "scopes-sha", "reader-identity"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    source_documents = original_documents(args.sources, args.source_sha)
    train_scopes = read(args.scopes, args.scopes_sha)
    if not isinstance(train_scopes, list) or any(not isinstance(s, str) for s in train_scopes):
        raise ValueError("explicit list of calibration scopes required")
    policy = fit_policy(source_documents, train_scopes, revision=2,
                        reader_identity=args.reader_identity, revoked=set())
    write(args.output, policy)
