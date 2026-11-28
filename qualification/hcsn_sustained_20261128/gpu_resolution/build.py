import base64
import hashlib
import json
from pathlib import Path
import zlib

here=Path(__file__).resolve().parent
parent=here.parent
sources={'population.py':parent/'price_cache/population.py',
         'he_xiong.py':parent/'zero_premium/he_xiong.py',
         'fft_transport.py':parent/'independent_experiment/fft_transport.py',
         'telemetry.py':parent/'gpu_quality/telemetry.py','worker.py':here/'worker.py'}
payload={}
for name,p in sources.items():
    b=p.read_bytes()
    payload[name]={'sha':hashlib.sha256(b).hexdigest(),'blob':base64.b64encode(zlib.compress(b,9)).decode('ascii')}
code=(here/'driver.py').read_text().replace('INPUTS = {}','INPUTS = '+repr(payload))
(here/'sealed.py').write_text(code)
print(json.dumps({'request':'hcsn-native-hires-transport-1140569-20261128',
                  'source_sha256':hashlib.sha256(code.encode()).hexdigest(),'bytes':len(code.encode()),
                  'components':{name:v['sha'] for name,v in payload.items()}},indent=2))
