"""Question-preserving input preparation for the existing physical Stem runner.

This is a versioned input adapter, not a new evaluator. It uses one shared,
question-independent state token budget in both candidate arms. No task question
or option is silently discarded to make a fast but meaningless joint baseline.
"""
from four_gate_common import digest, integer, require

PROFILE = "question_preserving_shared_state_budget.v2"


def joint_text(state, question, options):
    require(isinstance(state, str) and isinstance(question, str) and question,
            "text state and nonempty question required")
    require(isinstance(options, list) and 2 <= len(options) <= 128
            and all(isinstance(option, str) and option for option in options),
            "bounded nonempty options required")
    return f"Question: {question}\nOptions: {' | '.join(options)}\nState: {state}"


class QuestionPreservingInputs:
    """Tokenize once per admitted payload; preparation work must be charged.

    The complete condition is first and only state tokens are truncated. The
    shared state budget reserves the largest condition in the frozen workload,
    so the reuse arm does not quietly receive more source evidence. UTF-8 text
    and token inventories remain in the caller's controlled input evidence.
    """

    def __init__(self, tokenizer, payloads, max_tokens):
        integer(max_tokens, "token ceiling", 8, 8192)
        require(type(payloads) is dict and 0 < len(payloads) <= 100_000,
                "bounded admitted payload inventory required")
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.items = {}
        longest_condition = 0
        state_cache = {}
        for request_id, payload in payloads.items():
            require(set(payload) == {"state", "joint", "question", "options"},
                    "explicit state/question/options required; legacy truncation is not reinterpreted")
            require(payload["joint"] == joint_text(payload["state"], payload["question"], payload["options"]),
                    "joint payload differs from complete admitted components")
            condition = f"Question: {payload['question']}\nOptions: {' | '.join(payload['options'])}"
            condition_ids = tokenizer.encode(condition, add_special_tokens=False)
            if payload["state"] not in state_cache:
                state_cache[payload["state"]] = tokenizer.encode(payload["state"], add_special_tokens=False)
            state_ids = state_cache[payload["state"]]
            require(condition_ids and state_ids, "empty task or source token sequence")
            longest_condition = max(longest_condition, len(condition_ids))
            self.items[request_id] = (list(condition_ids), list(state_ids))
        pair_specials = tokenizer.num_special_tokens_to_add(pair=True)
        single_specials = tokenizer.num_special_tokens_to_add(pair=False)
        self.state_budget = max_tokens - max(pair_specials + longest_condition, single_specials)
        require(self.state_budget > 0, "question/options leave no evidence budget; increase token ceiling")
        self.audit = {}
        for request_id, (condition_ids, state_ids) in self.items.items():
            kept = state_ids[:self.state_budget]
            self.audit[request_id] = {
                "condition_tokens": len(condition_ids), "original_state_tokens": len(state_ids),
                "retained_state_tokens": len(kept), "condition_token_sha256": digest(condition_ids),
                "retained_state_token_sha256": digest(kept),
                "state_truncated": len(kept) < len(state_ids), "condition_truncated": False,
            }
        self.pipeline = {"profile": PROFILE, "max_tokens": max_tokens,
                         "common_state_budget": self.state_budget,
                         "condition_inventory_sha256": digest({k: v[0] for k, v in self.items.items()})}

    def __call__(self, rows, arm):
        require(arm in ("joint_batch", "feature_reuse"),
                "no-change needs its actual model input adapter")
        items = []
        for row in rows:
            require(row["request_id"] in self.items, "unregistered input")
            condition, state = self.items[row["request_id"]]
            state = state[:self.state_budget]
            ids = (self.tokenizer.build_inputs_with_special_tokens(condition, state)
                   if arm == "joint_batch" else self.tokenizer.build_inputs_with_special_tokens(state))
            require(0 < len(ids) <= self.max_tokens, "prepared input exceeds declared budget")
            items.append({"input_ids": ids, "attention_mask": [1] * len(ids)})
        # No truncation is allowed here. Only the registered state slice was shortened.
        return dict(self.tokenizer.pad(items, padding=True, return_tensors="pt"))
