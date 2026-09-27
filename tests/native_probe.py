"""Disposable Linux container test only. Never part of the production entrypoint."""
import ctypes
import errno
import json
import mmap
import os
import platform
import socket
import sys
import sysconfig

sys.path.insert(0,"/opt/operator/test")
import _confinement

libc=ctypes.CDLL(None,use_errno=True)
libc.syscall.restype=ctypes.c_long
architecture=platform.machine()
numbers={"aarch64":{"execveat":281,"clone3":435,"unshare":97,"ptrace":117,"bpf":280,"io_uring_setup":425},
         "x86_64":{"execveat":322,"clone3":435,"unshare":272,"ptrace":101,"bpf":321,"io_uring_setup":425}}
report={"python":sys.version.split()[0],"soabi":sysconfig.get_config_var("SOABI"),"machine":architecture,"uid":os.geteuid(),"denied":[]}
mapping=mmap.mmap(-1,4096,prot=mmap.PROT_READ|mmap.PROT_WRITE)
buffer=(ctypes.c_char*4096).from_buffer(mapping)
address=ctypes.addressof(buffer)
libc.mprotect.argtypes=(ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int)
_confinement.install()

def denied(name,call):
    try:result=call()
    except OSError as e:
        if e.errno!=errno.EPERM:raise AssertionError(name+" wrong denial") from None
    else:
        if result!=-1 or ctypes.get_errno()!=errno.EPERM:raise AssertionError(name+" allowed")
    report["denied"].append(name)

denied("socket",lambda:socket.socket())
denied("socketpair",lambda:socket.socketpair())
denied("fork",os.fork)
denied("execve",lambda:os.execve("/nonexistent",["probe"],{}))
for name,nr in numbers[architecture].items():
    denied(name,lambda nr=nr:libc.syscall(nr,0,0,0,0,0,0))
denied("mprotect-exec",lambda:libc.mprotect(address,4096,mmap.PROT_READ|mmap.PROT_EXEC))
denied("mmap-exec",lambda:mmap.mmap(-1,4096,prot=mmap.PROT_READ|mmap.PROT_EXEC))
try:_confinement.install()
except RuntimeError:pass
else:raise AssertionError("second install accepted")

# Approved runtime primitives must still work after the filter is irreversible.
payload=os.urandom(32)
fd=os.open("/work/probe",os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
os.write(fd,payload);os.fchmod(fd,0o640);os.close(fd)
os.rename("/work/probe","/work/ready")
fd=os.open("/work/ready",os.O_RDONLY|os.O_NOFOLLOW)
assert os.read(fd,32)==payload
os.close(fd);os.unlink("/work/ready")
report["file_io"]="passed"
print(json.dumps(report,sort_keys=True))
