set pagination off
set confirm off
set print frame-arguments none
set disable-randomization off
set debuginfod enabled off
set startup-with-shell off
handle SIGSEGV stop print nopass
handle SIGABRT stop print nopass
handle SIGPIPE nostop noprint pass
run
info program
info threads
thread apply all bt 64
info registers
info frame
info symbol $pc
x/40i $pc-64
info proc mappings
python
import gdb,json,os
inferior=gdb.selected_inferior()
thread=gdb.selected_thread()
sp=int(gdb.parse_and_eval("$sp"))
pc=int(gdb.parse_and_eval("$pc"))
pid=inferior.pid
tid=thread.ptid[1]
signal_info={}
fault_address=None
try:
 signal_info["raw"]=gdb.execute("p $_siginfo",to_string=True)
 signal_info["number"]=int(gdb.parse_and_eval("$_siginfo.si_signo"))
 if signal_info["number"]==11:fault_address=int(gdb.parse_and_eval("$_siginfo._sifields._sigfault.si_addr"));signal_info["fault_address"]=hex(fault_address)
except Exception as error:signal_info["read_error"]=type(error).__name__+": "+str(error)
print(json.dumps({"kernel_signal_info":signal_info},sort_keys=True))
lines=open("/proc/"+str(pid)+"/task/"+str(tid)+"/maps").read().splitlines()
mappings=[]
for line in lines:
 parts=line.split()
 lo,hi=[int(x,16) for x in parts[0].split("-")]
 if lo<=sp<hi or abs(lo-sp)<=65536 or abs(hi-sp)<=65536 or "[stack]" in line or (fault_address is not None and (lo<=fault_address<hi or abs(lo-fault_address)<=65536 or abs(hi-fault_address)<=65536)):
  mappings.append({"start":hex(lo),"end":hex(hi),"bytes":hi-lo,"contains_sp":lo<=sp<hi,"contains_fault_address":fault_address is not None and lo<=fault_address<hi,"line":line})
observation={"pid":pid,"tid":tid,"sp":hex(sp),"pc":hex(pc),"signal_info":signal_info,"near_sp_and_fault_and_named_stack_mappings":mappings,"method":"Read-only /proc thread maps plus stopped-thread registers; no inferior function call"}
print(json.dumps(observation,sort_keys=True))
with open('/home/qian-qi/hepta-utility-36fa-evidence/c0f-panel-first-signal-v1/STOPPED_THREAD_STACK.json',"x") as f:json.dump(observation,f,indent=2,sort_keys=True);f.write("\n")
end
quit
