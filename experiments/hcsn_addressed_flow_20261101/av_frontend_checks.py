"""Targeted tests for causal media prefixes, portable decoders and test locking."""

import itertools
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .av_frontend import (constructed_posterior, dtw_margin, fit_decoder, infer,
                         load_freeze, mouth_features, prepare, temporal_features)


class FrontendChecks(unittest.TestCase):
    def arrays(self):
        rng=np.random.default_rng(59)
        return (rng.normal(size=48000).astype(np.float32),
                rng.integers(0,256,(16,48,64),dtype=np.uint8),np.arange(16)/10)

    def test_suffix_cannot_change_features(self):
        wave,pixels,timestamps=self.arrays()
        a,_=temporal_features(wave,pixels,timestamps,0.,32000)
        wave[32000:]*=1000;pixels[11:]=255-pixels[11:]
        b,_=temporal_features(wave,pixels,timestamps,0.,32000)
        for modality in a: np.testing.assert_array_equal(a[modality],b[modality])

    def test_accepted_content_changes_features(self):
        wave,pixels,timestamps=self.arrays()
        a,_=temporal_features(wave,pixels,timestamps,0.,32000)
        wave[:32000]*=2;pixels[5]=255-pixels[5]
        b,_=temporal_features(wave,pixels,timestamps,0.,32000)
        for modality in a: self.assertGreater(float(np.max(np.abs(a[modality]-b[modality]))),.01)

    def test_native_fractional_origin(self):
        wave,pixels,timestamps=self.arrays()
        features,receipt=temporal_features(wave,pixels,timestamps+.027,0.,44100)
        self.assertEqual(features['audio'].shape,(640,))
        self.assertEqual(features['video'].shape,(1280,))
        self.assertLessEqual(receipt['last_selected_frame'],receipt['accepted_end'])

    def test_mouth_future_invariance_and_static_cancellation(self):
        _,pixels,timestamps=self.arrays()
        a=mouth_features(pixels,timestamps,0.)
        pixels[11:]=255-pixels[11:]
        np.testing.assert_array_equal(a,mouth_features(pixels,timestamps,0.))
        static=np.repeat(pixels[:1],16,axis=0)
        np.testing.assert_array_equal(mouth_features(static,timestamps,0.),np.zeros(684))

    def test_short_video_rejected(self):
        wave,pixels,timestamps=self.arrays()
        with self.assertRaises(ValueError): temporal_features(wave,pixels[:10],timestamps[:10],0.,32000)

    def test_short_audio_rejected(self):
        wave,pixels,timestamps=self.arrays()
        with self.assertRaises(ValueError): temporal_features(wave[:30000],pixels,timestamps,0.,32000)

    def test_test_preparation_requires_freeze_before_media_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'freeze'):
                prepare(Path(tmp)/'nonexistent',Path(tmp)/'out',['test'])
            self.assertFalse((Path(tmp)/'out').exists())

    def test_bad_freeze_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'candidate.json';p.write_text(json.dumps({'source_sha256':'bad'}))
            with self.assertRaisesRegex(ValueError,'source'): load_freeze(p)

    def test_weighted_information_ceilings(self):
        truth=np.array(list(itertools.product((0.,1.),repeat=3)))
        y=np.all(truth==truth[:,:1],axis=1);weights=np.where(y,3,1)
        for count in range(4):
            for visible in itertools.combinations(range(3),count):
                p=np.full_like(truth,.5);p[:,visible]=truth[:,visible]
                scores=constructed_posterior(p)
                actual=np.average((scores>=.5)==y,weights=weights)
                self.assertAlmostEqual(actual, [0.5,0.5,5/6,1.0][count])

    def test_decoder_export_and_batch_invariance(self):
        rng=np.random.default_rng(13);x=rng.normal(size=(48,3));y=(x[:,0]>0).astype(int)
        actors=np.repeat(np.arange(8),6)
        for kind in ('logistic','rbf'):
            cp,cross=fit_decoder(x,y,actors,kind,1.)
            full=infer(cp,x)
            np.testing.assert_allclose(full,np.concatenate([infer(cp,x[i:i+1]) for i in range(len(x))]),atol=1e-14)
            self.assertTrue(np.isfinite(cross).all());self.assertTrue(((full>=0)&(full<=1)).all())
            self.assertGreater(np.mean((full>=.5)==y),.9)

    def test_dtw_class_distance_and_batch_invariance(self):
        rng=np.random.default_rng(89)
        base=np.tile(np.sin(np.arange(10)/2)[:,None],(1,36))
        a=np.stack([base+.01*rng.normal(size=base.shape) for _ in range(3)])
        b=np.stack([-base+.01*rng.normal(size=base.shape) for _ in range(3)])
        x=np.concatenate((a,b)).reshape(6,360);labels=np.array([0]*3+[1]*3)
        margins=dtw_margin(x,x,labels)
        self.assertTrue(np.all((margins>0)==labels))
        np.testing.assert_allclose(margins,np.concatenate([dtw_margin(row[None,:],x,labels) for row in x]),atol=1e-12)


if __name__=='__main__':
    unittest.main()
