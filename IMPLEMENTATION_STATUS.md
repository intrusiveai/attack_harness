# Attack Harness implementation status

## Fixed serial model-tool dispatcher

The dispatcher now accepts only a complete prevalidated batch, rejects duplicate
provider call IDs before dispatch, enforces the shared per-response/cumulative
loop accounting, validates each argument against the installed fixed catalog and
invokes only an explicit handler map. Unknown and malformed calls receive bounded
correlated no-effect results; handler contract faults hard-stop the loop.

A successful restore ends the batch, charges only the dispatched restore and
returns the shared `TARGET_REVISION_CHANGED` result for every remaining original
call ID without decoding arguments or invoking handlers. Oversized batches dispatch
nothing and enter model-free finalization. Tests cover serial ordering, exact
correlation, invalid-call bounds, restore/read/helper skipping, schema validity,
duplicate IDs, batch limits and fatal integrity faults. Provider-native call
extraction and concrete handler composition remain pending.

## Five-message startup coordinator

The startup coordinator now selects only the launcher-provided FIFO/spool adapter,
validates the independently pinned package and host-platform transport binding,
pins Linux descriptors before confinement, installs confinement before constructing
the input loader, and performs the exact bootstrap/readiness/initialize/initialized/
admission exchange. Input reads yield to launch-scoped termination control. The
confinement and input phases use separate non-renewing deadlines; every mismatch,
filter failure, timeout or early termination closes the transport.

Tests prove the ordering boundary, exact guest control messages, admission handoff,
transport/platform mismatch rejection, native-filter failure behavior, termination
precedence and startup expiry. A fixed production entrypoint and release assets
remain to be composed.

## Committed artifacts and observation content

The deterministic artifact wrapper validates the fixed model argument schema,
preserves UTF-8/base64 bytes, emits canonical JSON without collapsing JSON strings,
and performs begin/ordered 256 KiB parts/commit with independent operation IDs.
Only the verified commit receipt becomes usable. Exact committed bytes are kept
in a bounded cache, with explicit `ARTIFACT_UNAVAILABLE` behavior when retention
is impossible.

Receipt-scoped observation reads validate ranges and consistent metadata, decode
canonical base64, assemble bounded chunks, verify full-object SHA-256 only at EOF,
decode textual media incrementally across UTF-8 boundaries, and leave unsupported
binary media opaque. Empty content and unavailable content remain distinct. Tests
cover chunk ordering, canonical encodings, cache bounds, corruption, changed
metadata, UTF-8 boundaries and authenticated size ceilings.

## Admitted ordinary-operation scheduler

The single-threaded Python client now constructs and validates closed ordinary
envelopes, permits only the host-advertised operation set, keeps one operation in
flight, pumps launch-scoped termination control ahead of ordinary responses and
uses non-renewing monotonic response deadlines. It keeps durable operation IDs
separate from call IDs, resolves exact completed duplicates locally, rejects
changed reuse, treats unknown/terminal outcomes as terminal and applies a healthy
restore revision exactly once without resetting transport state.

Unit tests cover correlation, exact duplicate suppression, changed-content
conflicts, restore continuity, next-request revision binding, host termination,
unknown effects and response timeout. Broker persistence and the composition root
remain pending, so this boundary alone is not an executable harness.

## Native live confinement feasibility

A release-owned stable-ABI C extension now installs the irreversible architecture-
checked syscall allowlist with TSYNC, verifies single-thread/no-new-privileges
prerequisites and denies new executable memory mappings. A pinned test-only
Distroless image passed live ARM64 denial and permitted-file-I/O probes under
Operator's startup profile. See [native policy and evidence](native/README.md).
This does not qualify the complete harness or all supported hosts. Bootstrap
composition, dependency/release locking and broader qualification remain pending.

## Startup inputs and instruction skills

Input loading now binds the validated bootstrap prefix to the independently
pinned package, raw/canonical manifest descriptors, exact mounted inventories,
context/bundle/prompt bytes and selected skill contents. The fixed skill loader
checks its own release-selected digest, bundle/manifest identities, UTF-8 data and
all inventoried entrypoints/references. It executes no skill code or hooks.

The initialized response body derives from verified input identities. Actual
`admission_open` must pass the complete shared launch-identity validator before
context, bundle and entry access are admitted. Admission cannot broaden frozen
limits or run twice. Tests cover empty/selected skills, wrong loader, missing
content, changed prompt, extra manifests, explicit admission and immutable copies.

## Linux FIFO peer

The Python FIFO backend opens only its directional endpoints, validates prepared
inodes, and uses bounded nonblocking reads/writes with four-byte framing. Initial
rendezvous has a 60-second limit; partial frames, blocked writes and full receivers
have non-renewing five-second deadlines. EOF after bootstrap, EPIPE, oversized
headers and inode/inventory changes are terminal. It never reconnects.

The bootstrap-only descriptor handoff maps ordinary/control endpoints to FD 3–6.
The opt-in Go/Python interoperability test exercises this mapping in the disposable
Python test process and then exchanges startup and an ordinary operation. The
current test host is macOS ARM64; POSIX FIFO mechanics passing here do not qualify
native Linux containment or a Docker mount.

## macOS spool peer

The single-threaded Python peer implements bounded ordinary/control queues,
atomic publication, strict sequence/identity checks, cumulative ACKs, producer
cleanup and non-renewing five-second transfer/backpressure deadlines. Control
capture precedes ordinary work. It rejects unsafe/replaced lanes, changed retained
files, reappearing/gapped sequences, stale temporaries and future ACKs. A transport
failure is terminal; it cannot reopen an old guest output directory.

`make test` covers these paths. Operator's opt-in
`OPERATOR_PYTHON_PEER_TEST=1 go test ./internal/transport -run
TestPythonSpoolInteroperability -count=1` exchanges the five startup messages and
an ordinary request/response between its actual Go transport and this Python peer
using real files. The peer script is test-only: it does not install confinement or
verify campaign inputs. This is interoperability evidence, not Docker Desktop
file-sharing or runtime qualification.

## Immutable data and shared-contract loading

The Python package now includes descriptor-relative, no-follow, bounded reads
and exact immutable inventories. Reads service a caller-supplied control/deadline
callback between 64 KiB chunks and reject mutable types, links, unexpected names,
missing data and changed inode/content metadata. Guest input mounts require
read-only file/directory permission bits; release trees may retain owner-write
bits because their immutable root filesystem is enforced by Docker.

The contract loader requires an independently selected version/content digest,
authenticates the manifest before reading its declared payloads, verifies all
bytes, and compiles the shared Operator validator from frozen resources offline.
No package file is executed. It imports `operator_contracts` rather than forking
schemas or validators. The dependency remains an unpublished development package;
release lockfiles, publication and qualification remain required.

Run `make test` with a sibling Operator checkout and its prepared development
virtualenv, or set `OPERATOR_ROOT` and `PYTHON` explicitly. The tests use test-only
package manifests with explicit pins; they do not approve an image or release.

Next: bootstrap, the model/tool loop, image construction and end-to-end qualification.
No executable campaign harness or qualified image is claimed by this boundary.
