"""Opt-in tri-state external-span learning; unknown windows have zero loss.

Only the evidence residual is optimized. The existing null head and paired
encoder stay fixed. Span coverage is supervision, not semantic certification.
"""

from dataclasses import dataclass
import math
import time

import torch

from native import digest
from selector_head import EvidenceHead, Features, TrainingCut

PROFILE = "external-span-masked-evidence-only-v1"


@dataclass(frozen=True)
class SpanLabels:
    features: Features
    positive_indices: tuple[int, ...]
    negative_indices: tuple[int, ...]
    annotation_digest: str


def masked_rows(queries, corpus, pools, features, cut):
    rows, dispositions = [], []
    for query in queries:
        if query.identity not in cut.question_ids or query.family not in cut.families:
            raise ValueError("outside external training cut")
        pool, feature = pools[query.identity], features[query.identity]
        target, doc = corpus.targets[query.identity], corpus.documents[query.scope]
        if (
            target.source_digest != digest(doc.content)
            or target.source_id != doc.identity
            or feature.question_id != query.identity
            or feature.family != query.family
            or feature.pool_digest != pool.seal()
            or feature.candidate_ids != tuple(w.identity() for w in pool.windows)
            or feature.roots != frozenset(w.root for w in pool.windows)
        ):
            raise ValueError("external source, annotation or feature binding")
        positive = target.indices(query, pool)
        negative = tuple(range(len(pool.windows))) if target.unanswerable else ()
        unknown = tuple(
            i for i in range(len(pool.windows)) if i not in positive + negative
        )
        note = dict(
            question_id=query.identity,
            annotation_digest=target.annotation_digest,
            pool_digest=pool.seal(),
            positive_ids=[feature.candidate_ids[i] for i in positive],
            negative_ids=[feature.candidate_ids[i] for i in negative],
            unknown_ids=[feature.candidate_ids[i] for i in unknown],
            unanswerable=target.unanswerable,
            negative_scope="only the externally annotated unanswerable paragraph",
        )
        if positive or negative:
            rows.append(SpanLabels(feature, positive, negative, target.annotation_digest))
            note["status"] = "external_tri_state_window_supervision"
        else:
            note["status"] = (
                "no_candidate_no_gradient"
                if target.unanswerable
                else "annotated_span_not_visible_not_a_null_target"
            )
        dispositions.append(note)
    return tuple(rows), dispositions


def masked_loss(logits, row):
    """Mean binary logistic loss over annotated windows, never unknown/null."""
    if logits.ndim != 1 or len(logits) != len(row.features.candidate_ids) + 1:
        raise ValueError("window loss shape")
    positive, negative = row.positive_indices, row.negative_indices
    if not positive and not negative:
        raise ValueError("no observed window labels")
    losses = []
    if positive:
        losses.append(torch.nn.functional.softplus(-logits[list(positive)]))
    if negative:
        losses.append(torch.nn.functional.softplus(logits[list(negative)]))
    return torch.cat(losses).mean()


class EvidenceOnlySpanHead(EvidenceHead):
    def fit(self, rows, cut: TrainingCut, *, revoked, steps=192):
        if (
            not 1 <= len(rows) <= 256
            or type(steps) is not int
            or not 1 <= steps <= 1024
            or not cut.admission_digest
            or self.quarantined
            or not self.roots.issubset(cut.allowed_roots)
            or self.roots.intersection(revoked | cut.forbidden_roots)
        ):
            raise ValueError("bounded admitted available training required")
        groups, seen = {}, set()
        for row in rows:
            feature = row.features
            feature.validate(self.dimension)
            if (
                not isinstance(row, SpanLabels)
                or not row.annotation_digest
                or feature.encoder_identity != self.encoder_identity
                or feature.question_id in seen
                or feature.question_id not in cut.question_ids
                or feature.family not in cut.families
                or not feature.roots.issubset(cut.allowed_roots)
                or feature.roots.intersection(revoked | cut.forbidden_roots)
            ):
                raise ValueError("unadmitted, held-out or withdrawn span labels")
            indices = row.positive_indices + row.negative_indices
            if (
                not indices
                or len(set(indices)) != len(indices)
                or any(
                    type(i) is not int or not 0 <= i < len(feature.candidate_ids)
                    for i in indices
                )
            ):
                raise ValueError("missing, overlapping or invalid window labels")
            seen.add(feature.question_id)
            groups.setdefault(feature.family, []).append(row)
        for group in groups.values():
            group.sort(key=lambda row: row.features.question_id)
        families = sorted(groups)
        before = {name: value.clone() for name, value in self.state_dict().items()}
        # Freezing null parameters does not freeze acceptance: evidence scores
        # may move. The forced-choice comparison remains the primary contrast.
        self.null.requires_grad_(False)
        parameters = list(self.projection.parameters()) + list(self.residual.parameters())
        optimizer = torch.optim.AdamW(parameters, lr=0.001, weight_decay=0.01)
        losses, evaluated, labelled, started = [], 0, 0, time.perf_counter()
        try:
            for step in range(steps):
                family = families[step % len(families)]
                group = groups[family]
                row = group[(step // len(families)) % len(group)]
                optimizer.zero_grad(set_to_none=True)
                loss = masked_loss(self(row.features), row)
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite masked span loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(parameters, 1.0, error_if_nonfinite=True)
                optimizer.step()
                if any(not torch.isfinite(p).all() for p in self.parameters()):
                    raise ValueError("nonfinite masked span update")
                losses.append(float(loss.detach()))
                evaluated += len(row.features.candidate_ids)
                labelled += len(row.positive_indices) + len(row.negative_indices)
            if any(
                not torch.equal(value, before["null." + name])
                for name, value in self.null.state_dict().items()
            ):
                raise ValueError("masked training changed null parameters")
            delta = sum(
                float((value - before[name]).square().sum())
                for name, value in self.state_dict().items()
            )
            if not math.isfinite(delta) or delta <= 0:
                raise ValueError("no finite evidence parameter update")
            self.roots = self.roots.union(*(row.features.roots for row in rows))
            self.training_receipt = dict(
                objective=PROFILE,
                admission_digest=cut.admission_digest,
                data_digest=digest(
                    [
                        (
                            row.features.seal(),
                            row.positive_indices,
                            row.negative_indices,
                            row.annotation_digest,
                        )
                        for row in rows
                    ]
                ),
                rows=len(rows),
                families=families,
                steps=steps,
                pair_evaluations=evaluated,
                labelled_window_evaluations=labelled,
                unknown_window_evaluations=evaluated - labelled,
                unknown_windows_in_loss=False,
                trainable_parameters=sum(p.numel() for p in parameters),
                total_head_parameters=sum(p.numel() for p in self.parameters()),
                null_parameters_unchanged=True,
                encoder_updates=0,
                losses=losses,
                delta_squared_norm=delta,
                seconds=time.perf_counter() - started,
                training_roots=sorted(self.roots),
                production_accepted=False,
            )
            return self.training_receipt
        except Exception:
            self.quarantined = True
            raise
