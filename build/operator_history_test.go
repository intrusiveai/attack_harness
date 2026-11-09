//go:build linux || darwin

// Harness-local overlay: remove complete old exchanges and finish honestly,
// preserving the full model record outside the current prompt.
package preparation_test

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func processText(text string) []byte {
	var v map[string]any
	_ = json.Unmarshal(processResponse(nil), &v)
	m := v["choices"].([]any)[0].(map[string]any)["message"].(map[string]any)
	m["refusal"] = nil
	m["content"] = text
	return encode(v)
}

func TestPythonProcessLargeHistoryCompaction(t *testing.T) {
	for _, transport := range []string{"fifo", "spool"} {
		t.Run(transport, func(t *testing.T) {
			reply := func(turn int, q map[string]any) ([]byte, error) {
				switch turn {
				case 1:
					// Cross the production 1 MiB threshold with a complete native
					// exchange. Reduction must not purchase another model call.
					// The transport carries history only; fixed host prompt/tools are
					// added later and must not trigger this wire-size fixture.
					relay := map[string]any{"purpose": "generation", "conversation": q["messages"].([]any)[1:]}
					count := (1 << 20) - len(encode(relay)) + 8192
					if count <= 512<<10 || count >= (1<<20)+8192 {
						return nil, fmt.Errorf("unexpected initial request size")
					}
					return processText(strings.Repeat("x", count)), nil
				case 2:
					raw := string(encode(q))
					if q["tool_choice"] != "auto" || !strings.Contains(raw, "harness-local-trimming") || !strings.Contains(raw, "omitted_complete_groups") || !strings.Contains(raw, "objective-marker") || len(encode(q)) >= 1<<20 {
						return nil, fmt.Errorf("local reduction lost task, provenance, or request bound")
					}
					if strings.Contains(raw, strings.Repeat("x", 1024)) || strings.Contains(raw, "model-generated-not-evidence") {
						return nil, fmt.Errorf("removed history retained or a model summary was purchased")
					}
					return processResponse([]any{modelCall("finish", "finish", map[string]any{
						"finish_reason": "no-useful-next-experiment", "summary": "No target attempt ran.",
						"objectives": []any{map[string]any{"objective_id": "objective-marker", "outcome": "not-tested", "summary": "No evidence was collected."}},
					})}), nil
				default:
					return nil, fmt.Errorf("unexpected model turn %d", turn)
				}
			}
			r := newProcessRun(t, processCase{transport: transport, prompt: "default", reply: reply})
			r.finish(t)
			if !r.service.AssessmentCommitted() {
				t.Fatal("honest zero-attempt assessment was not committed")
			}
			if len(r.provider.requests) != 2 {
				t.Fatal("local reduction must not consume a model turn", len(r.provider.requests))
			}
		})
	}
}
