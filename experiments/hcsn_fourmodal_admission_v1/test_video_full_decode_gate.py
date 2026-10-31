"""Full-clip frame integrity regression for HCSN four-modality preflight.

Synthetic FFmpeg fixtures are scientific source-integrity tests only, not
real four-modal source labels or model-quality evidence.
"""

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import shutil

from .manifest_gate import AdmissionError, _decode_video, _run_probe


def _probe(count: str | None) -> subprocess.CompletedProcess[str]:
    suffix = f',"nb_frames":"{count}"' if count is not None else ''
    return subprocess.CompletedProcess([], 0, '{"streams":[{"codec_type":"video","width":16,"height":16'+suffix+'}]}', '')


def _frames(count: int) -> subprocess.CompletedProcess[str]:
    rows = ['#software: Lavf\n', '#stream 0 video\n']
    rows.extend(f'0, {i}, {i}, 1, 384, 0x12345678\n' for i in range(count))
    return subprocess.CompletedProcess([], 0, ''.join(rows), '')


class FullClipGateTests(unittest.TestCase):
    def test_reject_metadata_declaring_three_frames_when_only_one_decodes(self):
        with patch('experiments.hcsn_fourmodal_admission_v1.manifest_gate._run_probe',
                   side_effect=[_probe('3'), _frames(1)]):
            with self.assertRaisesRegex(AdmissionError, 'decoded.*frame'):
                _decode_video(Path('virtual.mp4'))

    def test_full_decode_two_frames_matches_metadata(self):
        with patch('experiments.hcsn_fourmodal_admission_v1.manifest_gate._run_probe',
                   side_effect=[_probe('2'), _frames(2)]) as calls:
            _decode_video(Path('virtual.mp4'))
            decode_argv = calls.call_args_list[1].args[0]
            self.assertNotIn('-frames:v', decode_argv)
            self.assertIn('-xerror', decode_argv)

    def test_zero_or_invalid_declared_frames_are_refused(self):
        for count in ('0', '-2', 'foo', '10000000000000000000000000'):
            with self.subTest(count=count):
                with patch('experiments.hcsn_fourmodal_admission_v1.manifest_gate._run_probe',
                           side_effect=[_probe(count), _frames(2)]):
                    with self.assertRaises(AdmissionError):
                        _decode_video(Path('virtual.mp4'))

    def test_unknown_frame_count_still_requires_full_decode_and_a_real_frame(self):
        for count in (None, 'N/A'):
            with self.subTest(count=count):
                with patch('experiments.hcsn_fourmodal_admission_v1.manifest_gate._run_probe',
                           side_effect=[_probe(count), _frames(1)]):
                    _decode_video(Path('virtual.mp4'))

    def test_real_multiframe_generated_video_decodes_completely(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('FFmpeg required')
        with TemporaryDirectory(prefix='hcsn-full-video-') as tmp:
            video = Path(tmp)/'clip.mp4'
            command = ['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error',
                       '-y', '-f', 'lavfi', '-i', 'testsrc=size=32x32:rate=5:duration=2',
                       '-an', '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p', str(video)]
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            _decode_video(video)


if __name__ == '__main__':
    unittest.main()
