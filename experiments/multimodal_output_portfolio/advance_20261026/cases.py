"""Construct public tasks without exposing scoring targets to model execution.

Source rows retain their original left/right order. The public keep/swap
command alone orders text, video and real speech. Late speech is not opened by
image/video task construction. An initial audio task has no second observation
of that same recording masquerading as independent evidence.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

import torch

from ..closure_20261025.media.coherent import motion_targets
from ..next_20261025.joint.model import PublicTask
from ..next_20261025.media.audio_sources import load_audio
from ..v7.data import VIEWS, make_batch
from ..v7_media.corpus import speech_spectrum
from .input_codec import video_roundtrip
from .sources import load_images, load_rows


@dataclass(frozen=True)
class SourceCase:
    batch: object  # Trusted construction/offline scoring only; never passed to a host.
    source_group: str
    ordered_audio_rows: tuple
    identity: dict
    ordered_source_pixels: torch.Tensor
    public_digits: torch.Tensor


@dataclass(frozen=True)
class PreparedTask:
    task: PublicTask
    late_audio_rows: tuple | None
    receipt: dict


def registered_census(cache, allocation, protocol, role):
    """The only fresh-source entrance; checks the complete frozen candidate pins."""
    selected, _ = load_rows(allocation, protocol, role)
    return load_images(cache, allocation, protocol, role), selected


def construct_case(corpus, selected_role, pair_index, task_seed, view=None):
    """Trusted task construction from one fixed source pair, with no resampling."""
    role = selected_role["role"]
    source = corpus.splits[role]
    if not 0 <= pair_index < len(source) // 2:
        raise ValueError("Pair index outside the registered source census")
    view = VIEWS[pair_index % len(VIEWS)] if view is None else view
    batch = make_batch(corpus, role, 1, task_seed + pair_index, view=view, offset=pair_index)
    indices = [2 * pair_index, 2 * pair_index + 1]
    swap = int(batch.observation.text_tokens[0, 1]) == 10
    if swap:
        indices.reverse()
    records = selected_role["source_records"]
    if tuple(records[i]["source_id"] for i in range(2 * pair_index, 2 * pair_index + 2)) != batch.source_ids[0]:
        raise ValueError("Registered pair identities differ from actual source tensors")
    rows = tuple(selected_role["audio_rows_by_source_digit"][i] for i in indices)
    digits = source.labels[indices].reshape(1, 2).clone()
    pixels = torch.cat(tuple(source.images[i] for i in indices), -1).unsqueeze(0).float() / 255
    if (not torch.equal(digits, batch.target.labels) or not torch.equal(pixels, batch.target.pixels)
            or [row["label"] for row in rows] != digits[0].tolist()):
        raise ValueError("Public command, real speech and offline scoring target are misaligned")
    writer = str(selected_role["pair_writer_ids"][pair_index])
    speaker = selected_role["speaker_by_writer"][writer]
    if any(row["speaker"] != speaker for row in rows):
        raise ValueError("A source group must have exactly its registered speech speaker")
    group = f"writer:{writer}:speaker:{speaker}"
    identity = {"case": pair_index, "source_group": group, "writer": writer, "speaker": speaker,
                "view": view, "task_seed": task_seed + pair_index, "source_ids": list(batch.source_ids[0]),
                "public_swap_command": swap,
                "ordered_source_ids": [source.ids[i] for i in indices],
                "audio_source_files": [{key: row[key] for key in ("path", "sha256", "speaker")} for row in rows],
                "target_used_by_policy": False}
    return SourceCase(batch, group, rows, identity, pixels, digits)


def prepare_task(case, route, audio_root, directory, ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe"):
    """Produce only a public task and acquisition metadata, with an input receipt."""
    if route not in ("image", "text", "audio", "video"):
        raise ValueError("Unknown public modality route")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipt = {"schema": "hepta.advance.public-input.v1", "route": route,
               "identity": case.identity, "private_target_passed_to_model": False,
               "initial_waveform_opened": route == "audio", "late_waveform_opened": False}
    late = None
    if route == "image":
        task = PublicTask(route, observation=case.batch.observation)
    elif route == "text":
        task = PublicTask(route, text_digits=case.public_digits.clone())
        receipt["literal_public_request"] = case.public_digits[0].tolist()
    elif route == "audio":
        public_rows = [{key: row[key] for key in ("path", "sha256")} for row in case.ordered_audio_rows]
        waves = load_audio(audio_root, public_rows)
        task = PublicTask(route, spectrum=speech_spectrum(waves).reshape(1, 2, 1, 129, 101))
        receipt["actual_pcm_tensor_sha256"] = hashlib.sha256(waves.numpy().tobytes()).hexdigest()
        receipt["normalized_sample_rate"] = 8000
        receipt["initial_audio_is_not_available_again_as_new_evidence"] = True
    else:
        decoded, codec = video_roundtrip(motion_targets(case.ordered_source_pixels),
                                         Path(directory) / "video", ffmpeg, ffprobe)
        task = PublicTask(route, video=decoded)
        receipt["actual_video"] = codec
    if route in ("image", "video"):
        late = tuple({key: row[key] for key in ("path", "sha256")} for row in case.ordered_audio_rows)
    receipt.update(input_preparation_wall_ns=time.perf_counter_ns() - started,
                   input_preparation_parent_cpu_ns=time.process_time_ns() - cpu,
                   late_audio_available=late is not None,
                   source_scope="literal text, actual source pixels and speech, constructed source-digit motion")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "PUBLIC_INPUT.json"
    with path.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return PreparedTask(task, late, receipt)
