package record

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

const imageHex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func validRecord(platform string) Record {
	return Record{
		APIVersion:             APIVersion,
		ImageDigest:            "sha256:" + imageHex,
		MinimumOperatorVersion: "0.1.0",
		ContractPackageVersion: "0.1.0",
		ContractPackageDigest:  "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
		RuntimeProfile:         "operator-container/v1",
		Platform:               platform,
	}
}

func TestRoundTripPlatforms(t *testing.T) {
	for _, platform := range []string{"linux/amd64", "linux/arm64"} {
		raw, err := validRecord(platform).Bytes()
		if err != nil {
			t.Fatal(err)
		}
		parsed, err := Parse(raw)
		if err != nil || parsed.Platform != platform || parsed.Hex() != imageHex {
			t.Fatalf("Parse() = %#v, %v", parsed, err)
		}
	}
}

func TestGoldenFixtures(t *testing.T) {
	for _, name := range []string{"valid-amd64.json", "valid-arm64.json"} {
		raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "records", name))
		if err != nil {
			t.Fatal(err)
		}
		if _, err := Parse(raw); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
	}
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "records", "invalid-unknown-field.json"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Parse(raw); err == nil {
		t.Fatal("invalid fixture was accepted")
	}
}

func TestRejectsMalformedRecords(t *testing.T) {
	raw, _ := validRecord("linux/amd64").Bytes()
	cases := map[string][]byte{
		"pretty":         bytes.ReplaceAll(raw, []byte(":"), []byte(": ")),
		"no newline":     bytes.TrimSuffix(raw, []byte("\n")),
		"unknown":        bytes.Replace(raw, []byte("{\"api_version\""), []byte("{\"unknown\":1,\"api_version\""), 1),
		"duplicate":      bytes.Replace(raw, []byte("{\"api_version\""), []byte("{\"api_version\":\"intrusive.ai/engine-release/v1alpha1\",\"api_version\""), 1),
		"trailing":       append(append([]byte(nil), raw...), []byte("{}")...),
		"invalid utf8":   []byte("{\xff}"),
		"array":          []byte("[]\n"),
		"uppercase hash": bytes.Replace(raw, []byte("abcdef"), []byte("ABCDEF"), 1),
	}
	for name, input := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Parse(input); err == nil {
				t.Fatalf("accepted %q", input)
			}
		})
	}
}

func TestSemverAndFields(t *testing.T) {
	cases := []func(*Record){
		func(r *Record) { r.MinimumOperatorVersion = "0.1.0-rc.1" },
		func(r *Record) { r.MinimumOperatorVersion = "0.1.0+build" },
		func(r *Record) { r.ContractPackageVersion = "01.0.0" },
		func(r *Record) { r.Platform = "darwin/arm64" },
		func(r *Record) { r.RuntimeProfile = "other" },
		func(r *Record) { r.ImageDigest = "sha256:1234" },
	}
	for i, alter := range cases {
		release := validRecord("linux/amd64")
		alter(&release)
		if err := release.Validate(); err == nil {
			t.Fatalf("case %d accepted", i)
		}
	}
}
