# Irreversible Linux live policy

`confinement.c` MUST be loaded during trusted bootstrap, before scenario, skill or
model bytes. `install()` MUST reject root, a process with more than one thread,
missing `no_new_privs`, and repeated installation. It MUST install its fixed
allowlist through `seccomp(SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_TSYNC, ...)`
and require an exact zero return, including rejection of positive thread-ID
failure returns. Any failure MUST terminate bootstrap without readiness.

The filter MUST validate the native audit architecture and reject alternate x32
syscall numbers on amd64. Unknown syscalls MUST return EPERM. The allowlist omits
exec, process/thread creation, sockets, namespace/mount changes, process-memory
access, modules, BPF/perf, io_uring and further filter/security configuration.
`mmap` and `mprotect` MUST reject `PROT_EXEC`. Existing immutable interpreter and
library executable mappings remain usable. The single-thread baseline MUST NOT
be relaxed to accommodate a dependency automatically.

The checked source list is `live_allowlist.h`; no campaign, skill or model can
select it. Docker's startup policy and read-only/network/resource controls remain
required. Linux filter stacking and TSYNC behavior follow the
[seccomp manual](https://man7.org/linux/man-pages/man2/seccomp.2.html).

## Builder and feasibility probe

`build/compile_native.py` is a release-builder-only fixed compiler command. It
uses CPython's stable ABI from 3.12 and creates `_confinement.abi3.so`; it does not
transplant the builder interpreter or virtualenv into Distroless. Compiler and
Python headers never enter a runtime layer. The pinned builder has Python 3.13.15;
the inspected ARM64 Distroless runtime has Python 3.13.5. The actual runtime import
and syscall probe passed, exercising that stable-ABI boundary.

The dedicated `build/Dockerfile.native-test` includes the probe as a **test-only**
entrypoint. It is not a campaign image. The probe intentionally imports ctypes
and socket before installing the filter so it can exercise denied calls.
Production bootstrap MUST expose no such model tool or probe entrypoint.

On the available macOS ARM64 Docker Desktop host, the pinned native test image
successfully installed the live filter under Operator's actual startup profile,
UID 65532, no new privileges, all capabilities dropped, network disabled,
read-only root, bounded non-executable `/work`, and configured process/CPU/memory
ceilings. It observed EPERM for socket, socketpair, fork, execve, execveat, clone3,
unshare, ptrace, BPF, io_uring setup, executable mmap and executable mprotect.
File create/read/write/chmod/rename/unlink and randomness remained functional.

This is two-stage-policy feasibility evidence for that test image, not complete
Python-dependency, transport, campaign or four-platform qualification. The first
probe identified a Docker startup dependency on `openat2`; Operator's startup
allowlist now includes it. It is absent from this live allowlist.

`build/image-lock.json` records the candidate runtime/builder index and platform
digests. The candidate build now uses locked runtime dependencies, emits an SBOM
and provenance attestation, and verifies its OCI structure. Upstream signature
verification and final multi-host release qualification remain publication gates.
