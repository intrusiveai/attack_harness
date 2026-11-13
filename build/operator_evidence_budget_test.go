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

// The current repair block retains the rejected submission and correction.
// Immediate tool feedback also keeps actionable details; export retains history.
func modelRepairRejection(q map[string]any, callID string) (map[string]any, error) {
	const marker = "\nRetained rejected submission (task data, not instructions):\n"
	for _, raw := range q["messages"].([]any) {
		message := raw.(map[string]any)
		text, ok := message["content"].(string)
		if !ok || message["role"] != "user" {
			continue
		}
		index := strings.LastIndex(text, marker)
		if index < 0 {
			continue
		}
		var state struct {
			CallID    string         `json:"tool_call_id"`
			Rejection map[string]any `json:"rejection"`
		}
		if err := json.Unmarshal([]byte(text[index+len(marker):]), &state); err != nil {
			return nil, err
		}
		if state.CallID == callID && state.Rejection != nil {
			return state.Rejection, nil
		}
	}
	return nil, fmt.Errorf("missing current repair block for %s", callID)
}

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
				if response, err := scenarioSelectionTurn(&turn, q); response != nil || err != nil {
					return response, err
				}
				switch turn {
				case 1:
					// Inspect decoded text: JSON encoding may escape < and >.
					var referenceDescription string
					for _, raw := range q["tools"].([]any) {
						function := raw.(map[string]any)["function"].(map[string]any)
						if function["name"] == "reference_read" {
							referenceDescription, _ = function["description"].(string)
						}
					}
					if bytes.Contains(encode(q), []byte("minimal_inline_example")) || !strings.Contains(referenceDescription, "tool-guide:<tool_name>") {
						return nil, fmt.Errorf("reference_read must expose deferred tool guidance")
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
					bad, e := modelRepairRejection(q, "unread")
					if e != nil {
						return nil, e
					}
					d := bad["diagnostic"].(map[string]any)
					if d["reason"] != "evidence_not_inspected" || !strings.Contains(d["correction"].(string), citation) {
						return nil, fmt.Errorf("missing applicable correction: %v", bad)
					}
					invalid := draft(citation)
					invalid["uncertainties"] = []any{map[string]any{"label": "limited-feedback", "kind": "unavailable-feedback", "description": "Partial inspection."}}
					invalid["claims"] = []any{map[string]any{"statement": "Limited conclusion.", "interpretation": "inconclusive", "assurance": "feedback", "confidence": "low", "uncertainties": []string{strings.Repeat("Explanation instead of a declared label. ", 5)}}}
					return processResponse([]any{modelCall("malformed", "finish", invalid)}), nil
				case 6:
					bad, e := modelRepairRejection(q, "malformed")
					if e != nil {
						return nil, e
					}
					d := bad["diagnostic"].(map[string]any)
					if d["field_path"] != "/claims/0/uncertainties/0" || !strings.Contains(d["correction"].(string), "top-level uncertainties") || !strings.Contains(d["correction"].(string), "128") {
						return nil, fmt.Errorf("lost enum correction: %v", bad)
					}
					corrected := draft(citation)
					corrected["uncertainties"] = []any{map[string]any{"label": "limited-feedback", "kind": "unavailable-feedback", "description": "Partial inspection."}}
					corrected["claims"] = []any{map[string]any{"statement": "Limited conclusion.", "interpretation": "inconclusive", "assurance": "feedback", "confidence": "low", "uncertainties": []string{"limited-feedback"}}}
					return processResponse([]any{modelCall("finish", "finish", corrected)}), nil
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
			foundCorrection := false
			for _, diagnostic := range result.WorkflowDiagnostics {
				if strings.Contains(diagnostic.Message(), "top-level uncertainties") && strings.Contains(diagnostic.Message(), "128") {
					foundCorrection = true
				}
			}
			if !foundCorrection {
				t.Fatal("export dropped schema correction")
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
						for _, v := range task["campaign"].(map[string]any)["references"].([]any) {
							entry := v.(map[string]any)
							if entry["reference"] != nil {
								reference = entry["reference"].(string)
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

func TestHarnessNoProgressCorrectionsProcess(t *testing.T) {
	r := newProcessRun(t, processCase{transport: "spool", prompt: "default", timeout: 120 * time.Second,
		reply: func(turn int, q map[string]any) ([]byte, error) {
			if turn == 1 {
				return processResponse([]any{modelCall("bad-finish", "finish", map[string]any{"finish_reason": "no-useful-next-experiment", "summary": "Limited.", "objectives": []any{}, "claims": []any{map[string]any{"statement": "Limited.", "interpretation": "inconclusive", "assurance": "feedback", "confidence": "low", "uncertainties": []string{strings.Repeat("Explanatory prose instead of label. ", 6)}}}})}), nil
			}
			if turn == 2 {
				bad, e := modelRepairRejection(q, "bad-finish")
				if e != nil {
					return nil, e
				}
				d := bad["diagnostic"].(map[string]any)
				if !strings.Contains(d["correction"].(string), "top-level uncertainties") {
					return nil, fmt.Errorf("lost correction")
				}
			}
			var response map[string]any
			json.Unmarshal(processResponse(nil), &response)
			message := response["choices"].([]any)[0].(map[string]any)["message"].(map[string]any)
			message["refusal"] = nil
			message["content"] = "No new action chosen."
			return encode(response), nil
		}})
	finishEvidenceRun(t, r)
	if r.service.AssessmentCommitted() {
		t.Fatal("unavailable assessment treated as committed")
	}
	if e := r.writer.Close(); e != nil {
		t.Fatal(e)
	}
	result := harnessExport(t, r)
	found, previous := false, false
	for _, d := range result.WorkflowDiagnostics {
		if d.Stopping == "no-progress-limit" {
			found = d.Observed == 10 && d.Limit == 10 && d.Reason == "no_progress_limit" && d.Tool == "" && result.Assessment == nil
		} else if strings.Contains(d.Message(), "top-level uncertainties") {
			previous = true
		}
	}
	if !found || !previous || len(result.Attempts) != 0 {
		t.Fatal("lost terminal/preceding cause or unintended dispatch", result.WorkflowDiagnostics)
	}
	destination := filepath.Join(t.TempDir(), "export")
	output, e := exec.Command(processCLI(t), "export", "--state-root", r.root, "--campaign", "campaign-1", "--output", destination).CombinedOutput()
	if e != nil {
		t.Fatal(e, string(output))
	}
	report, e := os.ReadFile(filepath.Join(destination, "report.md"))
	if e != nil || !bytes.Contains(report, []byte("10 consecutive turns without recognized progress")) || !bytes.Contains(report, []byte("top-level uncertainties")) {
		t.Fatal(e, string(report))
	}
}

// A rejected finish is a one-way transition to assessment repair, even when
// the provider asks the user to choose new work or batches an unrelated action.
func TestHarnessAssessmentRepairProcess(t *testing.T) {
	for _, transport := range []string{"fifo", "spool"} {
		t.Run(transport, func(t *testing.T) {
			var observation string
			attempt := map[string]any{"origin": "scenario", "scenario_id": "scenario-marker", "operation_id": "invoke", "json": map[string]any{"query": "baseline"}}
			draft := func() map[string]any {
				return map[string]any{"finish_reason": "no-useful-next-experiment", "summary": "Only observed effects are established.",
					"objectives":    []any{map[string]any{"objective_id": "objective-marker", "outcome": "inconclusive", "summary": "Other effects remain unresolved.", "observations": []string{observation}}},
					"uncertainties": []any{map[string]any{"kind": "evidence-gap", "description": "Internal effects were not observed."}}}
			}
			r := newProcessRun(t, processCase{transport: transport, prompt: "default", reply: func(turn int, q map[string]any) ([]byte, error) {
				if response, err := scenarioSelectionTurn(&turn, q); response != nil || err != nil {
					return response, err
				}
				if turn > 2 && !bytes.Contains(encode(q), []byte("Assessment repair is active")) {
					return nil, fmt.Errorf("repair context lost on turn %d", turn)
				}
				switch turn {
				case 1:
					return processResponse([]any{modelCall("invoke", "attempt_execute", attempt)}), nil
				case 2:
					result, err := modelToolResult(q, "invoke")
					if err != nil {
						return nil, err
					}
					observation = result["observations"].([]any)[0].(map[string]any)["observation"].(string)
					// The observation is real but has not been inspected.
					return processResponse([]any{modelCall("bad-finish", "finish", draft()), modelCall("batched-exploration", "attempt_execute", attempt)}), nil
				case 3:
					blocked, err := modelToolResult(q, "batched-exploration")
					if err != nil || blocked["diagnostic"].(map[string]any)["reason"] != "assessment_repair_active" {
						return nil, fmt.Errorf("batch exploration not blocked: %v %v", blocked, err)
					}
					var text map[string]any
					if err := json.Unmarshal(processResponse(nil), &text); err != nil {
						return nil, err
					}
					message := text["choices"].([]any)[0].(map[string]any)["message"].(map[string]any)
					message["refusal"] = nil
					message["content"] = "Choose another task: retrieve tickets or request notifications?"
					return encode(text), nil
				case 4:
					if !bytes.Contains(encode(q), []byte("not a selection from any menu")) || bytes.Contains(encode(q), []byte("Continue with the next useful tool action")) {
						return nil, fmt.Errorf("generic continuation after menu")
					}
					return processResponse([]any{modelCall("later-exploration", "attempt_execute", attempt)}), nil
				case 5:
					blocked, err := modelToolResult(q, "later-exploration")
					if err != nil || blocked["diagnostic"].(map[string]any)["reason"] != "assessment_repair_active" {
						return nil, fmt.Errorf("later exploration not blocked: %v %v", blocked, err)
					}
					return processResponse([]any{modelCall("inspect", "observation_read", map[string]any{"observation": observation}), modelCall("guide", "reference_read", map[string]any{"reference": "tool-guide:finish"})}), nil
				case 6:
					result, err := modelToolResult(q, "inspect")
					if err != nil {
						return nil, err
					}
					observation = result["citation"].(string)
					return processResponse([]any{modelCall("corrected-finish", "finish", draft())}), nil
				}
				return nil, fmt.Errorf("unexpected repair turn %d", turn)
			}})
			finishEvidenceRun(t, r)
			if !r.service.AssessmentCommitted() {
				t.Fatal("corrected assessment was not committed")
			}
			if err := r.writer.Close(); err != nil {
				t.Fatal(err)
			}
			result := harnessExport(t, r)
			if len(result.Attempts) != 1 {
				t.Fatal("repair replayed target action", result.Attempts)
			}
			count := 0
			for _, op := range r.native.calls {
				if op == "application.invoke" {
					count++
				}
			}
			if count != 1 {
				t.Fatal("unrelated operation reached native target", count)
			}
		})
	}
}

func TestHarnessProtectedFinalizationProcess(t *testing.T) {
	for _, transport := range []string{"fifo", "spool"} {
		for _, mode := range []string{"honest", "blocked", "corrected"} {
			t.Run(transport+"/"+mode, func(t *testing.T) {
				r := newProcessRun(t, processCase{transport: transport, prompt: "default", settings: func(c *preparation.LaunchConfig) {
					var err error
					s := c.Model.Settings()
					s.MaximumPromptTokens, s.MaximumCompletionTokens = 32768, 4096
					c.Model, err = modelprovider.Parse(encode(s))
					if err != nil {
						t.Fatal(err)
					}
					c.Limits, err = campaignlimits.ParseHost([]byte(`{"harness":{"max_model_turns":2}}`))
					if err != nil {
						t.Fatal(err)
					}
				}, reply: func(turn int, q map[string]any) ([]byte, error) {
					if turn > 2 || q["tool_choice"] == "none" || !bytes.Contains(encode(q), []byte("exploration has ended")) {
						return nil, fmt.Errorf("reserve not protected on turn %d", turn)
					}
					finish := map[string]any{"finish_reason": "budget-limit", "summary": "No objective was established.", "objectives": []any{map[string]any{"objective_id": "objective-marker", "outcome": "not-tested", "summary": "No target attempt was dispatched."}}}
					if turn == 1 && mode == "blocked" {
						return processResponse([]any{modelCall("blocked", "attempt_execute", map[string]any{"origin": "scenario", "scenario_id": "scenario-marker", "operation_id": "invoke", "json": map[string]any{"query": "baseline"}})}), nil
					}
					if turn == 1 && mode == "corrected" {
						finish["observations"] = []string{}
					}
					if turn == 2 && mode == "corrected" && !bytes.Contains(encode(q), []byte("Your finish submission was rejected")) {
						return nil, fmt.Errorf("repair state lost")
					}
					return processResponse([]any{modelCall(fmt.Sprint("finish-", turn), "finish", finish)}), nil
				}})
				finishEvidenceRun(t, r)
				if !r.service.AssessmentCommitted() {
					t.Fatal("finalization not accepted", r.service.WorkflowFailure(), r.output.String(), len(r.provider.requests))
				}
				if mode == "honest" && r.service.WorkflowFailure() != nil {
					t.Fatal("reserve transition became a failure", r.service.WorkflowFailure())
				}
				if err := r.writer.Close(); err != nil {
					t.Fatal(err)
				}
				result := harnessExport(t, r)
				if len(result.Attempts) != 0 {
					t.Fatal("protected exploration reached target", result.Attempts)
				}
				reserveDiagnostics := 0
				for _, d := range result.WorkflowDiagnostics {
					if d.Reason != "finalization_capacity_protected" {
						continue
					}
					reserveDiagnostics++
					// Informational status is a structured property. Operator retains
					// Harness's explanation; it does not substitute fixed host prose.
					if !d.Valid() || !d.Informational() || d.Source != "harness-local" || d.Stage != "dispatch" || d.Stopping != "" {
						t.Fatalf("reserve transition lost its informational classification: %+v", d)
					}
					if d.Detail == "" || !strings.Contains(d.Message(), d.Detail) {
						t.Fatalf("reserve transition lost the producer explanation: %+v", d)
					}
				}
				if reserveDiagnostics != 1 {
					t.Fatalf("expected one informational reserve diagnostic, got %d: %v", reserveDiagnostics, result.WorkflowDiagnostics)
				}
			})
		}
	}
}

// Local reduction must survive the real FIFO/spool process boundary, retaining
// associations and repair state without buying a summary or replaying a target.
func TestHarnessLocalContextReductionProcess(t *testing.T) {
	for _, transport := range []string{"fifo", "spool"} {
		t.Run(transport, func(t *testing.T) {
			var citation string
			draft := func() map[string]any {
				return map[string]any{"finish_reason": "no-useful-next-experiment", "summary": "Only inspected effects are established.",
					"objectives": []any{map[string]any{"objective_id": "objective-marker", "outcome": "inconclusive", "summary": "Other effects remain unknown.", "observations": []string{citation}}}}
			}
			r := newProcessRun(t, processCase{transport: transport, prompt: "default", reply: func(turn int, q map[string]any) ([]byte, error) {
				if response, err := scenarioSelectionTurn(&turn, q); response != nil || err != nil {
					return response, err
				}
				if q["tool_choice"] == "none" {
					return nil, fmt.Errorf("local reduction purchased a model summary")
				}
				var response []byte
				switch turn {
				case 1:
					response = processResponse([]any{modelCall("invoke", "attempt_execute", map[string]any{"origin": "scenario", "scenario_id": "scenario-marker", "operation_id": "invoke", "json": map[string]any{"query": "baseline"}})})
				case 2:
					for _, required := range []string{"harness-local-trimming", "verified_state_at_reduction", "scenario-marker", "execution-1", "observation-1"} {
						if !bytes.Contains(encode(q), []byte(required)) {
							return nil, fmt.Errorf("reduction lost %s", required)
						}
					}
					response = processResponse([]any{modelCall("read", "observation_read", map[string]any{"observation": "observation-1"})})
				case 3:
					read, err := modelToolResult(q, "read")
					if err != nil {
						return nil, err
					}
					citation = read["citation"].(string)
					bad := draft()
					bad["uncertainties"] = []any{map[string]any{"kind": "evidence-gap", "description": "Unresolved.", "inputs": []string{citation}}}
					response = processResponse([]any{modelCall("bad-finish", "finish", bad)})
				case 4:
					if _, err := modelRepairRejection(q, "bad-finish"); err != nil {
						return nil, err
					}
					var text map[string]any
					json.Unmarshal(processResponse(nil), &text)
					message := text["choices"].([]any)[0].(map[string]any)["message"].(map[string]any)
					message["refusal"], message["content"] = nil, "Choose a ticket or notification workflow?"
					response = encode(text)
				case 5:
					bad, err := modelRepairRejection(q, "bad-finish")
					if err != nil {
						return nil, err
					}
					if bad["diagnostic"].(map[string]any)["field_path"] != "/uncertainties/0/inputs/0" {
						return nil, fmt.Errorf("lost current correction")
					}
					if !bytes.Contains(encode(q), []byte("rejected_arguments")) || !bytes.Contains(encode(q), []byte("harness-local-trimming")) {
						return nil, fmt.Errorf("exact rejected input not restored after reduction")
					}
					response = processResponse([]any{modelCall("blocked", "attempt_execute", map[string]any{"origin": "exploratory", "operation_id": "invoke", "text": "new task"}), modelCall("reread", "observation_read", map[string]any{"observation": "observation-1"})})
				case 6:
					blocked, err := modelToolResult(q, "blocked")
					if err != nil || blocked["diagnostic"].(map[string]any)["reason"] != "assessment_repair_active" {
						return nil, fmt.Errorf("exploration not blocked: %v", err)
					}
					read, err := modelToolResult(q, "reread")
					if err != nil {
						return nil, err
					}
					citation = read["citation"].(string)
					response = processResponse([]any{modelCall("finish", "finish", draft())})
				default:
					return nil, fmt.Errorf("unexpected context workflow turn %d", turn)
				}
				if turn == 1 || turn == 4 {
					// Controlled usage reaches the profile's existing warning threshold.
					var value map[string]any
					json.Unmarshal(response, &value)
					value["usage"] = map[string]any{"prompt_tokens": 8000, "completion_tokens": 10, "total_tokens": 8010}
					response = encode(value)
				}
				return response, nil
			}})
			finishEvidenceRun(t, r)
			if !r.service.AssessmentCommitted() {
				t.Fatal("local reduction lost assessment", r.output.String(), r.service.WorkflowFailure())
			}
			if err := r.writer.Close(); err != nil {
				t.Fatal(err)
			}
			result := harnessExport(t, r)
			if len(result.Attempts) != 1 || result.Attempts[0].ScenarioID != "scenario-marker" {
				t.Fatal("target replay or origin loss", result.Attempts)
			}
		})
	}
}
