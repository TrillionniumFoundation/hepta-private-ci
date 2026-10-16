"""Fail-closed E1 text-only runtime contract after actual FFmpeg/codec CI failure.

Research mechanism check only. Does not claim physical Encoder qualification,
model accuracy, production authorization, or full CI success.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STEP = '      - name: Install pinned CPU-only research runtime\n'
NEXT = '      - name: Run model-free and actual CPU optimizer integrity tests\n'


def check_text_runtime(workflow: str) -> None:
    """Require E1 text-only packages, reject video-codec install or import."""
    if type(workflow) is not str or workflow.count(STEP) != 1 or workflow.count(NEXT) != 1:
        raise ValueError('missing or duplicate exact text runtime step boundary')
    _, rest = workflow.split(STEP, 1)
    install, _ = rest.split(NEXT, 1)
    if len(install) > 5000 or len(install) < 300:
        raise ValueError('unsafe runtime step size')
    # An audio/video import is NOT part of an English text Encoder/Head test.
    # Installing torchcodec without FFmpeg shared libraries caused an observed
    # actual hosted failure BEFORE any physical Encoder trial.
    if re.search(r'\btorchcodec\b|libavutil|apt-get|ffmpeg|--no-deps', install, re.I):
        raise ValueError('unqualified media/FFmpeg runtime or package bypass')
    for required in ("'torch==2.10.0'", "'torchvision==0.25.0'",
                     "'transformers==5.19.0'", "'sentence-transformers==6.1.0'",
                     "'numpy==2.2.6'", "'safetensors==0.8.0'",
                     '"$PY" -m pip check', '"$PY" -m pip freeze',
                     'import numpy,torch,torchvision',
                     'assert torchvision.__version__.startswith(\'0.25.0\')'):
        if required not in install:
            raise ValueError('missing frozen core model/runtime dependency or smoke: '+required)
    if workflow.count('Actual three independent CPU model and 40-step Head executions') != 1:
        raise ValueError('original physical model work was removed')
    if workflow.count('Independent numeric scoring and three-way paired evidence') != 1:
        raise ValueError('original independent numeric scorer was removed')


class TextRuntimeContract(unittest.TestCase):
    @classmethod
    def fixture(cls) -> str:
        return '''name: text-only original E1
      - name: Install pinned CPU-only research runtime
        run: |
          set -euo pipefail
          PY="$RUNNER_TEMP/e1-real-venv/bin/python"
          "$PY" -m pip install --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu 'torch==2.10.0' 'torchvision==0.25.0'
          "$PY" -m pip install --only-binary=:all: 'transformers==5.19.0' 'sentence-transformers==6.1.0' 'numpy==2.2.6' 'safetensors==0.8.0'
          "$PY" -m pip check
          "$PY" - <<'PYCHECK'
          import numpy,torch,torchvision
          assert torchvision.__version__.startswith('0.25.0')
          PYCHECK
          "$PY" -m pip freeze > "$RUNNER_TEMP/e1-pinned-runtime.txt"
      - name: Run model-free and actual CPU optimizer integrity tests
        run: echo test
      - name: Actual three independent CPU model and 40-step Head executions
        run: echo model
      - name: Independent numeric scoring and three-way paired evidence
        run: echo review
'''

    def test_registered_workflow_rejects_optional_media_codec(self) -> None:
        actual = Path(__file__).resolve().parents[2] / '.github/workflows/hepta-e1-real-public-three.yml'
        self.assertTrue(actual.is_file(), 'the registered real E1 GitHub workflow is required')
        check_text_runtime(actual.read_text(encoding='utf-8'))

    def test_accepts_isolated_text_only_runtime(self) -> None:
        check_text_runtime(self.fixture())

    def test_rejects_original_broken_torchcodec_install(self) -> None:
        broken = self.fixture().replace("'torchvision==0.25.0'", "'torchvision==0.25.0' 'torchcodec==0.10.0'")
        with self.assertRaisesRegex(ValueError, 'media'):
            check_text_runtime(broken)

    def test_rejects_old_media_smoke_import(self) -> None:
        broken = self.fixture().replace('import numpy,torch,torchvision',
                                        'import numpy,torch,torchvision,torchcodec')
        with self.assertRaisesRegex(ValueError, 'media'):
            check_text_runtime(broken)

    def test_rejects_disabling_dependency_resolution(self) -> None:
        broken = self.fixture().replace('--only-binary=:all:', '--no-deps --only-binary=:all:')
        with self.assertRaisesRegex(ValueError, 'bypass'):
            check_text_runtime(broken)

    def test_rejects_missing_torch_and_source_review(self) -> None:
        broken = self.fixture().replace("'torch==2.10.0'", "'torch==2.9.0'")
        with self.assertRaisesRegex(ValueError, 'missing frozen'):
            check_text_runtime(broken)
        broken = self.fixture().replace('Independent numeric scoring and three-way paired evidence',
                                        'Skipped all independent reviews')
        with self.assertRaisesRegex(ValueError, 'numeric scorer'):
            check_text_runtime(broken)

    def test_rejects_duplicate_or_missing_runtime_steps(self) -> None:
        broken = self.fixture().replace(STEP, STEP+STEP)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            check_text_runtime(broken)
        broken = self.fixture().replace(NEXT, '')
        with self.assertRaisesRegex(ValueError, 'step boundary'):
            check_text_runtime(broken)


if __name__ == '__main__':
    unittest.main()
