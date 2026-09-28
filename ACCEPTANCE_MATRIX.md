# Attack Harness acceptance matrix

Evidence recorded 2026-09-28. `Pass (component)` means deterministic component
coverage; `Pass (process)` means the listed behavior passed across real Go/Python
processes. Neither status qualifies production containers or live infrastructure.
`Partial` identifies a tested subset and its remaining gate. `Not run` identifies
external qualification still required.

## Evidence identity

| Item | Identity |
|---|---|
| Harness source | `d9d85fb78c15bec40694a8e22fd471d8bdb35294` |
| Runtime source lock | `sha256:c727d8db9f5447d485e7d4ae9b4940263880e358986b9b96801e9b31f79e7d83` (51 files) |
| Operator source | `e6f3ccd1a08ea3e1defdbb1a5514ff55dbfa6220`, tree `fd8d715632d1f9491558a7081cc09e5718768353` |
| Contract package | development version `0.0.0`, digest `sha256:be32c73554eab728df22bd51940b20ce670bd8442a827f3d6bfb2fd34f106c61` |
| Local process host | macOS ARM64; Python 3.14.6; Go 1.26.5 |
| Harness suite | 82 tests passed; includes three large-history compaction cycles for each of five codecs |
| Shared validation | 28 Python tests passed; full Go suite, schema generator checks and shared fixtures passed |
| Process suite | Full Go suite with `OPERATOR_HARNESS_INTEGRATION=1 OPERATOR_PYTHON_PEER_TEST=1`; focused restore/failure/history/transport race checks passed |

The [process integration guide](../operator_sandbox/docs/PROCESS_INTEGRATION.md)
provides commands and fixture boundaries. Python invokes the production entrypoint
with test-only path relocation and a no-op confinement callback. Model, native
Interceptor, Docker and release approval are fixtures. HTTPS uses the production
adapter against a local TLS server. Physical FIFO tests on macOS demonstrate wire
behavior, not the native Linux container profile. CI pins the matching Operator
commit and runs the combined suite; this record reports local execution, not an
observed CI run.

## Historical image-build evidence

These candidates predate the source/contract pins above and MUST NOT be treated as
images validated by the current process suite. Updated image builds and native
qualification remain required. Historical Docker client/server was 29.0.1 with a
Linux/ARM64 Docker VM.

| Item | Historical identity |
|---|---|
| AMD64 candidate | config `sha256:9db407c25428ed3bb61dfc9c4c1daab659bdde77ec9c74578540769423eaaf12`; manifest `sha256:26a4046c7191e084ab4950cc19ec7f26f52600ba42701c5cc0d35d54c4acf0db`; OCI index `sha256:f8b32c513c173119a91310e283c7a92446d9ff77d04650feb959fae9df803d31`; archive `sha256:6439a753f867e5ce1863730c46a7e851489b6ec2971e4a3a11078c2066b0427c`; built locally, not native-qualified |
| ARM64 candidate | config `sha256:004bc121fb26b3ae1bb242276dd0d576e2af99294bf2997694952831a7e7b756`; manifest `sha256:2468f8f3a58f17af224016829ab7a9e715b3b9d19ea6c3650fa5a052e9db0e62`; OCI index `sha256:c5455df4b72a2068501e30c96393654973e7c5f25a5cc1aeedd80c982a788849`; archive `sha256:b31e3636928d55e6029f4c336df1bc80b249fd4364d72e2089dc2563e0a304b3`; built locally, not release-approved |
| Stopped-image check | ARM64 Docker ID `sha256:4dc8ac9935cf48dbcf0ace2ab98a0a2ae908448c47cf7fc17405f8ea19f5c927`; exact OCI config/layers matched; Operator inspection and cleanup passed |

Candidate files and reports remain under ignored `dist/`.

## AIH acceptance criteria

| ID | Status | Evidence / remaining gate |
|---|---|---|
| AIH-AC-001 | Partial | Exact input/package/skill inventories, corruption, additions and narrowing pass; production startup includes large manifests and selected skills. Complete incompatible-capability initialization matrix remains. |
| AIH-AC-002 | Pass (process) | Exact default, replacement and ordered-extension prompts reach the model through real staging/startup on both transports; five codec compaction request shapes pass in components. |
| AIH-AC-003 | Partial | Objectives-only and scenario-guided process campaigns, reference reads and a 250-reference startup inventory pass; broader catalog/source-provenance variants remain. |
| AIH-AC-004 | Pass (process) | Both transports execute related attempts, retrieve actual feedback bytes and commit an evidence-bound conclusion. Component marker tests separately demonstrate negative-to-positive adaptation. |
| AIH-AC-005 | Pass (process) | Exploratory process campaigns execute mapped operations and conclude without requiring a supplied scenario origin. |
| AIH-AC-006 | Partial | Go validates actual Python attempt identities, release-record digest and parent lineage, including after restore. Shared rejection fixtures pass; exhaustive joined rejection traces remain. |
| AIH-AC-007 | Partial | Failed/unknown effects close execution in process tests; no automatic replay or admission after interruption. Exhaustive native cleanup-unknown/report variants remain. |
| AIH-AC-008 | Pass (process) | Actual receipt-scoped feedback reaches the next model turn; components cover membership, ranges, integrity, UTF-8, binary opacity, truncation and empty/unavailable distinctions. |
| AIH-AC-009 | Partial | Real Chat Completions model/tool loop plus all five offline codecs pass; live provider route qualification remains. |
| AIH-AC-010 | Pass (process) | Production 1 MiB history threshold triggers tool-suppressed compaction on both transports, preserving task and non-evidence provenance; repeated 200-segment stress histories pass for all five codecs. |
| AIH-AC-011 | Partial | Production HTTPS adapter/local TLS process campaign passes with observer assurance; real deployment and native Interceptor qualification remain. |
| AIH-AC-012 | Partial | Control while model work is blocked, spool overflow, host/harness loss and finite-loop components pass; native resource/timer qualification remains. |
| AIH-AC-013 | Pass (process) | Real conclusion artifact, record and accepted stop chain pass; invalid references and conflicting acknowledgements retain component coverage. |
| AIH-AC-014 | Partial | Snapshot metadata/list/inspect, revision adoption in the same Python process, retained-injection cleanup, child lineage and correlated skipped batch calls pass; lost restore replies terminate. Native race matrix remains. |
| AIH-AC-015 | Pass (process) | Both peers verify the same fresh package and exchange the five-message startup through accepted stop over physical FIFO/spool. |

