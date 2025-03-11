import unittest

from video_dubbing.utils import len_hybrid, sub_hybrid


class TestSubHybrid(unittest.TestCase):
    def test_sub_hybrid_basic(self):
        text = "中 En 中En中  En   中en? 中en, zh-en混合"
        table = {
            (0, 2): "中 ",
            (0, 3): "中 En",
            (1, 2): "",
            (1, 3): "En",
            (1, 5): "En ",
            (2, 5): "En ",
            (2, 6): "En 中",
            (3, 4): "",
            (3, 6): "中",
        }
        for (start, stop), expected in table.items():
            self.assertEqual(sub_hybrid(text, start, stop), expected, f"start={start}, stop={stop}")

    def test_sub_hybrid_length(self):
        """
        [:i] 和 [i:] 切分的两个子串的总长度应该等于原字符串长度.
        """
        text = "中 En 中En中  En   中en? 中en, zh-en混合"
        for i in range(len(text)):
            sub1 = sub_hybrid(text, 0, i)
            sub2 = sub_hybrid(text, i, None)
            self.assertEqual(len_hybrid(sub1) + len_hybrid(sub2), len_hybrid(text))


if __name__ == "__main__":
    unittest.main()
