import ctypes,hashlib,io,json,os,posixpath,signal,stat,subprocess,sys,tarfile,time,traceback,urllib.parse,urllib.request
from pathlib import Path,PurePosixPath
PLAN=json.loads(sys.stdin.buffer.read(1048577))
ROOT=Path(PLAN["root"]);SYSROOT=ROOT/"sysroot";EVIDENCE=ROOT/"evidence"
if os.getuid()!=1000 or os.geteuid()!=1000:raise RuntimeError("ordinary uid/euid1000 required")
os.umask(0o077)
ROOT.mkdir(parents=True,exist_ok=False);SYSROOT.mkdir();EVIDENCE.mkdir()
def sha(data):return hashlib.sha256(data).hexdigest()
def version(s):return ":".join(str(x) for x in (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns))
def file_pin(path):
 path=Path(path)
 if path.is_symlink() or not path.is_file():raise RuntimeError("expected regular file: "+str(path))
 before=path.stat();data=path.read_bytes();after=path.stat()
 if version(before)!=version(after):raise RuntimeError("input changed while reading")
 return {"path":str(path),"bytes":len(data),"sha256":sha(data),"version":version(after)}
def write_once(path,data):
 with Path(path).open("xb") as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
 return file_pin(path)
def save(name,value):
 return write_once(EVIDENCE/name,(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n").encode())
def run(argv,limit=67108864):
 p=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
 if len(p.stdout)>limit or p.returncode:raise RuntimeError("package metadata/extraction command failed: "+argv[0]+"; "+p.stderr[:2000].decode("utf8","replace"))
 return p.stdout
def inventory():
 entries=[]
 for path in sorted(SYSROOT.rglob("*")):
  rel=path.relative_to(SYSROOT).as_posix()
  if path.is_symlink():
   target=os.readlink(path)
   if not path.resolve().is_relative_to(SYSROOT.resolve()):raise RuntimeError("external extracted symlink")
   entries.append({"path":rel,"type":"symlink","target":target,"sha256":sha(os.fsencode(target))})
  elif path.is_file():entries.append({"path":rel,"type":"file",**{k:v for k,v in file_pin(path).items() if k!="path"}})
  elif not path.is_dir():raise RuntimeError("unexpected extracted file type")
 return entries
class CXString(ctypes.Structure):_fields_=[("data",ctypes.c_void_p),("private_flags",ctypes.c_uint)]
def api(lib,name,restype,args):
 function=getattr(lib,name);function.restype=restype;function.argtypes=args;return function
def bind_library():
 lib=ctypes.CDLL(PLAN["library"])
 api(lib,"clang_getClangVersion",CXString,[])
 api(lib,"clang_getCString",ctypes.c_char_p,[CXString]);api(lib,"clang_disposeString",None,[CXString])
 api(lib,"clang_createIndex",ctypes.c_void_p,[ctypes.c_int,ctypes.c_int]);api(lib,"clang_disposeIndex",None,[ctypes.c_void_p])
 api(lib,"clang_parseTranslationUnit2",ctypes.c_int,[ctypes.c_void_p,ctypes.c_char_p,ctypes.POINTER(ctypes.c_char_p),ctypes.c_int,ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p)])
 api(lib,"clang_disposeTranslationUnit",None,[ctypes.c_void_p])
 api(lib,"clang_getNumDiagnostics",ctypes.c_uint,[ctypes.c_void_p]);api(lib,"clang_getDiagnostic",ctypes.c_void_p,[ctypes.c_void_p,ctypes.c_uint])
 api(lib,"clang_getDiagnosticSeverity",ctypes.c_int,[ctypes.c_void_p]);api(lib,"clang_formatDiagnostic",CXString,[ctypes.c_void_p,ctypes.c_uint])
 api(lib,"clang_defaultDiagnosticDisplayOptions",ctypes.c_uint,[]);api(lib,"clang_disposeDiagnostic",None,[ctypes.c_void_p])
 api(lib,"clang_getFileName",CXString,[ctypes.c_void_p])
 return lib
def cxtext(lib,value):
 try:return (lib.clang_getCString(value) or b"").decode("utf8","replace")
 finally:lib.clang_disposeString(value)
VISITOR=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p)
def parse_headers(lib,source_path,extra):
 args=["-x","c","-std=c11","--target=x86_64-unknown-linux-gnu"]+extra
 encoded=[x.encode() for x in args];argv=(ctypes.c_char_p*len(encoded))(*encoded)
 index=lib.clang_createIndex(0,0);tu=ctypes.c_void_p();record={"args":args,"diagnostics":[],"included_files":[]}
 if not index:raise RuntimeError("clang_createIndex returned null")
 try:
  record["parse_result"]=lib.clang_parseTranslationUnit2(index,os.fsencode(source_path),argv,len(encoded),None,0,0,ctypes.byref(tu))
  if tu:
   for i in range(lib.clang_getNumDiagnostics(tu)):
    diagnostic=lib.clang_getDiagnostic(tu,i)
    try:record["diagnostics"].append({"severity":lib.clang_getDiagnosticSeverity(diagnostic),"text":cxtext(lib,lib.clang_formatDiagnostic(diagnostic,lib.clang_defaultDiagnosticDisplayOptions()))})
    finally:lib.clang_disposeDiagnostic(diagnostic)
   @VISITOR
   def include(file,stack,length,client):
    if len(record["included_files"])<512:record["included_files"].append(cxtext(lib,lib.clang_getFileName(file)))
   api(lib,"clang_getInclusions",None,[ctypes.c_void_p,VISITOR,ctypes.c_void_p])(tu,include,None)
  return record
 finally:
  if tu:lib.clang_disposeTranslationUnit(tu)
  lib.clang_disposeIndex(index)
