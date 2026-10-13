package record

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
	"unicode/utf8"
)

const (
	APIVersion = "intrusive.ai/engine-release/v1alpha1"
	MaxBytes   = 64 << 10
	MaxDepth   = 32
)

var (
	digestPattern = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	numeric       = regexp.MustCompile(`^(0|[1-9][0-9]*)$`)
	identifier    = regexp.MustCompile(`^[0-9A-Za-z-]+$`)
	digits        = regexp.MustCompile(`^[0-9]+$`)
)

type Record struct {
	APIVersion             string `json:"api_version"`
	ImageDigest            string `json:"image_digest"`
	MinimumOperatorVersion string `json:"minimum_operator_version"`
	ContractPackageVersion string `json:"contract_package_version"`
	ContractPackageDigest  string `json:"contract_package_digest"`
	RuntimeProfile         string `json:"runtime_profile"`
	Platform               string `json:"platform"`
}

func Parse(raw []byte) (Record, error) {
	var out Record
	if len(raw) == 0 || len(raw) > MaxBytes {
		return out, fmt.Errorf("record size must be between 1 and %d bytes", MaxBytes)
	}
	if !utf8.Valid(raw) {
		return out, errors.New("record must be valid UTF-8")
	}
	if err := validateJSON(raw); err != nil {
		return out, err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&out); err != nil {
		return Record{}, fmt.Errorf("decode record: %w", err)
	}
	if err := requireEOF(decoder); err != nil {
		return Record{}, err
	}
	if err := out.Validate(); err != nil {
		return Record{}, err
	}
	canonical, err := out.Bytes()
	if err != nil {
		return Record{}, err
	}
	if !bytes.Equal(raw, canonical) {
		return Record{}, errors.New("record must use deterministic compact JSON with one terminal newline")
	}
	return out, nil
}

func (r Record) Validate() error {
	if r.APIVersion != APIVersion {
		return fmt.Errorf("api_version must be %q", APIVersion)
	}
	if !digestPattern.MatchString(r.ImageDigest) {
		return errors.New("image_digest must be a full lowercase SHA-256 digest")
	}
	if !digestPattern.MatchString(r.ContractPackageDigest) {
		return errors.New("contract_package_digest must be a full lowercase SHA-256 digest")
	}
	minimum, ok := parseVersion(r.MinimumOperatorVersion)
	if !ok || minimum.prerelease != "" || minimum.build != "" {
		return errors.New("minimum_operator_version must be stable SemVer without build metadata")
	}
	if _, ok := parseVersion(r.ContractPackageVersion); !ok {
		return errors.New("contract_package_version must be valid SemVer")
	}
	if r.RuntimeProfile != "operator-container/v1" {
		return errors.New("runtime_profile must be operator-container/v1")
	}
	if r.Platform != "linux/amd64" && r.Platform != "linux/arm64" {
		return errors.New("platform must be linux/amd64 or linux/arm64")
	}
	return nil
}

func (r Record) Bytes() ([]byte, error) {
	if err := r.Validate(); err != nil {
		return nil, err
	}
	raw, err := json.Marshal(r)
	if err != nil {
		return nil, fmt.Errorf("encode record: %w", err)
	}
	return append(raw, '\n'), nil
}

func (r Record) Hex() string { return strings.TrimPrefix(r.ImageDigest, "sha256:") }

type semver struct{ prerelease, build string }

func parseVersion(value string) (semver, bool) {
	if value == "" || len(value) > 128 {
		return semver{}, false
	}
	base, build, hasBuild := strings.Cut(value, "+")
	if hasBuild {
		if build == "" || strings.Contains(build, "+") || !validIdentifiers(build, false) {
			return semver{}, false
		}
	}
	base, pre, hasPre := strings.Cut(base, "-")
	if hasPre {
		if pre == "" || !validIdentifiers(pre, true) {
			return semver{}, false
		}
	}
	core := strings.Split(base, ".")
	if len(core) != 3 {
		return semver{}, false
	}
	for _, part := range core {
		if !numeric.MatchString(part) {
			return semver{}, false
		}
	}
	return semver{prerelease: pre, build: build}, true
}

func validIdentifiers(value string, rejectLeadingZero bool) bool {
	for _, part := range strings.Split(value, ".") {
		if !identifier.MatchString(part) || (rejectLeadingZero && digits.MatchString(part) && len(part) > 1 && part[0] == '0') {
			return false
		}
	}
	return true
}

func requireEOF(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("record contains trailing JSON content")
	}
	return nil
}

func validateJSON(raw []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := walkValue(decoder, 1); err != nil {
		return err
	}
	if err := requireEOF(decoder); err != nil {
		return err
	}
	return nil
}

func walkValue(decoder *json.Decoder, depth int) error {
	if depth > MaxDepth {
		return fmt.Errorf("JSON nesting exceeds %d levels", MaxDepth)
	}
	token, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("invalid JSON: %w", err)
	}
	delim, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delim {
	case '{':
		seen := make(map[string]struct{})
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return fmt.Errorf("invalid object key: %w", err)
			}
			key, ok := keyToken.(string)
			if !ok {
				return errors.New("object key must be a string")
			}
			if _, duplicate := seen[key]; duplicate {
				return fmt.Errorf("duplicate JSON field %q", key)
			}
			seen[key] = struct{}{}
			if err := walkValue(decoder, depth+1); err != nil {
				return err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim('}') {
			return errors.New("invalid JSON object")
		}
	case '[':
		for decoder.More() {
			if err := walkValue(decoder, depth+1); err != nil {
				return err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim(']') {
			return errors.New("invalid JSON array")
		}
	default:
		return errors.New("invalid JSON delimiter")
	}
	return nil
}
