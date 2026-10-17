"""P11: isolate genuine P1/P2 dependency names before any expensive Qwen loading.

These are intentionally synthetic source fixtures; the dedicated CI additionally
loads the original repository's P1/P2 modules in its pre-installation step.
Neither test path calls Hugging Face or produces real model evidence.
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import online

WEIGHTS = 'f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b'
TOKENIZER = 'aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4'
REV = '16706fc57485378d4ffaf54139b29ccc66ae08fa'


def make_parent(root: Path, drift: bool = False, bad_import: bool = False) -> Path:
    for name in ('physical_online_p8', 'physical_online_p2', 'token_portfolio_p1'):
        (root/name).mkdir(parents=True,exist_ok=True)
    marker = root/'physical_online_p8'/'online.py'
    marker.write_text('synthetic file identity; never used as model evidence\n')
    (root/'token_portfolio_p1'/'portfolio.py').write_text(
        'class Invalid(ValueError): pass\n'
        'POLICIES=("direct",)\n'
        'def digest(x): return "sha"\n'
        'def manifest(*a): return {}\n'
        'def public_cases(*a): return []\n'
        'def run(*a): return None\n')
    (root/'physical_online_p2'/'public_source.py').write_text(
        'SCHEMA="synthetic-source"\n'
        'def encoded(x): return b""\n'
        'def new_json(*a): pass\n'
        'def sha(x): return "sha"\n'
        'def original_manifest(): return {"synthetic":True}\n'
        'def sync_dir(*a): pass\n')
    (root/'physical_online_p2'/'physical_online.py').write_text(
        'from portfolio import Invalid, POLICIES, digest as p1_digest, manifest, public_cases, run\n'
        'from public_source import original_manifest, encoded\n'
        'MODEL_REPO="Qwen/Qwen3-0.6B"\n'
        f'MODEL_REV="{REV}"\n'
        f'MODEL_WEIGHTS_SHA256="{WEIGHTS if not drift else "0"*64}"\n'
        f'MODEL_TOKENIZER_SHA256="{TOKENIZER}"\n'
        'class QwenReader:\n'
        '    def dependency(self):\n'
        '        from portfolio import Invalid\n'
        '        return Invalid\n'
        + ('from nonexistent_p11_external_plugin import missing\n' if bad_import else ''))
    return marker


class ParentImportBindingsP11Tests(unittest.TestCase):
    def test_real_parent_binding_overrides_loaded_p9_module_only_inside_p5(self):
        with tempfile.TemporaryDirectory() as td:
            marker=make_parent(Path(td))
            p9_fake=types.ModuleType('portfolio')
            p9_fake.Invalid=type('WrongInvalid',(ValueError,),{})
            public_fake=types.ModuleType('public_source')
            with (patch.object(online,'__file__',str(marker)),
                  patch.dict(sys.modules, {'portfolio':p9_fake,'public_source':public_fake})):
                actual=online.old_model_loader()
                self.assertIs(sys.modules['portfolio'],p9_fake)
                self.assertIs(sys.modules['public_source'],public_fake)
                self.assertIsNot(actual.Invalid,p9_fake.Invalid)
                self.assertTrue(actual.Invalid.__module__.startswith('hepta_p8_locked_p1_portfolio_'))
                self.assertTrue(actual.original_manifest.__module__.startswith('hepta_p8_locked_p2_public_source_'))
                self.assertIs(actual.QwenReader().dependency(),actual.Invalid)
                self.assertIs(online.old_model_loader(),actual)

    def test_missing_parent_fails_closed_without_replacing_p9(self):
        with tempfile.TemporaryDirectory() as td:
            marker=make_parent(Path(td))
            (Path(td)/'token_portfolio_p1'/'portfolio.py').unlink()
            collision=types.ModuleType('portfolio')
            with patch.object(online,'__file__',str(marker)), patch.dict(sys.modules,{'portfolio':collision}):
                with self.assertRaisesRegex(ValueError,'original locked P1/P2 source unavailable'):
                    online.old_model_loader()
                self.assertIs(sys.modules['portfolio'],collision)

    def test_model_profile_drift_rejected_without_weight_download(self):
        with tempfile.TemporaryDirectory() as td:
            marker=make_parent(Path(td),drift=True)
            with patch.object(online,'__file__',str(marker)):
                with self.assertRaisesRegex(ValueError,'original P5 model source profile drift'):
                    online.old_model_loader()

    def test_failed_parent_import_does_not_poison_future_retry(self):
        with tempfile.TemporaryDirectory() as td:
            marker=make_parent(Path(td),bad_import=True)
            with patch.object(online,'__file__',str(marker)):
                with self.assertRaises(ModuleNotFoundError):
                    online.old_model_loader()
                make_parent(Path(td))
                self.assertIsNotNone(online.old_model_loader().QwenReader)

    def test_reject_symlink_as_locked_parent(self):
        with tempfile.TemporaryDirectory() as td:
            marker=make_parent(Path(td))
            p=Path(td)/'physical_online_p2'/'physical_online.py'
            real=p.with_suffix('.real.py')
            p.rename(real)
            p.symlink_to(real)
            with patch.object(online,'__file__',str(marker)):
                with self.assertRaisesRegex(ValueError,'original locked P1/P2 source unavailable'):
                    online.old_model_loader()


if __name__=='__main__':
    unittest.main()
