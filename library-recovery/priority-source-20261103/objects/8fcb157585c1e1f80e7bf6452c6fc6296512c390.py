"""Bounded official-source prefetch; ordinary curl HTTPS validation is unchanged."""
import hashlib, json, pathlib, subprocess, tempfile, time
url='https://github.com/v8/v8/archive/refs/tags/15.0.245.2.tar.gz'
redirect='https://codeload.github.com/v8/v8/tar.gz/refs/tags/15.0.245.2'
expected='164f3d3e0a8b4c02a386d3a88d1b1133d37e5c20be0239fecdcdde414a4340d5'
maximum=128*1024*1024
root=pathlib.Path('/workspace/shared/hepta-tools/cache/authbus-distfiles');root.mkdir(parents=True,exist_ok=True)
result={'requested_url':url,'expected_sha256':expected,'maximum_bytes':maximum,'deadline_seconds':180}
start=time.monotonic()
try:
    destination=root/'15.0.245.2.tar.gz'
    if destination.exists():
        data=destination.read_bytes()
        if len(data)>maximum or hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError('existing destination does not match pinned content; left untouched')
        result.update(status='existing_verified',actual_bytes=len(data),actual_sha256=expected)
    else:
        with tempfile.TemporaryDirectory(prefix='v8-prefetch-',dir=root) as temporary:
            temporary=pathlib.Path(temporary); payload=temporary/'archive';headers=temporary/'headers'
            current=url
            for attempt in range(2):
                remaining=180-(time.monotonic()-start)
                if remaining<=0: raise TimeoutError('overall deadline exceeded')
                run=subprocess.run(['curl','--fail','--silent','--show-error','--proto','=https','--max-time',str(remaining),'--connect-timeout','30','--max-filesize',str(maximum),'--dump-header',str(headers),'--output',str(payload),'--write-out','%{http_code}',current],text=True,capture_output=True,timeout=remaining)
                result.update(curl_exit=run.returncode,http_status=run.stdout,actual_bytes=payload.stat().st_size if payload.exists() else 0,effective_url=current)
                if run.returncode: raise RuntimeError(run.stderr.strip())
                if run.stdout=='200': break
                locations=[line.split(':',1)[1].strip() for line in headers.read_text().splitlines() if line.lower().startswith('location:')]
                if attempt!=0 or run.stdout not in ('301','302','303','307','308') or locations!=[redirect]:
                    raise ValueError('unexpected status or redirect; refusing further requests')
                current=redirect
            if run.stdout!='200': raise ValueError('archive response not successful')
            digest=hashlib.sha256(payload.read_bytes()).hexdigest()
            result['actual_sha256']=digest
            if payload.stat().st_size>maximum or digest!=expected: raise ValueError('archive exceeds bound or pinned digest mismatch')
            payload.rename(destination)
            result.update(status='verified',destination=str(destination))
except Exception as error:
    result.update(status='failed',error=str(error))
finally:
    result['elapsed_seconds']=round(time.monotonic()-start,3)
    print(json.dumps(result,indent=2))
    pathlib.Path('/workspace/shared/authbus-native-evidence/bazel-v8-prefetch.json').write_text(json.dumps(result,indent=2)+'\n')
raise SystemExit(0 if result['status'] in ('verified','existing_verified') else 1)
