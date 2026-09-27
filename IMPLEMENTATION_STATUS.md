# Attack Harness implementation status

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

Next: immutable startup inputs/skill loader, FIFO/spool I/O, confinement and
bootstrap, the model/tool loop, image construction and end-to-end qualification.
No executable campaign harness or qualified image is claimed by this boundary.
