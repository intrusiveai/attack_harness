package remote

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/intrusiveai-engineering/releases/internal/record"
)

var ErrUnexpectedRedirect = errors.New("unexpected redirect")

func Verify(ctx context.Context, origin string, expected []byte, missingDigest string) error {
	release, err := record.Parse(expected)
	if err != nil {
		return fmt.Errorf("validate expected record: %w", err)
	}
	base, err := parseOrigin(origin)
	if err != nil {
		return err
	}
	client := &http.Client{
		Timeout:       10 * time.Second,
		Transport:     &http.Transport{DisableCompression: true},
		CheckRedirect: func(*http.Request, []*http.Request) error { return ErrUnexpectedRedirect },
	}
	if err := verifyPublished(ctx, client, base, release.Hex(), expected); err != nil {
		return err
	}
	if missingDigest != "" {
		if err := verifyMissing(ctx, client, base, missingDigest); err != nil {
			return err
		}
	}
	return nil
}

func parseOrigin(origin string) (*url.URL, error) {
	parsed, err := url.Parse(origin)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || (parsed.Path != "" && parsed.Path != "/") {
		return nil, errors.New("origin must be an HTTPS origin without path, credentials, query, or fragment")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/")
	return parsed, nil
}

func verifyPublished(ctx context.Context, client *http.Client, origin *url.URL, digestHex string, expected []byte) error {
	response, err := request(ctx, client, origin, digestHex)
	if err != nil {
		return fmt.Errorf("fetch published record: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("published record returned HTTP %d, want 200", response.StatusCode)
	}
	values := response.Header.Values("Content-Type")
	if len(values) != 1 {
		return fmt.Errorf("published record must have exactly one Content-Type header, got %d", len(values))
	}
	mediaType, _, err := mime.ParseMediaType(values[0])
	if err != nil || mediaType != "application/json" {
		return fmt.Errorf("published record Content-Type must be application/json")
	}
	if response.Header.Get("Content-Encoding") != "" {
		return errors.New("published record must not have Content-Encoding")
	}
	cacheControl := response.Header.Values("Cache-Control")
	if len(cacheControl) != 1 || cacheControl[0] != "public,max-age=31536000,immutable" {
		return errors.New("published record Cache-Control must be public,max-age=31536000,immutable")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, record.MaxBytes+1))
	if err != nil {
		return fmt.Errorf("read published record: %w", err)
	}
	if len(body) > record.MaxBytes {
		return fmt.Errorf("published record exceeds %d bytes", record.MaxBytes)
	}
	parsed, err := record.Parse(body)
	if err != nil {
		return fmt.Errorf("parse published record: %w", err)
	}
	if parsed.Hex() != digestHex {
		return errors.New("published record image_digest does not match request path")
	}
	if !bytes.Equal(body, expected) {
		return errors.New("published record bytes differ from expected record")
	}
	return nil
}

func verifyMissing(ctx context.Context, client *http.Client, origin *url.URL, digest string) error {
	if len(digest) == 71 && strings.HasPrefix(digest, "sha256:") {
		digest = strings.TrimPrefix(digest, "sha256:")
	}
	if len(digest) != 64 || strings.Trim(digest, "0123456789abcdef") != "" {
		return errors.New("missing digest must be 64 lowercase hexadecimal characters")
	}
	response, err := request(ctx, client, origin, digest)
	if err != nil {
		return fmt.Errorf("fetch missing record: %w", err)
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, record.MaxBytes+1))
	if response.StatusCode != http.StatusNotFound {
		return fmt.Errorf("missing record returned HTTP %d, want 404", response.StatusCode)
	}
	return nil
}

func request(ctx context.Context, client *http.Client, origin *url.URL, digest string) (*http.Response, error) {
	target := *origin
	target.Path = strings.TrimRight(target.Path, "/") + "/sha256/" + digest
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, target.String(), nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Accept-Encoding", "identity")
	return client.Do(request)
}
