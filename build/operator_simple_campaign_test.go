//go:build linux || darwin

// Additional Harness workflow cases alongside Operator's authoritative fixtures.
// Uses its real process runner, production Python entrypoint and local native target.
package preparation_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/intrusiveai/operator_sandbox/internal/campaign"
	"github.com/intrusiveai/operator_sandbox/internal/reporting"
)

func TestHarnessSimpleCampaignProcess(t *testing.T) {
	if os.Getenv("OPERATOR_HARNESS_INTEGRATION") != "1" {
		t.Skip("controlled production Harness gate")
	}
	binary := processCLI(t)
	for _, transport := range []string{"fifo", "spool"} {
		for _, mode := range []string{"direct", "artifact", "corrected", "exhausted", "zero-attempt", "hypothesis-correction"} {
			// Business-rule variants run on FIFO; direct execution/observation/finish also runs on spool.
			if transport == "spool" && mode != "direct" {
				continue
			}
			t.Run(transport+"/"+mode, func(t *testing.T) {
				var observation string
				assessment := func() map[string]any {
					refs := []string{}
					outcome := "not-tested"
					if observation != "" {
						refs = append(refs, observation)
						outcome = "inconclusive"
					}
					return map[string]any{"finish_reason": "no-useful-next-experiment",
						"summary": "Honest controlled assessment.", "objectives": []any{map[string]any{
							"objective_id": "objective-marker", "outcome": outcome, "summary": "Report only observed evidence.", "observations": refs}},
					}
				}
				r := newProcessRun(t, processCase{transport: transport, prompt: "default", reply: func(turn int, q map[string]any) ([]byte, error) {
					if mode == "exhausted" || mode == "corrected" && turn == 1 {
						if turn > 5 {
							return nil, fmt.Errorf("invalid-call limit was increased")
						}
						return processResponse([]any{modelCall(fmt.Sprintf("bad-%d", turn), "attempt_execute", map[string]any{"origin": "exploratory", "operation_id": "invoke"})}), nil
					}
					if mode == "zero-attempt" {
						return processResponse([]any{modelCall("finish", "finish", assessment())}), nil
					}
					if mode == "hypothesis-correction" {
						draft := assessment()
						a := draft
						h := map[string]any{"label": "local-child", "parent": "local-parent", "origin": "exploratory", "outcome": "not-tested", "summary": "Untested hypothesis."}
						h["objective_refs"] = []string{"objective-marker"}

						if turn == 1 {
							a["hypotheses"] = []any{h}
						} else if turn == 2 {
							rejected, e := modelToolResult(q, "finish-bad")
							if e != nil || rejected["status"] != "error" {
								return nil, fmt.Errorf("invalid assessment falsely accepted: %v %v", rejected, e)
							}
							parent := map[string]any{"label": "local-parent", "origin": "exploratory", "outcome": "not-tested", "summary": "Untested parent."}
							parent["objective_refs"] = []string{"objective-marker"}

							a["hypotheses"] = []any{h, parent}
						} else {
							return nil, fmt.Errorf("assessment correction did not finish")
						}
						id := "finish-good"
						if turn == 1 {
							id = "finish-bad"
						}
						return processResponse([]any{modelCall(id, "finish", draft)}), nil
					}
					step := turn
					if mode == "corrected" {
						step--
						if turn == 2 {
							rejected, e := modelToolResult(q, "bad-1")
							if e != nil || rejected["code"] != "INVALID_ARGUMENTS" {
								return nil, fmt.Errorf("missing correction: %v %v", rejected, e)
							}
						}
					}
					if mode == "artifact" {
						if turn == 1 {
							return processResponse([]any{publishCall("payload", "baseline")}), nil
						}
						step--
					}
					switch step {
					case 1:
						input := map[string]any{"origin": "exploratory", "operation_id": "invoke", "json": map[string]any{"query": "baseline"}}
						if mode == "artifact" {
							a, e := modelToolResult(q, "payload")
							if e != nil {
								return nil, e
							}
							delete(input, "json")
							input["artifact"] = a["artifact"]
						}
						return processResponse([]any{modelCall("invoke", "attempt_execute", input)}), nil
					case 2:
						a, e := modelToolResult(q, "invoke")
						if e != nil || a["status"] != "completed" {
							return nil, fmt.Errorf("execution: %v %v", a, e)
						}

						entries := a["observations"].([]any)
						if len(entries) != 1 {
							return nil, fmt.Errorf("missing feedback: %v", a)
						}
						return processResponse([]any{modelCall("read", "observation_read", map[string]any{"observation": entries[0].(map[string]any)["observation"]})}), nil
					case 3:
						evidence, e := modelToolResult(q, "read")
						if e != nil {
							return nil, e
						}
						observation = evidence["observation"].(string)
						raw, e := modelContent(evidence)
						if e != nil || string(raw) != `{"answer":"test"}` {
							return nil, fmt.Errorf("wrong evidence: %v", evidence)
						}
						return processResponse([]any{modelCall("finish", "finish", assessment())}), nil
					default:
						return nil, fmt.Errorf("unexpected model turn %d", turn)
					}
				}})
				r.finish(t)
				if err := r.writer.Close(); err != nil {
					t.Fatal(err)
				}
				expected := 1
				if mode == "exhausted" || mode == "zero-attempt" || mode == "hypothesis-correction" {
					expected = 0
				}
				dispatched := 0
				for _, op := range r.native.calls {
					if op == "application.invoke" {
						dispatched++
					}
				}
				if dispatched != expected {
					t.Fatal("unexpected dispatch/replay", r.native.calls)
				}
				operations := []string{}
				_, err := campaign.Inspect(r.root, "campaign-1", func(event campaign.Event) error {
					if event.Kind == "service.request" {
						for _, ref := range event.Content {
							raw, e := os.ReadFile(filepath.Join(r.root, "campaigns", "campaign-1", filepath.FromSlash(ref.Path)))
							if e != nil {
								return e
							}
							var request struct{ Operation string }
							if e = json.Unmarshal(raw, &request); e != nil {
								return e
							}
							if request.Operation != "engine.model_generate" {
								operations = append(operations, request.Operation)
							}
						}
					}
					return nil
				})
				if err != nil {
					t.Fatal(err)
				}
				if mode == "direct" && strings.Join(operations, ",") != "engine.attempt_execute,engine.observation_read,engine.finish" {
					t.Fatal("ordinary workflow added prerequisites", operations)
				}
				if mode == "exhausted" && len(r.provider.requests) != 5 {
					t.Fatal("wrong invalid limit", len(r.provider.requests))
				}
				for _, verb := range []string{"inspect", "report", "export"} {
					args := []string{verb, "--state-root", r.root, "--campaign", "campaign-1"}
					destination := filepath.Join(t.TempDir(), "export")
					if verb == "export" {
						args = append(args, "--output", destination)
					}
					raw, e := exec.Command(binary, args...).CombinedOutput()
					if e != nil {
						t.Fatal(args, e, string(raw))
					}
					if verb == "inspect" && mode == "exhausted" {
						var info struct {
							Diagnostic *campaign.WorkflowDiagnostic `json:"workflow_diagnostic"`
						}
						if json.Unmarshal(raw, &info) != nil || info.Diagnostic == nil || info.Diagnostic.Stopping != "invalid-call-limit" || info.Diagnostic.Observed != 5 || info.Diagnostic.Limit != 5 || info.Diagnostic.Reason != "content_choice" {
							t.Fatal(string(raw))
						}
						t.Log("user-visible stopping reason:", info.Diagnostic.Message())
					}
					if verb == "report" || verb == "export" {
						var rr reporting.Receipt
						if json.Unmarshal(raw, &rr) != nil {
							t.Fatal(string(raw))
						}
						report := reportResult(t, r.root, rr)
						if len(report.Attempts) != expected {
							t.Fatal("report lost execution facts", report.Attempts)
						}
						if mode != "exhausted" && report.HarnessClaims != 1 {
							t.Fatal("missing accepted assessment", report)
						}
						if mode == "exhausted" && len(report.WorkflowDiagnostics) < 6 {
							t.Fatal("missing rejection/stopping history", report.WorkflowDiagnostics)
						}
						if verb == "export" && mode == "exhausted" {
							data, e := os.ReadFile(filepath.Join(destination, "result-manifest.json"))
							if e != nil || !bytes.Contains(data, []byte("invalid-call-limit")) {
								t.Fatal("export lost cause", e)
							}
						}
					}
				}
				t.Log("host operations:", operations)
			})
		}
	}
}
