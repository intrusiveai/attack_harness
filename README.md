# Attack Harness

Python runtime implementation is in progress. Immutable-file access and pinned
shared-contract loading, startup input/skill verification, Linux FIFO/macOS
spool I/O and the admitted ordinary-operation scheduler are implemented and
tested. No campaign executable or
qualified image is available yet. See [implementation status](IMPLEMENTATION_STATUS.md)
and run `make test` for the current unit tests.

The engine is the product-owned `operator-native` Python harness running in an
Operator-managed, network-disabled Linux OCI container. It generates payloads and
conducts adaptive experiments through Operator's typed FIFO/file-spool interface.

- [Accepted shared host/harness contract](../operator_sandbox/schemas/SHARED_CONTRACT.md): authoritative wire, startup,
  manifest and completion rules; package publication and conformance remain pending.
- [Custom AI harness implementation specification](CUSTOM_AI_HARNESS_IMPLEMENTATION_SPEC.md):
  Python components, objectives/scenario interpretation, model/tools, payload delivery,
  feedback-driven adaptation, conclusions and functional acceptance tests.
- [Guest artifact and harness specification](GUEST_ARTIFACT_LAYOUT_SPEC.md):
  container layout, startup, release requirements and
  [Dockerfile/build pipeline handoff](GUEST_ARTIFACT_LAYOUT_SPEC.md#41-container-build-deliverables).
- [Operator product specification](../operator_sandbox/OPERATOR_SANDBOX_SPEC.md)
- [Operator container contract](../operator_sandbox/GUEST_CONTAINER_SPEC.md)

Start implementation with the harness spec's reading order and shared contract
gates HC-01–HC-06. Observation reads and selection use the
[Operator contract](../operator_sandbox/schemas/FEEDBACK_CONTRACT.md) and native
Interceptor support. The shared contract defines conclusion and manifest delivery.
Complete package authoring, Go/Python conformance and publication remain required;
Operator/harness runtime implementation and native qualification are pending.

## Docker MVP deployment

Administrators install the matching Linux Attack Harness image in local Docker Engine (Linux)
or Docker Desktop (macOS) and configure
Operator's `engine.image`. Operator resolves the full local Docker image ID and
checks/caches the
[HTTPS release compatibility record](../operator_sandbox/schemas/ENGINE_RELEASE_CONTRACT.md) before launch.
Linux hosts use private named FIFOs; macOS hosts use regular-file spools for
ordinary/control traffic. Input/skill/manifests stay read-only. Host support targets
x86_64 and ARM64/AArch64 on both OSes. Journaling remains mandatory; administrative
termination calls Docker directly without campaign-worker cooperation. Runtime
qualification is pending.

See [host runtime profiles](../operator_sandbox/HOST_RUNTIME_PROFILES.md) for the support matrix and remaining decisions.

The MVP uses Docker mounts/permissions and two-stage seccomp. Additional filesystem
policy and separate user-namespace remapping are optional. Confirmed supported
OS/Docker versions are informational; startup checks required runtime capabilities.
