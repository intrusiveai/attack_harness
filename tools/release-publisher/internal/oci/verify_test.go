package oci

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestVerifyIndexAndSource(t *testing.T) {
	source := "https://github.com/intrusiveai/attack_harness"
	config := []byte(fmt.Sprintf(`{"config":{"Labels":{"org.opencontainers.image.source":%q}}}`, source))
	configDigest := digestBytes(config)
	manifest := []byte(fmt.Sprintf(`{"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json","config":{"digest":%q}}`, configDigest))
	manifestDigest := digestBytes(manifest)
	index := []byte(fmt.Sprintf(`{"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","manifests":[{"digest":%q,"platform":{"os":"linux","architecture":"amd64"}}]}`, manifestDigest))
	indexDigest := digestBytes(index)

	server := httptest.NewTLSServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		var raw []byte
		switch request.URL.Path {
		case "/v2/intrusiveai/attack_harness/manifests/v1.0.0":
			raw = index
		case "/v2/intrusiveai/attack_harness/manifests/" + manifestDigest:
			raw = manifest
		case "/v2/intrusiveai/attack_harness/blobs/" + configDigest:
			raw = config
		default:
			http.NotFound(response, request)
			return
		}
		response.Header().Set("Docker-Content-Digest", digestBytes(raw))
		_, _ = response.Write(raw)
	}))
	defer server.Close()
	verifier := Verifier{Client: server.Client(), RegistryURL: server.URL}
	err := verifier.Verify(context.Background(), "ghcr.io/intrusiveai/attack_harness:v1.0.0", "linux/amd64", manifestDigest, configDigest, indexDigest, source)
	if err != nil {
		t.Fatal(err)
	}
	if err := verifier.Verify(context.Background(), "ghcr.io/intrusiveai/attack_harness:v1.0.0", "linux/amd64", manifestDigest, configDigest, indexDigest, "https://github.com/wrong/repo"); err == nil {
		t.Fatal("accepted wrong OCI source label")
	}
}

func TestRejectsReferenceAndDigest(t *testing.T) {
	verifier := Verifier{}
	if err := verifier.Verify(context.Background(), "docker.io/example/image:latest", "linux/amd64", "bad", "bad", "", "source"); err == nil {
		t.Fatal("accepted invalid reference")
	}
}
