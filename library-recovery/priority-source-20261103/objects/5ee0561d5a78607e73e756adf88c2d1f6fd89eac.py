import hashlib
import math
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from PIL import Image
from media_bytes_gate import check_bytes


def h(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class FourModeRealBytesValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            raise unittest.SkipTest('ffmpeg/ffprobe not installed')
        cls.tmp=tempfile.TemporaryDirectory()
        root=Path(cls.tmp.name)
        (root/'clip.txt').write_text('synthetic clip transcript 0-0.5 seconds',encoding='utf-8')
        Image.new('RGB',(32,32),(30,60,120)).save(root/'frame.png')
        with wave.open(str(root/'audio.wav'),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
            audio.writeframes(b'\0\0'*16000)
        subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i',
                        'color=c=blue:s=64x64:r=8','-t','1',
                        '-c:v','mpeg4',str(root/'video.mp4')],check=True,timeout=10)
        cls.root=root
        cls.record={'sample_id':'synthetic-unit','entity_id':'fixture-1','scene_id':'scene-1',
                    'split':'holdout','t_start_sec':0.,'t_end_sec':.5,
                    'provenance':'LOCAL SYNTHETIC TEST FIXTURE, NO REAL DATA',
                    'files':{m:{'path':fname,'sha256':h(root/fname)} for m,fname in
                             (('text','clip.txt'),('image','frame.png'),
                              ('audio','audio.wav'),('video','video.mp4'))}}

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_four_modes_are_actually_readable(self):
        v=check_bytes([self.record],self.root)
        self.assertTrue(v['byte_integrity_metadata_valid'],v['failures'])
        self.assertFalse(v['four_modality_encoder_executed'])
        self.assertFalse(v['production_evidence_accepted'])

    def test_hash_tampering_denied(self):
        import copy
        r=copy.deepcopy(self.record)
        r['files']['audio']['sha256']='1'*64
        self.assertFalse(check_bytes([r],self.root)['byte_integrity_metadata_valid'])

    def test_path_escape_denied(self):
        import copy
        r=copy.deepcopy(self.record)
        r['files']['text']['path']='../not_present.txt'
        self.assertFalse(check_bytes([r],self.root)['byte_integrity_metadata_valid'])

    def test_bad_temporal_alignment_denied(self):
        import copy
        r=copy.deepcopy(self.record)
        r['t_end_sec']=5
        result=check_bytes([r],self.root)
        self.assertFalse(result['byte_integrity_metadata_valid'])
        self.assertIn('shorter than aligned window',str(result['failures']))

if __name__=='__main__':unittest.main()
