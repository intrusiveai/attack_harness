# Attack Harness catalog publisher

Attack Harness uses this product-local publisher to update its image release
catalog. The active entrypoint is `scripts/publish-catalog.sh`, called by the
repository's `.github/workflows/publish-catalog.yml`. Image compatibility is
embedded in the Harness image and checked by Operator; it is not published as an
external approval record.

`../publisher-source.json` records the reviewed upstream revision and file hashes.
Its `local_overrides` section records changes to imported documentation separately
from that source. Publisher executables retain their upstream bytes. The active
workflow and the [maintainer guide](../../../.github/maintainers/CANDIDATE_RELEASES.md)
define this product's setup and publication procedure.

## Dependencies and local verification

The publisher uses Bash, Go 1.26.5, AWS CLI v2 with conditional `put-object` support,
jq, curl, Python 3 for tests, and standard shell tools. Go packages use only the
standard library. There is no runtime dependency on a private releases checkout.

From `tools/release-publisher`:

```sh
export GOWORK=off GOPROXY=off GOTOOLCHAIN=local
go test -race ./...
go vet ./...
python3 -m unittest discover -s scripts/tests -v
```

The tests exercise local publication and validation with simulated services. They
do not write to AWS. The bundle contains only the catalog publisher; deployment
uses the catalog workflow and command below.

## Catalog publication

Run `.github/workflows/publish-catalog.yml` at the protected `v*` tag for the
published candidate or final release, in this repository's `production`
environment. The workflow derives and validates its catalog entry from actual
release artifacts before assuming the configured AWS role.

Required variables are `AWS_REGION`, `CONTENT_BUCKET`,
`CLOUDFRONT_DISTRIBUTION_ID`, and `CATALOG_PUBLISHER_ROLE_ARN`. The OIDC subject keys,
in order, are `repository_id`, `repository_owner_id`, `environment`, `ref`, and
`workflow_ref`; the role audience is `sts.amazonaws.com`.

With the authorized temporary credentials and a validated entry, the workflow
invokes this command from `tools/release-publisher`:

```sh
bash scripts/publish-catalog.sh /absolute/path/release-index-entry.json attack_harness
```

Candidates use `tags: ["rc"]`; final releases use `tags: ["release"]`. An entry
binds a versioned GHCR image reference, its exact OCI index digest, and
`contract_package_version`. The product generator reads the shared package version
from both verified platform images and rejects disagreement. Use exact
`major.minor.patch` without a `v` prefix, leading zeroes, suffix, or whitespace
(128-character maximum). The product version and a later source checkout's lock
are not substitutes for the shipped identity.

New versions prepend, updates keep their position, and unrelated history remains. Final
entries cannot change image or contract identity or lose the release label. A
rebuilt candidate may change contract version only with changed artifact identity.
The product's promotion workflow preserves the qualified candidate bytes and
retained contract identity when creating the final version. Historical entries
without the field remain readable; missing versions must not be guessed from the
current source. The site displays the shared contract version for final releases.

Conditional writes and bounded re-read/re-merge retries protect concurrent
updates. The publisher checks S3 bytes and headers, invalidates the catalog path,
and verifies public delivery. Routine publication does not require a site build,
infrastructure deployment, or manual full-catalog replacement.