## AHC acceptance criteria

| ID | Status | Evidence / remaining gate |
|---|---|---|
| AHC-AC-001 | Not run | No final approved image has run on all four native host tuples. |
| AHC-AC-002 | Partial | Minimal Distroless release tree, locked dependencies and build inventory checks pass; final forbidden-file inventory qualification remains. |
| AHC-AC-003 | Partial | Production isolated entrypoint completes real host startup using test-only path/confinement shims; full launched production image qualification remains. |
| AHC-AC-004 | Partial | ARM64 feasibility image denied representative exec/fork/socket/namespace/memory/kernel probes; final image and AMD64 probe matrix remain. |
| AHC-AC-005 | Partial | Socket denial and allowed file I/O were probed; complete address-family/network and live transport matrix remains. |
| AHC-AC-006 | Partial | Physical FIFO/spool process campaigns and fault tests pass; native Linux/macOS Docker transport qualification remains. |
| AHC-AC-007 | Partial | Joined startup/ordinary/restore/stop traces and shared framing/identity fault fixtures pass; exhaustive hostile cross-language wire qualification remains. |
| AHC-AC-008 | Partial | Control terminates blocked model work across processes; spool overflow closes execution. Native hostile-pressure and Docker kill deadlines remain. |
| AHC-AC-009 | Partial | Immutable inventory, links, traversal, replacement and extra-entry tests pass; mounted live filesystem/scratch enforcement remains. |
| AHC-AC-010 | Pass (process) | Empty and selected skills load through real host staging without image rebuild; component inventory tests reject changed/missing/extra content. |
| AHC-AC-011 | Pass (process) | Default, replacement and ordered-extension prompts match exact staged bytes at the first model request over both transports. |
| AHC-AC-012 | Partial | Large startup inventory/reference handles and real large-history compaction pass; complete native large-bundle qualification remains. |
| AHC-AC-013 | Pass (component) | Closed fixed dispatch rejects unknown/prose/malformed arguments; payload bytes remain passive data; call/result order is preserved. |
| AHC-AC-014 | Partial | All five native codecs pass offline request/result/continuation fixtures; real provider exchanges are not run. |
| AHC-AC-015 | Pass (process) | Real multipart artifacts become usable only after commit; component fixtures cover quotas, declared/actual bytes, media and integrity. |
| AHC-AC-016 | Partial | Actual Python requests reach Go allocation, translation, feedback and immutable lineage, including restore; live native target qualification remains. |
| AHC-AC-017 | Partial | Production declarative HTTPS adapter passes against a local TLS server; live HTTPS and native Interceptor qualification remain. |
| AHC-AC-018 | Partial | Real Go journal persists model intent across abrupt host death; repeated cleanup preserves the uncertain committed prefix. Full native audit/gap qualification remains. |
| AHC-AC-019 | Not run | Resource exhaustion, audit failure and direct Docker-kill matrix is not run. |
| AHC-AC-020 | Partial | Killed Go host, killed Python harness, cancellation and unknown restore tests reject replay/readmission; native Docker/host interruption qualification remains. |
| AHC-AC-021 | Partial | Same-process restore, snapshot metadata, retained injection cleanup, lineage and batch skipping pass; full native restore/termination races remain. |
| AHC-AC-022 | Pass (process) | Related attempts, actual feedback reads and receipt-bound conclusions pass with the Go host; component marker slice verifies adaptive negative-to-positive refinement. |
| AHC-AC-023 | Partial | Locked dual-platform builds, offline tests, normalized OCI, SBOM/provenance, identity comparison and stopped-image inspection are implemented; native CI and publication repeatability remain unobserved. |
| AHC-AC-024 | Partial | Actual feedback bytes reach the model through host visibility filtering and receipt reads; range/integrity/unavailable distinctions pass in components. Complete native profile/restore matrix remains. |
| AHC-AC-025 | Pass (process) | HC-05 descriptor carries an input manifest exceeding the control-frame limit; Python validates and consumes its staged immutable files. |
| AHC-AC-026 | Pass (process) | Real Go/Python FIFO/spool traces cover pinned package, startup, operations, restore, conclusion and accepted stop; native container qualification remains separate. |
