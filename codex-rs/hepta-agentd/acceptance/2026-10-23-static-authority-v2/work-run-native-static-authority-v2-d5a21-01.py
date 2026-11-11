from pathlib import Path
import gzip, hashlib, json, os, re, shutil, subprocess, sys, time

BASE=Path(__file__).resolve().parents[1]
DATA=Path('/data/asterinas-audit-build.8tdrjboi')
OUT=DATA/'native-static-authority-v2-d5a21-kvm-01'
OUT.mkdir(mode=0o700,exist_ok=False)
sys.dont_write_bytecode=True
SOURCE=DATA/'vmar-fallible-fault-fixed'
sys.path.insert(0,str(SOURCE/'tests/kernel/control'))
from run_proc_boot_identity import pack, unpack
from run_g1c_guest import inspect_probe_elf

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
ordinary=DATA/'vmar-fault-native-d5a2-01/ordinary'
receipt=json.loads((ordinary/'result.json').read_text())
assert receipt['passed'] and receipt['source_inputs_unchanged']
kernel=ordinary/'product-kernel.elf'
assert receipt['source_head']=='d5a21bb7e70a22cd022f4275ba2d22a6b726d233'
assert sha(kernel)==receipt['kernel_elf_sha256']
build=DATA/'native-authority-static-3a50-02'
products=json.loads((build/'result.json').read_text())
reference=json.loads((DATA/'native-authority-v2-static-host-reference-04-system-ssd/result.json').read_text())
assert products['packaged'] and products['source_inputs_unchanged'] and reference['passed']
files={name:build/'packaged'/name for name in products['products']}
files['native-authority-launcher']=DATA/'native-authority-v2-qualification-launcher-01'
assert sha(files['native-authority-launcher'])==reference['launcher_sha256']
for name,path in files.items():
    inspect_probe_elf(path.read_bytes())
    if name in products['products']: assert sha(path)==products['products'][name]['packaged_sha256']
initramfs=SOURCE/'support/build/evidence/2026-10-16/artifacts/initramfs.cpio.gz'
entries=unpack(gzip.decompress(initramfs.read_bytes()))
scope=json.dumps(list(hashlib.sha256(b'hepta:agentd:signed-objective:v1\0'+b'018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12').digest()),separators=(',',':'))
invocation='''/bin/busybox mkdir -p /run /mnt/hepta-native-disk /var/lib/hepta-native-q
/bin/busybox mount -t ext2 /dev/vda /mnt/hepta-native-disk
/bin/busybox mkdir /mnt/hepta-native-disk/authority-source
/bin/busybox chmod 0700 /mnt/hepta-native-disk/authority-source
/bin/busybox mount --bind /mnt/hepta-native-disk/authority-source /var/lib/hepta-native-q
/bin/busybox cat /mnt/hepta-native-disk/hepta-authority-host > /dev/null
/bin/busybox cat /mnt/hepta-native-disk/authority_host_peer_qualification > /dev/null
if /bin/native-authority-launcher /var/lib/hepta-native-q/qualification /var/lib/hepta-native-q /mnt/hepta-native-disk/authority-source /mnt/hepta-native-disk/hepta-authority-host /mnt/hepta-native-disk/authority_host_peer_qualification 'SCOPE'; then
  echo NATIVE_AUTHORITY_LAUNCH_EXIT=0
else
  echo NATIVE_AUTHORITY_LAUNCH_EXIT=$?
fi
'''.replace('SCOPE',scope).encode()
marker=b'echo "TRILLIONNIUM_A01_BOOT_OK"'
patched=[];found=0
for name,fields,data in entries:
    assert name.lstrip('./') not in {'bin/'+key for key in files}
    if name.lstrip('./')=='init':
        assert data.count(marker)==1;data=data.replace(marker,invocation+marker);found+=1
    patched.append((name,fields,data))
assert found==1
ino=max(fields[0] for _,fields,_ in entries)+1
for name,path in {'native-authority-launcher':files['native-authority-launcher']}.items():
    patched.append(('bin/'+name,[ino,0o100755,0,0,1,0,0,0,0,0,0,0,0],path.read_bytes()));ino+=1
