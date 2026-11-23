"""Read the previously archived c12 failure using only its fixed Bazel shard log."""
import hashlib
import json
import re
import sys
from zipfile import ZipFile
with ZipFile(sys.argv[1]) as z:
    name='7016/test-attempt-logs-atskssrv/files/000002.log'
    b=z.read(name)
assert hashlib.sha256(b).hexdigest()=='f5d3e01d3a0b5afba10289280ee5c88e0183a7d4ce196d8d2e053ce1500fbadc'
txt=b.decode()
patterns=[r'^HEPTA_PUBLISHED_ORIGINAL_READ request_id=4 cut_receipts=4 .*?total_handler_us=(124097) ',r'^HEPTA_SELECTOR_REMOTE_READBACK elapsed_us=(137518) result=Ok\(\(\)\)',
          r'^HEPTA_PUBLISHED_ORIGINAL_READ request_id=5 cut_receipts=4 .*?total_handler_us=(126396) ',r'^HEPTA_SELECTOR_REMOTE_READBACK elapsed_us=(103325) result=Err\(PublishedRead\(Transport\(Closed\)\)\)']
hits=[re.search(p,txt,re.M) for p in patterns]
assert all(hits) and sorted(h.start() for h in hits)==[h.start() for h in hits]
durations=[int(h.group(1)) for h in hits]
assert len(set(durations))==4 and sum(durations)==491336
assert not re.search(r'^HEPTA_PUBLISHED_ORIGINAL_READ request_id=11 ',txt,re.M)
assert 'HEPTA_SELECTOR_REMOTE_PUBLISHED elapsed_us=35368 result=Err(Transport(Closed))' in txt
assert 'original published Circuit read: invalid agentd configuration: Unavailable' in txt
assert 'OwnerUnavailable("original learning evidence owner")' in txt
assert 'Q24_CLOCK' not in txt and 'Q24_BOUND' not in txt
print(json.dumps({'source':'ae404b2935fa0b7ea39bf09ef1016917a507f6d5','source_tree':'9554ddb1b5cca7502b58b7bacfc446671fe5289c',
                  'artifact':14803055341,'member':name,'raw_shard_sha256':hashlib.sha256(b).hexdigest(),
                  'four_successive_stage_us':durations,'sum_us':sum(durations),'nested_closed_after_us':35368,
                  'request_11_success_output':False,'outer_selection_or_shutdown_order_in_this_record':None},indent=2))
