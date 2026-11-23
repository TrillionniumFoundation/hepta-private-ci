import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from . import recording_features as media
from .verify_media import check_manifest


class RecordingFeaturesTest(unittest.TestCase):
    def test_fixed_partitions(self):
        rows=json.loads((Path(__file__).parent/'sources.json').read_text())
        check_manifest(rows)
        crossed=[r.copy() for r in rows]
        crossed[-1]['group']=crossed[0]['group']
        with self.assertRaisesRegex(ValueError,'crosses'):
            check_manifest(crossed)

    def test_four_excerpts_and_shared_margins(self):
        for length in (14.613,16.04,63.568,1121.128):
            times=media.starts(length)
            self.assertEqual(len(times),4)
            self.assertGreaterEqual(np.diff(times).min(),2.88+.19998)
            self.assertAlmostEqual(times[0],.05*length,places=4)
            self.assertAlmostEqual(times[-1]+2.88,.95*length,places=4)
        with self.assertRaises(ValueError):
            media.starts(12.)

    def test_unchanged_prefix_for_future_audio_video_perturbation(self):
        rng=np.random.default_rng(19);rate=16000
        pcm=rng.normal(0,.1,rate*3)
        frames=rng.uniform(size=(150,16,24,3))
        pts=np.arange(150)/50
        def compute(a,v):
            with patch.object(media,'make_frames',return_value=(a,rate,v,pts,0.)):
                return media.extract('no-file',0.)
        original=compute(pcm,frames)
        cut=2*.48
        future_audio=pcm.copy();future_audio[int(cut*rate):]=0.
        future_video=frames.copy();future_video[pts>=cut]=0.
        changed=compute(future_audio,future_video)
        for key in original:
            np.testing.assert_array_equal(original[key][:2],changed[key][:2])
            self.assertFalse(np.array_equal(original[key][2:],changed[key][2:]))
        audio_only=compute(pcm,future_video)
        np.testing.assert_array_equal(original['audio'],audio_only['audio'])
        np.testing.assert_array_equal(original['audio_block'],audio_only['audio_block'])


if __name__=='__main__':unittest.main()
