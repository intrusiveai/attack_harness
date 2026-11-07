//go:build linux || darwin

// Controlled provider responses, production Harness process and Operator services.
package preparation_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/intrusiveai/operator_sandbox/internal/campaign"
	"github.com/intrusiveai/operator_sandbox/internal/campaignlimits"
	"github.com/intrusiveai/operator_sandbox/internal/modelprovider"
	"github.com/intrusiveai/operator_sandbox/internal/preparation"
	"github.com/intrusiveai/operator_sandbox/internal/reporting"
)

func TestHarnessEvidencePaginationProcess(t *testing.T) {
	for _, transport := range []string{"fifo", "spool"} {
		t.Run(transport, func(t *testing.T) {
			var readable, citation string
			draft := func(handle string) map[string]any {
				return map[string]any{"finish_reason": "no-useful-next-experiment", "summary": "Partially inspected.",
					"objectives":    []any{map[string]any{"objective_id": "objective-marker", "outcome": "inconclusive", "summary": "Partial evidence.", "observations": []string{handle}}},
					"uncertainties": []any{map[string]any{"kind": "evidence-gap", "description": "Only inspected ranges support this assessment."}}}
			}
			r := newProcessRun(t, processCase{transport: transport, prompt: "default", reply: func(turn int, q map[string]any) ([]byte, error) {
				switch turn {
				case 1:
					if !bytes.Contains(encode(q), []byte("minimal_inline_example")) || !bytes.Contains(encode(q), []byte("readable_observation")) {
						return nil, fmt.Errorf("shared guidance missing")
					}
					return processResponse([]any{modelCall("invoke", "attempt_execute", map[string]any{"origin": "scenario", "scenario_id": "scenario-marker", "operation_id": "invoke", "json": map[string]any{"query": "baseline"}})}), nil
				case 2:
					a, e := modelToolResult(q, "invoke")
					if e != nil {
						return nil, e
					}
					readable = a["observations"].([]any)[0].(map[string]any)["observation"].(string)
					return processResponse([]any{modelCall("page-1", "observation_read", map[string]any{"observation": readable, "max_bytes": 4})}), nil
				case 3:
					page, e := modelToolResult(q, "page-1")
					if e != nil {
						return nil, e
					}
					citation = page["citation"].(string)
					next := page["continuation"].(map[string]any)
					if citation == readable || page["readable_observation"] != readable || next["arguments"].(map[string]any)["observation"] != readable {
						return nil, fmt.Errorf("read/citation conflated: %v", page)
					}
					return processResponse([]any{modelCall("page-2", next["tool"].(string), next["arguments"])}), nil
				case 4:
					page, e := modelToolResult(q, "page-2")
					if e != nil {
						return nil, e
					}
					if page["offset"] != float64(4) || page["raw_length"] != float64(4) {
						return nil, fmt.Errorf("wrong continuation: %v", page)
					}
					return processResponse([]any{modelCall("unread", "finish", draft(readable))}), nil
				case 5:
					bad, e := modelToolResult(q, "unread")
					if e != nil {
						return nil, e
					}
					d := bad["diagnostic"].(map[string]any)
					if d["reason"] != "evidence_not_inspected" || !strings.Contains(d["correction"].(string), citation) {
						return nil, fmt.Errorf("missing applicable correction: %v", bad)
					}
					invalid := draft(citation)
					invalid["uncertainties"] = []any{map[string]any{"kind": "invented", "description": "gap"}}
					return processResponse([]any{modelCall("malformed", "finish", invalid)}), nil
				case 6:
					bad, e := modelToolResult(q, "malformed")
					if e != nil {
						return nil, e
					}
					d := bad["diagnostic"].(map[string]any)
					if d["field_path"] != "/uncertainties/0/kind" || !strings.Contains(d["correction"].(string), "evidence-gap") {
						return nil, fmt.Errorf("lost enum correction: %v", bad)
					}
					return processResponse([]any{modelCall("finish", "finish", draft(citation))}), nil
				}
				return nil, fmt.Errorf("unexpected model call %d", turn)
			}})
			finishEvidenceRun(t, r)
			if !r.service.AssessmentCommitted() {
				t.Fatal("finish accepted without the corrected assessment")
			}
			if e := r.writer.Close(); e != nil {
				t.Fatal(e)
			}
			result := harnessExport(t, r)
			if result.HarnessClaims != 1 || len(result.Attempts) != 1 || result.Attempts[0].Origin != "scenario" || result.Attempts[0].ScenarioID != "scenario-marker" {
				t.Fatal("lost assessment/origin or replayed target", result)
			}
			count := 0
			for _, op := range r.native.calls {
				if op == "application.invoke" {
					count++
				}
			}
			if count != 1 {
				t.Fatal("finish correction replayed target", count)
			}
		})
	}
}

func harnessExport(t *testing.T, r *processRun) reporting.Result {
	t.Helper()
	output, e := exec.Command(processCLI(t), "report", "--state-root", r.root, "--campaign", "campaign-1").CombinedOutput()
	if e != nil {
		t.Fatal(e, string(output))
	}
	var receipt reporting.Receipt
	if e = json.Unmarshal(output, &receipt); e != nil {
		t.Fatal(e)
	}
	return reportResult(t, r.root, receipt)
}

func finishEvidenceRun(t *testing.T, r *processRun) {
	t.Helper()
	r.finish(t) // Requires accepted finish and actual Python process exit zero.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	terminal, err := r.service.Shutdown(ctx) // Cached, independently confirmed result.
	if err != nil || terminal.Closure != "confirmed" || terminal.CleanupState != "complete" {
		t.Fatalf("native target cleanup: %+v; %v", terminal, err)
	}
}

