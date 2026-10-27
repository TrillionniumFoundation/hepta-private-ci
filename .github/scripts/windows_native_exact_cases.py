"""Independent exact-ID parser: actual Nextest phase only, never synthetic stdout."""
import collections,re
ANSI=re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERM=re.compile(r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",re.M)
def require(condition,message):
 if not condition:raise ValueError(message)
def parse(text,package,expected_count,expected_ids=None):
 text=ANSI.sub('',text)
 starts=list(re.finditer(r"^\s*Starting (\d+) tests? across",text,re.M))
 summaries=list(re.finditer(r"^\s*Summary \[",text,re.M))
 require(len(starts)==len(summaries)==1,'exactly one native execution phase required')
 start,end=starts[0],summaries[0]
 require(end.start()>start.start(),'summary before actual start')
 require(int(start.group(1))==expected_count,'selected count drift')
 require(not TERM.findall(text[:start.start()]),'terminal stdout before actual phase')
 actual=TERM.findall(text[start.start():end.start()]);recap=TERM.findall(text[end.start():])
 require(len(actual)==expected_count,'missing or extra actual terminal')
 ids=[(pkg,name) for _,pkg,name in actual]
 require(len(ids)==len(set(ids)),'duplicate actual identity')
 require(all(pkg==package for pkg,_ in ids),'wrong package')
 require(all(status!='SKIP' for status,_,_ in actual),'skipped original case')
 if expected_ids is not None:
  require(set(ids)==set(tuple(row) for row in expected_ids),'unknown or missing exact original ID')
 # Nextest 0.9.103 prints a successful-but-leaky process as LEAK in the
 # execution phase and includes it in the summary's passed (N leaky) count.
 # It does not print that LEAK in the failure recap. Keep LEAK non-PASS.
 failures=[row for row in actual if row[0] not in ('PASS','LEAK')]
 summary_line=text[end.start():].splitlines()
 summary_line=next(line.strip() for line in summary_line if line.strip())
 summary_match=re.fullmatch(r'Summary \[[^\]\n]+\] (\d+) tests? run: (.*)',summary_line)
 require(summary_match is not None,'unknown actual summary shape')
 require(int(summary_match.group(1))==expected_count,'summary run count drift')
 summary=summary_match.group(2)
 items=summary.split(', ')
 parsed={}
 for item in items:
  match=re.fullmatch(r'(?P<count>\d+) (?P<status>passed|failed|skipped)(?: \((?P<leaky>\d+) leaky\))?',item)
  require(match is not None,'unknown summary item')
  status=match['status']
  require(status not in parsed,'duplicate summary item')
  require(match['leaky'] is None or status=='passed','leaky annotation on wrong summary item')
  parsed[status]=(int(match['count']),int(match['leaky'] or 0))
 count=collections.Counter(row[0] for row in actual)
 require('passed' in parsed and parsed['passed'][0]==count['PASS']+count['LEAK'],'summary pass count differs from actual PASS+LEAK')
 require(parsed['passed'][1]==count['LEAK'],'summary leaky count differs from actual LEAK')
 require(parsed.get('failed',(0,0))[0]==len(failures),'summary failed count differs from actual failures')
 start_line=text[start.start():].splitlines()[0]
 skipped=re.search(r'\((\d+) tests? skipped\)$',start_line)
 require(parsed.get('skipped',(0,0))[0]==(int(skipped.group(1)) if skipped else 0),'summary skip count differs from original selection')
 require(len(recap)==len(set(recap)),'duplicate failure recap')
 require(set(recap)==set(failures),'failure recaps differ from actual failures')
 return {'identities':sorted([list(row) for row in ids]),'counts':dict(collections.Counter(row[0] for row in actual)),'actual':actual,'recap':recap,'actualExecutionCount':len(actual)}
