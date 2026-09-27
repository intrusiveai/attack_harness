# Attack Harness implementation status

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

Next: confinement and
bootstrap, the model/tool loop, image construction and end-to-end qualification.
No executable campaign harness or qualified image is claimed by this boundary.
