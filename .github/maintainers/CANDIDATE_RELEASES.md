# Release management

Use this guide to publish an Attack Harness candidate for Operator QA, then
promote the tested image to `latest`. These instructions are for maintainers;
they are not part of installing or running Attack Harness through Operator.

Complete the one-time setup before your first release. For later releases, start
at [Publish and qualify a candidate](#publish-and-qualify-a-candidate).

These workflows publish images and the website's release catalog. Compatibility
is verified locally from each image using the exact
[release contract and runtime pins](../../docs/INTEGRATION.md#locked-contract-and-runtime).
Catalog publication requires the production reviewer. The guest's execution,
assessment, and image bindings are described in the integration guide.

Create each new candidate from `main`. Source and publisher updates may travel
together on that candidate branch: publication runs the code at its immutable
release tag. The dispatchable catalog workflow must already exist on `main`
(see the one-time setup below). A code fix requires a new candidate run rather
than rerunning an old tagged workflow.

## One-time repository setup

Perform these steps in [`intrusiveai/attack_harness`](https://github.com/intrusiveai/attack_harness)
with repository administrator access. The releases service and its publisher role
must already exist; routine publication does not deploy infrastructure or the site.

### 1. Make the workflows available

1. Merge or push the release-workflow commits to the default branch, `main`.
2. In the **Code** tab, confirm that `main` contains
   `.github/workflows/verify.yml`, `.github/workflows/publish-catalog.yml`,
   `build/publish_candidate.py`, and the complete `tools/release-publisher` directory.
3. Create candidate branches from a commit containing those files. The catalog
   publisher workflow must exist on `main`; the eventual release tag must contain
   the workflow and complete bundle. Once set up, update them together with the
   source on a candidate branch. Rerunning an old run uses its old workflow code;
   do not move an existing immutable tag to install updates.

### 2. Enable Actions, runners, and package access

1. Open **Settings → Actions → General** and enable Actions. If an allowlist is
   enforced, allow the pinned `actions/checkout`, `actions/setup-go`,
   `actions/upload-artifact`, `actions/setup-python`, `docker/setup-docker-action`,
   `docker/setup-buildx-action`, and `aws-actions/configure-aws-credentials` actions.
   Use the exact SHAs in the two workflow files. The catalog publisher runs local
   code and needs no exception for a private releases-repository workflow.
2. Allow GitHub-hosted `ubuntu-24.04` (AMD64) and `ubuntu-24.04-arm` (ARM64)
   runners. Each native build installs Python 3.13.15, Go 1.26.5, Docker 29.0.1,
   and Buildx 0.29.1, then starts the digest-pinned BuildKit v0.25.2 image.
   No self-hosted runner registration or emulation is required; the setup actions
   use Node.js 24 and remove the temporary builder and Docker daemon after the job.
3. Open the `attack_harness` package settings in GHCR. Make the package public
   and grant this repository Actions write access. Confirm that unauthenticated
   clients can inspect published image manifests; catalog publication checks
   public image identity and public build evidence.
4. Keep the automatic `GITHUB_TOKEN`; do not create a secret with that name.
   The workflows request Contents, Packages, and Actions write access for image
   publication/promotion. The catalog job requests read access and `id-token: write`
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
   local workflow path `.github/workflows/publish-catalog.yml`.
   Step 5 supplies the matching custom subject. Retain the existing role for
   catalog publication; this workflow publishes catalog entries only.
2. Open **Settings → Environments → production**, creating the environment if
   necessary. Under **Deployment branches and tags**, select **Selected branches
   and tags** and add a **Tag** rule for `v*`. After checking other consumers,
   remove any branch rules or other tag patterns. This is not a rule for the
   `candidate-v*` branches.
3. Retain required reviewer approval for catalog publication. Approving a candidate
   catalog entry does not certify that QA passed.
4. Under **Environment variables**, add or verify each value below. These are
   variables, not secrets. Confirm the values against the deployed service.

   | Variable | Value |
   | --- | --- |
   | `AWS_REGION` | `us-west-2` |
   | `CONTENT_BUCKET` | `intrusiveai-releases` |
   | `CLOUDFRONT_DISTRIBUTION_ID` | `E1ET1MODBEJLY6` |
   | `CATALOG_PUBLISHER_ROLE_ARN` | `arn:aws:iam::389547485478:role/releases-record-publisher` |

Do not substitute another product's catalog role or add AWS access keys. The
environment belongs to this product repository.

### 5. Set and verify the repository's OIDC subject

OIDC lets GitHub request temporary AWS credentials. AWS checks the subject to
identify the repository, environment, tag, and workflow file.

1. Inventory other jobs requesting OIDC and coordinate their cloud trust settings
   before changing the repository-wide subject:

   ```sh
   rg -n 'id-token:|environment:' .github/workflows
   ```

   Every OIDC job must declare an environment with this template. The checked-in
   workflows grant OIDC only to the catalog publisher.
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
   `job_workflow_ref`. For catalog publication, AWS must accept this subject:

   ```text
   repository_id:1384026211:repository_owner_id:296295422:environment:production:ref:refs/tags/<TAG>:workflow_ref:intrusiveai/attack_harness/.github/workflows/<FILE>@refs/tags/<TAG>
   ```

   Replace `<FILE>` with `publish-catalog.yml`; both `<TAG>` positions contain
   the same `v*` tag. The subject binds the workflow
   path and ref, not its contents, so review workflow and publisher changes.
5. Follow the candidate procedure below to confirm a real OIDC exchange and
   public delivery. Passing local tests alone does not establish live readiness.

## Verify local compatibility before publication

1. Check out Operator commit `dc2f1c40a3e6c3c88209e5f393493e6a627fc03f`
   in a separate clean directory. This is the immutable contract source in
   `build/contract-lock.json`; its package is `0.3.0`, digest
   `sha256:1ec7a4c0d8d5e4783c6f2bf5c473d3722c47dd193922b4c63feb1e0a0aac7502`.
   Move any older generated `build/context/contracts` aside before rebuilding.
2. Check out matching Operator runtime commit
   `e4de591a40ce25a9a37d310ff24e43374337ac15` in a second directory for integration
   and stopped-image inspection. Its shared contracts/schemas are unchanged from
   the package source; its database integration verifies snapshot backup evidence
   and exercises live oracle feedback through the Python Harness. CI builds the
   package first, then checks out this runtime revision in its Operator directory.
   `build/operator-runtime-commit.txt` is the shared runtime pin for CI checkout,
   local integration tests, and publication's inspection-report check. When
   updating Operator, change that pin; keep the contract source lock tied to the
   exact package bytes. The two revisions may differ only while their shared
   contracts/schemas remain identical, as verified by the integration gate.
   Install the locked dependencies, verify the package, and run the tests:

   ```sh
   python3 -m venv .ci-venv
   .ci-venv/bin/python -m pip install --require-hashes --only-binary=:all: --no-deps -r requirements-runtime.lock
   make verify-contracts OPERATOR_ROOT=/path/to/pinned/operator PYTHON=.ci-venv/bin/python
   make test OPERATOR_ROOT=/path/to/pinned/operator PYTHON=.ci-venv/bin/python
   make test-integration OPERATOR_ROOT=/path/to/matching/operator PYTHON=.ci-venv/bin/python
   python3 -m unittest discover -s build/tests -v
   ```

   `make test-integration` runs Operator's authoritative explicit-origin and
   corrected-finish fixtures, plus Harness's additional workflow and exit tests
   through a test-only overlay. Production Harness processes over FIFO/spool
   verify correction without duplicate dispatch, observation inspection, accepted
   finish, exit 0, cleanup and report/export attribution. The overlay does not
   replace Operator's tests or modify runtime/contract bytes. Controlled responses
   do not establish live-model reliability or native container qualification.

   In the matching Operator runtime checkout, run `go test ./contracts ./internal/imagerelease
   ./internal/dockercontrol ./cmd/operatorctl`. Run its shared Python fixtures with
   `PYTHONPATH=contracts/python /path/to/harness/.ci-venv/bin/python -m unittest
   discover -s contracts/python/tests -v`.

3. Build and inspect each platform with the pinned BuildKit configuration from
   `verify.yml`. Repeat the build, saving the first build report, and run
   `build/compare_builds.py` as CI does:

   ```sh
   make image PLATFORM=linux/arm64 OPERATOR_ROOT=/path/to/pinned/operator PYTHON=.ci-venv/bin/python
   make inspect-stopped-image PLATFORM=linux/arm64 OPERATOR_ROOT=/path/to/matching/operator PYTHON=.ci-venv/bin/python
   ```

   Repeat for `linux/amd64`. Prefer native hosts. For local file inspection on a
   different architecture, explicitly set
   `INSPECTION_FLAGS=--allow-cross-platform-inspection`; this records a non-native
   check and does not qualify runtime execution or satisfy native CI evidence.
4. Confirm each build report identifies the exact embedded compatibility bytes
   and raw digest separately from the OCI config, manifest and index. The stopped
   check uses the pinned Operator's real reader with external HTTP disabled, verifies
   all five fixed files, and confirms inspection-container removal. It records the
   independently resolved Docker image ID separately: containerd-backed Docker can
   expose a manifest-based ID while classic Docker exposes the config ID.
5. Run Operator's process integration suite with this Harness checkout (see its
   [process integration guide](https://github.com/intrusiveai/operator_sandbox/blob/e4de591a40ce25a9a37d310ff24e43374337ac15/docs/PROCESS_INTEGRATION.md)). Check frozen startup, attempt-generator and
   conclusion bindings. The release digest hashes the exact compatibility bytes,
   not normalized JSON. Record fixture/cross-platform results separately from
   native runtime and live-provider QA; neither latter activity blocks candidate
   publication.

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

### 2. Approve and confirm catalog publication

1. Open the resulting GitHub **Pre-release**. Record its unique tag
   `v1.2.3-candidate.<run-id>.<attempt>`, source commit, and the image index digest
   in `candidate.json`. Confirm that the source is the candidate branch head
   you intend to test.
2. Open **Actions → publish release catalog** and select the run at that unique
   tag. When prompted, choose **Review deployments**, select `production`, and
   approve the deployment after reviewing the candidate's build evidence.
3. Wait for the **catalog run** to succeed. It verifies the candidate's source,
   successful native build jobs, published image digest, and shared contract
   identity retained from both platform images. The parent build
   dispatches this run but does not wait for completion; a green parent run alone
   does not mean that the catalog has been updated.
4. Download `candidate.json` and `release-index-entry.json` from the prerelease.
   Confirm the [public catalog](https://releases.intrusive.ai/docs/releases/attack_harness.json)
   contains that unique candidate version with `tags: ["rc"]`, its unique GHCR
   tag, and the same index digest. Confirm `contract_package_version` equals the
   package version in both platform build reports and embedded compatibility
   files (`0.3.0` for the current contract). It must remain absent from the stable
   listing on the [releases website](https://releases.intrusive.ai/).

The rolling image `ghcr.io/intrusiveai/attack_harness:v1.2.3` is convenient for QA
pulls. The unique candidate image tag and recorded index digest identify the exact
build even after another push changes the rolling tag. Catalog entries retain
image digests to identify the published bytes; they are not compatibility records.

### 3. Run QA against the published image

1. Run Operator QA against the recorded candidate image, covering the intended
   host/runtime and live provider/target scenarios. Retain the unique candidate
   tag, index/config digests, test results, and evidence links.
2. If a fix is needed, push it to the candidate branch. Repeat publication,
   catalog approval, and QA for the replacement image. Do not claim the previous
   build's QA results qualify different bytes.
3. Open or update a pull request from the same repository's candidate branch to
   `main`. Put the actual QA results and evidence links in the PR description;
   promotion retains that description, PR URL, and merge commit.
4. If `main` has advanced, merge it into the candidate before the final QA pass.
   Let that push publish its candidate, and test the exact resulting image.
   Promotion requires the merged tree to equal the tested candidate's tree.

## Promote the qualified candidate

1. Confirm that the PR head is the source recorded in the tested candidate and
   its catalog publication succeeded. Have the maintainer review the recorded
   QA evidence.
2. Merge the same-repository candidate PR into `main`. This merge is the QA
   sign-off. A direct local merge pushed to `main`, an ordinary `main` push, or
   closing a PR without merging it does not trigger promotion.
3. Open the merge's **verify-candidate** run and wait for promotion to succeed.
   It verifies source and tree identity and successful build jobs, copies the exact
   OCI index to `:latest` without rebuilding, and creates the final GitHub Release
   at `v1.2.3`. The unique candidate prerelease remains as evidence.
4. Open the **publish release catalog** run at `v1.2.3`, approve its `production`
   deployment when prompted, and wait for success. This is a separate run from
   the candidate catalog publication.
5. Confirm the public catalog has a final `v1.2.3` entry with `tags: ["release"]`,
   image `ghcr.io/intrusiveai/attack_harness:v1.2.3`, the tested index digest,
   and the candidate's unchanged `contract_package_version`.
   Verify `:latest` resolves to that same digest and older catalog entries remain.
   The unique candidate entry stays labeled `rc`; the final entry is separate.
6. Reload the releases website. The version is eligible for its stable listing,
   which displays the first two entries labeled exactly `release`. Confirm its
   **Shared contract: 0.3.0** indicator matches the promoted package version.
   No site build or redeployment is needed. Use a new version for further candidate
   work; promotion freezes `v1.2.3` against later candidate writes.

## Recover from a failed publication

1. Open the failed job and identify whether the failure occurred during the
   build, GHCR publication, promotion, or catalog publication.
   Check the selected source/tag and fix the reported cause before retrying.
2. For a failed build or interrupted image publication, rerun the failed jobs
   in **verify-candidate**. If the fix changes source or workflow code, push the
   change to the candidate instead so a new run uses it. An older build keeps
   its unique evidence but cannot replace a newer branch head's rolling tag.
3. If the image exists but catalog publication failed, retry the catalog publisher
   at the **same unique candidate tag**. Replace the example tag below with the
   tag from that build:

   ```sh
   gh workflow run publish-catalog.yml --repo intrusiveai/attack_harness \
     --ref v1.2.3-candidate.123456.1
   ```

   The workflow derives its entry from the published release. Approve the new
   deployment if prompted and wait for success. If the failure requires a newer
   publisher (for example, to recognize a catalog field), a retry at the old tag
   cannot install that fix. Publish a new candidate containing the updated bundle.
4. If a merge raced a build or publication, finish those runs and rerun the merge's
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
catalog reconstructed from an old local copy. A failed catalog publication does
not discard an already published image; a failed QA candidate stays outside the
stable list.

## Verify locally and update the publisher

The reviewed bundle in `tools/release-publisher` comes from releases commit
`0a88c3564b5266581dc94d3f1ce71880cac2376a`. Its `publisher-source.json` records the
upstream revision and per-file SHA-256 hashes. Its `local_overrides` section
records the catalog-only documentation adjustment. Executable publisher files
retain their upstream identities; this repository invokes only catalog publication.

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
2. For a publisher update, obtain a complete `attack_harness` export from an
   authorized releases maintainer at an explicitly reviewed commit. Require the
   provenance manifest; never use a `--working-tree` export or install just a
   shell script. Review the full diff, including deletions, and replace the old
   bundle with the complete export.
3. Adapt its catalog workflow example while retaining this repository's real build
   evidence and promotion checks. Keep execution product-local: no runtime
   checkout, reusable workflow call, or dependency fetch from the private releases
   repository. Preserve the offline Go settings shown above.
4. Run the local checks, review and commit the changes on the candidate before
   its tag is created. Promotion merges that candidate into `main`. Repeat the
   candidate publication checks to verify live authentication and public delivery.
