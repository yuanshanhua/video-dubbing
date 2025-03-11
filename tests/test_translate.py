import json
import unittest
from dataclasses import dataclass
from pathlib import Path

from video_dubbing.args import TranslateArgument
from video_dubbing.translate import LLMTranslator


def load_translate_config(path: Path) -> dict[str, TranslateArgument] | None:
    if not path.is_file():
        return
    r = json.loads(path.read_text())
    assert isinstance(r, dict)
    return {k: TranslateArgument(**v) for k, v in r.items()}


translators = load_translate_config(Path(__file__).parent.parent / "translator.local.json")


class TestTranslate(unittest.IsolatedAsyncioTestCase):
    @dataclass
    class Case:
        lines: list[str]
        target_lang: str

    def setUp(self):
        if translators is None:
            self.skipTest("No translator config found")
        self.translator = LLMTranslator.from_args(translators["qwen-2.5-7b-free"])

    cases = [
        Case(
            [
                "Before we get to that though, just go through what's due for you guys right now.",
                "Alright, homework one and project zero are due this Sunday at midnight.",
                "If you haven't started project zero, please get started now.",
                "That's also due at the same day.",
            ],
            "简体中文",
        ),
        Case(
            [
                "Before we get to that though, just go through",
                "what's due for you guys right now. Alright, homework one and project zero",
                "are due this Sunday at midnight. If you haven't started project",
                "zero, please get started now. That's also due at the same day.",
            ],
            "简体中文",
        ),
    ]

    async def _test_translate_lines_as_html(self):
        for case in self.cases:
            result = await self.translator._translate_lines_as_html(case.lines, case.target_lang)
            self.assertEqual(len(result), len(case.lines))
            print(f"Raw lines: {case.lines}")
            print(f"Translated lines: {result}")

    async def _test_translate_lines(self):
        for case in self.cases:
            result = await self.translator.translate_lines(case.lines, case.target_lang, 0)
            print(f"Raw lines: {case.lines}")
            print(f"Translated lines: {result}")


if __name__ == "__main__":
    unittest.main()
