"""Bounded fail-closed native FFmpeg prerequisites for TorchCodec CPU runtime.

Only checks that the pinned research job can load native video/audio library
symbols; model weights, source, labels and acceptance remain independently gated.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import re


class Invalid(ValueError):
    pass


FAMILIES = ('avutil', 'avcodec', 'avformat')
# Supported TorchCodec wheel 0.10.x runtime families: FFmpeg 4--8.
SONAME = re.compile(r'lib(?:avutil|avcodec|avformat)\.so\.[0-9]{1,2}\Z')


def require_native_ffmpeg(*, finder=None, loader=None):
    """Return only family names; never store paths or binary contents."""
    finder = finder or ctypes.util.find_library
    loader = loader or ctypes.CDLL
    for family in FAMILIES:
        name = finder(family)
        if type(name) is not str or not SONAME.fullmatch(name):
            raise Invalid('required pinned native FFmpeg family missing')
        try:
            loader(name)
        except (OSError, ValueError, TypeError) as e:
            raise Invalid('native FFmpeg shared library cannot load') from None
    return {'native_ffmpeg_families': list(FAMILIES),
            'torchaudio_or_video_task_quality_proved': False,
            'production_accepted': False,
            'authority':'DENY_ALL'}


if __name__ == '__main__':
    import json
    print(json.dumps(require_native_ffmpeg(),sort_keys=True))
