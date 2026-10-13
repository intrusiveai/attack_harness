package oci

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

const maxResponseBytes = 8 << 20

var (
	referencePattern = regexp.MustCompile(`^ghcr\.io/([a-z0-9._-]+/[a-z0-9._-]+):([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})$`)
	digestPattern    = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
)

type Verifier struct {
	Client      *http.Client
	RegistryURL string
}

type indexDocument struct {
	MediaType string `json:"mediaType"`
	Manifests []struct {
		Digest   string `json:"digest"`
		Platform struct {
			OS           string `json:"os"`
			Architecture string `json:"architecture"`
		} `json:"platform"`
	} `json:"manifests"`
	Config struct {
		Digest string `json:"digest"`
	} `json:"config"`
}

type imageConfig struct {
	Config struct {
		Labels map[string]string `json:"Labels"`
	} `json:"config"`
}

func (v Verifier) Verify(ctx context.Context, reference, platform, manifestDigest, configDigest, indexDigest, source string) error {
	match := referencePattern.FindStringSubmatch(reference)
	if match == nil {
		return errors.New("image reference must be a tagged ghcr.io/<owner>/<package>:<tag> reference")
	}
	if !validDigest(manifestDigest) || !validDigest(configDigest) || (indexDigest != "" && !validDigest(indexDigest)) {
		return errors.New("manifest, config, and optional index digests must be full lowercase SHA-256 digests")
	}
	parts := strings.Split(platform, "/")
	if len(parts) != 2 || parts[0] != "linux" || (parts[1] != "amd64" && parts[1] != "arm64") {
		return errors.New("platform must be linux/amd64 or linux/arm64")
	}
	if source == "" {
		return errors.New("expected OCI source URL is required")
	}
	base := v.RegistryURL
	if base == "" {
		base = "https://ghcr.io"
	}
	client := v.Client
	if client == nil {
		client = &http.Client{Timeout: 15 * time.Second}
	}
	token := ""
	root, rootHeaderDigest, nextToken, err := v.fetch(ctx, client, base, match[1], "manifests/"+match[2], token, manifestAccept)
	if err != nil {
		return fmt.Errorf("fetch tagged manifest: %w", err)
	}
	token = nextToken
	rootDigest := digestBytes(root)
	if rootHeaderDigest != "" && rootHeaderDigest != rootDigest {
		return errors.New("registry root digest header does not match returned bytes")
	}
	var document indexDocument
	if err := json.Unmarshal(root, &document); err != nil {
		return fmt.Errorf("decode tagged manifest: %w", err)
	}
	selectedDigest := rootDigest
	if len(document.Manifests) > 0 {
		if indexDigest == "" || rootDigest != indexDigest {
			return errors.New("tag resolved to an OCI index that does not match the supplied index digest")
		}
		selectedDigest = ""
		for _, candidate := range document.Manifests {
			if candidate.Platform.OS == parts[0] && candidate.Platform.Architecture == parts[1] {
				if selectedDigest != "" {
					return errors.New("OCI index contains multiple manifests for the requested platform")
				}
				selectedDigest = candidate.Digest
			}
		}
		if selectedDigest == "" {
			return errors.New("OCI index does not contain the requested platform")
		}
	} else if indexDigest != "" {
		return errors.New("an index digest was supplied but the tag resolved to a single manifest")
	}
	if selectedDigest != manifestDigest {
		return errors.New("resolved platform manifest digest does not match supplied digest")
	}

	manifest, headerDigest, nextToken, err := v.fetch(ctx, client, base, match[1], "manifests/"+manifestDigest, token, manifestAccept)
	if err != nil {
		return fmt.Errorf("fetch platform manifest: %w", err)
	}
	token = nextToken
	if digestBytes(manifest) != manifestDigest || (headerDigest != "" && headerDigest != manifestDigest) {
		return errors.New("platform manifest digest does not match returned bytes")
	}
	var platformDocument indexDocument
	if err := json.Unmarshal(manifest, &platformDocument); err != nil {
		return fmt.Errorf("decode platform manifest: %w", err)
	}
	if platformDocument.Config.Digest != configDigest {
		return errors.New("platform manifest config digest does not match supplied image config digest")
	}

	configRaw, _, _, err := v.fetch(ctx, client, base, match[1], "blobs/"+configDigest, token, "application/octet-stream")
	if err != nil {
		return fmt.Errorf("fetch image config: %w", err)
	}
	if digestBytes(configRaw) != configDigest {
		return errors.New("image config digest does not match returned bytes")
	}
	var config imageConfig
	if err := json.Unmarshal(configRaw, &config); err != nil {
		return fmt.Errorf("decode image config: %w", err)
	}
	if config.Config.Labels["org.opencontainers.image.source"] != source {
		return errors.New("image config OCI source label does not match expected repository")
	}
	return nil
}

const manifestAccept = "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json"

func (v Verifier) fetch(ctx context.Context, client *http.Client, base, repository, resource, token, accept string) ([]byte, string, string, error) {
	target := strings.TrimRight(base, "/") + "/v2/" + repository + "/" + resource
	response, err := doRequest(ctx, client, target, accept, token)
	if err != nil {
		return nil, "", token, err
	}
	if response.StatusCode == http.StatusUnauthorized && token == "" {
		challenge := response.Header.Get("WWW-Authenticate")
		response.Body.Close()
		token, err = anonymousToken(ctx, client, challenge)
		if err != nil {
			return nil, "", "", err
		}
		response, err = doRequest(ctx, client, target, accept, token)
		if err != nil {
			return nil, "", token, err
		}
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, "", token, fmt.Errorf("registry returned HTTP %d", response.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil {
		return nil, "", token, err
	}
	if len(raw) > maxResponseBytes {
		return nil, "", token, errors.New("registry response exceeds size limit")
	}
	return raw, response.Header.Get("Docker-Content-Digest"), token, nil
}

func doRequest(ctx context.Context, client *http.Client, target, accept, token string) (*http.Response, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Accept", accept)
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	return client.Do(request)
}

func anonymousToken(ctx context.Context, client *http.Client, challenge string) (string, error) {
	if !strings.HasPrefix(challenge, "Bearer ") {
		return "", errors.New("registry did not provide a bearer-token challenge")
	}
	values := map[string]string{}
	for _, field := range strings.Split(strings.TrimPrefix(challenge, "Bearer "), ",") {
		key, value, ok := strings.Cut(strings.TrimSpace(field), "=")
		if ok {
			values[key] = strings.Trim(value, `"`)
		}
	}
	realm, err := url.Parse(values["realm"])
	if err != nil || realm.Scheme != "https" || realm.Host == "" {
		return "", errors.New("registry token realm must be HTTPS")
	}
	query := realm.Query()
	query.Set("service", values["service"])
	query.Set("scope", values["scope"])
	realm.RawQuery = query.Encode()
	request, _ := http.NewRequestWithContext(ctx, http.MethodGet, realm.String(), nil)
	response, err := client.Do(request)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", fmt.Errorf("token service returned HTTP %d", response.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	if err != nil {
		return "", err
	}
	var result struct {
		Token string `json:"token"`
	}
	if err := json.NewDecoder(bytes.NewReader(raw)).Decode(&result); err != nil || result.Token == "" {
		return "", errors.New("token service returned no token")
	}
	return result.Token, nil
}

func validDigest(value string) bool { return digestPattern.MatchString(value) }

func digestBytes(raw []byte) string {
	sum := sha256.Sum256(raw)
	return "sha256:" + hex.EncodeToString(sum[:])
}
