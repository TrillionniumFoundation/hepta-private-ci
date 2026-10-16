"""Losslessly reconstruct the original 64-call journal from its pinned delta.

The delta contains original generated token IDs and wall-seconds, not post-hoc
answers. All prompts and input IDs regenerate from exact original source views,
reader template and immutable script hashes; complete SHA-256 must match the
original fsynced raw journal. This performs ZERO model calls or training.
"""

import argparse
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path

from offline_event_reader_trial import inputs
from historical_reader_format_source import locked_reader_format

EXPECTED_SHA256 = "a26133473451003c8708f1fa3e3ea40e975b7febcd45039870e19d1d067a461c"
EXPECTED_CODE_SHA256 = (
    "84952869d55069d0830add604883750929efd22e1f93bcf34dbc01b40890bcd5"
)
EXPECTED_DELTA_SHA256 = (
    "1408dab69c30d583f1fbfe46cd6533e9a5e92abeacafffab478bd209eff33a8d"
)


def reconstruct(archive, reader_dir, delta_file, destination, *, expected_delta_sha):
    if expected_delta_sha != EXPECTED_DELTA_SHA256:
        raise ValueError("unregistered delta identity")
    if destination.exists():
        raise ValueError("never overwrite an archived research observation")
    prompt, reader, source_digests = locked_reader_format()
    if source_digests["prompt_representation_probe.py"] != EXPECTED_CODE_SHA256:
        raise ValueError("historical generating source changed")
    reader.verify_files(reader_dir)
    tokenizer = reader.ByteLevel(reader_dir)
    plan, sources, _ = inputs(archive)
    encoded = Path(delta_file).read_bytes().strip()
    data = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(data).hexdigest() != expected_delta_sha:
        raise ValueError("compressed original delta bytes changed")
    rows = json.loads(lzma.decompress(data))
    if len(rows) != 64:
        raise ValueError("not 64 original model outcomes")
    serialized = []
    index = 0
    for case in plan["cases"]:
        for style in prompt.STYLES:
            for arm in prompt.ARMS:
                value = rows[index]
                index += 1
                if (
                    type(value) is not list
                    or len(value) != 2
                    or not isinstance(value[0], list)
                    or not 1 <= len(value[0]) <= 64
                    or any(type(t) is not int or not 0 <= t < 49152 for t in value[0])
                    or type(value[1]) not in (int, float)
                    or not 0 <= value[1] <= 3600
                ):
                    raise ValueError("invalid original output token receipt")
                row = dict(
                    question_id=case["query"]["identity"],
                    kind=case["kind"],
                    representation=style,
                    arm=arm,
                    candidate_digest=case["candidate_digest"],
                    reader_identity=reader.digest(reader.PINS),
                    reader_profile=reader.PROFILE,
                )
                messages, selected = prompt.build_messages(
                    case, arm, style, sources
                )
                rendered_prompt = tokenizer.render(messages)
                ids = tokenizer.encode(rendered_prompt)
                if len(ids) > 2048:
                    raise ValueError("original prompt budget drift")
                generated = value[0]
                row.update(
                    status="succeeded",
                    messages=messages,
                    prompt=rendered_prompt,
                    input_ids=ids,
                    input_digest=reader.digest(ids),
                    selected=selected,
                    generated_ids=generated,
                    generated_tokens=len(generated),
                    answer=tokenizer.decode(generated),
                )
                row["elapsed_seconds"] = value[1]
                serialized.append(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
    raw = "".join(serialized).encode()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError("lossless round-trip of ORIGINAL journal failed")
    with destination.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return dict(
        reconstructed_original_rows=len(rows),
        exact_original_journal_sha256=EXPECTED_SHA256,
        recovered_bytes=len(raw),
        new_model_calls=0,
        independent_human_review=False,
        production_accepted=False,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("reader", type=Path)
    p.add_argument("delta", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--delta-sha", required=True)
    opts = p.parse_args()
    print(
        json.dumps(
            reconstruct(
                opts.archive,
                opts.reader,
                opts.delta,
                opts.output,
                expected_delta_sha=opts.delta_sha,
            )
        )
    )