func TestHarnessModelBudgetProcess(t *testing.T) {
	for _, consumed := range []int{493460, 502198} {
		t.Run(fmt.Sprint(consumed), func(t *testing.T) {
			var reference string
			r := newProcessRun(t, processCase{transport: "fifo", prompt: "default", timeout: 120 * time.Second,
				settings: func(c *preparation.LaunchConfig) {
					s := c.Model.Settings()
					s.MaximumPromptTokens = 20480
					s.MaximumCompletionTokens = 16384
					var e error
					c.Model, e = modelprovider.Parse(encode(s))
					if e != nil {
						t.Fatal(e)
					}
					c.Limits, e = campaignlimits.ParseHost([]byte(`{"max_model_tokens":524288}`))
					if e != nil {
						t.Fatal(e)
					}
				}, reply: func(turn int, q map[string]any) ([]byte, error) {
					if turn > 18 {
						return nil, fmt.Errorf("unfunded model request %d", turn)
					}
					var call any
					switch turn {
					case 1:
						var task map[string]any
						if e := json.Unmarshal([]byte(q["messages"].([]any)[1].(map[string]any)["content"].(string)), &task); e != nil {
							return nil, e
						}
						for _, v := range task["reference_handles"].([]any) {
							entry := v.(map[string]any)
							if entry["role"] == "reference" {
								reference = entry["entry_id"].(string)
								break
							}
						}
						call = modelCall("invoke", "attempt_execute", map[string]any{"origin": "exploratory", "operation_id": "invoke", "json": map[string]any{"query": "baseline"}})
					case 3, 18:
						// Recoverable errors must not become the terminal model-budget cause.
						call = modelCall(fmt.Sprint("bad-", turn), "finish", map[string]any{"finish_reason": "budget-limit", "summary": "Incomplete.", "objectives": []any{}, "observations": []string{}})
					default:
						call = modelCall(fmt.Sprint("reference-", turn), "reference_read", map[string]any{"reference": reference, "offset": turn, "max_bytes": 1})
					}
					var response map[string]any
					_ = json.Unmarshal(processResponse([]any{call}), &response)
					if q["tool_choice"] == "none" {
						response["choices"] = []any{map[string]any{"index": 0, "finish_reason": "stop", "logprobs": nil, "message": map[string]any{"role": "assistant", "content": "Retain completed invocation; final assessment not yet accepted.", "refusal": nil, "annotations": []any{}}}}
					}
					used := 27500
					if turn == 18 {
						used = consumed - 17*27500
					}
					response["usage"] = map[string]any{"prompt_tokens": used - 16384, "completion_tokens": 16384, "total_tokens": used}
					if turn == 18 && !bytes.Contains(encode(q), []byte("Harness budget notice")) {
						return nil, fmt.Errorf("missing early finalization notice")
					}
					return encode(response), nil
				}})
			finishEvidenceRun(t, r)
			if r.service.AssessmentCommitted() || r.service.WorkflowFailure() == nil || r.service.WorkflowFailure().Stopping != "budget-limit" {
				t.Fatal("exit zero erased the unsuccessful unavailable finish")
			}
			if len(r.provider.requests) != 18 {
				t.Fatal("wrong funded request count", len(r.provider.requests), r.output.String())
			}
			if e := r.writer.Close(); e != nil {
				t.Fatal(e)
			}
			result := harnessExport(t, r)
			if result.HarnessClaims != 0 || len(result.Attempts) != 1 {
				t.Fatal("unavailable finish reported an assessment or lost execution", result)
			}
			var terminal *campaign.WorkflowDiagnostic
			for i := range result.WorkflowDiagnostics {
				d := &result.WorkflowDiagnostics[i]
				if d.Reason == "model_reservation_unavailable" {
					terminal = d
				}
			}
			if terminal == nil || terminal.Budget == nil || terminal.FieldPath != "" || terminal.Tool != "" || terminal.CallID != "" || terminal.Observed != 0 || terminal.Limit != 0 {
				t.Fatal("missing or contaminated terminal diagnostic", terminal)
			}
			b := terminal.Budget
			if b.TotalAllowance != 524288 || b.Consumed != int64(consumed) || b.Remaining != int64(524288-consumed) || b.NextRequestReservation != 36864 {
				t.Fatal("wrong model accounting", b)
			}
			facts := []string{fmt.Sprint(consumed), fmt.Sprint(524288 - consumed), "524288", "36864"}
			destination := filepath.Join(t.TempDir(), "export")
			for _, verb := range []string{"inspect", "export"} {
				args := []string{verb, "--state-root", r.root, "--campaign", "campaign-1"}
				if verb == "export" {
					args = append(args, "--output", destination)
				}
				raw, e := exec.Command(processCLI(t), args...).CombinedOutput()
				if e != nil {
					t.Fatal(e, string(raw))
				}
				if verb == "inspect" {
					for _, fact := range facts {
						if !bytes.Contains(raw, []byte(fact)) {
							t.Fatal("inspection lost budget", fact, string(raw))
						}
					}
				}
			}
			for _, file := range []string{"report.md", "events/000001.jsonl", "result-manifest.json"} {
				raw, e := os.ReadFile(filepath.Join(destination, file))
				if e != nil {
					t.Fatal(e)
				}
				for _, fact := range facts {
					if !bytes.Contains(raw, []byte(fact)) {
						t.Fatal(file, "lost budget", fact)
					}
				}
				if file == "events/000001.jsonl" && !bytes.Contains(raw, []byte("invalid_structure")) {
					t.Fatal("earlier rejection lost")
				}
			}
			t.Log("Production Harness exit zero with unavailable assessment; Operator retained unsuccessful finalization and exact model accounting.")
		})
	}
}
