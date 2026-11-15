import hashlib,json,os,signal,subprocess,sys,time,urllib.parse,urllib.request
from pathlib import Path
ROOT=Path("/home/qq/neuro-act6243-v8-network-862531d11598/probe-v1")
REPO=Path("/home/qq/neuro-act6243-native-862531d11598/7d31bf967774-v1/source")
URL="https://github.com/openai/codex/releases/download/rusty-v8-v150.4.0/rusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.sha256"
EXPECTED="6774b42c9424c098c72a805c08d4e94be17c591cf02b1dc2633060255a8a61be"
PINS={"codex-rs/Cargo.lock":"e47a4418a1e62ea67fa14085fa1c479e90187fed2af9e245893fbd1b5577e425","scripts/codex_package/v8.py":"d7739840d17ea4f1afff15e552add403f2a479cde6422c27c92c2ef3823c27fc"}
def digest(raw):return hashlib.sha256(raw).hexdigest()
def write(name,raw):
 with (ROOT/name).open("xb") as f:f.write(raw);f.flush();os.fsync(f.fileno())
def save(name,value):write(name,(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n").encode())
def expire(*_):raise TimeoutError("Bounded read-only V8 connection diagnostic expired")
signal.signal(signal.SIGALRM,expire);signal.setitimer(signal.ITIMER_REAL,60)
if os.getuid()!=1000 or os.geteuid()!=1000:raise PermissionError("Ordinary uid1000 required")
os.umask(0o077);ROOT.mkdir(parents=True,exist_ok=False)
source=sys.orig_argv[sys.orig_argv.index("-c")+1].encode()
write("SOURCE.py",source)
result={"schema":"hepta.act6243.v8-connection-diagnostic.v1","source_sha256":digest(source),"url":URL,"expected_manifest_sha256":EXPECTED,"uid":os.getuid(),"euid":os.geteuid(),"native_compile_started":False,"actors":0,"source_or_failed_run_writes":0,"attempts":[],"status":"FAILED"}
began=time.monotonic()
try:
 for path,pin in PINS.items():
  if digest((REPO/path).read_bytes())!=pin:raise ValueError("Exact resolver/lock pin differs")
 result["original_source_pins"]=PINS
 proc=subprocess.run(["git","-C",str(REPO),"config","--get-urlmatch","http.proxy",URL],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
 if proc.returncode not in (0,1):raise RuntimeError("Existing Git proxy metadata could not be read")
 proxy=proc.stdout.decode().strip()
 proxies=urllib.request.getproxies()
 result["proxy_metadata"]={"git_proxy_present":bool(proxy),"urllib_proxy_schemes":sorted(proxies),"git_proxy_matches_urllib_https":bool(proxy and proxy==proxies.get("https"))}
 if proxy:
  parsed=urllib.parse.urlparse(proxy)
  result["proxy_metadata"].update(git_proxy_scheme=parsed.scheme,git_proxy_has_userinfo=parsed.username is not None or parsed.password is not None)
 def attempt(name,opener):
  t=time.monotonic()
  record={"route":name,"url":URL,"timeout_seconds":20}
  try:
   with opener.open(URL,timeout=20) as response:
    final=urllib.parse.urlparse(response.geturl())
    if final.scheme!="https":raise ValueError("Non-HTTPS redirect rejected")
    raw=response.read(8193)
    record.update(http_status=response.status,bytes=len(raw),sha256=digest(raw),final_https_host=final.hostname)
   if len(raw)!=262 or digest(raw)!=EXPECTED:raise ValueError("Official checksum asset size or SHA256 differs")
   write(name+"-CHECKSUMS.sha256",raw)
   record["status"]="OFFICIAL_CHECKSUM_BYTES_VERIFIED"
   return True
  except BaseException as error:
   record.update(status="FAILED",error_type=type(error).__name__)
   if hasattr(error,"code") and isinstance(error.code,int):record["http_status"]=error.code
   return False
  finally:
   record["elapsed_seconds"]=time.monotonic()-t
   result["attempts"].append(record)
 ok=attempt("existing-urllib-environment",urllib.request.build_opener())
 if not ok and proxy and urllib.parse.urlparse(proxy).scheme in {"http","https"} and proxy!=proxies.get("https"):
  ok=attempt("existing-git-proxy",urllib.request.build_opener(urllib.request.ProxyHandler({"http":proxy,"https":proxy})))
 for path,pin in PINS.items():
  if digest((REPO/path).read_bytes())!=pin:raise ValueError("Original source changed during diagnostic")
 result["original_source_unchanged"]=True
 result["status"]="OFFICIAL_CHECKSUM_CONNECTION_VERIFIED" if ok else "CONNECTION_UNRESOLVED"
except BaseException as error:
 result["error_type"]=type(error).__name__
finally:
 signal.setitimer(signal.ITIMER_REAL,0)
 result["elapsed_seconds"]=time.monotonic()-began
 save("RESULT.json",result)
 print(json.dumps(result,sort_keys=True,allow_nan=False),flush=True)
if result["status"]!="OFFICIAL_CHECKSUM_CONNECTION_VERIFIED":raise SystemExit(1)
