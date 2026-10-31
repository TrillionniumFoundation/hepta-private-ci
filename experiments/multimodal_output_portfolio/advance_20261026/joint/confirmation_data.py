"""Registered input construction, separated from public model execution."""

from dataclasses import dataclass
import json
from pathlib import Path
import time

import torch

from ...closure_20261025.media.coherent import motion_targets
from ...next_20261025.joint.model import PublicTask
from ...next_20261025.media.audio_sources import load_audio
from ...v7.data import VIEWS, make_batch
from ...v7.sources import load_roles
from ...v7_media.corpus import speech_spectrum
from ..sources import load_images, load_rows
from ..cases import construct_case, prepare_task


@dataclass(frozen=True)
class ConstructedCase:
    tasks: dict
    expected_for_offline_scoring: list
    identity: dict
    input_preparation_wall_ns: dict


class InputCensus:
    """Build tasks from a fixed source pair; target values never enter policy calls."""

    def __init__(self, settings, spec, protocol):
        self.spec = spec
        self.old = spec["mode"] == "old_smoke"
        if self.old:
            shared = Path(settings["shared"])
            self.corpus = load_roles(shared / "abc2-assets/mnist",
                                     shared / "abc2-runs/source-recovery-001/source-manifest.json",
                                     roles=("development",))
            self.role = "development"
            self.rows = json.loads(Path(settings["audio_allocation"]).read_text())["roles"]["qualification"]
            self.pools = {digit: [row for row in self.rows if row["label"] == digit] for digit in range(10)}
            self.audio_root = settings["audio_root"]
        else:
            selected, _ = load_rows(spec["source_allocation"], protocol, "confirmation")
            self.selected = selected
            self.corpus = load_images(spec["image_cache"], spec["source_allocation"], protocol, "confirmation")
            if selected["pair_count"] != spec["pair_count"] or selected["writer_count"] != 85:
                raise ValueError("The complete fixed confirmation panel is required")
            self.role, self.rows = selected["role"], selected["audio_rows_by_source_digit"]
            self.writers, self.speakers = selected["pair_writer_ids"], selected["speaker_by_writer"]
            self.audio_root = spec["new_audio_root"]

    def case(self, case, directory):
        if not self.old:
            source = construct_case(self.corpus, self.selected, case, self.spec["task_seed"])
            prepared = {route: prepare_task(source, route, self.audio_root, Path(directory) / route)
                        for route in self.spec["routes"]}
            return ConstructedCase({route: item.task for route, item in prepared.items()},
                                   source.batch.target.labels[0].tolist(),
                                   {**source.identity, "cluster": source.source_group},
                                   {route: item.receipt["input_preparation_wall_ns"] for route, item in prepared.items()})
        view = VIEWS[case % len(VIEWS)]
        batch = make_batch(self.corpus, self.role, 1, self.spec["task_seed"] + case, view=view, offset=case)
        swap = int(batch.observation.text_tokens[0, 1]) == 10
        if self.old:
            rng = torch.Generator().manual_seed(self.spec["task_seed"] * 1009 + case)
            rows = [pool[int(torch.randint(len(pool), (), generator=rng))]
                    for label in batch.target.labels[0].tolist() for pool in [self.pools[label]]]
            cluster = "old-pair-" + str(case)
            speaker = None
        else:
            # Allocation rows follow immutable source order. Reorder using the
            # public command, never by asking the policy for a private label.
            rows = self.rows[2 * case:2 * case + 2]
            if swap:
                rows = list(reversed(rows))
            cluster = str(self.writers[case])
            speaker = self.speakers[cluster]
        audio_started = time.perf_counter_ns()
        waves = load_audio(self.audio_root, rows)
        spectrum = speech_spectrum(waves).reshape(1, 2, 1, 129, 101)
        audio_ns = time.perf_counter_ns() - audio_started
        tasks = {"image": PublicTask("image", observation=batch.observation),
                 "text": PublicTask("text", text_digits=batch.target.labels.clone()),
                 "audio": PublicTask("audio", spectrum=spectrum),
                 "video": PublicTask("video", video=motion_targets(batch.target.pixels))}
        expected = batch.target.labels[0].tolist()
        if [row["label"] for row in rows] != expected:
            raise ValueError("Source construction has misordered the actual external recordings")
        identity = {"case": case, "cluster": cluster, "speaker": speaker, "view": view,
                    "source_ids": list(batch.source_ids[0]), "public_swap_command": swap,
                    "audio_source_files": [{key: row[key] for key in ("path", "sha256", "speaker")} for row in rows],
                    "input_scope": "Literal text; observed degraded image; actual recorded speech; synthetic twenty-frame source-digit motion",
                    "target_used_by_policy": False}
        return ConstructedCase(tasks, expected, identity, {"image": 0, "text": 0, "audio": audio_ns, "video": 0})
