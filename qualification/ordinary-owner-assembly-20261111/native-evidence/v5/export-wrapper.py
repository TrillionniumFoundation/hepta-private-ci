import sys
_original_exporter = sys.argv[1]
sys.argv = [sys.argv[0], ''.join(sys.argv[2:])]
exec(compile(_original_exporter, '<string>', 'exec'))
