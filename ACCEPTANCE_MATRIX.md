# Attack Harness acceptance matrix

Evidence recorded 2026-09-27. `Pass (component)` means the deterministic harness
component or fake-host behavior passed, not that the complete native criterion is
qualified. `Partial` means only the listed subset passed. `Not run` is an explicit
external qualification gap; no row is inferred from image construction alone.

## Evidence identity

| Item | Identity |
|---|---|
| Harness source | repository commit containing this matrix; runtime source lock `sha256:35dd1f2ac24b71a22aa8ea914bb0681631ee904368780334b3243f10f112d78a` |
| Operator source | `51a11c1bbbc27246e9913b1d71b6ebb49f2102af` |
| Contract package | version `0.0.0`, digest `sha256:648c7b2641a05505d8aa21f24054832dc3867fd63a302ec87ef855a213313b7a` |
| Local host | macOS ARM64; Python 3.14.6 test interpreter; Go 1.26.5; Docker client/server 29.0.1; Linux/ARM64 Docker VM |
| Test suite | `make test`: 81 passed |
| AMD64 candidate | config `sha256:9db407c25428ed3bb61dfc9c4c1daab659bdde77ec9c74578540769423eaaf12`; manifest `sha256:26a4046c7191e084ab4950cc19ec7f26f52600ba42701c5cc0d35d54c4acf0db`; OCI index `sha256:f8b32c513c173119a91310e283c7a92446d9ff77d04650feb959fae9df803d31`; archive `sha256:6439a753f867e5ce1863730c46a7e851489b6ec2971e4a3a11078c2066b0427c`; built locally, not native-qualified |
| ARM64 candidate | config `sha256:004bc121fb26b3ae1bb242276dd0d576e2af99294bf2997694952831a7e7b756`; manifest `sha256:2468f8f3a58f17af224016829ab7a9e715b3b9d19ea6c3650fa5a052e9db0e62`; OCI index `sha256:c5455df4b72a2068501e30c96393654973e7c5f25a5cc1aeedd80c982a788849`; archive `sha256:b31e3636928d55e6029f4c336df1bc80b249fd4364d72e2089dc2563e0a304b3`; built locally, not release-approved |
| Stopped-image check | ARM64 Docker ID `sha256:4dc8ac9935cf48dbcf0ace2ab98a0a2ae908448c47cf7fc17405f8ea19f5c927`; exact OCI config/layers matched; Operator inspection and cleanup passed |

Candidate files and machine-generated reports remain under ignored `dist/`.

## AIH acceptance criteria

| ID | Status | Evidence / remaining gate |
|---|---|---|
| AIH-AC-001 | Partial | Exact input/package/skill inventories, corruption, additions, empty/nonempty skills and admission narrowing pass; complete incompatible-capability initialization matrix remains. |
| AIH-AC-002 | Partial | Exact prompt bytes and all five compaction request shapes pass; Operator default/replace/ordered-extension end-to-end staging remains. |
| AIH-AC-003 | Partial | Bounded objective work queue, coverage ledger, full scenario index and reference handles pass; broader objectives-only/catalog/source-provenance variants remain. |
| AIH-AC-004 | Pass (component) | Production-path scripted marker vertical slice performs baseline, actual negative feedback read, changed child payload/attempt, marker read and evidence-bound conclusion. |
| AIH-AC-005 | Partial | Direct mapped operations and scenario-independent dispatch pass; complete exploratory-origin fixture matrix remains. |
| AIH-AC-006 | Partial | Shared allocator/loop implementations are used and local decode/schema/semantic/lineage/artifact checks pass; the full cross-language trace set is not rerun here. |
| AIH-AC-007 | Partial | Completed negatives adapt and failed/unknown operations terminate; all cleanup-unknown/partial-report variants remain. |
| AIH-AC-008 | Pass (component) | Receipt scope, campaign membership, range assembly, integrity, UTF-8 boundaries, binary opacity, truncation and unavailable/empty distinctions pass. |
| AIH-AC-009 | Partial | Native serial batches, ordering, duplicates, malformed calls and all five offline codecs pass; real provider route qualification is not run. |
| AIH-AC-010 | Partial | Oversized initial context, explicit handles, tool-suppressed complete-segment compaction, provenance and impossible-fit context-limit pass; stress-scale histories remain. |
| AIH-AC-011 | Partial | Only host-advertised mapped operations are installed and source-bound shared validators run; real HTTPS/Interceptor integrations are not run. |
| AIH-AC-012 | Partial | Shared finite-loop accounting, deadlines, invalid/no-progress/read/compaction behavior and model-free finalization pass in components; full transport pressure/timer matrix remains. |
| AIH-AC-013 | Pass (component) | Conclusion artifact, record and stop ordering, unknown receipt rejection, unavailable conclusion and conflicting acknowledgement handling pass. |
| AIH-AC-014 | Partial | Restore advances once and skips every later call with correlated results; complete snapshot/restore/compaction/termination race matrix remains. |
| AIH-AC-015 | Partial | Exact package pin, five-message startup, bounded identities, FIFO/spool component traces and stop finalization pass; complete real Go/Python peer-through-stop traces remain. |

