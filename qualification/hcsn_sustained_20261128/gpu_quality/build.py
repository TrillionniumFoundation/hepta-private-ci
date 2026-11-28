import base64
import hashlib
import json
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent
base=HERE.parent
spec={'population.py':base/'price_cache/population.py','he_xiong.py':base/'zero_premium/he_xiong.py',
      'fft_transport.py':base/'independent_experiment/fft_transport.py','validate_prices.py':base/'price_cache/validate_prices.py',
      'digits01.npz':base/'independent_experiment/digits01.npz','worker.py':HERE/'worker.py','telemetry.py':HERE/'telemetry.py'}
payload={}
for name,path in spec.items():
    body=path.read_bytes()
    payload[name]={'sha':hashlib.sha256(body).hexdigest(),'blob':base64.b64encode(zlib.compress(body,9)).decode('ascii')}
source=(HERE/'driver.py').read_text().replace('INPUTS = {}','INPUTS = '+repr(payload))
(HERE/'sealed.py').write_text(source)
print(json.dumps({'request':'hcsn-native-quality-energy-1140569-20261128','source_sha256':hashlib.sha256(source.encode()).hexdigest(),
      'source_bytes':len(source.encode()),'inputs':{name:data['sha'] for name,data in payload.items()}},indent=2))
