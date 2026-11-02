"""Bounded acquisition of the checkpoint linked by its original authors."""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

FILE_ID = '1vqMpxZ5LzJjg50HlZdj_QFJGm2gQmDUD'
PUBLIC_URL = 'https://drive.google.com/uc?export=download&id=' + FILE_ID


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__(); self.action = None; self.fields = {}
    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == 'form': self.action = values.get('action')
        if tag == 'input' and values.get('type') == 'hidden': self.fields[values['name']] = values.get('value', '')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True); parser.add_argument('--receipt', type=Path, required=True); args = parser.parse_args()
    if args.output.exists() or args.receipt.exists(): raise FileExistsError('Refuse overwrite')
    args.output.parent.mkdir(parents=True, exist_ok=True); args.receipt.parent.mkdir(parents=True, exist_ok=True)
    cpu, wall = time.process_time(), time.perf_counter()
    with urllib.request.urlopen(PUBLIC_URL, timeout=45) as response:
        page = response.read(65537)
        if len(page) > 65536: raise ValueError('Unexpected public download response')
    form = DownloadForm(); form.feed(page.decode('utf-8'))
    if form.action != 'https://drive.usercontent.google.com/download' or form.fields.get('id') != FILE_ID: raise ValueError('Unexpected checkpoint form')
    if set(form.fields) - {'id', 'export', 'confirm', 'uuid'}: raise ValueError('Unexpected form fields')
    request_url = form.action + '?' + urllib.parse.urlencode(form.fields)
    digest, count = hashlib.sha256(), 0
    with urllib.request.urlopen(request_url, timeout=90) as response, args.output.open('xb') as stream:
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' in content_type: raise ValueError('Checkpoint download returned HTML')
        for block in iter(lambda: response.read(1024 * 1024), b''):
            count += len(block)
            if count > 180_000_000: raise ValueError('Checkpoint exceeds registered180MB cap')
            digest.update(block); stream.write(block)
    if count < 100_000_000: raise ValueError('Unexpected truncated/small checkpoint')
    receipt = dict(schema='hcsn-official-lipreading-checkpoint.v1', source_repository='https://github.com/mpc001/Lipreading_using_Temporal_Convolutional_Networks', source_commit='0cc99fab046bd959578f2baac52e654746da4825', official_model_link='https://bit.ly/3AQTFOG', public_file_id=FILE_ID, filename=args.output.name, bytes=count, sha256=digest.hexdigest(), content_type=content_type, acquired_utc=datetime.now(timezone.utc).isoformat(), cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall, publisher_sha256=None, identity_scope='Observed local bytes from original-author public model link; original repository publishes no SHA256 for this file')
    with args.receipt.open('x') as stream: json.dump(receipt, stream, indent=2, sort_keys=True); stream.write('\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__': main()
