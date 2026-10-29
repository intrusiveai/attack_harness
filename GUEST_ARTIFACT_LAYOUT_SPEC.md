# Attack Harness container and artifact layout

Attack Harness v0.1.4 is an immutable Linux OCI image for `linux/amd64` and
`linux/arm64`, launched by Operator under runtime profile `operator-container/v1`.
The image contains the Python runtime, fixed Harness code, native confinement
module, default prompt, and the exact shared contract package. Operator provides
campaign inputs and transports and retains durable outputs outside the guest.

The [integration guide](docs/INTEGRATION.md#locked-contract-and-runtime) specifies
the locked contract, matching Operator revision, and installation procedure.
The [runtime guide](CUSTOM_AI_HARNESS_IMPLEMENTATION_SPEC.md) describes the adaptive
loop and tools.

## Image construction and identity

[`Dockerfile`](Dockerfile) uses three stages:

1. The builder downloads dependencies using hashes in
   [`requirements-runtime.lock`](requirements-runtime.lock), prepares the release
   tree from the locked package, and compiles the native confinement module.
2. The test stage runs Harness tests and verifies the generated release tree with
   networking disabled.
3. The runtime stage copies the tested tree into digest-pinned Distroless Python.
   It does not copy the compiler, test suite, source checkout, or builder Python.

[`build/image-lock.json`](build/image-lock.json) records image/toolchain identities;
the Dockerfile and workflow select those pinned inputs. The contract version and
digest are fixed in [`build/contract-lock.json`](build/contract-lock.json).
[`build/source-lock.json`](build/source-lock.json) binds runtime build inputs.
Builds use `SOURCE_DATE_EPOCH=0` and normalized timestamps. OCI output includes
SBOM and provenance attestations; reproducibility checks compare the runtime
config, manifest, and layers independently of attestation timestamps.

The runtime process uses UID/GID `65532:65532`, working directory
`/run/operator/work`, and this fixed entrypoint:

```text
/usr/bin/python3 -I -S -B /opt/operator/engine/bootstrap.py
```

The bootstrap admits only fixed immutable import locations. Campaign inputs,
skills, writable work, and target responses are never code or module search paths.

## Release files

```text
/opt/operator/engine/
  bootstrap.py
  lib/
    attack_harness/
    operator_contracts/
    _confinement.abi3.so
    <locked dependencies and their license notices>
  share/
    compatibility.json
    engine-manifest.json
    runtime-config.json
    default-system-prompt.txt
    tool-catalog.json
    schemas/
      package.json
      <manifest-declared shared package files>
  licenses/
```

[`build/prepare_release.py`](build/prepare_release.py) validates the exact shared
package inventory, digest, registries, file count, and content size before copying
it. Tool declarations are generated from the shared package for all supported
codecs. Release verification checks the copied package, compatibility fields,
resource digests, runtime configuration, and generated catalog against those inputs.

## Embedded compatibility and digest bindings

`/opt/operator/engine/share/compatibility.json` is a bounded closed JSON object.
For AMD64 its values are:

```json
{
  "api_version": "operator.dev/harness-compatibility/v1alpha1",
  "minimum_operator_version": "0.1.0",
  "contract_package_version": "0.3.0",
  "contract_package_digest": "sha256:1ec7a4c0d8d5e4783c6f2bf5c473d3722c47dd193922b4c63feb1e0a0aac7502",
  "runtime_profile": "operator-container/v1",
  "platform": "linux/amd64"
}
```

The ARM64 image uses `linux/arm64`. The minimum Operator version and exact
contract identity are both enforced. The compatibility file does not contain its
own image digest, registry tag, or a remote approval identity. It is at most 64 KiB;
invalid fields, types, duplicate keys, or mismatched package/platform values fail.

Operator inspects fixed release files in a stopped container and validates them
before campaign execution. The following identities are distinct:

| Identity | Meaning |
| --- | --- |
| OCI index digest | Published multi-platform image and attestation selection; retained in the release catalog. |
| Platform manifest digest | One platform's config and layer descriptors. |
| OCI config digest | Platform image configuration, including root filesystem identities. |
| Local Docker image ID | Independently resolved by Docker; classic and containerd-backed stores can expose different identity forms. |
| Compatibility digest | SHA-256 of the exact embedded `compatibility.json` bytes, without JSON normalization. |
| Shared package digest | Content identity of the installed Operator contract package. |

Operator freezes the compatibility-byte digest as `release_record_digest` in
startup and assessment bindings. Attempt generator metadata uses that same value
as `generator.release_digest`. The resolved image identity is a separate binding.
These names do not imply an external record lookup. The shared
[image contract](https://github.com/intrusiveai/operator_sandbox/blob/dc2f1c40a3e6c3c88209e5f393493e6a627fc03f/schemas/ENGINE_RELEASE_CONTRACT.md)
is authoritative.

`engine-manifest.json` binds platform, runtime profile, contract identity, fixed
entrypoint, transports, and exact prompt/skill-loader/tool-catalog resource
sizes and digests. `runtime-config.json` supplies the fixed package identity and
skill-loader digest to the entrypoint. Host and guest validate these bindings;
re-encoding a resource changes its raw identity.

## Campaign filesystem

| Location | Purpose and access |
| --- | --- |
| `/run/operator/input` | Frozen scenario bundle, effective prompt, context, and admitted references; read-only. |
| `/run/operator/customer-skills` | Selected instruction-only skills and inventoried passive references; read-only. |
| `/run/operator/manifests` | Separate input-tree, skill-set, and per-skill manifests; read-only. |
| `/run/operator/ipc` | Four directional FIFO lanes for Linux hosts. |
| `/run/operator/spool` | Directional file-spool lanes for macOS hosts. |
| `/run/operator/work` | Fresh bounded writable campaign scratch; non-executable. |
| `/tmp` | Fresh bounded non-executable temporary storage. |

Operator owns immutable staging and mount publication. A read-only bind alone
cannot make caller-writable backing data immutable. The Harness independently
checks inventory, regular-file/no-link constraints, identity, and bounded reads.
Unmanifested files, escaping paths, and changed bytes are rejected. Model or
skill text cannot select mount destinations. Credentials, host source trees,
runtime sockets, protected journals, and target volumes are not guest inputs.

Manifest limits are 8 MiB for input-tree, 64 KiB for skill-set, 2 MiB per skill
manifest, and 40 MiB aggregate. Relative paths are bounded to 1,024 UTF-8 bytes
and depth 16. Inventories do not include themselves; initialization carries
fixed-path descriptors instead of embedding full inventories in a control frame.

## Startup and confinement

Operator establishes the container's read-only root, disabled network, dropped
capabilities, resource limits, and startup policy. Linux hosts use FIFO transport;
macOS hosts use file spool through their Linux Docker runtime. Host selection and
mount details follow the pinned
[container contract](https://github.com/intrusiveai/operator_sandbox/blob/e4de591a40ce25a9a37d310ff24e43374337ac15/GUEST_CONTAINER_SPEC.md).

The guest loads fixed code and the shared package, accepts `bootstrap`, pins
transport descriptors, and installs the irreversible native filter. Only then does
it send `confinement_ready` and read campaign data during `initialize`.
`initialized` confirms the verified bindings; `admission_open` authorizes ordinary
operations. Startup mismatch or confinement failure terminates before admission.

The [native live policy](native/README.md) denies process creation, execution,
sockets, namespace changes, process-memory access, and executable memory changes.
The guest cannot launch helpers or contact providers directly. Instruction-only
skills and the fixed dispatcher preserve this boundary; writable storage does not
provide an interpreter or shell tool.

## Transport and durable output

Ordinary requests and responses are distinct from control traffic. Strict framing,
sequence and correlation checks, bounded queues, deadlines, and acknowledgements
come from the shared protocol. One ordinary operation is in flight while control
traffic remains serviceable. Spool publication is atomic and acknowledgements
control deletion; neither spool files nor scratch storage are durable campaign
artifacts.

Harness publishes durable content through Operator and reads feedback only through
permitted handles. Operator journals results and owns reports and exported
evidence. Accepted finish closes execution and requests guest exit; final cleanup
state is established by Operator. Transport loss or uncertain effects do not cause
reconnection, automatic restart, or campaign replay.

## Build and inspection commands

Prepare the exact shared package and Python environment using
[the development instructions](README.md#development). Build a platform image:

```sh
make image PLATFORM=linux/arm64 OPERATOR_ROOT=/absolute/path/to/contract-source PYTHON=.ci-venv/bin/python
```

Use `linux/amd64` for AMD64. Output under `dist/` includes an OCI archive and build
report. Inspect with the separately pinned Operator runtime:

```sh
make inspect-stopped-image PLATFORM=linux/arm64 OPERATOR_ROOT=/absolute/path/to/matching-operator PYTHON=.ci-venv/bin/python
```

The check reads fixed files without starting the image, compares OCI config and
layers, validates embedded compatibility and runtime resource bindings, and
removes the inspection container. A cross-platform local inspection requires
`INSPECTION_FLAGS=--allow-cross-platform-inspection` and records that fact; it is
not native runtime execution. Image inspection and a running Operator campaign
exercise different boundaries.

CI builds each platform twice, compares runtime identity, and performs native
stopped-image inspection before publication. The registry/catalog workflow is
maintainer-facing and documented in the
[release guide](.github/maintainers/CANDIDATE_RELEASES.md).
