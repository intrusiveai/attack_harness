import json
import unittest

from attack_harness.composition import TASK_LIMIT,build_task


class Skill:
    skill_id="skill-1";name="Skill";description="Guidance"
    instructions="x"*(200<<10)


class Inputs:
    skills=(Skill(),)
    def context(self):
        return {"campaign_id":"campaign-1","launch_id":"launch-1","run_revision":1,
            "operations":[],"remaining_limits":{},"feedback":{},"omissions":[],
            "target":{"schema_version":"target/v1","source":{"kind":"synthetic"},
                "capability_projection_digest":"sha256:"+"1"*64,
                "capabilities":{"operations":[{"ref":"operation:invoke"}],"actions":[]}}}
    def bundle(self):
        return {"objectives":[{"objective_id":"objective-1","required":True,
            "description":"x"*(100<<10)}],"scenarios":[{
                "scenario_id":f"scenario-{index}","objective_refs":["objective-1"],
                "hypothesis":"y"*(8<<10),"priority":index+1,"required":False,
            } for index in range(100)]}
    def reference_index(self):
        return [{"entry_id":f"reference-{index}","path":"z"*(8<<10)}
                for index in range(100)]


class CompositionTest(unittest.TestCase):
    def test_oversized_initial_material_keeps_all_compact_handles(self):
        raw=build_task(Inputs())
        self.assertLessEqual(len(raw.encode()),TASK_LIMIT)
        task=json.loads(raw)
        self.assertEqual(len(task["scenario_index"]),100)
        self.assertEqual(len(task["reference_handles"]),100)
        self.assertEqual(task["portfolio"]["work_queue"], [{
            "objective_id":"objective-1","required":True,"scenario_count":100,
            "status":"untested","exploratory_origin_allowed":False,
        }])
        self.assertEqual(task["portfolio"]["coverage_ledger"][0]["status"],
                         "untested")
        self.assertTrue(task["selected_skills"][0]["instructions_deferred"])
        self.assertTrue(task["target"]["details_deferred"])


if __name__=="__main__":unittest.main()
