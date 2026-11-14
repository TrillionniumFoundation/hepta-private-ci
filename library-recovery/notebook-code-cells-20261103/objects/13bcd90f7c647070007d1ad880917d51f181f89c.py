# Recompute the main summary from the saved episode outcomes. No training.
import subprocess
import sys
subprocess.run([sys.executable, '-m', 'rrsnn_experiments.aggregate_results'],
               cwd=str(ROOT.parent), check=True)
