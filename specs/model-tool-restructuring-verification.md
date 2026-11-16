# Model tool restructuring verification

Verified locally on 2026-11-05 for `feat/model-tool-restructuring`, targeting
`candidate-v0.1.4`. This records controlled implementation evidence, not release
qualification or live-provider reliability.

## Matching identities

- Operator shared package: **0.6.0**,
  `sha256:bdf6b558c8c56ee189fc0531413b6273d1bb6d9614929d0ddc1a9ca72bf8c8de`.
- Contract source: `3c4f8d51df8cf04d308f343a27f83908d6fb304f`.
- Operator runtime: `47e4aa4dc36e5b28c6c31b96354fcdbd4a2bd1a0`.
- Harness runtime input inventory:
  `sha256:3af00646dd2889f9e50346f8af2c730cb723c37cf145a072bff012468177e897`.

The package matches Operator's finalized lock exactly. The runtime revision's
contracts and schemas match the package source. Existing embedded compatibility
checks remain authoritative; no old model-argument fallback was added.

The finalized handoff agrees with the implementation spec. It concretely defines
observation-selection retention through batches of the existing diagnostic
operation before assessment submission. Those batches add host calls but no model
turn. Restore follows Operator's injection-cleanup contract: known same-campaign
action mappings survive a healthy restore, and a fresh deletion is revalidated
against the current target. A historical deletion result does not prove absence
after restore.

## Controlled verification

- `make test-pr`: 142 Harness tests, source-lock and compilation checks, and 37
  shared Python contract tests passed.
- `python -m unittest discover -s build/tests -v`: 32 build/publication tests passed.
- `make test-integration`: controlled Operator–Harness process suites passed over
  FIFO and spool. Coverage includes execution and observation inspection, accepted
  finish, exit behavior, explicit scenario origin, reports/exports and cleanup;
  artifact input, hypothesis correction without preregistration, invalid-call
  exhaustion, retained injections, restore boundaries, host interruption,
  uncertain outcomes, context warnings and compaction.
- The four-attempt regression rejects duplicate summary keys, then commits claims
  selecting actual observation handles. Harness derives their execution receipt
  lists. Repeated finish delivery does not repeat host effects. Selection-retention
  failure prevents assessment submission. Shared fixtures and runtime tests cover
  wrong-kind/unread/partial references, path remapping and native database keys.
- Both `linux/arm64` and `linux/amd64` images passed their embedded 142-test suites,
  OCI compatibility/binding inspection, SBOM/provenance checks and matching
  Operator stopped-image inspection. BuildKit was pinned to the repository's
  v0.25.2; inspection requirements were not weakened for a newer local builder.

The process runner uses test-only Go overlays for obsolete fixture arguments and
assertions, plus the existing exit adapter. Operator's production code and checkout
are unchanged. It runs the production Python entrypoint with relocated guest paths
and a confinement shim. PostgreSQL/native Interceptor qualification was not run;
database coverage here uses controlled/shared fixtures. The AMD64 stopped-image
check is explicitly cross-platform on an ARM64 Mac. These checks do not establish
native Linux containment or live cloud/model behavior. No release was published.

## Context and formatting measurements

`build/measure_model_tools.py` compares candidate source
`bd5379834206803ce0be796d3386255323bbae9d` / contract 0.5.0 against this implementation.
The baseline Operator source is `485042787cc75e1776acaac11023ba9d210cc1f3`.
The generated `dist/model-tool-context-comparison.json` records exact locks,
per-tool bytes/descriptions/required fields, initial requests including the same
scenario task, submitted argument shapes, histories, and compaction points.

| Provider format | Ordinary catalog bytes before → after | Full catalog bytes before → after |
| --- | --- | --- |
| OpenAI Chat | 12,426 → 8,701 | 30,124 → 29,764 |
| OpenAI Responses | 12,374 → 8,649 | 29,981 → 29,621 |
| Anthropic Messages | 12,010 → 8,525 | 29,337 → 29,280 |
| Bedrock Converse | 12,094 → 8,609 | 29,568 → 29,511 |
| Gemini | 12,069 → 8,584 | 29,452 → 29,395 |

Ordinary catalogs shrink 28.8–30.1%. All 45 codec/capability combinations pass
no-growth checks for catalogs, combined prompt/catalog cost, and serialized initial
requests. The trusted prompt shrinks from 6,204 to 6,084 bytes. Fully admitted
catalogs retain all advanced capabilities, so their reduction is smaller.

The ordinary fixture still uses three model turns and three model tool calls, with
no retry. Excluding intrinsic target content, its submitted fields/container
nesting change as follows: execute 5/2 → 3/1; read 4/1 → 2/1; minimal finish
8/5 → 7/4. Optional assessment collections remain structured; repeated claim
receipt lists and generated IDs are supplied by product code.

Actual controlled OpenAI runtime request bytes total 62,395 → 41,799 with that
fixture's restricted catalog and short fixed prompt. Replaying the same history
into all five validated native formats with the full catalog and production prompt
also reduces request sizes. Separate advanced-setup/partial-read serialization
fixtures show no growth. In 60-group execute/read history fixtures, first
compaction moves from group 12–13 to group 16–17, and total compactions fall from
4–5 to 3. This is serialization/compaction evidence, not simulated target replay.

No applicable tokenizer is installed. Token estimates use the reproducible
existing cold-start heuristic `ceil(UTF-8 JSON bytes / 2)` and are not exact
provider token counts or admission guarantees. No paid API calls were made.

To regenerate the measurements, export the baseline Harness and Operator revisions
into separate directories, then run:

```sh
python build/measure_model_tools.py --operator ../operator_sandbox \
  --baseline-harness /path/to/baseline-harness \
  --baseline-operator /path/to/baseline-operator \
  --output dist/model-tool-context-comparison.json
```
