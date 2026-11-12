//go:build linux || darwin

package preparation_test

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/intrusiveai/operator_sandbox/internal/preparation"
)

func scenarioTask(q map[string]any) (map[string]any, error) {
	for _, value := range q["messages"].([]any) {
		m := value.(map[string]any)
		if m["role"] == "user" {
			var task map[string]any
			if err := json.NewDecoder(strings.NewReader(m["content"].(string))).Decode(&task); err == nil && task["scenario_references"] != nil {
				return task, nil
			}
		}
	}
	return nil, fmt.Errorf("missing scenario task")
}

func scenarioSelectionCall(q map[string]any, id string) (any, error) {
	task, err := scenarioTask(q)
	if err != nil {
		return nil, err
	}
	for _, value := range task["scenario_references"].([]any) {
		r := value.(map[string]any)
		if r["scenario_id"] == id {
			return modelCall("select-"+id, "reference_read", map[string]any{"reference": r["reference_id"]}), nil
		}
	}
	return nil, fmt.Errorf("scenario %s missing from index", id)
}

func mustScenarioSelection(q map[string]any) any {
	call, err := scenarioSelectionCall(q, "scenario-marker")
	if err != nil {
		panic(err)
	}
	return call
}

// Existing scripted scenarios now buy a real selection turn before their old
// sequence. This changes neither runtime state nor accounting on their behalf.
func scenarioSelectionTurn(turn *int, q map[string]any) ([]byte, error) {
	if *turn == 1 {
		call, err := scenarioSelectionCall(q, "scenario-marker")
		if err != nil {
			return nil, err
		}
		return processResponse([]any{call}), nil
	}
	*turn--
	return nil, nil
}

func TestHarnessScenarioLoadingProcess(t *testing.T) {
	for _, lane := range []string{"fifo", "spool"} {
		t.Run(lane, func(t *testing.T) {
			var snapshot string
			citations := []any{}
			run := newProcessRun(t, processCase{transport: lane, prompt: "default", change: func(in *preparation.Input) {
				snapshotInput(t)(in)
				var bundle map[string]any
				json.Unmarshal(in.Bundle, &bundle)
				first := bundle["scenarios"].([]any)[0]
				var second map[string]any
				json.Unmarshal(encode(first), &second)
				second["scenario_id"] = "second-scenario"
				bundle["scenarios"] = []any{first, second}
				in.Bundle = encode(bundle)
			}, reply: func(turn int, q map[string]any) ([]byte, error) {
				task, err := scenarioTask(q)
				if err != nil {
					return nil, err
				}
				for _, value := range q["messages"].([]any) {
					m := value.(map[string]any)
					if m["role"] == "tool" && strings.Contains(fmt.Sprint(m["content"]), "coverage_obligations") {
						return nil, fmt.Errorf("scenario body duplicated in provider tool history")
					}
				}
				active := task["scenario_bundle"].(map[string]any)["scenarios"].([]any)
				if len(task["scenario_references"].([]any)) != 2 || len(active) > 1 {
					return nil, fmt.Errorf("bad scenario projection")
				}
				selectCall := func(id string) any {
					call, e := scenarioSelectionCall(q, id)
					if e != nil {
						t.Fatal(e)
					}
					return call
				}
				switch turn {
				case 1:
					if len(active) != 0 {
						return nil, fmt.Errorf("full scenarios in initial request")
					}
					return processResponse([]any{selectCall("scenario-marker")}), nil
				case 2:
					selected, e := modelToolResult(q, "select-scenario-marker")
					if e != nil || selected["content"] != nil || selected["status"] != "scenario-selected" {
						return nil, fmt.Errorf("selection duplicated instructions")
					}
					return processResponse([]any{modelCall("snapshot", "snapshot_request", map[string]any{}), modelCall("first", "attempt_execute", processAttempt("scenario", "", []byte(`{"query":"baseline"}`), ""))}), nil
				case 3:
					result, e := modelToolResult(q, "snapshot")
					if e != nil {
						return nil, e
					}
					snapshot = result["snapshot"].(string)
					return processResponse([]any{modelCall("read-first", "observation_read", map[string]any{"observation": "observation-1"}), selectCall("second-scenario")}), nil
				case 4:
					result, e := modelToolResult(q, "read-first")
					if e != nil {
						return nil, e
					}
					citations = append(citations, result["citation"])
					if active[0].(map[string]any)["scenario_id"] != "second-scenario" {
						return nil, fmt.Errorf("active scenario not replaced")
					}
					attempt := processAttempt("scenario", "", []byte(`{"query":"followup"}`), "")
					attempt["scenario_id"] = "second-scenario"
					return processResponse([]any{modelCall("second", "attempt_execute", attempt)}), nil
				case 5:
					return processResponse([]any{modelCall("read-second", "observation_read", map[string]any{"observation": "observation-2"})}), nil
				case 6:
					result, e := modelToolResult(q, "read-second")
					if e != nil {
						return nil, e
					}
					citations = append(citations, result["citation"])
					return processResponse([]any{modelCall("restore", "restore_request", map[string]any{"snapshot": snapshot})}), nil
				case 7:
					return processResponse([]any{selectCall("scenario-marker")}), nil
				case 8:
					facts := task["execution_records"].(map[string]any)
					if len(facts["executions"].([]any)) != 2 || len(facts["restores"].([]any)) != 1 {
						return nil, fmt.Errorf("verified history lost on switch")
					}
					return processResponse([]any{modelCall("finish", "finish", map[string]any{"finish_reason": "no-useful-next-experiment", "summary": "Two scenario outputs inspected; internal effects remain unknown.", "objectives": []any{map[string]any{"objective_id": "objective-marker", "outcome": "inconclusive", "summary": "External evidence only.", "observations": citations}}})}), nil
				}
				return nil, fmt.Errorf("unexpected model turn %d", turn)
			}})
			finishEvidenceRun(t, run)
			if !run.service.AssessmentCommitted() || run.cmd.ProcessState.ExitCode() != 0 {
				t.Fatal("assessment not committed", run.output.String())
			}
			if run.native.restores != 1 {
				t.Fatal("restore lost or repeated")
			}
			if err := run.writer.Close(); err != nil {
				t.Fatal(err)
			}
			result := harnessExport(t, run)
			if len(result.Attempts) != 2 || result.Attempts[0].ScenarioID != "scenario-marker" || result.Attempts[1].ScenarioID != "second-scenario" {
				t.Fatal("scenario evidence attribution lost", result.Attempts)
			}
		})
	}
}
