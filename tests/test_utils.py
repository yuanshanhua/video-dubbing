import unittest

from video_dubbing.utils import len_hybrid, sub_hybrid


class TestSubHybrid(unittest.TestCase):
    def _run_cases(self, text, cases: dict[tuple[int, int], str]):
        for (start, end), expected in cases.items():
            self.assertEqual(
                sub_hybrid(text, start, end),
                expected,
                f"s={start}, e={end}, raw_sub={text[start:end]}, expected={expected}",
            )

    def test_basic(self):
        text = "中 E3n 6中E9"
        table = {
            (0, 1): "中",
            (0, 2): "中 ",
            (0, 3): "中 E3n",
            (1, 2): "",
            (1, 3): "E3n",
            (1, 5): "E3n",
            (2, 5): "E3n",
            (2, 6): "E3n ",
            (2, 7): "E3n 6",
            (2, 8): "E3n 6中",
            (3, 4): "",
            (3, 6): "",
        }
        self._run_cases(text, table)

    def test_start_greater_than_stop(self):
        """
        测试start大于stop时,应返回空字符串
        """
        text = "中 En 中En中  En   中en? 中en, zh-en混合"
        cases = dict.fromkeys([(5, 3), (10, 5), (15, 10), (20, 15), (30, 20)], "")
        self._run_cases(text, cases)

    def test_special_characters(self):
        chars = r"!@#$%^&*()_+[]{}|~ -`·～;':\",./<>?》《。，、；：【】‘’“”……—"
        word_chars = r"$^_+|~-`～<>—"  # 被视为单词组成的字符
        for i in range(len(chars)):
            word_char = sub_hybrid(chars, i, None)[0]
            # print(f"单词开始: [{word_char}]", f"字串开始: [{chars[i:][0]}]")
            self.assertIn(word_char, word_chars, f"字符 {chars[i]} 应被视为组成单词的字符")

    def test_word_boundary(self):
        """
        测试单词边界处理
        """
        text = "Hello 世界 World"
        self.assertEqual(sub_hybrid(text, 0, 6), "Hello ")
        self.assertEqual(sub_hybrid(text, 6, 9), "世界 ")
        self.assertEqual(sub_hybrid(text, 9, None), "World")

    def test_negative_index(self):
        """
        测试负索引. 负索引应该从字符串末尾开始计算.
        """
        text = "zh-en混合"
        cases = {
            (-1, None): "合",
            (-2, -1): "混",
            (-6, None): "混合",
        }
        self._run_cases(text, cases)

    def test_index_out_of_range(self):
        """
        测试索引范围. 超出范围的索引应该返回空字符串.
        """
        text = "text"
        self.assertEqual(sub_hybrid(text, len(text), len(text) + 1), "")


class TestLenHybrid(unittest.TestCase):
    def _run_cases(self, cases: dict[str, int]):
        for text, expected in cases.items():
            self.assertEqual(len_hybrid(text), expected, f"raw_len={len(text)}, expected={expected}")

    def test_basic(self):
        cases = {
            "中 E3n 6中E9": 5,
            "Hello?世界(World)": 4,
            "zh-en混合": 3,
            "中En中En中": 5,
        }
        self._run_cases(cases)


if __name__ == "__main__":
    unittest.main()
