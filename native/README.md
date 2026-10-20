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

## Build and verification

`build/compile_native.py` is a release-builder-only fixed compiler command. It
uses CPython's stable ABI from 3.12 and creates `_confinement.abi3.so`; the runtime
image uses its own interpreter. Compiler and Python headers do not enter the
runtime layer. The exact builder/runtime identities and compiler flags are in
[`build/image-lock.json`](../build/image-lock.json).

The dedicated `build/Dockerfile.native-test` uses `tests/native_probe.py` as a
test-only entrypoint. The probe loads test helpers before installing the filter
and checks permitted file operations and denied syscalls. It is distinct from a
campaign image and does not add a production model tool or entrypoint.

The container startup policy and this guest live filter are separate layers.
Bootstrap-required calls may be available before the irreversible live policy is
installed; `openat2`, for example, is absent from the live allowlist. The production
image is built and inspected through the
[container build procedure](../GUEST_ARTIFACT_LAYOUT_SPEC.md#build-and-inspection-commands).
