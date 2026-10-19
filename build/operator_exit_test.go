//go:build linux || darwin

// Test-only overlay: production Harness, controlled provider, real local transport.
package preparation_test

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/intrusiveai/operator_sandbox/internal/campaign"
)

func TestHarnessExitProcess(t *testing.T) {
	for _, transport := range []string{"fifo", "spool"} {
		for _, mode := range []string{"healthy-unwind", "post-finish-fatal", "runtime-fatal"} {
			t.Run(transport+"/"+mode, func(t *testing.T) {
				t.Setenv("HARNESS_TEST_EXIT_MODE", mode)
				r := newProcessRun(t, processCase{transport: transport, prompt: "default", reply: func(turn int, request map[string]any) ([]byte, error) {
					assessment := map[string]any{"summary": "No target attempt ran.", "objectives": []any{map[string]any{
						"objective_id": "objective-marker", "outcome": "not-tested", "summary": "Untested.", "attempt_receipt_refs": []string{}}}}
					if mode == "healthy-unwind" && turn == 1 {
						assessment["objectives"].([]any)[0].(map[string]any)["attempt_receipt_refs"] = []string{"unknown-receipt"}
					} else if mode == "healthy-unwind" {
						feedback, err := modelToolResult(request, "finish-1")
						if err != nil || feedback["status"] != "error" {
							t.Fatalf("missing rejection: %v %v", feedback, err)
						}
					}
					id := "finish-1"
					if turn == 2 {
						id = "finish-2"
					}
					return processResponse([]any{modelCall(id, "finish", map[string]any{
						"finish_reason": "no-useful-next-experiment", "assessment": assessment})}), nil
				}})
				err := r.cmd.Wait()
				r.waited = true
				r.cancel()
				<-r.pump
				<-r.serve
				expected := 1
				if mode == "healthy-unwind" {
					expected = 0
				}
				if r.cmd.ProcessState.ExitCode() != expected {
					t.Fatalf("exit=%v error=%v output=%s", r.cmd.ProcessState, err, r.output.String())
				}
				if r.service.StopAccepted() != (mode != "runtime-fatal") {
					t.Fatal("wrong finish acceptance")
				}
				if expected == 0 {
					if r.output.Len() != 0 {
						t.Fatal(r.output.String())
					}
				} else {
					var d map[string]any
					raw := r.output.String()
					if len(raw) > 1025 || strings.Count(raw, "\n") != 1 || json.Unmarshal([]byte(raw), &d) != nil {
						t.Fatalf("unbounded or missing diagnostic: %s", raw)
					}
					if d["stage"] != "runtime" || d["reason"] != "io-error" || d["exception"] != "OSError" || d["message"] != "Input/output error" {
						t.Fatal(d)
					}
					for _, secret := range []string{"synthetic-secret", "https://", "prompt=response", "Traceback"} {
						if strings.Contains(raw, secret) {
							t.Fatal("unsafe diagnostic")
						}
					}
				}
				cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				if _, err = r.service.Shutdown(cleanup); err != nil {
					t.Fatal(err)
				}
				if err = r.writer.Close(); err != nil {
					t.Fatal(err)
				}
				operations := []string{}
				diagnosticReports := 0
				_, err = campaign.Inspect(r.root, "campaign-1", func(event campaign.Event) error {
					if event.Kind == "workflow.diagnostic" && mode == "runtime-fatal" {
						var metadata struct {
							Diagnostic campaign.WorkflowDiagnostic `json:"diagnostic"`
						}
						if e := json.Unmarshal(event.Metadata, &metadata); e != nil {
							return e
						}
						if metadata.Diagnostic.Source == "harness-local" && metadata.Diagnostic.Stage == "termination" && metadata.Diagnostic.Reason == "local_error" {
							diagnosticReports++
						}
					}
					if event.Kind == "service.request" {
						// Diagnostic bodies are intentionally not retained by the host.
						if len(event.Content) == 0 {
							operations = append(operations, "engine.diagnostic_report")
						}
						for _, ref := range event.Content {
							raw, e := os.ReadFile(filepath.Join(r.root, "campaigns", "campaign-1", filepath.FromSlash(ref.Path)))
							if e != nil {
								return e
							}
							var request struct{ Operation string }
							if e = json.Unmarshal(raw, &request); e != nil {
								return e
							}
							operations = append(operations, request.Operation)
						}
					}
					return nil
				})
				if err != nil {
					t.Fatal(err)
				}
				want := "engine.model_generate,engine.finish"
				if mode == "healthy-unwind" {
					want = "engine.model_generate,engine.finish,engine.model_generate,engine.finish"
				}
				if mode == "runtime-fatal" {
					want = "engine.diagnostic_report"
					if diagnosticReports != 1 {
						t.Fatalf("missing fatal report: %d", diagnosticReports)
					}
				}
				if strings.Join(operations, ",") != want {
					t.Fatal("unexpected operations or replay", operations)
				}
				t.Logf("Harness process exit=%d, finish accepted=%v, operations=%v", expected, r.service.StopAccepted(), operations)
			})
		}
	}
}
