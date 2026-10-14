"""Pinned source/video staging contracts; real images, synthetic decoder/tower."""
from __future__ import annotations

import copy
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_video as p


def image_frames(seed, count=40):
    return [(Image.new("RGB", (48, 48), ((seed+i) % 255, i % 255, 3*i % 255)), i*33333)
            for i in range(count)]


def tree(inventory, revision, readme_blob):
    rows = [{"path": "README.md", "mode": "100644", "type": "blob",
             "sha": readme_blob, "size": 10}]
    rows += [{"path": "videos/small/"+name, "mode":"100644", "type":"blob",
              "sha": blob, "size": size} for name, (blob, size, _split) in inventory.items()]
    return {"sha": revision, "tree": rows, "truncated": False}


class FakeTower:
    simulated = True
    def __init__(self, root, models):
        self.calls = {"clip":0}; self.identities={"clip":"fake"}; self.materializations={}
        self.models={}; self.processors={}
    def encode(self, name, item, root):
        self.calls["clip"] += 1
        values=[]
        for frame in item:
            raw=(root/frame["path"]).read_bytes()
            image=Image.open(io.BytesIO(raw)).convert("RGB")
            r,g,b=image.getpixel((0,0))
            values.append(torch.tensor([r/255,g/255,b/255,1.],dtype=torch.float32))
        return torch.stack(values), torch.tensor([f["timestamp_us"] for f in item],dtype=torch.long)
    def close(self): pass


class PublicVideoTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.readme=b"TEST SOURCE README; license unspecified."
        names=[f"clip{i}.mp4" for i in range(10)]
        splits=["train"]*6+["calibration"]*2+["holdout"]*2
        self.raw={name: bytes([i+1])* (100+i) for i,name in enumerate(names)}
        self.inventory={name:(p.git_blob(self.raw[name]),len(self.raw[name]),split)
                        for name,split in zip(names,splits)}
        self.revision="a"*40; self.readme_blob=p.git_blob(self.readme)
        self.tree=tree(self.inventory,self.revision,self.readme_blob)
    def tearDown(self): self.temp.cleanup()
    def read(self,url,maximum):
        if "/git/trees/" in url: return e.canonical(self.tree)
        if url.endswith("README.md"): return self.readme
        return self.raw[url.rsplit("/",1)[-1]]
    def decode(self,raw): return image_frames(raw[0])

    def test_fixed_stage_is_source_disjoint_balanced_and_opaque(self):
        dataset, cohort = p.stage(self.root,_read=self.read,_decode=self.decode,
                                  inventory=self.inventory,revision=self.revision,
                                  readme_blob=self.readme_blob)
        rows=[e.decode(line) for line in (self.root/"dataset.jsonl").read_bytes().splitlines()]
        self.assertEqual({s:sum(r["split"]==s for r in rows) for s in ("train","calibration","holdout")},
                         {"train":48,"calibration":16,"holdout":16})
        self.assertTrue(all(len(r["inputs"]["video"])==8 for r in rows))
        self.assertTrue(all(Path(f["path"]).stem==f["sha256"] for r in rows for f in r["inputs"]["video"]))
        groups={s:{r["group"] for r in rows if r["split"]==s} for s in ("train","calibration","holdout")}
        self.assertTrue(all(not groups[a]&groups[b] for a in groups for b in groups if a!=b))
        registered=e.decode((self.root/cohort["path"]).read_bytes())
        for i in range(0,len(registered),2):
            self.assertEqual(registered[i]["frame_sha256s"], list(reversed(registered[i+1]["frame_sha256s"])))
        self.assertEqual(dataset["sha256"],e.sha((self.root/"dataset.jsonl").read_bytes()))

    def test_tree_and_source_corruption_fail_without_replacement(self):
        altered=copy.deepcopy(self.tree); altered["tree"][1]["sha"]="0"*40
        with self.assertRaises(e.InputError):
            p.verify_tree(altered,inventory=self.inventory,revision=self.revision,readme_blob=self.readme_blob)
        def bad(url,maximum):
            value=self.read(url,maximum)
            return value+b"x" if url.endswith("clip0.mp4") else value
        with self.assertRaises(e.InputError):
            p.stage(self.root,_read=bad,_decode=self.decode,inventory=self.inventory,
                    revision=self.revision,readme_blob=self.readme_blob)

    def test_decode_mp4_uses_exact_pts_and_bounds(self):
        import sys
        from types import SimpleNamespace
        class Frame:
            time_base = SimpleNamespace(numerator=1, denominator=1000)
            def __init__(self, i): self.pts = i
            def to_image(self): return Image.new("RGB", (64,64), (self.pts,0,0))
        class Container:
            def __init__(self, count):
                self.stream = SimpleNamespace(time_base=Frame.time_base)
                self.streams = SimpleNamespace(video=[self.stream])
                self.count = count
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def decode(self, stream): return iter(Frame(i) for i in range(self.count))
        prior = sys.modules.get("av")
        sys.modules["av"] = SimpleNamespace(open=lambda *_a, **_k: Container(32))
        try:
            frames = p.decode_mp4(b"video")
            self.assertEqual(len(frames),32); self.assertEqual(frames[0][1],0)
            self.assertEqual(frames[-1][1],31000)
            sys.modules["av"] = SimpleNamespace(open=lambda *_a, **_k: Container(31))
            with self.assertRaises(e.InputError): p.decode_mp4(b"video")
        finally:
            if prior is None: sys.modules.pop("av",None)
            else: sys.modules["av"] = prior

    def test_landmarks_are_exact_unique_and_cover_endpoints(self):
        frames=image_frames(1,63); selected=p.select_landmarks(frames)
        self.assertEqual(len(selected),32); self.assertEqual(selected[0][0],0)
        self.assertEqual(selected[-1][0],62); self.assertEqual(len({r[0] for r in selected}),32)

    def test_full_execution_uses_real_training_and_frame_cache(self):
        root=self.root/"study"
        def stage_model(model_root,*args,**kwargs):
            (model_root/"model").mkdir()
            return {"path":"model","revision":"b"*40,"files":{}}
        root.mkdir()
        dataset,cohort=p.stage(root,_read=self.read,_decode=self.decode,inventory=self.inventory,
                               revision=self.revision,readme_blob=self.readme_blob)
        model_root=root/"vision"; model_root.mkdir(); model=stage_model(model_root)
        model["path"]="vision/model"
        manifest={"schema":"hepta.shared-stem-media.v1","classes":2,"steps":80,"seed":17,
                  "temporal":False,"video_profile":"paired_temporal_order_v1",
                  "dataset":dataset,"cohort":cohort,"models":{"clip":model}}
        e.write_once(root/"manifest.json",manifest)
        from experiments.shared_stem_cell.video_temporal import run
        report=run(root/"manifest.json",root/"execution",_tower_factory=FakeTower)
        self.assertEqual(report["frame_cache"]["unique_frames"],320)
        self.assertEqual(report["frame_cache"]["requested_frame_rows"],640)
        self.assertEqual(report["frame_cache"]["hits"],320)
        self.assertEqual(report["frame_cache"]["physical_video_calls"],40)
        self.assertEqual(report["order_blind_pair_max_probability_difference"],0.)
        self.assertFalse(report["action_recognition_established"])


if __name__ == "__main__": unittest.main()
