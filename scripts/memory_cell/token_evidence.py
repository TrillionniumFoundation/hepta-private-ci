"""Answer-position learning on a frozen joint encoder, not entailment approval.

The native relevance logit stays a frozen comparator. Only a 2*d+2 token head
learns externally annotated starts/ends. Unlabelled windows receive no loss.
Predicted spans select evidence; they are NOT substituted for generated answers.
"""

from dataclasses import dataclass
import json
import math
import time

import torch
from torch import nn

from native import digest


@dataclass(frozen=True)
class TokenWindow:
    question_id: str
    family: str
    window_id: str
    root: str
    hidden: torch.Tensor
    offsets: tuple[tuple[int, int], ...]
    native_score: float

    def validate(self, dimension):
        if (
            not self.question_id
            or not self.family
            or not self.root
            or self.hidden.shape != (len(self.offsets), dimension)
            or not 1 <= len(self.offsets) <= 512
            or self.hidden.dtype != torch.float32
            or self.hidden.device.type != "cpu"
            or self.hidden.requires_grad
            or not torch.isfinite(self.hidden).all()
            or not math.isfinite(self.native_score)
            or self.offsets[0] != (-1, -1)
        ):
            raise ValueError("token evidence shape/identity/value")
        if any(a != -1 and not 0 <= a < b for a, b in self.offsets):
            raise ValueError("token byte offsets")

    def seal(self):
        return digest(
            (
                self.question_id,
                self.family,
                self.window_id,
                self.root,
                self.offsets,
                self.native_score,
                self.hidden.tolist(),
            )
        )


@torch.no_grad()
def encode_tokens(encoder, query, family, pool, *, revoked):
    pool.revalidate(query, revoked)
    records, inputs, tokens = [], [], 0
    started = time.perf_counter()
    question = f"As of {query.observed_at}: {query.content}"
    if len(encoder.tokenizer.encode(question, add_special_tokens=False)) > 192:
        raise ValueError("token encoder question budget")
    for window in pool.windows:
        prefix = f"Observed {window.observed_at}. Passage: "
        text = prefix + window.text
        packed = encoder.tokenizer(
            question,
            text,
            return_offsets_mapping=True,
            return_tensors="pt",
            truncation=False,
        )
        offsets = packed.pop("offset_mapping")[0].tolist()
        sequence = packed.sequence_ids(0)
        if packed["input_ids"].shape[1] > 512:
            raise ValueError("token encoder budget; no truncation")
        mapped = []
        for (a, b), side in zip(offsets, sequence, strict=True):
            if side == 1 and len(prefix) <= a < b <= len(text):
                start = window.start + len(window.text[: a - len(prefix)].encode())
                end = window.start + len(window.text[: b - len(prefix)].encode())
                mapped.append((start, end))
            else:
                mapped.append((-1, -1))
        result = encoder.model(**packed, output_hidden_states=True)
        record = TokenWindow(
            query.identity,
            family,
            window.identity(),
            window.root,
            result.hidden_states[-1][0].detach().cpu(),
            tuple(mapped),
            float(result.logits.flatten()[0]),
        )
        record.validate(encoder.dimension)
        records.append(record)
        tokens += int(packed["attention_mask"].sum())
        inputs.append({k: v.tolist() for k, v in sorted(packed.items())})
    return tuple(records), dict(
        input_digest=digest(inputs),
        pool_digest=pool.seal(),
        pair_tokens=tokens,
        seconds=time.perf_counter() - started,
        frozen_encoder=True,
    )


def position_labels(target, record):
    if target.question_id != record.question_id:
        raise ValueError("answer-position query mismatch")
    if target.unanswerable:
        if target.spans:
            raise ValueError("contradictory no-answer annotation")
        return ((0, 0),)
    pairs = set()
    for start, end, _ in target.spans:
        left = [i for i, (a, b) in enumerate(record.offsets) if a <= start < b]
        right = [i for i, (a, b) in enumerate(record.offsets) if a < end <= b]
        if left and right and 0 < left[0] <= right[-1]:
            pairs.add((left[0], right[-1]))
    return tuple(sorted(pairs))  # Unknown/out-of-view never becomes a null label.


