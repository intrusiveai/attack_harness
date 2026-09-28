//go:build linux || darwin

package dockercontrol

import (
	"context"
	"os"
	"os/exec"
	"slices"
	"testing"
	"time"
)

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
	client, err := New(docker)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	pin, err := client.ResolveImage(ctx, endpoint, selector, hostPlatform)
	if err != nil {
		t.Fatal(err)
	}
	if pin.ImageID != selector {
		t.Fatalf("Docker changed immutable selector: got %s want %s", pin.ImageID, selector)
	}
	result, err := client.ReadReleaseFiles(ctx, pin)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		"/opt/operator/engine/lib/attack_harness/skill_loader.py",
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
