#!/usr/bin/env python3
"""Read only the actual old summary and the frozen new census; no API calls."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--old-root",type=Path,default=Path(__file__).resolve().parent)
p.add_argument("--census-root",type=Path,default=Path(__file__).resolve().parent.parent)
a=p.parse_args()
raw=(a.old_root/"old-summary.actual-5fac62f.json").read_bytes()
assert len(raw)==1846885
assert hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()=="5fac62f2526a56ebc0cdaa8cfe66531c9a33f912"
assert hashlib.sha256(raw).hexdigest()=="4adb3a73f03226fd73daba8c5ae2a5644fb84cde7702ddc892abb72d75a810f9"
get=json.loads((a.old_root/"old-summary.full-GET.original.json").read_bytes())
assert get["structuredContent"]["content"].encode()==raw
old=json.loads(raw)
new=json.loads((a.census_root/"PR_INVENTORY.json").read_bytes())["items"]
om={r["number"]:r for r in old["prs"]};nm={r["number"]:r for r in new}
onlynew=[r for r in new if r["number"] not in om]
assert old["observations"]["pagination"]["pulls"]["requested_pages"]==list(range(1,14))
assert old["observations"]["pagination"]["pulls"]["counts"]==[100]*11+[3,0]
for page in [1,12,13]:
 assert any(q["url"]=="https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/pulls?state=open&sort=created&direction=asc&per_page=100&page="+str(page) for q in old["observations"]["final_anchor_queries"])
boundary="2026-11-05T03:24:00Z"
result={
 "old_count":len(old["prs"]),"old_unique":len(om),"new_count":len(nm),
 "intersection":len(om.keys()&nm.keys()),"only_in_new":len(onlynew),
 "only_in_old":[r["number"] for r in old["prs"] if r["number"] not in nm],
 "only_new_created_after_old_window":sum(r["created_at"]>boundary for r in onlynew),
 "only_new_updated_at_or_before_old_window":sum(r["updated_at"]<=boundary for r in onlynew),
 "examples_only_new_old_dates":[{"number":r["number"],"created_at":r["created_at"],"updated_at":r["updated_at"],"base_ref":r["base"]["ref"]} for r in onlynew if r["updated_at"]<=boundary][:8],
 "old_anchor_query_scope":"state=open&sort=created&direction=asc&per_page=100 with page1,12,13 and additional created desc first100",
 "explicit_filter_or_pagination_gap_proven":False,
 "cause":"UNKNOWN_FROM_SUMMARY_ALONE",
 "old_underlying_raw_pagination_bodies_not_reopened_this_review":True,
}
assert result==json.loads((a.old_root/"COMPARISON.json").read_bytes())
print(json.dumps(result,ensure_ascii=False,indent=2))