archive=pack(patched);assert len(unpack(archive))==len(entries)+1
injected=OUT/'initramfs.cpio.gz';injected.write_bytes(gzip.compress(archive,mtime=0))
assert injected.stat().st_size<=8*1024*1024,'original compressed-initramfs limit remains unchanged'
disk=OUT/'private-authority.ext2'
with disk.open('xb') as stream:stream.truncate(128*1024*1024)
disk.chmod(0o600)
format_command=['/usr/sbin/mkfs.ext2','-F','-q','-b','4096','-I','256','-O','none,filetype','-d','/data/hepta-static-authority-v2-reference-bin-04',str(disk)]
with (OUT/'format.log').open('xb') as log:subprocess.run(format_command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
shutil.copyfile('/usr/share/seabios/bios-256k.bin',OUT/'bios.bin')
argv=['/usr/bin/qemu-system-x86_64','-kernel',str(kernel),'-initrd',str(injected),'-bios',str(OUT/'bios.bin'),'-append','earlycon console=ttyS0 loglevel=warn SHELL=/bin/sh LOGNAME=root HOME=/ USER=root PATH=/bin:/sbin --','-machine','q35','-accel','kvm','-cpu','host','-m','512M','-smp','1','-nodefaults','-no-user-config','-no-reboot','-nographic','-display','none','-monitor','none','-serial','stdio','-nic','none','-drive','file='+str(disk)+',format=raw,id=authority,if=none','-device','virtio-blk-pci,bus=pcie.0,addr=0x7,drive=authority,disable-legacy=on,disable-modern=off','-device','isa-debug-exit,iobase=0xf4,iosize=0x04']
report={'schema':'hepta.native-static-authority-qualification.v1','kernel_source_head':receipt['source_head'],'kernel_source_tree':receipt['source_tree'],'kernel_sha256':sha(kernel),'ordinary_receipt_sha256':sha(ordinary/'result.json'),'hepta_source_head':products['source_head'],'hepta_source_tree':products['source_tree'],'products':{name:{'bytes':p.stat().st_size,'sha256':sha(p)} for name,p in files.items()},'original_initramfs_sha256':sha(initramfs),'injected_initramfs_sha256':sha(injected),'injected_initramfs_bytes':injected.stat().st_size,'format_argv':format_command,'qemu_argv':argv,'guest_deadline_seconds':120,'disk_before_sha256':sha(disk),'private_disk_contains_qualification_keys':True,'production_authority':False,'g2_complete':False,'passed':False,'status':'running'}
def save():(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
save();start=time.monotonic();timed_out=False
with (OUT/'serial.log').open('xb') as log:
    try:code=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=120).returncode
    except subprocess.TimeoutExpired:code=None;timed_out=True
text=re.sub(r'\x1b\[[0-9;]*m','',(OUT/'serial.log').read_text(errors='replace')).replace('\r','')
observations=[]
for line in text.splitlines():
    if line.startswith('{'):
        try:item=json.loads(line)
        except json.JSONDecodeError:continue
        if item.get('qualification')=='root_authority_original_peer_v1':observations.append(item)
passed=(code==33 and not timed_out and len(observations)==1 and observations[0]['uid']==60001 and observations[0]['feed_elapsed_ms']<=500 and observations[0]['objective_sequence']==2 and observations[0]['final_use_sequence']==3 and observations[0]['checkpoint_ack'] is False and observations[0]['capabilities_clear'] and observations[0]['no_new_privileges'] and text.count('NATIVE_AUTHORITY_COMPLETE pass=1 production_ready=0 g2_complete=0')==1 and text.count('NATIVE_AUTHORITY_LAUNCH_EXIT=0')==1 and text.count('TRILLIONNIUM_A01_BOOT_OK')==1 and not any(x in text for x in ['Uncaught panic:','An uncaught panic occurred:','Non-resettable panic!']))
report.update(raw_qemu_exit=code,timed_out=timed_out,passed=bool(passed),observations=observations,serial_sha256=sha(OUT/'serial.log'),disk_after_sha256=sha(disk),seconds=round(time.monotonic()-start,3),status='complete')
save();assert report['passed'],'actual native static authority qualification failed'
