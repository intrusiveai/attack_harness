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
the completed build jobs and runs the local record publisher once per platform
using the public build evidence. It also dispatches `publish-catalog.yml`
to register that immutable candidate version with `tags: ["rc"]`, hidden from the
website. The rolling `:v1.2.3` image remains available for convenient QA pulls.
Approve the existing `production` environment deployments when prompted.
After it completes, Operator can admit the candidate by its exact config digest.
This is approval for QA use, not a claim that the full runtime acceptance matrix
has passed. The seven-field service record has no QA-only restriction.

Record actual QA results and evidence links in the candidate PR before merging it;
the merge is the maintainer's QA sign-off. The workflow retains the PR URL, merge
commit, and description with the promoted release, without claiming it ran QA.
Merging the same-repository candidate PR into `main` verifies its published source,
unchanged merge tree, and both public approval records, then copies that exact OCI
index to `:latest` without rebuilding. It creates `v1.2.3` as a stable GitHub Release
and freezes that version against later candidate writes. Merge `main` into the
candidate before releasing if needed to make their trees agree. Use a new version
for further development after promotion. Direct pushes to `main` only verify code.
Promotion also dispatches catalog publication at `v1.2.3`, with `tags: ["release"]`.
The catalog caller verifies that this final version retains the candidate's exact
image digest, platform records, and build evidence. Approval record bytes do not
change during promotion.

The workflow changes, including `approve-candidate.yml` and `publish-catalog.yml`,
must first exist on the default branch and selected tags so GitHub can dispatch
them. Native runners retain the existing
`self-hosted`, `Linux`, `attack-harness-release`, and `X64`/`ARM64` labels and need
Python 3.13.15, Go 1.26.5, Docker 29.0.1 and Buildx 0.29.1. The GHCR package must be
public and grant this repository Actions write access. Protect `candidate-v*` and
`v*` against unauthorized changes; keep the existing `production` environment's
`v*` tag policy. Configure the production variables and OIDC subject described
below before running these local publishers. Only the ordinary publishing jobs
receive OIDC permission; no AWS keys or cross-repository token are required.

Approval failure does not discard the image. Inspect the failure, fix its cause,
then rerun the approval workflow at the same candidate tag. If a merge races a
build or approval, finish those jobs and rerun the merge workflow. Promotion refuses
to roll back `latest` if `main` has since advanced. Superseded builds retain their
unique image/evidence but do not replace the rolling version tag. Registry writes
are serialized across publication and promotion.

Each GitHub Release includes `release-index-entry.json`, which the catalog caller
downloads and verifies against the public image before passing it to the local
publisher. That publisher merges one entry directly into the S3 catalog, preserves
history, and verifies public delivery. No releases-repository edit, PR, site build,
or site deployment is part of this release cycle. Unique candidate catalog versions
prevent a delayed candidate retry from replacing a newer candidate or final entry.

A dispatch acknowledgement means publication was requested, not completed. Follow
both the record and catalog workflows to successful completion. On a catalog
failure, inspect and fix the cause, then rerun `publish-catalog.yml` at the same Git
tag. Verify the entry in
`https://releases.intrusive.ai/docs/releases/attack_harness.json`: candidates stay
hidden on the website, while the first two entries labeled `release` are displayed.
The production environment approval for candidate admission does not certify QA;
merging the candidate PR after QA is the separate promotion decision.

## Local publisher and one-time configuration

Both publishing workflows check out only this repository and execute the complete
reviewed bundle in `tools/release-publisher`. Its `publisher-source.json` records
source revision `c651c5fa47346f1ca02abe33791667f838b59e03` and per-file SHA-256
hashes. Updates must replace the bundle from a reviewed commit export and review
the provenance and code diff. Never fetch the private releases repository at
workflow runtime or use a working-tree export. The bundle uses only the Go
standard library, with workspace, proxy, and automatic toolchain fetching disabled.

Both jobs run on protected `v*` tags in `production`. Candidate records pass
`prepare-record.sh` (canonical record, published OCI identity, public evidence)
before acquiring AWS credentials. Catalog entries pass local validation before
acquiring credentials. The existing source pipeline additionally verifies the
contents and provenance of build evidence. Publication checks S3 readback and
public delivery; records also probe a genuinely unknown digest for a 404.

Set these **production environment** variables:

| Variable | Value |
| --- | --- |
| `AWS_REGION` | `us-west-2` |
| `CONTENT_BUCKET` | `intrusiveai-releases` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `E1ET1MODBEJLY6` |
| `CATALOG_PUBLISHER_ROLE_ARN` | `arn:aws:iam::389547485478:role/releases-record-publisher` |
| `RECORD_PUBLISHER_ROLE_ARN` | `arn:aws:iam::389547485478:role/releases-record-publisher` |

After an authorized administrator verifies the deployed role's migration to local
workflow trust, configure the repository's custom OIDC subject with this exact
ordered template:

```json
{"use_default":false,"include_claim_keys":["repository_id","repository_owner_id","environment","ref","workflow_ref"]}
```

This changes every OIDC job in the repository; inventory other cloud consumers
before applying it. The current workflows grant OIDC only to the two publishers.
The resulting subject must be:

```text
repository_id:1384026211:repository_owner_id:296295422:environment:production:ref:refs/tags/<TAG>:workflow_ref:intrusiveai/attack_harness/.github/workflows/<FILE>@refs/tags/<TAG>
```

Both tag positions must start with `v`; the role must accept only
`approve-candidate.yml` and `publish-catalog.yml` at those exact workflow paths,
retain its numeric repository/owner, environment and tag conditions, and require
audience `sts.amazonaws.com`. Ordinary jobs use `workflow_ref`, not the reusable
workflow claim `job_workflow_ref`. Both jobs share this existing role's catalog
and record permissions. Local test success does not establish that this migration
has been deployed. No site redeployment or data reset is required.

Install these workflow changes on `main` before creating the next candidate tag;
do not move an existing immutable tag to install the new publisher. Old tags keep
their old workflows and cannot be assumed to work with migrated trust.

## Verification

CI runs the candidate lifecycle tests and the bundle's Go race tests, vet checks,
and shell publisher tests against simulated S3 and local HTTP. From the bundle:

```sh
export GOWORK=off GOPROXY=off GOTOOLCHAIN=local
go test -race ./...
go vet ./...
python3 -m unittest discover -s scripts/tests -v
```

These tests do not publish to AWS or prove a live GitHub OIDC exchange. For the
first real candidate, follow both tagged runs through successful completion;
verify both public records and the candidate catalog entry against the generated
release evidence. The candidate remains absent from the website. After QA and
promotion, verify the final entry and website visibility, unchanged image/config
digests and record bytes, and preservation of older catalog history. Probe each
downloaded canonical platform record with the local publisher:

```sh
go run ./cmd/release-publisher remote verify \
  --origin https://releases.intrusive.ai --record /absolute/path/record.json
```
