"""Read-only remeasurement of retained codec artifacts; never loads a model."""
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import numpy as np
from temporal_diagnostics import temporal_diagnostics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(record):
    path = Path(record['path'])
    if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
        raise ValueError('retained artifact identity mismatch: ' + path.name)
    return path


def probe(path):
    command = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
               '-show_entries', 'frame=pts_time,pkt_dts_time,best_effort_timestamp_time', '-of', 'json', str(path)]
    frames = json.loads(subprocess.check_output(command, timeout=30))['frames']
    return frames, [float(f['best_effort_timestamp_time']) for f in frames]


def main(root):
    wall, cpu = time.perf_counter(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    ingestion_path, codec_path = root / 'ingestion-fresh.json', root / 'codec-fresh.json'
    ingestion, codec = json.loads(ingestion_path.read_text()), json.loads(codec_path.read_text())
    inputs = {k: checked(v) for k, v in ingestion['artifacts'].items()}
    outputs = {k: checked(v) for k, v in codec['artifacts'].items()}
    with np.load(inputs['input-tensors.npz'], allow_pickle=False) as arrays:
        reference = arrays['video'].copy()
    with np.load(outputs['codec-tensors.npz'], allow_pickle=False) as arrays:
        reconstruction = arrays['video_reconstruction'].copy()
    input_frames, input_times = probe(inputs['recorded-four-frames.webm'])
    output_frames, output_times = probe(outputs['video-reconstructed.webm'])
    # Decode the retained ingestion video exactly as the original tensor builder.
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1',
        '-i', str(inputs['recorded-four-frames.webm']), '-map', '0:v:0', '-f', 'rawvideo',
        '-pix_fmt', 'rgb24', 'pipe:1'], timeout=30)
    decoded = np.frombuffer(raw, dtype=np.uint8).reshape(4, 72, 128, 3).astype(np.float32).transpose(0, 3, 1, 2) / 255
    if not np.array_equal(reference, decoded):
        raise ValueError('decoder presentation order differs from stored reference tensor')
    arms = {'source_identity': reference, 'source_reversed': reference[::-1],
            'source_frozen': np.repeat(reference[:1], 4, axis=0),
            'codec_ordered': reconstruction, 'codec_reversed': reconstruction[::-1],
            'codec_frozen': np.repeat(reconstruction[:1], 4, axis=0)}
    results = {name: temporal_diagnostics(reference, value, input_times, output_times)
               for name, value in arms.items()}
    sums = {key: sum(row[side][key] for row in codec['roundtrips'] for side in ('encoder_work', 'decoder_work'))
            for key in codec['total_forward_work']}
    if sums != codec['total_forward_work']:
        raise ValueError('historical per-forward counters differ from total')
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {'schema': 'hepta.codec-ordered-temporal-diagnostic.v1',
            'mode': 'exploratory retained-artifact diagnostic, not preregistered efficacy',
            'source_hashes': {p.name: sha(p) for p in (ingestion_path, codec_path, Path(__file__), Path(__file__).with_name('temporal_diagnostics.py'))},
            'artifact_hashes': {k: sha(v) for k, v in inputs.items() if k in ('original.webm', 'input-tensors.npz', 'recorded-four-frames.webm')} |
                               {k: sha(v) for k, v in outputs.items() if k in ('codec-tensors.npz', 'video-reconstructed.webm')},
            'input_frame_timestamps': input_frames, 'export_frame_timestamps': output_frames,
            'decoded_reference_exact': True, 'arms': results,
            'historical_forward_counter_sums': sums, 'historical_forward_counter_match': True,
            'historical_cost_scope': codec['cost_scope'], 'new_model_forwards': 0,
            'new_cost': {'wall_seconds': time.perf_counter() - wall, 'process_cpu_seconds': time.process_time() - cpu,
                         'child_cpu_seconds': child_end.ru_utime + child_end.ru_stime - child_start.ru_utime - child_start.ru_stime},
            'scope': 'Pixel frame alignment only. Audio/text not evaluated. No output codec quality threshold, neural rerun, model improvement, semantic synchrony, independent source replication or new MAC measurement.'}


if __name__ == '__main__':
    print(json.dumps(main(Path(sys.argv[1])), indent=2, allow_nan=False))
