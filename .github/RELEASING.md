# Release management

These instructions are for Attack Harness maintainers publishing and promoting
releases. They are not part of installing or running Attack Harness through
Operator Sandbox.

## Candidate releases and QA

Push to `candidate-v1.2.3` (including merging another branch into it) to build both
Linux architectures and publish `ghcr.io/intrusiveai/attack_harness:v1.2.3`.
Every push runs the existing source/contract checks, Python and Go/Python process
tests, OCI inspection, SBOM/provenance checks, reproducibility comparison, and
Operator stopped-image inspection. **Running the image through Operator and live
provider/target tests belong to subsequent QA; they do not block candidate admission.**
The version may include a prerelease suffix, but not SemVer build metadata.

Each build also publishes a unique `v1.2.3-candidate.<run-id>.<attempt>` image tag
and GitHub prerelease with exact platform/config/index identities and reports.
The OCI images retain their SBOM and provenance attestations. The workflow
dispatches `approve-candidate.yml` at that unique Git tag; it independently checks
the completed build jobs and calls the pinned releases-service publisher once per
platform. Approve the existing `production` environment deployment when prompted.
After it completes, Operator can admit the candidate by its exact config digest.
This is approval for QA use, not a claim that the full runtime acceptance matrix
has passed. The seven-field service record has no QA-only restriction.

Merging the same-repository candidate PR into `main` verifies its published source,
unchanged merge tree, and both public approval records, then copies that exact OCI
index to `:latest` without rebuilding. It creates `v1.2.3` as a stable GitHub Release
and freezes that version against later candidate writes. Merge `main` into the
candidate before releasing if needed to make their trees agree. Use a new version
for further development after promotion. Direct pushes to `main` only verify code.

The workflow changes, including `approve-candidate.yml`, must first exist on the
default branch so GitHub can dispatch approval. Native runners retain the existing
`self-hosted`, `Linux`, `attack-harness-release`, and `X64`/`ARM64` labels and need
Python 3.13.15, Go 1.26.5, Docker 29.0.1 and Buildx 0.29.1. The GHCR package must be
public and grant this repository Actions write access. Protect `candidate-v*` and
`v*` against unauthorized changes; keep the existing `production` environment's
`v*` tag policy and its `AWS_REGION`, `CONTENT_BUCKET`,
`CLOUDFRONT_DISTRIBUTION_ID`, and `RECORD_PUBLISHER_ROLE_ARN` variables.
Only the reusable publisher receives OIDC permission; no AWS keys or extra
cross-repository write token are required.

Approval failure does not discard the image. Inspect the failure, fix its cause,
then rerun the approval workflow at the same candidate tag. If a merge races a
build or approval, finish those jobs and rerun the merge workflow. Promotion refuses
to roll back `latest` if `main` has since advanced. Superseded builds retain their
unique image/evidence but do not replace the rolling version tag. Registry writes
are serialized across publication and promotion.

Each GitHub Release includes `release-index-entry.json` for the releases service's
existing reviewed catalog-update process. Candidates carry `tags: ["rc"]` and
stay hidden; promotion generates `tags: ["release"]`. Merge the entry into
`site/docs/releases/attack_harness.json` in `intrusiveai-engineering/releases`,
preserving older entries and keeping `latest: true` only on the first entry, then
run `make site` and use its normal review/deployment workflow. Image approval is
automatic through the workflow above; website catalog submission remains separate.
