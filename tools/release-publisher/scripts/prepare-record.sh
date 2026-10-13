#!/usr/bin/env bash
set -euo pipefail

# Validate built candidates before AWS credentials are acquired. Operator QA runs
# after publication; qualification status and website labels are not record fields.
record_file="${1:?usage: prepare-record.sh RECORD_FILE}"
record_body="${RECORD_JSON:?RECORD_JSON is required}"
while [[ "$record_body" == *$'\n' ]]; do record_body="${record_body%$'\n'}"; done
printf '%s\n' "$record_body" > "$record_file"
go run ./cmd/release-publisher record validate --file "$record_file"
jq -e --arg digest "$IMAGE_CONFIG_DIGEST" --arg platform "$PLATFORM" \
  '.image_digest == $digest and .platform == $platform' "$record_file" >/dev/null

case "$IMAGE_REFERENCE" in
  ghcr.io/intrusiveai/attack_harness:*) ;;
  *) echo "image reference must name the canonical Attack Harness package" >&2; exit 1 ;;
esac
go run ./cmd/release-publisher image verify \
  --reference "$IMAGE_REFERENCE" \
  --platform "$PLATFORM" \
  --manifest-digest "$PLATFORM_MANIFEST_DIGEST" \
  --config-digest "$IMAGE_CONFIG_DIGEST" \
  --index-digest "${INDEX_DIGEST:-}"

case "${EVIDENCE_URL:-}" in
  https://github.com/intrusiveai/attack_harness/*) ;;
  *) echo "build evidence must be public in intrusiveai/attack_harness" >&2; exit 1 ;;
esac
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "source commit must be a full lowercase Git commit ID" >&2
  exit 1
fi
curl --fail --silent --show-error --location --max-time 20 --output /dev/null "$EVIDENCE_URL"
