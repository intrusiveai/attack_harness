<h1><img src="assets/attack-harness.png" alt="Attack Harness icon" width="48" height="48" align="absmiddle"> Attack Harness</h1>

This repository contains the initial production-path Python Attack Harness and a
locked OCI candidate build. The fixed bootstrap performs the five-message startup,
installs native confinement before reading campaign inputs, composes the admitted
adaptive campaign, executes only the shared typed tool catalog, consumes bounded
observation bytes, and commits a structured conclusion before requesting stop.

The implementation and deterministic fake-host vertical slice are complete enough
to build candidates, but no image is release-approved or fully qualified. Live
provider routes, native target integrations, and all four host/architecture tuples
remain external qualification gates. See [implementation status](IMPLEMENTATION_STATUS.md)
and the [acceptance matrix](ACCEPTANCE_MATRIX.md).

The engine is the product-owned `operator-native` Python harness running in an
Operator-managed, network-disabled Linux OCI container. It generates payloads and
conducts adaptive experiments through Operator's typed FIFO/file-spool interface.

- [Accepted shared host/harness contract](../operator_sandbox/schemas/SHARED_CONTRACT.md): authoritative wire, startup,
  manifest and completion rules. The development package is pinned by exact content
  digest; public package/release publication remains pending.
- [Custom AI harness implementation specification](CUSTOM_AI_HARNESS_IMPLEMENTATION_SPEC.md):
  Python components, objectives/scenario interpretation, model/tools, payload delivery,
  feedback-driven adaptation, conclusions and functional acceptance tests.
- [Guest artifact and harness specification](GUEST_ARTIFACT_LAYOUT_SPEC.md):
  container layout, startup, release requirements and
  [Dockerfile/build pipeline handoff](GUEST_ARTIFACT_LAYOUT_SPEC.md#41-container-build-deliverables).
- [Operator product specification](../operator_sandbox/OPERATOR_SANDBOX_SPEC.md)
- [Operator container contract](../operator_sandbox/GUEST_CONTAINER_SPEC.md)

Observation reads and selection use the
[Operator contract](../operator_sandbox/schemas/FEEDBACK_CONTRACT.md). The shared
package supplies the validators, native codecs, tool projections and loop accounting;
the harness does not maintain an independent schema registry.

## Reproducible checks

The sibling Operator checkout must be at the commit pinned in `Makefile`.

```sh
make test
make verify-source verify-contracts
make image PLATFORM=linux/arm64
make image PLATFORM=linux/amd64
make inspect-stopped-image PLATFORM=linux/arm64
```

`make image` writes ignored, non-approved OCI candidate evidence under `dist/`.
`make inspect-stopped-image` first requires the matching `make image` output; it
builds an equivalent single-manifest Docker archive and runs Operator's production
stopped-image reader through an opt-in overlay test. The container is never started
and successful inspection is not reported until cleanup succeeds.

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
