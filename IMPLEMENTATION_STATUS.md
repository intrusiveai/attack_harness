# Attack Harness implementation status

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

Next: immutable startup inputs/skill loader, FIFO I/O, confinement and
bootstrap, the model/tool loop, image construction and end-to-end qualification.
No executable campaign harness or qualified image is claimed by this boundary.
