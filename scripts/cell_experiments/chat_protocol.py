"""Native tokenizer chat serialization shared by SFT and controlled inference.

Each supervised turn uses the exact independently tokenized inference prefix.
Its continuation is tokenized separately, so BPE whitespace merges cannot
rewrite tokens that inference already consumed. Tool
observations use a labeled user message; arbitrary template role support is not
evidence that the base model learned a tool role.
"""

import hashlib

from .data import build_sft_examples

LEGACY = "legacy_v1"
NATIVE = "native_chat_v2"


def protocol_name(runtime):
    name = runtime.get("message_protocol", LEGACY)
    if name not in (LEGACY, NATIVE):
        raise ValueError("unsupported message protocol")
    return name


def template_digest(template):
    if not isinstance(template, str) or not template:
        raise ValueError("native chat requires one explicit tokenizer template")
    return hashlib.sha256(template.encode()).hexdigest()


def inference_messages(prompt, messages=None):
    """Bind incremental observations to the original task without rewriting it."""
    if messages is None:
        messages = [{"role": "user", "content": prompt}]
    if not isinstance(messages, list) or not 1 <= len(messages) <= 129:
        raise ValueError("bounded chat history required")
    result = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] not in ("user", "assistant", "tool")
            or not isinstance(message["content"], str)
            or len(message["content"].encode()) > 65536
        ):
            raise ValueError("invalid chat message")
        result.append(dict(message))
    if result[0] != {"role": "user", "content": prompt}:
        raise ValueError("chat history must preserve the original task input")
    if result[-1]["role"] == "assistant":
        raise ValueError("generation requires a user or tool observation")
    return result


def _wire(messages):
    return [
        {
            "role": "user" if message["role"] == "tool" else message["role"],
            "content": ("Tool observation:\n" if message["role"] == "tool" else "")
            + message["content"],
        }
        for message in messages
    ]


def inference_wire_messages(prompt, messages=None):
    """Return the validated message sequence passed to the native chat template."""
    return _wire(inference_messages(prompt, messages))


def render_prompt(tokenizer, prompt, messages=None):
    return tokenizer.apply_chat_template(
        inference_wire_messages(prompt, messages),
        tokenize=False,
        add_generation_prompt=True,
    )


def native_examples(records, mode):
    return training_examples(records, mode, NATIVE)


def training_examples(records, mode, protocol):
    """Carry per-event loss masks into the encoder for the selected protocol."""
    if protocol not in (LEGACY, NATIVE):
        raise ValueError("unsupported training protocol")
    from . import paired_opaque_teacher

    if len(records) == 1 and records[0].get("schema") == paired_opaque_teacher.DERIVED:
        example = paired_opaque_teacher.training_example(records[0], mode)
        if protocol == NATIVE:
            example["initial_messages"] = inference_messages(
                records[0]["task"]["input"], records[0]["task"].get("messages")
            )
        return [example]
    examples = build_sft_examples(records, mode)
    for record, example in zip(records, examples):
        if protocol == NATIVE:
            example["initial_messages"] = inference_messages(
                record["task"]["input"], record["task"].get("messages")
            )
        if mode == "trajectory":
            for event, segment in zip(record["trajectory"], example["segments"]):
                default = protocol == LEGACY or event["actor"] != "student"
                flag = event.get("trainable", default)
                if type(flag) is not bool:
                    raise ValueError("event.trainable must be an explicit boolean")
                if protocol == NATIVE:
                    segment["trainable"] = flag
                else:
                    segment["train"] = segment["train"] and flag
    return examples


def training_messages(example):
    """Mask observations and unverified student actions; deduplicate final alias.

    A terminal final_answer that exactly repeats the last supervised assistant
    action is an alias, even when a verification observation follows that action.
    Other repeated actions stay intact. Student targets require trainable=True;
    this is a supervision declaration, not independent verification of success.
    """
    initial = inference_messages(example["input"], example.get("initial_messages"))
    messages = [{**message, "train": False} for message in initial]
    previous_assistant = None
    duplicates = 0
    for segment in example["segments"]:
        role = segment["role"]
        if role not in ("assistant", "tool", "user"):
            raise ValueError("unsupported training message role")
        flag = segment.get("trainable", segment.get("actor") != "student")
        if type(flag) is not bool:
            raise ValueError("trainable must be a boolean")
        supervised = role == "assistant" and segment["train"] is True and flag
        if (
            segment.get("kind") == "final_answer"
            and previous_assistant is not None
            and previous_assistant["train"]
            and previous_assistant["content"] == segment["content"]
        ):
            duplicates += 1
            continue
        message = {"role": role, "content": segment["content"], "train": supervised}
        messages.append(message)
        if role == "assistant":
            previous_assistant = message
    return messages, duplicates


def encode_native_turns(tokenizer, example, limit):
    """One example per supervised turn, with the full preceding history masked.

    The native template's rendered complete message must extend its generation
    prefix as text. Tokenizing that complete string can merge a header newline
    with leading answer spaces. Instead, tokenize the exact inference prefix and
    continuation independently. Original record groups remain the sampling unit.
    """
    messages, duplicates = training_messages(example)
    wire = _wire(messages)
    turns = []
    for index, message in enumerate(messages):
        if not message["train"]:
            continue
        prefix = tokenizer.apply_chat_template(
            wire[:index], tokenize=False, add_generation_prompt=True
        )
        complete = tokenizer.apply_chat_template(
            wire[: index + 1], tokenize=False, add_generation_prompt=False
        )
        if not complete.startswith(prefix):
            raise ValueError("chat template text boundary is not prefix-stable")
        prompt = tokenizer.encode(prefix, add_special_tokens=False)
        target = tokenizer.encode(complete[len(prefix) :], add_special_tokens=False)
        ids = prompt + target
        if len(ids) > limit:
            raise ValueError(
                f"record {example['record_id']} turn {len(turns)} needs {len(ids)} tokens; limit={limit}; no truncation"
            )
        if not prompt or not target:
            raise ValueError("no causally predicted supervised token")
        turns.append(
            {
                "record_id": example["record_id"],
                "turn_index": len(turns),
                "message_index": index,
                "input_ids": ids,
                "labels": [-100] * len(prompt) + target,
                "prefix_tokens": len(prompt),
                "supervised_tokens": len(target),
                "message_protocol": NATIVE,
                "dropped_terminal_duplicates": duplicates,
            }
        )
    if not turns:
        raise ValueError("no causally predicted supervised token")
    return turns


def encode_native_example(tokenizer, example, limit):
    """Single-target compatibility wrapper; never discard other trajectory turns."""
    turns = encode_native_turns(tokenizer, example, limit)
    if len(turns) != 1:
        raise ValueError("multiple native targets require encode_native_turns")
    return turns[0]


def generation_termination(produced, eos_token_id, maximum):
    """Report observed termination; reaching the cap with EOS is still EOS."""
    ids = produced.tolist() if hasattr(produced, "tolist") else list(produced)
    eos_seen = eos_token_id is not None and eos_token_id in ids
    capped = len(ids) >= maximum and not eos_seen
    return {
        "finish_reason": "eos_token"
        if eos_seen
        else "max_new_tokens"
        if capped
        else "other",
        "eos_seen": eos_seen,
        "hit_output_limit": capped,
        "max_new_tokens": maximum,
    }
