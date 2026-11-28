"""Build one offline T4 experiment with hashed copies of each declared input."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import zlib

HERE = Path(__file__).resolve().parent


def build(sources, destination):
    payload = {
        name: {
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': base64.b64encode(zlib.compress(path.read_bytes(), 9)).decode('ascii'),
        } for name, path in sources.items()
    }
    main = (HERE / 'run_t4.py').read_text()
    replace = "INPUTS = {}  # replaced in the sealed single-file cloud worker"
    assert main.count(replace) == 1
    worker = main.replace(replace, 'INPUTS = ' + repr(payload))
    destination.write_text(worker)
    return {
        'source_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'bytes': len(worker.encode()),
        'inputs': {name: row['sha256'] for name, row in payload.items()}
    }


if __name__ == '__main__':
    population, law, transport, data, destination = map(Path, sys.argv[1:])
    source = {'population.py': population, 'he_xiong.py': law, 'fft_transport.py': transport,
              'digits01.npz': data, 'validate_prices.py': HERE / 'validate_prices.py'}
    print(json.dumps(build(source, destination), indent=2))
