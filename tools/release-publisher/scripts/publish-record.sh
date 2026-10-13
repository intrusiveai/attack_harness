#!/usr/bin/env bash
set -euo pipefail

: "${CONTENT_BUCKET:?CONTENT_BUCKET is required}"
: "${CLOUDFRONT_DISTRIBUTION_ID:?CLOUDFRONT_DISTRIBUTION_ID is required}"
: "${RELEASE_ORIGIN:=https://releases.intrusive.ai}"

record_file="${1:?usage: publish-record.sh RECORD_FILE}"
go run ./cmd/release-publisher record validate --file "$record_file"
image_digest="$(jq -er '.image_digest' "$record_file")"
image_hex="${image_digest#sha256:}"
key="sha256/$image_hex"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if ! aws s3api put-object \
  --bucket "$CONTENT_BUCKET" \
  --key "$key" \
  --body "$record_file" \
  --content-type application/json \
  --cache-control 'public,max-age=31536000,immutable' \
  --checksum-algorithm SHA256 \
  --if-none-match '*' >"$work/result.json" 2>"$work/error.txt"; then
  if ! grep -q 'PreconditionFailed' "$work/error.txt"; then
    sed -E 's/(access_key|secret|token)[^ ]*/[redacted]/Ig' "$work/error.txt" >&2
    exit 1
  fi
  aws s3api get-object --bucket "$CONTENT_BUCKET" --key "$key" "$work/existing" >/dev/null
  if ! cmp -s "$record_file" "$work/existing"; then
    echo "immutable conflict: $key already contains different bytes" >&2
    exit 1
  fi
  echo "record already exists with identical bytes: $key"
else
  jq -e '.ChecksumSHA256 and .VersionId' "$work/result.json" >/dev/null
  aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" --paths "/$key" >/dev/null
fi

aws s3api get-object --bucket "$CONTENT_BUCKET" --key "$key" "$work/readback" >/dev/null
cmp "$record_file" "$work/readback"
metadata="$(aws s3api head-object --bucket "$CONTENT_BUCKET" --key "$key")"
jq -e '.ContentType == "application/json" and .CacheControl == "public,max-age=31536000,immutable" and (.ContentEncoding == null)' <<<"$metadata" >/dev/null
go run ./cmd/release-publisher remote verify --origin "$RELEASE_ORIGIN" --record "$record_file"
