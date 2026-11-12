"""自拍构图回归：自拍模式不得画出第三条手臂，全身要求改走他人/支架持机分支。"""

import ast
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (PLUGIN_DIR / "main.py").read_text(encoding="utf-8")
OPTIMIZER_SOURCE = (PLUGIN_DIR / "core" / "prompt_optimizer.py").read_text(encoding="utf-8")

FULL_BODY_ACTIONS = (
    "全身竖构图自拍，纯白背景，一只手抬到脸旁边",
    "帮我拍一张全身照",
    "从头到脚都拍进去",
    "整身入镜，站在窗边",
    "全身照，站着别动",
)

SELF_SHOT_ACTIONS = (
    "自拍一张，比个耶",
    "和朋友一起自拍",
    "对着镜子自拍",
    "来张自拍",
)


def _external_camera_hints():
    for node in ast.walk(ast.parse(MAIN_SOURCE)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_external_camera_hints"
            for target in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("main.py 里找不到 _external_camera_hints")


class SelfieFramingTest(unittest.TestCase):
    def test_full_body_request_uses_external_camera(self):
        hints = _external_camera_hints()
        for action in FULL_BODY_ACTIONS:
            with self.subTest(action=action):
                self.assertTrue(any(hint in action for hint in hints))

    def test_plain_selfie_stays_self_shot(self):
        hints = _external_camera_hints()
        for action in SELF_SHOT_ACTIONS:
            with self.subTest(action=action):
                self.assertFalse(any(hint in action for hint in hints))

    def test_selfie_mode_forbids_extra_limbs(self):
        for phrase in (
            "Draw exactly two arms and two hands",
            "no third arm",
            "clips through, or merges into the clothing",
            "never imply that someone else is holding the camera",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, OPTIMIZER_SOURCE)


if __name__ == "__main__":
    unittest.main()
