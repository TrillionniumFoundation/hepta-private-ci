from fractions import Fraction
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import torch

from .vision import _info, cumulative_class_probability, decode_prefixes, select_indices, source_meta


class SemanticCausality(unittest.TestCase):
    def test_exact_vfr_and_equal_timestamps(self):
        pts=list(map(Fraction,["0",".15",".42",".42",".95","1.6"]))
        self.assertEqual(select_indices(pts,list(map(Fraction,[".42",".48",".96","1.20"]))),[1,3,4,4])
        with self.assertRaises(ValueError):select_indices(pts,[Fraction(0)])

    def test_class_union_and_causal_mean(self):
        idx=[[579,881],[402,546]]
        logits=torch.full((6,1000),-12.,dtype=torch.float64)
        logits[:,579]=1
        logits[:2,402]=3
        result=cumulative_class_probability(logits,idx)
        direct=logits.exp()[:,[579,881]].sum(1)/(logits.exp()[:,[579,881,402,546]].sum(1))
        self.assertTrue(torch.allclose(result[:,0],direct.cumsum(0)/torch.arange(1,7),atol=1e-12))
        logits[3:,402]=100.
        self.assertTrue(torch.equal(result[:3],cumulative_class_probability(logits,idx)[:3]))

    def test_same_decoder_preserves_physical_pts_at_nonzero_seek(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"fixture.mp4"
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                  "testsrc2=size=40x30:duration=7:rate=5","-c:v","mpeg4","-pix_fmt","yuv420p",
                  "-threads","1",str(p)],check=True)
            frames,rec=decode_prefixes(p,3.12,source_meta(p))
            np.testing.assert_allclose(rec["chosen_pts_seconds"],[3.4,4.,4.4,5.,5.4,5.8])
            self.assertEqual([im.size for im in frames],[(40,30)]*6)
            self.assertTrue(all(x<y for x,y in zip(rec["chosen_pts_seconds"],rec["absolute_endpoint_seconds"])))

    def test_invalid_showinfo_clock_is_refused(self):
        with self.assertRaises(ValueError):
            _info(b"config in time_base: 1/30\nconfig in time_base: 1/22")


if __name__=="__main__":
    unittest.main()
