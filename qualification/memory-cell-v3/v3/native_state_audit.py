"""Independently bind native model drives to journal and witness bytes."""

import struct

import numpy as np

from .native_structure_audit_core import _prefix, require, same, sha

PROFILE = b"hepta.memory.hard-tanh.q12.v1:input-round=floor(x*4096+0.5);hidden=clip(floor((dot+2048)/4096),-4096,4096);logit=int64-dot;bit=logit>=0;bit-order=little;weights=int16le;matrix-order=C;bias=last-row"

Q24 = 1 << 24

SUBJECT = b"memory.qualification.subject"


def _native_state(
    reader, prefix, manifest, cell, process_rows, query_inputs, selection
):
    width, generation = max(5, cell.bits), manifest["generation"]
    head = bytes.fromhex(
        sha(b"hepta.memory.integer-head.v1" + bytes.fromhex(cell.digest) + PROFILE)
    )
    scope = bytes.fromhex(
        sha(
            b"hepta.neuron.subject-scope.v1" + struct.pack(">I", len(SUBJECT)) + SUBJECT
        )
    )
    objective = bytes.fromhex(sha(b"memory.qualification.integer-parameter-read.v1"))
    source = bytes.fromhex(manifest["source_set_sha256"])
    body = bytes.fromhex(
        sha(
            b"hepta.neuron.body-binding.v1"
            + head
            + struct.pack(">QQ", generation, generation)
        )
    )
    config = sha(
        b"hepta.neuron.sparse-config.q24.v1"
        + head
        + bytes.fromhex(manifest["preprocessor_sha256"])
        + struct.pack(">Q", generation)
        + struct.pack(">10q", width, 1, Q24 // 2, 0, 0, 0, 0, Q24 // 2, 0, Q24)
    )
    same(selection["native_config_sha256"], config, "native selected config")
    journal = reader.raw(_prefix(prefix, "owner/journal.bin"))
    frame_size, tick_size = 304 + 16 * width, 176 + 16 * width
    require(
        len(journal) == 136 + len(process_rows) * frame_size
        and journal[:8] == b"HPTNSJ01",
        "native journal shape/magic differs",
    )
    require(
        journal[8:104] == bytes.fromhex(config) + scope + objective,
        "native journal header tuple differs",
    )
    require(
        sha(journal[:104]) == journal[104:136].hex(),
        "native journal header checksum differs",
    )
    before = bytes(32)
    for offset, row in enumerate(process_rows):
        frame = journal[136 + offset * frame_size : 136 + (offset + 1) * frame_size]
        sequence = offset + 1
        require(
            sha(frame[:-32]) == frame[-32:].hex(),
            f"native frame {sequence} checksum differs",
        )
        require(
            struct.unpack_from(">QQ", frame) == (sequence, sequence * 1000),
            "native sequence/time differs",
        )
        require(
            frame[16:144] == scope + objective + source + body,
            "native tick scope/source/body differs",
        )
        features = query_inputs[offset].astype(np.int64) * 4096
        vector = struct.pack(f">{len(features)}q", *features.tolist())
        feature_hash = bytes.fromhex(
            sha(
                b"hepta.neuron.input-features.q24.v1"
                + struct.pack(">Q", len(features))
                + vector
            )
        )
        tick_id = f"memory.qualification.tick.{sequence}".encode()
        input_digest = sha(
            b"hepta.neuron.tick-input.v1"
            + struct.pack(">I", len(tick_id))
            + tick_id
            + struct.pack(">I", len(SUBJECT))
            + SUBJECT
            + struct.pack(">QQ", sequence, sequence * 1000)
            + before
            + feature_hash
            + objective
            + source
            + b"\1"
            + struct.pack(">Q", generation)
            + b"\0"
            + vector
        )
        require(
            frame[144:176].hex() == input_digest,
            "native tick feature/checkpoint input binding differs",
        )
        drive = np.clip(
            np.asarray(row["raw_logits_q24"], dtype=np.int64), -8 * Q24, 8 * Q24
        ).tolist()
        drive.extend([0] * (width - cell.bits))
        require(
            frame[176:tick_size]
            == struct.pack(f">{2 * width}q", *(drive + [0] * width)),
            "journal drive is not the actual clipped model output",
        )
        require(
            frame[tick_size : tick_size + 32] == before,
            "native journal predecessor differs",
        )
        same(row["checkpoint_before"], before.hex(), "native process predecessor")
        before = frame[tick_size + 32 : tick_size + 64]
        same(row["checkpoint_after"], before.hex(), "native process successor")
        same(row["journal_bytes_written"], frame_size, "native frame bytes receipt")
    witness = reader.raw(_prefix(prefix, "owner/witness.bin"))
    require(
        len(witness) == 112 * (len(process_rows) + 1) and witness[:8] == b"HPTNWA01",
        "native witness shape/magic differs",
    )
    require(
        witness[8:80] == scope + objective + struct.pack(">Q", generation),
        "native witness scope/generation differs",
    )
    require(
        sha(witness[:80]) == witness[80:112].hex(),
        "native witness header checksum differs",
    )
    previous = bytes(32)
    for offset, row in enumerate(process_rows):
        record = witness[112 * (offset + 1) : 112 * (offset + 2)]
        require(
            sha(record[:80]) == record[80:].hex(),
            "native witness record checksum differs",
        )
        require(
            record[:40] == struct.pack(">Q", offset) + previous,
            "native witness predecessor differs",
        )
        previous = bytes.fromhex(row["checkpoint_after"])
        require(
            record[40:80] == struct.pack(">Q", offset + 1) + previous,
            "native witness acknowledgment differs",
        )
    return {
        "frames": len(process_rows),
        "journal_bytes": len(journal),
        "witness_bytes": len(witness),
        "final_checkpoint": previous.hex(),
        "tick_inputs_and_actual_model_drives_bound": True,
    }