result={"schema":PLAN["schema"],"status":"FAILED","uid":os.getuid(),"euid":os.geteuid(),"system_install":False,"source_or_lock_modified":False,"native_build_started":False,"actor_calls":0,"owner_decision":None}
signal.signal(signal.SIGALRM,lambda signum,frame:(_ for _ in ()).throw(TimeoutError("resource preparation bounded deadline")))
signal.alarm(240)
try:
 save("PLAN.json",PLAN)
 library_before=file_pin(PLAN["library"])
 if library_before["bytes"]!=PLAN["library_bytes"] or library_before["sha256"]!=PLAN["library_sha256"]:raise RuntimeError("original libclang bytes differ")
 lib=bind_library();actual_version=cxtext(lib,lib.clang_getClangVersion())
 if actual_version!=PLAN["library_version"]:raise RuntimeError("original libclang version differs")
 result["library"]={**library_before,"clang_getClangVersion":actual_version}
 request=urllib.request.Request(PLAN["url"],headers={"User-Agent":"hepta-clang-resource-preparation/1"})
 began=time.monotonic()
 with urllib.request.urlopen(request,timeout=45) as response:
  final=urllib.parse.urlsplit(response.geturl())
  if final.scheme!="https" or final.hostname!="archive.ubuntu.com":raise RuntimeError("unexpected official download redirect")
  data=response.read(PLAN["package_bytes"]+1)
  receipt={"url":PLAN["url"],"final_url":response.geturl(),"status":response.status,"headers":{k:response.headers.get(k) for k in ("Content-Length","Content-Type","ETag","Last-Modified","Content-Encoding")},"bytes":len(data),"sha256":sha(data),"elapsed_seconds":time.monotonic()-began}
 save("DOWNLOAD.json",receipt)
 if receipt["status"]!=200 or len(data)!=PLAN["package_bytes"] or sha(data)!=PLAN["package_sha256"]:raise RuntimeError("official package Size/SHA256 mismatch")
 package=ROOT/"libclang-common-21-dev_21.1.8-6ubuntu1_amd64.deb";write_once(package,data);package.chmod(0o444)
 identity=run(["/usr/bin/dpkg-deb","-f",str(package),"Package","Version","Architecture"],4096).decode().splitlines()
 expected=["Package: "+PLAN["package"],"Version: "+PLAN["version"],"Architecture: "+PLAN["architecture"]]
 if identity!=expected:raise RuntimeError("official package control identity mismatch: "+repr(identity))
 save("PACKAGE_IDENTITY.json",{"fields":identity,"dpkg_deb":file_pin("/usr/bin/dpkg-deb")})
 tar_data=run(["/usr/bin/dpkg-deb","--fsys-tarfile",str(package)])
 with tarfile.open(fileobj=io.BytesIO(tar_data),mode="r:") as archive:
  members=archive.getmembers()
  if len(members)>10000 or sum(m.size for m in members if m.isfile())>67108864:raise RuntimeError("package inventory bound")
  seen=set();listing=[]
  for member in members:
   path=PurePosixPath(member.name);name=path.as_posix()
   if path.is_absolute() or ".." in path.parts or name in seen:raise RuntimeError("unsafe/duplicate package member")
   seen.add(name)
   if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):raise RuntimeError("unsupported package member")
   if member.issym() or member.islnk():
    target=PurePosixPath(member.linkname)
    resolved=posixpath.normpath(posixpath.join(str(path.parent) if member.issym() else "",member.linkname))
    if target.is_absolute() or resolved==".." or resolved.startswith("../"):raise RuntimeError("external package link")
   item={"path":name,"size":member.size,"type":"file" if member.isfile() else "directory" if member.isdir() else "symlink" if member.issym() else "hardlink","link":member.linkname or None}
   if member.isfile():item["sha256"]=sha(archive.extractfile(member).read())
   listing.append(item)
  save("PACKAGE_MEMBERS.json",{"tar_bytes":len(tar_data),"tar_sha256":sha(tar_data),"members":listing})
  archive.extractall(SYSROOT,filter="data")
  for item in listing:
   if item["type"]=="file" and file_pin(SYSROOT/item["path"])["sha256"]!=item["sha256"]:raise RuntimeError("extracted bytes mismatch")
 headers=[SYSROOT/item["path"] for item in listing if item["type"]=="file" and item["path"].endswith("/include/stddef.h") and "/lib/clang/21/" in item["path"]]
 if len(headers)!=1:raise RuntimeError("expected exactly one package-provided Clang21 resource")
 resource=headers[0].parent.parent
 required=[resource/"include"/name for name in ("stddef.h","stdarg.h","stdint.h")]
 if not all(p.is_file() and not p.is_symlink() for p in required):raise RuntimeError("required built-in headers incomplete")
 for path in sorted(SYSROOT.rglob("*"),reverse=True):
  if path.is_symlink():continue
  path.chmod(0o555 if path.is_dir() else 0o444)
 SYSROOT.chmod(0o555)
 before=inventory();resource_manifest=save("RESOURCE_MANIFEST.json",{"package_sha256":PLAN["package_sha256"],"resource_dir":str(resource),"entries":before})
 source=ROOT/"header_probe.c";write_once(source,b"#include <stddef.h>\n#include <stdarg.h>\n#include <stdint.h>\nsize_t size_probe;\nva_list args_probe;\nuint32_t integer_probe;\n");source.chmod(0o444);source_before=file_pin(source)
 baseline=parse_headers(lib,source,[])
 positive=parse_headers(lib,source,["-resource-dir="+str(resource)])
 result["baseline"]=baseline;result["with_resource"]=positive
 save("C_API_PARSE.json",{"probe":source_before,"library":result["library"],"baseline":baseline,"with_resource":positive})
 if not any(d["severity"]>=3 and "stddef.h" in d["text"] for d in baseline["diagnostics"]):raise RuntimeError("baseline did not reproduce missing stddef.h")
 if positive["parse_result"]!=0 or any(d["severity"]>=3 for d in positive["diagnostics"]):raise RuntimeError("matched resource parse still fails")
 included={str(Path(p).resolve()) for p in positive["included_files"]}
 if not {str(p.resolve()) for p in required}.issubset(included):raise RuntimeError("actual expected resource header inclusion not observed")
 if inventory()!=before or file_pin(PLAN["library"])!=library_before or file_pin(source)!=source_before:raise RuntimeError("library/resource changed")
 result.update(status="MATCHED_CLANG21_RESOURCE_PREPARED",resource_dir=str(resource),resource_manifest=resource_manifest,package=file_pin(package),environment={"LIBCLANG_PATH":str(Path(PLAN["library"]).parent),"BINDGEN_EXTRA_CLANG_ARGS":"-resource-dir="+str(resource)},header_pins=[file_pin(p) for p in required])
except BaseException as error:
 result["error"]={"type":type(error).__name__,"message":str(error)};traceback.print_exc()
finally:
 signal.alarm(0);save("RESULT.json",result)
 print(json.dumps({"status":result["status"],"result":str(EVIDENCE/"RESULT.json"),"resource_dir":result.get("resource_dir"),"error":result.get("error")},sort_keys=True),flush=True)
if result["status"]!="MATCHED_CLANG21_RESOURCE_PREPARED":raise SystemExit(1)