class TokenEvidenceHead(nn.Module):
    def __init__(self, dimension, encoder_identity):
        super().__init__()
        if type(dimension) is not int or not 1 <= dimension <= 1024:
            raise ValueError("token head dimension")
        self.dimension, self.encoder_identity = dimension, encoder_identity
        self.positions = nn.Linear(dimension, 2)
        nn.init.zeros_(self.positions.weight)
        nn.init.zeros_(self.positions.bias)
        self.roots, self.receipt, self.quarantined = set(), None, False

    def forward(self, record):
        record.validate(self.dimension)
        if self.quarantined:
            raise ValueError("quarantined token head")
        valid = torch.tensor(
            [i == 0 or a >= 0 for i, (a, _) in enumerate(record.offsets)]
        )
        values = self.positions(record.hidden)
        return values.masked_fill(~valid[:, None], -1e9)

    @torch.no_grad()
    def margin(self, record, *, revoked):
        if self.roots.intersection(revoked) or record.root in revoked:
            raise ValueError("withdrawn token evidence")
        values = self(record)
        best = None
        for start, (a, _) in enumerate(record.offsets):
            if a < 0:
                continue
            for end in range(start, min(len(record.offsets), start + 32)):
                if record.offsets[end][0] < 0:
                    break
                score = float(values[start, 0] + values[end, 1] - values[0].sum())
                if best is None or score > best[0]:
                    best = (score, start, end)
        return best or (-1e9, 0, 0)

    def fit(self, rows, cut, *, steps=512, revoked):
        if not rows or len(rows) > 4096 or not 1 <= steps <= 1024:
            raise ValueError("token training budget")
        groups, seen = {}, set()
        for record, gold in rows:
            record.validate(self.dimension)
            identity = (record.question_id, record.window_id)
            if (
                identity in seen
                or record.question_id not in cut.question_ids
                or record.family not in cut.families
                or record.root not in cut.allowed_roots
                or record.root in cut.forbidden_roots | revoked
                or not cut.admission_digest
                or not gold
            ):
                raise ValueError("non-admitted token supervision")
            for start, end in gold:
                if not (start == end == 0) and not (
                    0 < start <= end < len(record.offsets)
                    and record.offsets[start][0] >= 0
                    and record.offsets[end][0] >= 0
                ):
                    raise ValueError("gold token outside source")
            seen.add(identity)
            groups.setdefault(record.family, {}).setdefault(
                record.question_id, []
            ).append((record, gold))
        if self.quarantined or self.roots.intersection(cut.forbidden_roots | revoked):
            raise ValueError("unavailable ancestor training state")
        before = {k: v.clone() for k, v in self.state_dict().items()}
        optimizer = torch.optim.AdamW(self.parameters(), lr=0.002, weight_decay=0.01)
        families, losses, started = sorted(groups), [], time.perf_counter()
        try:
            for step in range(steps):
                questions = groups[families[step % len(families)]]
                keys = sorted(questions)
                visit = step // len(families)
                group = questions[keys[visit % len(keys)]]
                record, gold = group[(visit // len(keys)) % len(group)]
                scores = self(record).log_softmax(0)
                loss = (
                    -torch.logsumexp(
                        torch.stack([scores[a, 0] + scores[b, 1] for a, b in gold]), 0
                    )
                    / 2
                )
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite token loss")
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                nn.utils.clip_grad_norm_(
                    self.parameters(), 1.0, error_if_nonfinite=True
                )
                optimizer.step()
                if any(not torch.isfinite(p).all() for p in self.parameters()):
                    raise ValueError("nonfinite token update")
                losses.append(float(loss.detach()))
            self.roots.update(r.root for r, _ in rows)
            delta = sum(
                float((v - before[k]).square().sum())
                for k, v in self.state_dict().items()
            )
            if not math.isfinite(delta) or delta <= 0:
                raise ValueError("no finite token update")
            self.receipt = dict(
                objective="external-token-start-end-marginal-v1",
                steps=steps,
                rows=len(rows),
                questions=len({r.question_id for r, _ in rows}),
                families=families,
                losses=losses,
                delta_squared_norm=delta,
                parameters=sum(p.numel() for p in self.parameters()),
                seconds=time.perf_counter() - started,
                training_digest=digest([(r.seal(), g) for r, g in rows]),
                admission_digest=cut.admission_digest,
                unknown_windows_used_as_negatives=False,
                production_accepted=False,
            )
            return self.receipt
        except Exception:
            self.quarantined = True
            raise

    def export(self):
        if self.quarantined or self.receipt is None:
            raise ValueError("no valid token artifact")
        return json.dumps(
            dict(
                schema="hepta.token-evidence-head.v1",
                dimension=self.dimension,
                encoder=self.encoder_identity,
                roots=sorted(self.roots),
                training=self.receipt,
                state={k: v.tolist() for k, v in self.state_dict().items()},
            ),
            sort_keys=True,
            allow_nan=False,
        ).encode()

    @classmethod
    def restore(cls, raw, *, expected_digest, encoder_identity, allowed_roots, revoked):
        from span_supervision import strict_json

        if len(raw) > 2 * 1024 * 1024 or digest(raw.hex()) != expected_digest:
            raise ValueError("token artifact bound/digest")
        data = strict_json(raw)
        if (
            data["schema"] != "hepta.token-evidence-head.v1"
            or data["encoder"] != encoder_identity
        ):
            raise ValueError("token artifact profile")
        roots = set(data["roots"])
        if not roots.issubset(allowed_roots) or roots.intersection(revoked):
            raise ValueError("token artifact roots")
        model = cls(data["dimension"], encoder_identity)
        state = {
            k: torch.tensor(v, dtype=torch.float32) for k, v in data["state"].items()
        }
        expected = model.state_dict()
        if set(state) != set(expected) or any(
            v.shape != expected[k].shape or not torch.isfinite(v).all()
            for k, v in state.items()
        ):
            raise ValueError("token artifact tensors")
        model.load_state_dict(state, strict=True)
        model.roots, model.receipt = roots, data["training"]
        model.eval().requires_grad_(False)
        return model
