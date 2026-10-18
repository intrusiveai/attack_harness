# Attack Harness acceptance matrix

Current contract rebuild evidence recorded 2026-10-18 UTC; earlier results are dated below. `Pass (component)` means deterministic component
coverage; `Pass (process)` means the listed behavior passed across real Go/Python
processes. Neither status qualifies production containers or live infrastructure.
`Partial` identifies a tested subset and its remaining gate. `Not run` identifies
external qualification still required.

## OpenAI tool declaration rebuild (2026-10-18 UTC)

Branch `fix/openai-tools-contract-0.0.5` starts from candidate commit
`a3747af`. It follows Operator's
[qualification handoff](../operator_sandbox/docs/qualification/openai-tools-2026-10-18/README.md).
The correction is shipped by the shared package; Harness dispatcher code and
startup/compatibility/declaration-digest checks are unchanged. Local evidence below
does not repeat or extend the handoff's live-provider qualification.

| Input/check | Identity or result |
|---|---|
| Contract source and inspection Operator | `1eaca1da7ad236353cb86d8799c93c679389ca4f`, tree `0b5aed5fcba919f46366d20b04487aca5a4e1bb6`; source confirmed available on GitHub |
| Exact contract | `0.0.5`, `sha256:3b5690013ca4e0bb5f7e7c904b26df401f113ec61ef6158ad948db337ef13198`; receipt matches all lock fields, 270 files / 7,533,149 bytes |
| Harness runtime source lock | `sha256:de8bbe5fb8b3cfede50bf01158096a1e4bc593a4edb579505c35239e6468df57` |
| Component checks | 86 Harness tests, 22 publication/inspection tests, both specified Go model-tool tests and both shared Python model-tool tests passed |
| Process checks | Eight `TestPythonProcessCampaigns` cases and both FIFO/spool `TestPythonProcessToolSchemaRejections` cases passed |
| Build checks | Both architectures built twice; config, platform manifest and layers identical within each pair; SBOM/provenance verified |
| Actual Operator inspection | Both built images passed the stopped-image reader, embedded contract/resource checks, exact compatibility bytes/digest and confirmed container cleanup with external HTTP disabled |
| `amd64` image config | `sha256:198ac8548130089b278ab8344743d65f4ab8259810c95b62e6d1e97da315271f` |
| `amd64` platform manifest | `sha256:6a2bb7339bfa94c70470a7fda513bc79a58bc2e1b536d23cc68886ac0ca54002` |
| `amd64` embedded compatibility raw digest | `sha256:60247af7a0e14b2448503170e7db0239584a83b741297c81695f0bc63bf0c603` |
| `arm64` image config | `sha256:e75337ab0f0af78a906f0f9d6acaa23d58d91558369e193f429051905b4dc07f` |
| `arm64` platform manifest | `sha256:1adbe15ae9c9602346e2bf93190c1704aeb80aa789c31c1809493312d883e58e` |
| `arm64` embedded compatibility raw digest | `sha256:715c792e2083ee4e15487ea757fb88c313995da29b31ab137a2f749899ae0156` |

The tool arrays extracted from both final OCI images match the installed `0.0.5`
package and the handoff's exact declarations, with all eleven tools enabled:

| Projection | Canonical bytes | SHA-256 |
|---|---:|---|
| Chat Completions | 58,000 | `ace7da1e99d0dc197dad729b479267c1c3674ef5b27a20900e3813f0a6a5631b` |
| Responses | 57,857 | `6d43b72d94ae1c8c18c5fb3982ed8f499b55b604d02ae160c6992d08d11dd3e0` |

The generated model-tool schema also matches
`sha256:59dd92ce5124538ec83bdfa0649905d0acab9b9e3232cbe613b31549c2dc583b`.
Each OpenAI declaration has an ordinary object root. Shared/runtime tests retain
scenario, generation, carrier and record-kind constraints. The process rejection
case proves invalid calls do not reach target execution or refund the submission
index; the subsequent valid attempt succeeds at index 2 and concludes normally.
These process tests use a temporary development package from the pinned source and
controlled model/target peers; actual image inspection separately verifies the
locked release package `0.0.5`.

The local host is macOS ARM64 with Docker 29.8.2 and pinned BuildKit v0.25.2.
AMD64 builds used emulation and explicit cross-platform stopped-file inspection;
this is not native AMD64 runtime qualification. Attestation/archive envelopes vary
between builds; runtime bytes match. No live API calls, GHCR publication or catalog
writes were performed. Merge into the candidate branch to run the existing native
CI build/publication workflow. Select the rebuilt image and matching Operator
candidate, then start a new campaign; do not resume a previously failed campaign.

Archives and per-platform reports are under ignored `dist/`. Declaration evidence
is `dist/contract-0.0.5-tool-declarations.json`; test/build logs are under
`dist/contract-0.0.5-evidence/`. Prior `0.0.4` artifacts were moved to
`dist/contract-0.0.4-previous/` to keep their evidence distinct.

## Embedded compatibility verification (2026-10-17)

These local results cover the changes on `feat/local-harness-compatibility`,
created from `candidate-v0.1.0` and updated with the already merged workflow cleanup.
The runtime source lock identifies the uncommitted tested runtime independently
of this documentation. No GHCR image or website catalog was published by this run.

