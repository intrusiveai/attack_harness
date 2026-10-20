//go:build linux || darwin

package dockercontrol_test

import (
	"bytes"
	"context"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"slices"
	"testing"
	"time"

	"github.com/intrusiveai/operator_sandbox/contracts"
	"github.com/intrusiveai/operator_sandbox/internal/contractstore"
	"github.com/intrusiveai/operator_sandbox/internal/dockercontrol"
	"github.com/intrusiveai/operator_sandbox/internal/imagerelease"
)

type rejectNetwork struct{ calls int }

func (r *rejectNetwork) RoundTrip(*http.Request) (*http.Response, error) {
	r.calls++
	return nil, fmt.Errorf("external HTTP is unavailable during local compatibility verification")
}

// This test is injected into Operator's dockercontrol package with go -overlay.
// It therefore exercises the production stopped-image reader rather than a
// harness-owned approximation of its Docker behavior.
func TestCandidateStoppedImageInspection(t *testing.T) {
	docker := os.Getenv("ATTACK_HARNESS_DOCKER")
	endpoint := os.Getenv("ATTACK_HARNESS_DOCKER_ENDPOINT")
	selector := os.Getenv("ATTACK_HARNESS_IMAGE_SELECTOR")
	hostPlatform := os.Getenv("ATTACK_HARNESS_HOST_PLATFORM")
	if docker == "" || endpoint == "" || selector == "" || hostPlatform == "" {
		t.Fatal("candidate inspection environment is incomplete")
	}
	client, err := dockercontrol.New(docker)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	protocol, err := contractstore.Load(ctx, os.Getenv("ATTACK_HARNESS_CONTRACT_ROOT"), contracts.PackageIdentity{
		Version: os.Getenv("ATTACK_HARNESS_CONTRACT_VERSION"), Digest: os.Getenv("ATTACK_HARNESS_CONTRACT_DIGEST"),
	})
	if err != nil {
		t.Fatal(err)
	}
	pin, _ := protocol.Protocol().PackageIdentity()
	expected, err := os.ReadFile(os.Getenv("ATTACK_HARNESS_EXPECTED_COMPATIBILITY"))
	if err != nil {
		t.Fatal(err)
	}
	network := &rejectNetwork{}
	previous := http.DefaultTransport
	http.DefaultTransport = network
	t.Cleanup(func() { http.DefaultTransport = previous })
	prepared, embedded, result, err := imagerelease.Prepare(ctx, client, endpoint, selector,
		imagerelease.Requirements{OperatorVersion: "0.1.0", Contract: pin, HostPlatform: hostPlatform, RuntimeProfile: "operator-container/v1"}, protocol.Protocol())
	if err != nil {
		t.Fatal(err)
	}
	if network.calls != 0 || prepared.Image.ImageID != selector || !embedded.Matches(prepared) ||
		!bytes.Equal(prepared.Release.Bytes(), expected) || prepared.Release.Digest() != contracts.RawDigest(expected) {
		t.Fatal("local image preparation did not preserve independently pinned image and exact compatibility bytes")
	}
	want := []string{
		"/opt/operator/engine/lib/attack_harness/skill_loader.py",
		"/opt/operator/engine/share/compatibility.json",
		"/opt/operator/engine/share/default-system-prompt.txt",
		"/opt/operator/engine/share/engine-manifest.json",
		"/opt/operator/engine/share/tool-catalog.json",
	}
	got := make([]string, 0, len(result.Files))
	for name, body := range result.Files {
		if len(body) == 0 {
			t.Fatalf("Operator returned empty release file %s", name)
		}
		got = append(got, name)
	}
	slices.Sort(got)
	if !slices.Equal(got, want) || result.ContainerID == "" || !result.Removed {
		t.Fatalf("incomplete inspection result: files=%v container=%q removed=%v",
			got, result.ContainerID, result.Removed)
	}
	probe := exec.CommandContext(ctx, docker, "--host", endpoint,
		"container", "inspect", "--", result.ContainerID)
	if err := probe.Run(); err == nil {
		t.Fatal("inspection container still exists after successful read")
	}
}
