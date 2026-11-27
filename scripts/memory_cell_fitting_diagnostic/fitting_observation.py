"""Observe actual public forwards and classify paired, frozen-state probes."""

from collections import Counter
import json
import os

from fitting_common import require


class ForwardLedger:
    """Retain entered/completed calls separately, including interruption evidence."""

    def __init__(self, examples, quotas, stream, training_order=()):
        self.examples, self.quotas, self.stream = examples, quotas, stream
        self.training_order = training_order
        self.stage = None
        self.entered, self.completed, self.tokens = Counter(), Counter(), Counter()
        self.indices, self.pending, self.rejected = [], None, 0

    def event(self, value):
        self.stream.write(json.dumps(value, separators=(",", ":")) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def begin(self, stage):
        require(
            stage in self.quotas and self.entered[stage] == 0 and self.pending is None,
            "stage cannot repeat or overlap a pending forward",
        )
        if self.stage is not None:
            require(
                self.completed[self.stage] == self.quotas[self.stage],
                "previous stage incomplete",
            )
        self.stage = stage

    def observe(self, ids, labels, attention, use_cache):
        try:
            require(
                self.stage is not None and self.pending is None,
                "unregistered or overlapping forward",
            )
            require(
                self.entered[self.stage] < self.quotas[self.stage],
                "forward budget exhausted",
            )
            prefill = self.stage == "reload_prefill"
            require(
                use_cache is prefill and attention == [1] * len(ids),
                "cache or attention policy changed",
            )
            field = "prompt_ids" if prefill else "input_ids"
            matches = [
                i for i, example in enumerate(self.examples) if example[field] == ids
            ]
            require(
                len(matches) == 1, "actual forward does not match a registered example"
            )
            index = matches[0]
            require(
                labels == (None if prefill else self.examples[index]["labels"]),
                "actual target mask differs from the independent registration",
            )
            if self.stage != "training":
                require(
                    index == self.entered[self.stage],
                    "diagnostic examples changed order",
                )
            else:
                require(
                    index == self.training_order[self.entered[self.stage]],
                    "registered training order changed",
                )
        except Exception as error:
            self.rejected += 1
            self.event(
                dict(
                    event="rejected_before_forward", stage=self.stage, error=str(error)
                )
            )
            raise
        self.pending = dict(
            stage=self.stage, index=index, ordinal=sum(self.entered.values()) + 1
        )
        self.entered[self.stage] += 1
        self.tokens[self.stage] += len(ids)
        self.indices.append(index)
        self.event(
            dict(
                event="entered",
                **self.pending,
                input_ids=ids,
                labels=labels,
                attention_mask=attention,
                use_cache=use_cache,
            )
        )

    def before(self, _module, args, kwargs):
        try:
            ids = kwargs.get("input_ids", args[0] if args else None)
            labels, attention = kwargs.get("labels"), kwargs.get("attention_mask")
            require(
                ids is not None
                and len(ids.shape) == 2
                and ids.shape[0] == 1
                and 1 <= ids.shape[1] <= 208,
                "one bounded actual input sequence required",
            )
            require(
                attention is not None
                and attention.shape == ids.shape
                and (labels is None or labels.shape == ids.shape),
                "actual mask shape differs",
            )
            values = (
                ids.tolist()[0],
                None if labels is None else labels.tolist()[0],
                attention.tolist()[0],
            )
        except Exception as error:
            self.rejected += 1
            self.event(
                dict(
                    event="rejected_before_forward", stage=self.stage, error=str(error)
                )
            )
            raise
        self.observe(*values, kwargs.get("use_cache"))

    def after(self, _module, _args, _kwargs, _output):
        require(self.pending is not None, "completion without an admitted forward")
        self.completed[self.stage] += 1
        self.event(dict(event="completed", **self.pending))
        self.pending = None

    def summary(self):
        return dict(
            entered=dict(self.entered),
            completed=dict(self.completed),
            input_tokens=dict(self.tokens),
            observed_example_indices=list(self.indices),
            rejected_before_forward=self.rejected,
            incomplete_forward=self.pending,
        )


def classify(memory, reloaded, prefill):
    require(
        len(memory) == len(reloaded) == len(prefill) == 40,
        "complete paired panels required",
    )
    for index, rows in enumerate(zip(memory, reloaded, prefill)):
        require(
            all(r["example_index"] == index for r in rows),
            "paired example identity changed",
        )
        require(
            len({r["prompt_sha256"] for r in rows}) == 1
            and len({r["adapter_state_sha256"] for r in rows}) == 1
            and len({tuple(r["target_ids"]) for r in rows}) == 1,
            "paired prompt, state or target differs",
        )
    saved_equal = sum(
        a["supervised_logits_sha256"] == b["supervised_logits_sha256"]
        for a, b in zip(memory, reloaded)
    )
    save_argmax = sum(
        a["first"]["argmax_id"] != b["first"]["argmax_id"]
        for a, b in zip(memory, reloaded)
    )
    prefill_argmax = sum(
        a["first"]["argmax_id"] != b["first"]["argmax_id"]
        for a, b in zip(reloaded, prefill)
    )
    wrong = sum(r["first"]["argmax_id"] != r["target_ids"][0] for r in memory)
    reason = (
        "save_reload_logits_differ"
        if saved_equal != 40 or save_argmax
        else "teacher_prefill_argmax_differs"
        if prefill_argmax
        else "first_token_fitting_incomplete"
        if wrong
        else "first_token_fitting_complete"
    )
    return dict(
        classification=reason,
        examples=40,
        memory_teacher_wrong_first_tokens=wrong,
        save_reload_exact_logit_matches=saved_equal,
        save_reload_first_argmax_differences=save_argmax,
        teacher_prefill_first_argmax_differences=prefill_argmax,
        maximum_teacher_prefill_logit_abs_difference=max(
            r["teacher_prefill_max_abs_difference"] for r in prefill
        ),
        intrinsic_capacity_limit_established=False,
        full_answer_quality_measured=False,
        future_gate_satisfied=False,
        production_accepted=False,
    )