| Input/check | Identity or result |
|---|---|
| Harness runtime source lock | `sha256:1cd4917b5a4aecd75f346a30f442f374dd1dc30c14c742a36911d4ea7ecc3c07` |
| Contract and CI Operator source | `cb43a919bda9b8689c11e20b7a09db35d2a98f89`, tree `1fcded221a5fa02d2cb60f493e57dcd8150adcc1` |
| Updated Operator used for local verification | `9dfc8f6f4e913d5f9fcbfa8eb8af6fe070fe8ac2` (follow-up package-lock/handoff commit) |
| Exact contract package | `0.0.4`, `sha256:750deac00ebece408dd7514ceae75e090f458f07ed1988b26859f7332ade32be`; complete receipt verified |
| Harness tests | 86 passed on host and in each image builder |
| Publication/inspection tests | 22 passed, including candidate-to-final catalog/image preservation without external records |
| Shared and admission checks | 28 Python fixtures and Go `contracts`, `internal/imagerelease`, `internal/dockercontrol`, `cmd/operatorctl` suites passed |
| Operator process integration | Complete `make test-integration` passed against this Harness source |
| Image builds | Both architectures rebuilt twice with BuildKit v0.25.2; config, platform manifest and layers identical within each pair; SBOM/provenance verified |
| Stopped-image preparation | Both variants passed actual updated Operator `imagerelease.Prepare`, five-file inspection, exact compatibility bytes/digest and confirmed cleanup with external HTTP disabled |
| `amd64` OCI config | `sha256:521aab977a40770230bdba7d3c2b13c5df233eb5c9206f69bd8a36c92c03c8d1` |
| `amd64` OCI platform manifest | `sha256:0e3159b575bcdba4f85441b52e6007464c229f067261901186ffb148a0c9a6ef` |
| `amd64` embedded compatibility raw digest | `sha256:35f075b079095d9eb90a9a3fa52e9c24b51cae2e156fce9e57ba341bc45ee0f5` |
| `amd64` resolved local Docker ID | `sha256:96ed6101df27fe108c6a37afc22472ff0e7448538cc3829717d2db612350b6dd` |
| `arm64` OCI config | `sha256:3526f4a754fee368bf2de511cc8ab79e522b741b8b298ce185eaf83957f94465` |
| `arm64` OCI platform manifest | `sha256:8c6a478dcae94defb1e34f2df776a7f5080dd14f915b122b78cc4ea97d83a8f0` |
| `arm64` embedded compatibility raw digest | `sha256:c6c31a5524257676894d49f9b4cde443f58bb2b613460e55187751ff2b3ed1ee` |
| `arm64` resolved local Docker ID | `sha256:f07f4954c654f6914d5722425a0411d18f4fdf0c416d687f919fd801267a8e2b` |

The local host was macOS ARM64 with Docker Desktop 4.95.0 / Docker 29.8.2,
Go 1.26.5 and Python 3.14.7; image builders use locked Python 3.13.15. ARM64
inspection matched host architecture. AMD64 was built under emulation and inspected
with the explicit cross-platform file-inspection option; no AMD64 execution or
native qualification is claimed. Publication still requires native CI evidence.
Containerd-backed Docker reports a local manifest-based ID here; reports preserve
that independently resolved ID and the separate OCI config digest. OCI attestations
and enclosing archive/index digests can vary between builds without changing runtime
bytes; comparison reports record that distinction.

Missing, malformed, oversized, duplicate/extra-field, wrong-version/package/platform
records and altered resources fail closed in Harness and updated Operator fixtures.
Operator's diagnostic tests verify rejection before attachment/execution and local
admission without release-service access or an approval cache.

Focused representative Go/Python campaigns use the exact built ARM64 compatibility
bytes, resolved image ID and installed package `0.0.4`, across FIFO/spool and
objectives-only, scenario, exploratory and local HTTPS fixtures. A temporary Go test
overlay replaces development-package/image fixtures and adds assertions for retained
raw bytes, frozen startup identities, two attempt generator digests and the conclusion
binding. It journals compatibility through the real campaign writer, modeling the
worker's release retention; Docker/target/model and confinement remain fixtures in
these process campaigns. This does not claim a launched-image or live-provider QA
pass. Historical campaign identities are not rewritten.

Build archives, reports and the exact-package campaign overlay are retained locally
under ignored `dist/`; ordinary CI retains its own build/inspection evidence. Native
four-host runtime and live integration qualification remain post-publication QA.

## Historical process evidence identity (2026-09-28)

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
observed CI run. These are historical results; the current workflow selects the
`0.0.5` contract source listed in the current evidence above.

## Additional local container evidence (2026-10-07)

The following runtime revisions passed benign support campaigns on macOS ARM64
using an actual confined Harness image and actual targets, rather than fixture
Docker. Both the standalone HTTPS and Interceptor paths passed required scenario,
independent ticket/sink checks, cleanup, and the test controller's result handoff.
Interceptor's protected archive passed Operator's unchanged evidence verifier.

| Input | Validated identity |
|---|---|
| Harness runtime source | `4469a97c87832f513f9a187a3ada1998fa9d794c` |
| Runtime source lock | `sha256:1370be3c06f661a1880fcde4d76ae93c603ed63a219dc6464d91ef2030a68689` (51 files) |
| Operator source | `396a90d215e57b582ee0a71c3a0802ee2ed278f4` |
| Interceptor source | `bd80a449ae32d4ecb57e7899a1d5d4ea8011d762` |
| Contract package | development version `0.0.3`, digest `sha256:7d85bc39910f23b2c8f8de761f447be5dedc9c74d0833f358eadded20a07bfac` |

Harness and target models were separate scripted providers. Image compatibility
records were private test fixtures; runtime checks were not bypassed. The Harness
suite passed 83 tests. These results supplement, rather than re-date or replace,
the historical process evidence and matrix below. They do not establish live-model
susceptibility, native Linux/rootless or cloud isolation, release approval, or full
native-platform qualification. No acceptance criterion is promoted to a complete
qualification pass by this limited example.

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
| AHC-AC-001 | Partial | Both new image variants pass updated Operator stopped-image compatibility inspection. No final image has run on all four native host tuples. |
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
