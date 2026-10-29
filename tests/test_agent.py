"""可执行测试：覆盖全部验收点。

运行：python -m unittest discover -s tests -v
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.llm import ModelClient
from src.agent.react_loop import MAX_STEPS, run
from src.agent.tools import DraftStore, Tools


def sched(material_id, time=None, tools=None, model=None):
    tools = tools or Tools(DraftStore())
    model = model or ModelClient(offline=True)
    return run(material_id, requested_time=time, model=model, tools=tools), tools


class TestNormalScheduling(unittest.TestCase):
    def test_free_slot_saves_draft(self):
        r, tools = sched("M02", "10:00")
        self.assertEqual(r.status, "draft_saved")
        self.assertEqual(len(tools.store.all()), 1)
        self.assertEqual(tools.store.all()[0].suggested_time, "10:00")

    def test_never_claims_published(self):
        r, _ = sched("M02", "10:00")
        blob = json.dumps({"final": r.final, "pending": r.pending}, ensure_ascii=False)
        self.assertNotIn("已发布", blob)
        self.assertNotIn("published", blob)


class TestMissingInfo(unittest.TestCase):
    def test_missing_fields_requested_not_blocked(self):
        r, tools = sched("M03")  # 缺 category/copyright/duration_sec
        self.assertEqual(r.status, "needs_more_info")
        self.assertTrue(any("category" in p for p in r.pending))
        self.assertEqual(len(tools.store.all()), 0)

    def test_unknown_material(self):
        r, _ = sched("MX9")
        self.assertEqual(r.status, "needs_more_info")


class TestRuleRisk(unittest.TestCase):
    def test_violation_blocks(self):
        r, tools = sched("M04")  # duration 180 > 60
        self.assertEqual(r.status, "blocked")
        self.assertEqual(len(tools.store.all()), 0)


class TestSlotConflict(unittest.TestCase):
    def test_soft_conflict_suggests_alt_and_needs_confirm(self):
        r, tools = sched("M01", "18:00")  # 18:00 被占，19:00 可用
        self.assertEqual(r.status, "needs_confirm")
        drafts = tools.store.all()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].suggested_time, "19:00")
        self.assertTrue(any("待用户确认" in p for p in r.pending))

    def test_hard_requirement_not_changed(self):
        r, tools = sched("M05", "20:00")  # hard 且被占
        self.assertEqual(r.status, "needs_confirm")
        self.assertEqual(len(tools.store.all()), 0)  # 不得擅自改时段保存
        self.assertTrue(any("硬性要求" in p for p in r.pending))


class TestIdempotency(unittest.TestCase):
    def test_duplicate_request_single_draft(self):
        tools = Tools(DraftStore())
        model = ModelClient(offline=True)
        r1 = run("M01", "18:00", model=model, tools=tools)
        r2 = run("M01", "18:00", model=model, tools=tools)
        self.assertEqual(len(tools.store.all()), 1)  # 只一份草稿
        self.assertEqual(r1.status, r2.status)

    def test_different_time_new_draft(self):
        tools = Tools(DraftStore())
        model = ModelClient(offline=True)
        run("M01", "18:00", model=model, tools=tools)
        run("M01", "19:00", model=model, tools=tools)
        self.assertEqual(len(tools.store.all()), 2)


class TestSaveFailure(unittest.TestCase):
    def test_save_failure_reported(self):
        r, tools = sched("M06", "14:00")  # 故障注入
        self.assertEqual(r.status, "save_failed")
        self.assertEqual(len(tools.store.all()), 0)
        self.assertTrue(any("保存失败" in p for p in r.pending))


class TestStepLimit(unittest.TestCase):
    def test_max_steps_returns_incomplete(self):
        class LoopingModel:
            mode = "loop"

            def decide(self, system, messages):
                return {"action": "query_slots", "args": {"date": "2026-11-01"},
                        "reason": "loop"}

        r = run("M01", model=LoopingModel(), tools=Tools(DraftStore()))
        self.assertEqual(r.status, "incomplete")
        self.assertTrue(any("超限" in p for p in r.pending))
        self.assertLessEqual(len([s for s in r.trace if s.action != "abort"]), MAX_STEPS)


if __name__ == "__main__":
    unittest.main()
