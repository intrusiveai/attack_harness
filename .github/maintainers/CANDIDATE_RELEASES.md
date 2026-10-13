# Release management

Use this guide to publish an Attack Harness candidate for Operator QA, then
promote the tested image to `latest`. These instructions are for maintainers;
they are not part of installing or running Attack Harness through Operator.

Complete the one-time setup before your first release. For later releases, start
at [Publish and qualify a candidate](#publish-and-qualify-a-candidate).

## One-time repository setup

Perform these steps in [`intrusiveai/attack_harness`](https://github.com/intrusiveai/attack_harness)
with repository administrator access. The releases service and its publisher role
must already exist; routine publication does not deploy infrastructure or the site.

### 1. Make the workflows available

1. Merge or push the release-workflow commits to the default branch, `main`.
2. In the **Code** tab, confirm that `main` contains
   `.github/workflows/verify.yml`, `.github/workflows/approve-candidate.yml`,
   `.github/workflows/publish-catalog.yml`, `build/publish_candidate.py`, and the
   complete `tools/release-publisher` directory.
3. Create candidate branches from a commit containing those files. Both dispatched
   publisher workflows and the bundle must exist on `main` and on the eventual
   release tag. For an existing candidate, merge the updated `main` into it and
   let the resulting push build a new candidate. Rerunning an old run uses its
   old workflow code; do not move an existing immutable tag to install updates.

### 2. Enable Actions, runners, and package access

1. Open **Settings → Actions → General** and enable Actions. If an allowlist is
   enforced, allow the pinned `actions/checkout`, `actions/setup-go`,
   `actions/upload-artifact`, and `aws-actions/configure-aws-credentials` actions.
   Use the exact SHAs in the three workflow files. The publishers run local code
   and need no exception for a private releases-repository workflow.
2. Provide native Linux runners with the labels `self-hosted`, `Linux`,
   `attack-harness-release`, and respectively `X64` or `ARM64`. Install
   Python 3.13.15, Go 1.26.5, Docker 29.0.1, and Buildx 0.29.1 on both.
   Confirm the runners are online under **Settings → Actions → Runners**.
3. Open the `attack_harness` package settings in GHCR. Make the package public
   and grant this repository Actions write access. Confirm that unauthenticated
   clients can inspect published image manifests; candidate admission checks
   public image identity and public build evidence.
4. Keep the automatic `GITHUB_TOKEN`; do not create a secret with that name.
   The workflows request Contents, Packages, and Actions write access for image
   publication/promotion. Publisher jobs request read access and `id-token: write`
   for temporary AWS credentials. Default workflow permissions can remain
   read-only. These workflows do not read a `RELEASE_TOKEN` secret.

### 3. Protect release sources and tags

1. Under **Settings → Rules → Rulesets**, review the rules for `main` and
   `candidate-v*`. Limit workflow changes and candidate pushes to trusted
   maintainers, while permitting direct candidate pushes if you use that path.
2. Review the rules for `v*` tags. Permit the publishing identity to create the
   unique candidate tags and final version tags; prevent unauthorized movement
   or deletion. Resolve any required creation bypass with the repository owner
   before attempting a release.
3. Keep candidate Git tags immutable. Each build creates a new tag such as
   `v1.2.3-candidate.123456.1`; promotion creates the separate final tag `v1.2.3`.
   Only the GHCR image tag `:v1.2.3` rolls forward during candidate development.
   Do not configure a process that moves candidate Git tags or replaces published
   release evidence.

### 4. Configure the production environment

1. Have the releases-service administrator verify the deployed trust policy for
   `arn:aws:iam::389547485478:role/releases-record-publisher`. It must accept this
   repository's numeric ID `1384026211`, owner ID `296295422`, the `production`
   environment, protected `v*` tags, audience `sts.amazonaws.com`, and the exact
   local workflow paths `approve-candidate.yml` and `publish-catalog.yml` under
   `.github/workflows/`. Step 5 supplies the matching custom subject.
   Retain the existing role and its catalog and create-only record permissions.
2. Open **Settings → Environments → production**, creating the environment if
   necessary. Under **Deployment branches and tags**, select **Selected branches
   and tags** and add a **Tag** rule for `v*`. After checking other consumers,
   remove any branch rules or other tag patterns. This is not a rule for the
   `candidate-v*` branches.
3. Retain required reviewer approval. Candidate record publication must be
   approvable before Operator QA; approving this deployment permits QA to begin
   and does not certify that QA passed.
4. Under **Environment variables**, add or verify each value below. These are
   variables, not secrets. Confirm the values against the deployed service.

   | Variable | Value |
   | --- | --- |
   | `AWS_REGION` | `us-west-2` |
   | `CONTENT_BUCKET` | `intrusiveai-releases` |
   | `CLOUDFRONT_DISTRIBUTION_ID` | `E1ET1MODBEJLY6` |
   | `CATALOG_PUBLISHER_ROLE_ARN` | `arn:aws:iam::389547485478:role/releases-record-publisher` |
   | `RECORD_PUBLISHER_ROLE_ARN` | `arn:aws:iam::389547485478:role/releases-record-publisher` |

Both publishers use the same existing role. Do not substitute another product's
role or add AWS access keys. The environment belongs to this product repository.

### 5. Set and verify the repository's OIDC subject

OIDC lets GitHub request temporary AWS credentials. AWS checks the subject to
identify the repository, environment, tag, and workflow file.

1. Inventory other jobs requesting OIDC and coordinate their cloud trust settings
   before changing the repository-wide subject:

   ```sh
   rg -n 'id-token:|environment:' .github/workflows
   ```

   Every OIDC job must declare an environment with this template. The checked-in
   workflows grant OIDC only to the two publishers.
2. Authenticate `gh` with repository administrator access. Read and retain the
   existing configuration with your change record:

   ```sh
   gh api repos/intrusiveai/attack_harness/actions/oidc/customization/sub
   ```

3. After the service administrator confirms the AWS trust from step 4, apply this
   template if it is not already configured:

   ```sh
   gh api --method PUT \
     repos/intrusiveai/attack_harness/actions/oidc/customization/sub \
     --input - <<'JSON'
   {"use_default":false,"include_claim_keys":["repository_id","repository_owner_id","environment","ref","workflow_ref"]}
   JSON
   ```

4. Repeat the GET command. Confirm `use_default` is `false` and all five keys
   appear in exactly that order. Ordinary jobs use `workflow_ref`, not
   `job_workflow_ref`. For each publishing workflow, AWS must accept this subject:

   ```text
   repository_id:1384026211:repository_owner_id:296295422:environment:production:ref:refs/tags/<TAG>:workflow_ref:intrusiveai/attack_harness/.github/workflows/<FILE>@refs/tags/<TAG>
   ```

   Replace `<FILE>` with `approve-candidate.yml` or `publish-catalog.yml`; both
   `<TAG>` positions contain the same `v*` tag. The subject binds the workflow
   path and ref, not its contents, so review workflow and publisher changes.
5. Follow the candidate procedure below to confirm a real OIDC exchange and
   public delivery. Passing local tests alone does not establish live readiness.

## Publish and qualify a candidate

### 1. Create or update the candidate branch

1. Choose an unused final version, for example `1.2.3`. Create
   `candidate-v1.2.3` in this repository from the intended source, including the
   release workflows. A SemVer prerelease suffix is allowed; build metadata is
   not. Do not reuse a version that already has its final `v1.2.3` tag.
2. Push the branch. Later direct pushes and merges into that branch also start
   a new build. A pull-request check alone does not publish a candidate.
3. Open **Actions → verify-candidate** and select the run for that exact branch
   head. Wait for both native platform jobs and image publication to succeed.
   The build runs source/contract and process tests, OCI inspection,
   SBOM/provenance checks, reproducibility comparison, and Operator stopped-image
   inspection. Runtime Operator campaigns and live provider/target tests follow
   publication as QA.

### 2. Approve and confirm candidate publication

1. Open the resulting GitHub **Pre-release**. Record its unique tag
   `v1.2.3-candidate.<run-id>.<attempt>`, source commit, and the image index digest
   in `candidate.json`. Confirm that the source is the candidate branch head
   you intend to test.
2. Open **Actions → approve candidate for Operator QA** and **Actions → publish
   release catalog**. Select the runs at that unique tag. When prompted, choose
   **Review deployments**, select `production`, and approve the deployments after
   reviewing the candidate's build evidence.
3. Wait for **both platform approval jobs and the catalog run** to succeed.
   The parent build dispatches these runs but does not wait for their completion.
   A green parent run or dispatch acknowledgement alone does not mean that
   Operator can admit the image or that the catalog has been updated.
4. Download `candidate.json` and `release-index-entry.json` from the prerelease.
   Confirm the [public catalog](https://releases.intrusive.ai/docs/releases/attack_harness.json)
   contains that unique candidate version with `tags: ["rc"]`, its unique GHCR
   tag, and the same index digest. It must remain absent from the stable listing
   on the [releases website](https://releases.intrusive.ai/).
5. For each platform in `candidate.json`, open
   `https://releases.intrusive.ai/sha256/<config-digest-without-sha256-prefix>`.
   Compare the response with that platform's `record`: it must contain the exact
   seven fields, in order, as compact JSON with one terminal newline. Use the
   platform config digest (`image_digest`), not its manifest or index digest.
   The publisher verifies the response bytes, JSON content type, immutable cache
   header, absence of content encoding, and a true unknown-digest 404.

The rolling image `ghcr.io/intrusiveai/attack_harness:v1.2.3` is convenient for QA
pulls. The unique candidate image tag and recorded index digest identify the exact
build even after another push changes the rolling tag. Approval records permit
Operator use; their seven-field format has no QA-only restriction or QA status.

### 3. Run QA against the published image

1. Run Operator QA against the recorded candidate image, covering the intended
   host/runtime and live provider/target scenarios. Retain the unique candidate
   tag, index/config digests, test results, and evidence links.
2. If a fix is needed, push it to the candidate branch. Repeat publication,
   approval, and QA for the replacement image. Do not claim the previous build's
   QA results qualify different bytes.
3. Open or update a pull request from the same repository's candidate branch to
   `main`. Put the actual QA results and evidence links in the PR description;
   promotion retains that description, PR URL, and merge commit.
4. If `main` has advanced, merge it into the candidate before the final QA pass.
   Let that push publish its candidate, and test the exact resulting image.
   Promotion requires the merged tree to equal the tested candidate's tree.

## Promote the qualified candidate

1. Confirm that the PR head is the source recorded in the tested candidate, both
   public approval records exist, and its catalog publication succeeded. Have
   the maintainer review the recorded QA evidence.
2. Merge the same-repository candidate PR into `main`. This merge is the QA
   sign-off. A direct local merge pushed to `main`, an ordinary `main` push, or
   closing a PR without merging it does not trigger promotion.
3. Open the merge's **verify-candidate** run and wait for promotion to succeed.
   It verifies source and tree identity and both public records, copies the exact
   OCI index to `:latest` without rebuilding, and creates the final GitHub Release
   at `v1.2.3`. The unique candidate prerelease remains as evidence.
4. Open the **publish release catalog** run at `v1.2.3`, approve its `production`
   deployment when prompted, and wait for success. This is a separate run from
   the candidate catalog publication.
5. Confirm the public catalog has a final `v1.2.3` entry with `tags: ["release"]`,
   image `ghcr.io/intrusiveai/attack_harness:v1.2.3`, and the tested index digest.
   Verify `:latest` resolves to that same digest, both approval records are
   unchanged, and older catalog entries remain. The unique candidate entry stays
   labeled `rc`; the final entry is separate.
6. Reload the releases website. The version is eligible for its stable listing,
   which displays the first two entries labeled exactly `release`. No site build
   or redeployment is needed. Use a new version for further candidate work;
   promotion freezes `v1.2.3` against later candidate writes.

## Recover from a failed publication

1. Open the failed job and identify whether the failure occurred during the
   build, GHCR publication, record admission, promotion, or catalog publication.
   Check the selected source/tag and fix the reported cause before retrying.
2. For a failed build or interrupted image publication, rerun the failed jobs
   in **verify-candidate**. If the fix changes source or workflow code, push the
   change to the candidate instead so a new run uses it. An older build keeps
   its unique evidence but cannot replace a newer branch head's rolling tag.
3. If the image exists but record or catalog publication failed, retry the
   affected publisher at the **same unique candidate tag**. For example, replace
   the example tag below with the tag from that build and run only the command
   for the failed publisher:

   ```sh
   gh workflow run approve-candidate.yml --repo intrusiveai/attack_harness \
     --ref v1.2.3-candidate.123456.1
   gh workflow run publish-catalog.yml --repo intrusiveai/attack_harness \
     --ref v1.2.3-candidate.123456.1
   ```

   These workflows derive their inputs from the published release; do not supply
   invented record JSON or qualification status. Approve the new deployment if
   prompted and wait for success. Identical record bytes are safe to retry. A
   conflicting record is immutable: stop and investigate; a compatibility change
   normally requires rebuilding to obtain a new config digest.
4. If a merge raced a build or admission, finish those runs and rerun the merge's
   failed promotion job. Promotion refuses to roll back `latest` once `main` has
   advanced; do not bypass that check or move an old tag to force a retry.
5. If promotion succeeded but the final catalog failed, retry only the catalog
   workflow at the final tag:

   ```sh
   gh workflow run publish-catalog.yml --repo intrusiveai/attack_harness --ref v1.2.3
   ```

   Wait for approval and successful public delivery, then repeat the final
   catalog checks above. Do not rebuild or replace the stable image.

The local catalog publisher merges one generated entry, preserves unrelated
history, and refuses final-image replacement or demotion. Never upload a full
catalog reconstructed from an old local copy. A failed approval does not discard
an already published image; a failed QA candidate stays outside the stable list.

## Verify locally and update the publisher

The reviewed bundle in `tools/release-publisher` comes from releases commit
`c651c5fa47346f1ca02abe33791667f838b59e03`. Its `publisher-source.json` records the
revision and per-file SHA-256 hashes. It includes both catalog and record code.

1. Install Go 1.26.5, Python 3, Bash, jq, and curl. From the repository root, run:

   ```sh
   python3 -m unittest discover -s build/tests -v
   cd tools/release-publisher
   export GOWORK=off GOPROXY=off GOTOOLCHAIN=local
   go test -race ./...
   go vet ./...
   python3 -m unittest discover -s scripts/tests -v
   ```

   These checks exercise candidate-to-final metadata continuity and publication
   using simulated GitHub, GHCR, S3, and local HTTP. They do not publish to AWS or
   prove a live OIDC exchange. Actual publication also requires AWS CLI v2 with
   conditional `put-object` support.
2. To independently verify a published platform record, save its expected canonical
   JSON from the build evidence and run from `tools/release-publisher`:

   ```sh
   go run ./cmd/release-publisher remote verify \
     --origin https://releases.intrusive.ai --record /absolute/path/record.json
   ```

3. For a publisher update, obtain a complete `attack_harness` export from an
   authorized releases maintainer at an explicitly reviewed commit. Require the
   provenance manifest; never use a `--working-tree` export or install just a
   shell script. Review the full diff, including deletions, and replace the old
   bundle with the complete export.
4. Adapt its workflow examples while retaining this repository's real build
   evidence and promotion checks. Keep execution product-local: no runtime
   checkout, reusable workflow call, or dependency fetch from the private releases
   repository. Preserve the offline Go settings shown above.
5. Run the local checks, review and commit the changes, and deliver them to `main`
   and the next candidate before its tag is created. Repeat the candidate
   publication checks to verify live authentication and public delivery.
