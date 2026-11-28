"""Filesystem and resume controls only; synthetic receipts are not scientific results."""
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

import numpy as np
import torch


HERE=Path(__file__).resolve().parent


def module_at(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scorer=module_at("ravdess_resume_under_test",HERE/"score.py")
controller=module_at("ravdess_controller_under_test",HERE/"complete.py")


def sha(data):return hashlib.sha256(data).hexdigest()


def json_bytes(value):return (json.dumps(value,indent=2)+"\n").encode()


def array_bytes(value):
    stream=BytesIO();np.savez_compressed(stream,value=np.array([value]))
    return stream.getvalue()


class Fixture:
    """Real files and seals around a forbidden model implementation."""
    def __init__(self,base,kind="sustained"):
        self.base=Path(base);self.kind=kind
        self.root=self.base/"external";self.src=self.base/"source"
        self.study=self.base/"study";self.analytic=self.base/"analytic"
        for directory in (self.root,self.src/"src",self.src/"data",self.study,self.analytic):
            directory.mkdir(parents=True,exist_ok=True)
        code={
            self.src/"src/hcsn_temporal.py":"MARKER='captured source'\n",
            self.src/"src/encoder.py":"from hcsn_temporal import MARKER\nclass AVText:\n def __init__(self,*a,**k):raise AssertionError('no model construction in integrity controls')\n",
            self.analytic/"torch_prices.py":"value=7\n",
            self.analytic/"exact_law.py":"from torch_prices import value\n",
            self.analytic/"encoder_adapter.py":"from encoder import AVText\nfrom exact_law import value\nclass AnalyticAVText(AVText):pass\n",
        }
        for path,text in code.items():path.write_text(text)
        self.source_data=self.src/"data/data.npz";self.source_data.write_bytes(array_bytes(11))
        self.law=self.src/"src/law4.npz";self.law.write_bytes(array_bytes(13))
        hashes={name:sha((self.src/name).read_bytes()) for name in
                ("src/encoder.py","src/hcsn_temporal.py","src/law4.npz","data/data.npz")}
        (self.study/"study.py").write_text("HASHES="+repr(hashes)+"\nclass Data:\n def __init__(self,*a):raise AssertionError('no science data loading in integrity controls')\n")
        self.external=self.root/"external.npz";self.external.write_bytes(array_bytes(17))
        (self.root/"prepared.json").write_bytes(json_bytes({"prepared_sha256":sha(self.external.read_bytes())}))
        tensor=BytesIO();torch.save({"synthetic_scalar":torch.tensor([1.])},tensor)
        weight=tensor.getvalue()
        self.weights=[]
        if kind=="full":
            folder=self.study/"whole_edit";selection={"picks":{},"fits":{}}
            for arm in ("forward","same_site_bp","full_bp"):
                for seed in scorer.SEEDS:
                    key=f"{arm}-{seed}";path=folder/key/"scalar.pt"
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(weight);self.weights.append(path)
                    selection["picks"][key]={"raw":1}
                    selection["fits"][key]=[{"epoch":1,"weights":path.name,"sha256":sha(weight)}]
            self.seal=folder/"development_seal.json"
        elif kind=="analytic":
            folder=self.analytic/"run";selection={}
            for index in range(30):
                key=f"synthetic-{index}";path=folder/key/"scalar.pt"
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(weight);self.weights.append(path)
                selection[key]={"arm":"literal","seed":137,"history":{f"tag{index}":{"file":path.name,"sha256":sha(weight)}}}
            self.seal=folder/"seal.json"
        else:
            folder=self.study/"run";selection={}
            for arm in ("literal","smooth","lif","sdpa"):
                for seed in scorer.SEEDS:
                    key=f"{arm}-{seed}";path=folder/key/"scalar.pt"
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(weight);self.weights.append(path)
                    selection[key]={"best":{"file":path.name,"sha256":sha(weight)}}
            self.seal=folder/"seal.json"
        self.seal.write_bytes(json_bytes(selection))
        self.selection_terminal=folder/"terminal.json"
        self.selection_terminal.write_bytes(json_bytes({"seal_sha256":sha(self.seal.read_bytes())}))
        self.out=self.root/("scores-"+kind);self.out.mkdir()
        self.terminal=self.out/"terminal.json"

    def emit(self,out,src,external,kind,specs,context,modules):
        """Replace only numerical scoring; all production identity gates run."""
        if src==self.src or external==self.external:raise AssertionError("live data passed to numerical stage")
        for path,value in ((src/"data/data.npz",11),(src/"src/law4.npz",13),(external,17)):
            with np.load(path,allow_pickle=False) as data:
                np.testing.assert_array_equal(data["value"],np.array([value]))
            if path.stat().st_nlink!=1 or path.stat().st_mode&0o222:raise AssertionError("not a private readonly file")
        scorer.write(out/"source_models.json",context["models"])
        controls=scorer.save_arrays(out/"controls.npz",synthetic=np.array([0]))
        rows={}
        for key,pin in context["models"].items():
            output=scorer.save_arrays(out/(key+".npz"),synthetic=np.array([0]))
            rows[key]={"weight_sha256":pin["sha256"],"external_scores_sha256":output}
        return dict(group=kind,resume_context=context,external_sha256=context["external_sha256"],
                    source_selection_sha256=scorer.digest(out/"source_models.json"),
                    controls_sha256=controls,models=rows)

    def run(self):
        return scorer.run(self.root,self.src,self.study,self.analytic,self.kind)

    def complete(self):
        with patch.object(scorer,"score_panel",side_effect=self.emit) as numerical:
            self.run()
            if numerical.call_count!=1:raise AssertionError("new stage not invoked")
        return self.terminal.read_bytes()


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name)

    def test_all_three_selection_profiles_resume_without_numerical_work(self):
        for kind in ("full","analytic","sustained"):
            with self.subTest(kind=kind):
                fixture=Fixture(self.base/kind,kind);terminal=fixture.complete()
                with patch.object(scorer,"score_panel",side_effect=AssertionError("resume recomputed")) as numerical:
                    fixture.run();numerical.assert_not_called()
                self.assertEqual(fixture.terminal.read_bytes(),terminal)

    def test_legacy_terminal_is_retained_and_refused(self):
        fixture=Fixture(self.base);fixture.terminal.write_bytes(b"{}")
        with patch.object(scorer,"score_panel",side_effect=AssertionError("unqualified history recomputed")) as numerical:
            with self.assertRaisesRegex(ValueError,"unbound or changed"):
                fixture.run()
            numerical.assert_not_called()
        self.assertEqual(fixture.terminal.read_bytes(),b"{}")

    def test_resume_rejects_changed_inputs_sources_selection_and_runtime(self):
        fixture=Fixture(self.base);terminal=fixture.complete()
        paths=(fixture.weights[0],fixture.external,fixture.root/"prepared.json",
               fixture.source_data,fixture.law,fixture.src/"src/encoder.py",
               fixture.study/"study.py",fixture.analytic/"exact_law.py",fixture.selection_terminal)
        for path in paths:
            with self.subTest(path=path.relative_to(self.base)):
                before=path.read_bytes()
                replacement=before+(b"\n# changed context\n" if path.suffix==".py" else b"\n ")
                path.write_bytes(replacement)
                try:
                    with patch.object(scorer,"score_panel",side_effect=AssertionError("stale result recomputed")):
                        with self.assertRaises(ValueError):fixture.run()
                    self.assertEqual(fixture.terminal.read_bytes(),terminal)
                finally:path.write_bytes(before)
        with patch.object(np,"__version__","synthetic-different-runtime"):
            with self.assertRaisesRegex(ValueError,"context"):fixture.run()
        self.assertEqual(fixture.terminal.read_bytes(),terminal)

    def test_resume_rejects_modified_outputs_without_rewriting_terminal(self):
        fixture=Fixture(self.base);terminal=fixture.complete()
        one=next(fixture.out.glob("literal-*.npz"))
        for path in (fixture.out/"controls.npz",fixture.out/"source_models.json",one):
            with self.subTest(path=path.name):
                before=path.read_bytes();path.write_bytes(before+b"\n ")
                try:
                    with self.assertRaises(ValueError):fixture.run()
                    self.assertEqual(fixture.terminal.read_bytes(),terminal)
                finally:path.write_bytes(before)

    def test_replaced_live_input_is_not_consumed_or_committed(self):
        fixture=Fixture(self.base)
        def numerical(out,src,external,kind,specs,context,modules):
            fixture.external.write_bytes(array_bytes(99))
            result=fixture.emit(out,src,external,kind,specs,context,modules)
            self.assertEqual(result["external_sha256"],sha(array_bytes(17)))
            return result
        with patch.object(scorer,"score_panel",side_effect=numerical):
            with self.assertRaisesRegex(ValueError,"context changed"):fixture.run()
        self.assertFalse(fixture.terminal.exists())

    def test_torch_reads_the_same_weight_bytes_that_were_checked(self):
        fixture=Fixture(self.base);path=fixture.weights[0];wanted=sha(path.read_bytes())
        replacement=BytesIO();torch.save({"synthetic_scalar":torch.tensor([9.])},replacement)
        actual_load=torch.load
        def replacing(stream,**kwargs):
            path.write_bytes(replacement.getvalue())
            self.assertIsInstance(stream,BytesIO)
            self.assertEqual(kwargs,{"weights_only":True,"map_location":"cpu"})
            return actual_load(stream,**kwargs)
        with patch.object(torch,"load",side_effect=replacing):
            actual=scorer.verified_state(path,wanted)
        torch.testing.assert_close(actual["synthetic_scalar"],torch.tensor([1.]),rtol=0,atol=0)
        with patch.object(torch,"load",side_effect=AssertionError("bad hash reached loader")):
            with self.assertRaisesRegex(ValueError,"input identity"):scorer.verified_state(path,wanted)

    def test_original_module_dependencies_ignore_ambient_module_cache(self):
        project=HERE.parent
        original={
            self.base/"source/src/encoder.py":project/"billion_recovery/original/scripts/encoder.py",
            self.base/"source/src/hcsn_temporal.py":project/"generation/model.py",
            self.base/"study/study.py":project/"crema/study.py",
            self.base/"analytic/encoder_adapter.py":project/"analytic_encoder/encoder_adapter.py",
            self.base/"analytic/exact_law.py":project/"analytic_encoder/exact_law.py",
            self.base/"analytic/torch_prices.py":project/"differentiable_law/torch_prices.py",
        }
        for path,source in original.items():
            path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,path)
        poisoned={name:ModuleType(name) for name in
                  ("encoder","hcsn_temporal","study","exact_law","torch_prices","encoder_adapter")}
        with patch.dict(sys.modules,poisoned):
            modules,pins=scorer.source_modules(self.base/"source",self.base/"study",self.base/"analytic")
        self.assertIs(modules["encoder_adapter"].AVText,modules["encoder"].AVText)
        self.assertIs(modules["exact_law"].price,modules["torch_prices"].price)
        self.assertEqual(pins,{str(path):sha(source.read_bytes()) for path,source in original.items()})

    def test_controller_invokes_actual_child_for_existing_markers_and_propagates_failure(self):
        root=self.base/"external";root.mkdir();(root/"prepared.json").write_text("{}")
        for folder in ("hcsn-sustained-1140569/whole_edit","hcsn-analytic-encoder-1140569/run","hcsn-sustained-1140569/run"):
            path=self.base/folder;path.mkdir(parents=True,exist_ok=True);(path/"terminal.json").write_text("{}")
        for kind in ("full","analytic","sustained"):
            path=root/("scores-"+kind);path.mkdir();(path/"terminal.json").write_text("legacy marker")
        script="from pathlib import Path\nimport sys\np=Path(sys.argv[1])/'called'\nwith p.open('a') as f:f.write(sys.argv[-1]+'\\n')\n"
        (root/"score.py").write_text(script)
        controller.main(root)
        self.assertEqual((root/"called").read_text().splitlines(),["full","analytic","sustained"])
        (root/"score.py").write_text(script+"raise SystemExit(7)\n")
        with self.assertRaises(subprocess.CalledProcessError):controller.main(root)
        self.assertEqual((root/"scores-full/terminal.json").read_text(),"legacy marker")

    def test_resume_json_paths_reject_fifos(self):
        for name in ("terminal.json","source_models.json"):
            with self.subTest(name=name):
                fixture=Fixture(self.base/name);original=fixture.complete()
                target=fixture.out/name;target.unlink();os.mkfifo(target)
                inode=target.stat().st_ino
                with patch.object(scorer,"score_panel",side_effect=AssertionError("resume recomputed")):
                    with self.assertRaisesRegex(ValueError,"nonregular input"):fixture.run()
                self.assertEqual(target.stat().st_ino,inode)
                if name!="terminal.json":self.assertEqual(fixture.terminal.read_bytes(),original)

    def test_nonregular_inputs_fail_without_waiting_for_a_fifo_writer(self):
        fifo=self.base/"fifo";os.mkfifo(fifo)
        for reader in (scorer.captured,scorer.digest):
            with self.subTest(reader=reader.__name__):
                with self.assertRaisesRegex(ValueError,"nonregular"):reader(fifo)


if __name__=="__main__":unittest.main()
