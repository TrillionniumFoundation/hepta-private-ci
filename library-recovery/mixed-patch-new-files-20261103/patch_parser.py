# Newly authored bounded data parser. Never applies or executes original source.
import hashlib
import re
import sys
if sys.flags.optimize:raise SystemExit("optimized parser refused")
OBJECT_LIMIT=1024*1024

def require(value,message):
    if not value:raise ValueError(message)

def fp(raw):
    return {'git_blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
            'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

def lf_lines(raw):
    chunks=raw.split(b'\n')
    return [x+b'\n' for x in chunks[:-1]]+([chunks[-1]] if chunks[-1] else [])

def parse_new_file(block):
    """Accept only one complete zero-old-lines hunk with a Git index prefix."""
    modes=[line for line in block if line.startswith(b'new file mode ')]
    if not modes:return None,'existing file requires separately verified base'
    require(len(modes)==1 and re.fullmatch(rb'new file mode [0-9]{6}\n',modes[0]),'invalid/duplicate new-file mode')
    mode=modes[0].rstrip(b'\n').split(b' ')[-1]
    if mode not in (b'100644',b'100755'):return None,'non-regular new-file mode'
    if b'GIT binary patch\n' in block:return None,'binary patch not source-projected'
    hunks=[i for i,line in enumerate(block) if line.startswith(b'@@ ')]
    if len(hunks)!=1:return None,'requires exactly one complete new-file hunk'
    hi=hunks[0]
    header=block[:hi]
    minus=[line for line in header if line.startswith(b'--- ')]
    plus=[line for line in header if line.startswith(b'+++ ')]
    require(minus==[b'--- /dev/null\n'] and len(plus)==1 and plus[0].startswith(b'+++ b/'),'unsupported original/new file labels')
    path_raw=plus[0][6:].removesuffix(b'\n')
    require(path_raw and len(path_raw)<=4096 and b'\0' not in path_raw and not path_raw.startswith(b'"'),'unsupported path encoding')
    path=path_raw.decode('utf-8')
    require(block[0]==b'diff --git a/'+path_raw+b' b/'+path_raw+b'\n','ambiguous diff/new-path labels')
    indices=[re.fullmatch(rb'index (0+)\.\.([0-9a-f]{7,40})(?: (100644|100755))?\n?',line) for line in header if line.startswith(b'index ')]
    require(len(indices)==1 and indices[0] is not None and len(indices[0].group(1))>=7,'missing/invalid zero-base Git index')
    index=indices[0];abbreviated_new=index.group(2).decode()
    require(index.group(3) is None or index.group(3)==mode,'Git index mode differs from new-file mode')
    hunk=re.fullmatch(rb'@@ -0,0 \+(\d+)(?:,(\d+))? @@[^\n]*\n?',block[hi])
    require(hunk is not None,'not a complete new-file hunk')
    start=int(hunk.group(1));declared=int(hunk.group(2) or b'1')
    require(start==1 and 0<declared<=200000,'unexpected new-line coordinates')
    content=[];total=0;no_final_newline=False
    for line in block[hi+1:]:
        if line==b'\\ No newline at end of file\n' or line==b'\\ No newline at end of file':
            require(content and not no_final_newline and content[-1].endswith(b'\n'),'invalid no-newline marker')
            content[-1]=content[-1][:-1];total-=1;no_final_newline=True
        else:
            require(not no_final_newline and line.startswith(b'+'),'unexpected incomplete/additional hunk content')
            require(line.endswith(b'\n'),'truncated added line lacks explicit no-newline marker')
            chunk=line[1:];total+=len(chunk)
            require(total<=OBJECT_LIMIT,'new-file object limit exceeded')
            content.append(chunk)
    require(len(content)==declared,'hunk line count differs from header')
    raw=b''.join(content)
    require(len(raw)==total and b'\0' not in raw,'binary/new file byte mismatch')
    raw.decode('utf-8',errors='strict')
    identity=fp(raw)
    require(identity['git_blob_sha'].startswith(abbreviated_new),'reconstructed source differs from Git index prefix')
    return {'original_path':path,'original_mode':mode.decode(),'index_new_blob_prefix':abbreviated_new,
            'index_prefix_length':len(abbreviated_new),'declared_new_lines':declared,
            'no_final_newline':no_final_newline,'raw':raw,**identity},None
