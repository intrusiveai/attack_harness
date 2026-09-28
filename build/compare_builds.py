"""Compare two OCI build reports without conflating attestations with runtime bytes."""

import argparse
import json
from pathlib import Path


RUNTIME_KEYS = ("image_digest", "manifest_digest", "layer_digests")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    first, second = (json.loads(path.read_bytes()) for path in (args.first,args.second))
    if first["platform"] != second["platform"] or first["contract"] != second["contract"]:
        raise SystemExit("build comparison inputs differ")
    comparisons = {key:first["oci"][key] == second["oci"][key]
                   for key in RUNTIME_KEYS}
    if not all(comparisons.values()):
        raise SystemExit("runtime OCI payload is not reproducible")
    result={
        "api_version":"intrusive.ai/attack-harness-rebuild-comparison/v1alpha1",
        "platform":first["platform"],"runtime_identity":"identical",
        "runtime_comparisons":comparisons,
        "attestation_envelope_identical":first["oci"]["attestation_manifest_digest"] ==
            second["oci"]["attestation_manifest_digest"],
        "archive_identical":first["archive"]["digest"] == second["archive"]["digest"],
        "note":"Attestation statements may contain build-session metadata; release identity is the stable image config digest.",
    }
    args.output.write_bytes(json.dumps(result,sort_keys=True,separators=(",",":")).encode())
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":main()
