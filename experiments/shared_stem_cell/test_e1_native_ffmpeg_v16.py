"""Research E1 TorchCodec missing-system-libraries regression, model-free."""
import unittest
from e1_native_ffmpeg_v16 import require_native_ffmpeg, Invalid

class NativeFFmpegTests(unittest.TestCase):
    def test_ffmpeg6_family_allowed(self):
        got=require_native_ffmpeg(
            finder=lambda x: {'avutil':'libavutil.so.58','avcodec':'libavcodec.so.60',
                              'avformat':'libavformat.so.60'}[x],loader=lambda s: object())
        self.assertEqual(got['authority'],'DENY_ALL')
        self.assertFalse(got['production_accepted'])
    def test_ffmpeg7_family_allowed(self):
        self.assertEqual(require_native_ffmpeg(
            finder=lambda x: {'avutil':'libavutil.so.59','avcodec':'libavcodec.so.61',
                              'avformat':'libavformat.so.61'}[x],loader=lambda s: object())['native_ffmpeg_families'],
                         ['avutil','avcodec','avformat'])
    def test_missing_avutil_fails(self):
        with self.assertRaises(Invalid):require_native_ffmpeg(finder=lambda x: None,loader=lambda s: object())
    def test_missing_codec_fails(self):
        with self.assertRaises(Invalid):
            require_native_ffmpeg(finder=lambda x: None if x=='avcodec' else 'libavutil.so.59',loader=lambda s: object())
    def test_incorrect_shared_library_fails(self):
        with self.assertRaises(Invalid):
            require_native_ffmpeg(finder=lambda x: '/tmp/evil/libavutil.so.59',loader=lambda s: object())
    def test_injection_path_fails(self):
        with self.assertRaises(Invalid):
            require_native_ffmpeg(finder=lambda x: 'libavutil.so.59\nX-GH-TOKEN: secret',loader=lambda s: object())
    def test_invalid_extension_fails(self):
        with self.assertRaises(Invalid):
            require_native_ffmpeg(finder=lambda x: 'libavutil.a',loader=lambda s: object())
    def test_loader_failure_fails(self):
        def fail(s): raise OSError('private file /tmp/token_path')
        with self.assertRaisesRegex(Invalid,'native FFmpeg shared library cannot load') as cm:
            require_native_ffmpeg(finder=lambda x: 'libavutil.so.59',loader=fail)
        self.assertNotIn('/tmp',str(cm.exception))
    def test_system_runtime_library(self):
        # Only check this isolated execution environment, not any hosted pass.
        report=require_native_ffmpeg()
        self.assertEqual(report['authority'],'DENY_ALL')
        self.assertEqual(len(report['native_ffmpeg_families']),3)

if __name__=='__main__': unittest.main()
