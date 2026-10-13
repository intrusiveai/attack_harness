package remote

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/intrusiveai-engineering/releases/internal/record"
)

func validRecord(t *testing.T) []byte {
	t.Helper()
	release := record.Record{
		APIVersion: record.APIVersion, ImageDigest: "sha256:" + strings.Repeat("a", 64),
		MinimumOperatorVersion: "1.2.3", ContractPackageVersion: "2.0.0",
		ContractPackageDigest: "sha256:" + strings.Repeat("b", 64), RuntimeProfile: "operator-container/v1", Platform: "linux/amd64",
	}
	raw, err := release.Bytes()
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestVerify(t *testing.T) {
	raw := validRecord(t)
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Accept") != "application/json" || request.Header.Get("Accept-Encoding") != "identity" {
			t.Errorf("unexpected request headers")
		}
		if strings.HasSuffix(request.URL.Path, strings.Repeat("f", 64)) {
			http.NotFound(w, request)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "public,max-age=31536000,immutable")
		_, _ = w.Write(raw)
	}))
	defer server.Close()
	base, _ := parseOrigin(server.URL)
	client := server.Client()
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return ErrUnexpectedRedirect }
	if err := verifyPublished(context.Background(), client, base, strings.Repeat("a", 64), raw); err != nil {
		t.Fatal(err)
	}
	if err := verifyMissing(context.Background(), client, base, strings.Repeat("f", 64)); err != nil {
		t.Fatal(err)
	}
}

func TestRejectsRedirectAndEncoding(t *testing.T) {
	raw := validRecord(t)
	tests := []struct {
		name    string
		handler http.HandlerFunc
	}{
		{"redirect", func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, "/elsewhere", http.StatusFound) }},
		{"encoding", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Cache-Control", "public,max-age=31536000,immutable")
			w.Header().Set("Content-Encoding", "gzip")
			_, _ = w.Write(raw)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewTLSServer(test.handler)
			defer server.Close()
			base, _ := parseOrigin(server.URL)
			client := server.Client()
			client.CheckRedirect = func(*http.Request, []*http.Request) error { return ErrUnexpectedRedirect }
			err := verifyPublished(context.Background(), client, base, strings.Repeat("a", 64), raw)
			if err == nil {
				t.Fatal("verification unexpectedly succeeded")
			}
		})
	}
}

func TestParseOrigin(t *testing.T) {
	for _, value := range []string{"http://example.test", "https://user@example.test", "https://example.test/path", "not-a-url"} {
		if _, err := parseOrigin(value); err == nil {
			t.Fatalf("accepted %q", value)
		}
	}
	if _, err := parseOrigin(fmt.Sprintf("https://%s", "example.test")); err != nil {
		t.Fatal(err)
	}
}
