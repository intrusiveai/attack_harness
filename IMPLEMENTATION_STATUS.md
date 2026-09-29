# Attack Harness implementation status

## Current boundary

The initial production-path harness is implemented and packaged as a reproducible,
non-approved OCI candidate. The fixed entrypoint loads the exact pinned shared
contract package, selects only the launcher-provided FIFO or spool transport,
completes confinement and startup, constructs all campaign-lifetime services once,
and runs the adaptive model/tool loop through structured conclusion and stop.

This boundary is not a release claim. Deterministic Go/Python process integration
now covers both transports, campaign completion and interruption. Live provider
routes, real target deployments, release publication and native qualification on
all supported host tuples remain outstanding. Historical image candidates predate
the current source/contract pins and require rebuilding. Exact per-criterion status is in [ACCEPTANCE_MATRIX.md](ACCEPTANCE_MATRIX.md).

## Implemented runtime

- Immutable, no-follow input and selected-skill loading validates exact inventories,
  digests, permissions, identities and bounded reads before admission.
- Linux FIFO and macOS spool peers implement fixed lanes, framing, ordering,
  cumulative acknowledgements, producer cleanup, control priority and non-renewing
  deadlines without reconnect or resume.
- The startup coordinator enforces the exact five-message exchange and installs the
  architecture-specific stable-ABI seccomp filter before campaign input parsing.
- The ordinary scheduler keeps one operation in flight, separates operation/call/
  attempt identities, resolves exact duplicates locally, and treats unknown effects,
  peer loss and host termination as terminal.
- Provider-native OpenAI Chat, OpenAI Responses, Anthropic Messages, Bedrock Converse
  and Gemini request/result/continuation shapes are validated by the shared package.
  Calls execute serially through a fixed handler map; payload bytes never become code.
- Initial context includes an explicit objective work queue, coverage ledger,
  scenario index, immutable reference handles, budget projection and uncertainties.
  Model-assisted compaction suppresses tools, charges a model turn, summarizes only
  complete valid history, records source digest/omitted segments, labels the summary
  non-evidence, and fails closed when safe compaction cannot fit.
- Artifact upload is begin/ordered-part/commit; only a verified commit receipt is
  usable. Observation reads are receipt-scoped, bounded, range/integrity checked and
  distinguish empty, truncated, binary and unavailable content.
- Attempts receive deterministic allocation and local schema/semantic/lineage/
  artifact checks before target contact. Known negative results remain adaptive;
  failures or unknown effects stop later work.
- Conclusion finalization validates evidence references and commits conclusion
  artifact, conclusion record and stop in that order under a separate bounded budget.

## Deterministic evidence

`make test` runs 82 tests. They include the scripted benign marker vertical slice:
a baseline negative observation causes a distinct child payload/attempt, the child
returns actual marker bytes, and the final conclusion cites both receipts. The same
production `AdaptiveHarness`, native conversation, dispatcher, handlers, artifact,
attempt, observation and finalizer components are used.

The suite also covers contract/input drift, prompt and skill identities, all five
codec families, serial multi-call behavior, restore batch skipping, allocator and
loop boundaries, reference/observation reads, FIFO/spool faults, graceful and
unavailable conclusions, compaction provenance and impossible-context handling.

The [joined process suite](../operator_sandbox/docs/PROCESS_INTEGRATION.md) invokes
the production Python entrypoint against the Go host over FIFO and spool. It covers
large manifests, all prompt modes, skills, objectives-only/scenario/exploratory
campaigns, production HTTPS against local TLS, feedback and conclusions, healthy
restore with retained injections, correlated skipped calls, uncertain outcomes,
spool overflow and abrupt host/harness loss without replay. Large histories cross
the real compaction threshold; component stress tests repeat compaction for all
five codecs. The test-only launcher relocates paths and bypasses confinement;
Docker, native Interceptor and model responses remain controlled fixtures.

The acceptance matrix pins both source commits and the development contract
package. CI consumes these same pins and includes the process suite.

## Candidate build

The Dockerfile pins its frontend, Python builder, Distroless runtime and SBOM scanner.
Runtime wheels and build backend are hash/version locked. The build regenerates the
release tree from the exact contract package, runs all tests offline, verifies the
embedded manifest/catalog/prompt/loader, normalizes timestamps, and emits a
single-platform OCI archive with SPDX SBOM and SLSA provenance.

CI uses native self-hosted Linux AMD64 and ARM64 runners, builds each platform twice,
compares runtime identity, and exercises Operator's stopped-image inspection and
cleanup. That workflow is configured but has not been observed in this implementation
session. Local macOS/ARM64 evidence built both platform candidates (AMD64 through the
builder's non-native path) and passed stopped-image inspection for ARM64. These are
`built-not-qualified` artifacts and are intentionally ignored by git.

## Remaining qualification gates

- Run real non-streaming text, tool and follow-up exchanges for every advertised
  provider route, including cancellation and ambiguous outcomes.
- Run real declarative-HTTPS and native Interceptor target integrations with the
  required assurance, selection and cleanup behavior.
- Execute the complete `AIH-AC`/`AHC-AC` matrix on native Linux and macOS AMD64/ARM64
  hosts, including transport, confinement, networking, resource, crash, journaling,
  Docker-kill and restore races.
- Publish the shared contract package and immutable HTTPS release approval for the
  final image IDs; verify cache/offline preparation and installation lifecycle.

No remaining item above should be replaced by a mock or inferred from a successful
build. Until those gates pass, Operator must not treat these candidates as approved.

## Bedrock compatibility contract update

The contract candidate is now version `0.0.1`, pinned in
[build/contract-lock.json](build/contract-lock.json). It accepts the empty native
`usage.serverToolUsage` object observed by Operator's live Nova Lite probe while
rejecting populated hosted-tool usage. Shared Go/Python fixtures cover both cases.
Existing images contain the earlier contract and require rebuilding with this pin;
a host-only probe does not qualify the full Python/container campaign path.
