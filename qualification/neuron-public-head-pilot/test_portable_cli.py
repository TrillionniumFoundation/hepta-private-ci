"""CLI smoke tests need numpy, never torch/model/data downloads."""
import subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
class PortableCliTests(unittest.TestCase):
 def test_extract_help_without_model(self):
  p=subprocess.run([sys.executable,str(ROOT/'extract.py'),'--help'],capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr);self.assertIn('--snapshot',p.stdout);self.assertIn('--output-dir',p.stdout)
 def test_prepare_help(self):
  p=subprocess.run([sys.executable,str(ROOT/'prepare.py'),'--help'],capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr);self.assertIn('--output-dir',p.stdout)
 def test_analyze_import_no_torch(self):
  p=subprocess.run([sys.executable,'-c','import sys,analyze;assert "torch" not in sys.modules'],cwd=ROOT,capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr)
if __name__=='__main__':unittest.main()