## AHC acceptance criteria

| ID | Status | Evidence / remaining gate |
|---|---|---|
| AHC-AC-001 | Not run | No final approved image has run on all four native host tuples. |
| AHC-AC-002 | Partial | Minimal Distroless release tree, locked dependencies and build inventory checks pass; final forbidden-file inventory qualification remains. |
| AHC-AC-003 | Partial | Fixed isolated entrypoint and confinement-before-input ordering pass in tests; full launched candidate startup remains. |
| AHC-AC-004 | Partial | ARM64 feasibility image denied representative exec/fork/socket/namespace/memory/kernel probes; final image and AMD64 probe matrix remain. |
| AHC-AC-005 | Partial | Socket denial and allowed file I/O were probed; complete address-family/network and live transport matrix remains. |
| AHC-AC-006 | Partial | FIFO/spool direction, framing, EOF, ACK, cleanup, queue and deadline component tests pass; native Linux/macOS transport qualification remains. |
| AHC-AC-007 | Partial | Shared validators and framing/identity fault fixtures pass through Python components; complete cross-language wire suite remains. |
| AHC-AC-008 | Partial | Control is pumped during bounded waits/reads and deadlines are non-renewing; hostile pressure and kill-deadline qualification remains. |
| AHC-AC-009 | Partial | Immutable inventory, links, traversal, replacement and extra-entry tests pass; mounted live filesystem/scratch enforcement remains. |
| AHC-AC-010 | Pass (component) | Empty and selected skill sets load atomically without image rebuild; missing, changed and extra content fail. |
| AHC-AC-011 | Partial | Prompt raw identity and every model system request are bound; all Operator prompt composition modes need end-to-end qualification. |
| AHC-AC-012 | Partial | Bounded bundle index/reference reads, omissions, coverage and compaction gaps pass; complete large-bundle qualification remains. |
| AHC-AC-013 | Pass (component) | Closed fixed dispatch rejects unknown/prose/malformed arguments; payload bytes remain passive data; call/result order is preserved. |
| AHC-AC-014 | Partial | All five native codecs pass offline request/result/continuation fixtures; real provider exchanges are not run. |
| AHC-AC-015 | Pass (component) | Declared/actual artifact bytes, media, digest, parts, quotas and commit-only usability pass. |
| AHC-AC-016 | Partial | Guest request semantics, allocation and immutable lineage pass; native host translation goldens/targets remain. |
| AHC-AC-017 | Not run | Real declarative-HTTPS and native Interceptor qualification is unavailable. |
| AHC-AC-018 | Not run | Full host journal authenticity/gap qualification is Operator-owned and not run here. |
| AHC-AC-019 | Not run | Resource exhaustion, audit failure and direct Docker-kill matrix is not run. |
| AHC-AC-020 | Partial | Guest crash/stop/unknown-effect paths do not reconnect or replay; committed host-journal crash evidence is not run. |
| AHC-AC-021 | Partial | Guest restore continuity, revision adoption and batch skipping pass; complete snapshot history and termination race matrix remains. |
| AHC-AC-022 | Pass (component) | The scripted marker vertical slice demonstrates adaptive refinement and an evidence-scoped structured conclusion without shell/code tools. |
| AHC-AC-023 | Partial | Locked dual-platform builds, offline tests, normalized OCI, SBOM/provenance, identity comparison and stopped-image inspection are implemented; native CI and publication repeatability remain unobserved. |
| AHC-AC-024 | Partial | Actual bounded observation bytes, membership, ranges, hashes, UTF-8, empty/unavailable and retained receipts pass; all selection/profile/restore variants remain. |
| AHC-AC-025 | Partial | Manifest descriptor, immutable file and identity validation pass; explicit over-one-frame HC-05 integration remains. |
| AHC-AC-026 | Partial | Package/startup/envelope/restore/conclusion behavior passes in shared and component fixtures; complete real FIFO/spool fake-peer trace through accepted stop remains. |
