import unittest

from video_dubbing.srt import SRT, SRTEntry
from video_dubbing.utils import len_hybrid


def new_srt_for_test(entries: list[tuple[float, float, str]]) -> SRT:
    srt_entries = [SRTEntry(i + 1, start, end, text) for i, (start, end, text) in enumerate(entries)]
    return SRT(srt_entries)


def assert_srt_text_equal(t: unittest.TestCase, srt1: SRT, srt2: SRT, msg: str):
    """断言两个字幕的文本长度相同 (使用 len_hybrid 以忽略空格和标点)"""
    t.assertEqual(
        sum(len_hybrid(s) for s in srt1.texts()),
        sum(len_hybrid(s) for s in srt2.texts()),
        msg + f":  text1: {'|'.join(srt1.texts())}  text2: {'|'.join(srt2.texts())}",
    )


def assert_srt_time_match(t: unittest.TestCase, srt1: SRT, srt2: SRT, msg: str):
    """断言两个字幕的时间轴匹配"""
    t.assertEqual(len(srt1), len(srt2), msg + ": 行数不一致")
    for e1, e2 in zip(srt1, srt2):
        t.assertAlmostEqual(
            e1.start,
            e2.start,
            msg=msg + f": 开始时间不一致 行{e1.index} {e1.start} != {e2.start}  e1: {e1.text}  e2:{e2.text}",
        )
        t.assertAlmostEqual(
            e1.end,
            e2.end,
            msg=msg + f": 结束时间不一致 行{e1.index} {e1.end} != {e2.end}  e1: {e1.text}  e2:{e2.text}",
        )


class TestSplitByLength(unittest.TestCase):
    def test_split_by_length_basic(self):
        # 创建一个包含长文本的SRT对象
        srt = new_srt_for_test(
            [
                (
                    0.0,
                    10.0,
                    "这是一段很长的中文文本，需要被分割成多个部分。This is a long English text that needs to be split into multiple parts.",
                )
            ]
        )

        # 使用split_by_length进行分割
        res = srt.split_by_length(max_length=30, min_tail_length=10)

        # 检查分割后的SRT对象
        self.assertGreater(len(res), 1, "文本应该被分割成多个部分")
        self.assertEqual(res[0].start, 0.0, "第一段的开始时间应该与原始文本相同")
        self.assertEqual(res[-1].end, 10.0, "最后一段的结束时间应该与原始文本相同")

        # 检查无文本丢失
        assert_srt_text_equal(self, srt, res, "分割后的总文本长度应与原始文本相同")

    def test_split_by_length_min_tail_length(self):
        text = "这是一段需要分割的长文本。This is a long text that needs to be split."
        entry = SRTEntry(1, 0.0, 5.0, text)
        srt = SRT([entry])

        # 设置较大的min_tail_length以测试短尾部合并
        split_srt = srt.split_by_length(max_length=20, min_tail_length=15)

        # 检查最后一段长度不应小于min_tail_length
        for i in range(1, len(split_srt)):
            self.assertGreaterEqual(len(split_srt[i].text), 15, f"分割后的尾部长度不应小于min_tail_length={15}")

    def test_no_split_for_short_entries(self):
        # 创建一个短文本的SRT对象，不需要分割
        entry = SRTEntry(1, 0.0, 5.0, "短文本。Short text.")
        srt = SRT([entry])

        # 使用较大的max_length，应该不会分割
        split_srt = srt.split_by_length(max_length=50)

        # 验证没有分割
        self.assertEqual(len(split_srt), 1, "短文本不应该被分割")
        self.assertEqual(split_srt[0].text, entry.text, "文本内容应保持不变")

    def test_time_distribution(self):
        # 创建一个长文本的SRT对象
        entry = SRTEntry(
            1,
            10.0,
            20.0,
            "这是一段很长的中文文本，需要被分割成多个部分。This is a long English text that needs to be split.",
        )
        srt = SRT([entry])

        # 分割文本
        split_srt = srt.split_by_length(max_length=20)

        # 检查时间分布
        self.assertEqual(split_srt[0].start, 10.0, "第一段的开始时间应该与原始文本相同")
        self.assertEqual(split_srt[-1].end, 20.0, "最后一段的结束时间应该与原始文本相同")

        # 检查中间部分的时间是连续的
        for i in range(len(split_srt) - 1):
            self.assertAlmostEqual(split_srt[i].end, split_srt[i + 1].start, msg="分割后的相邻段落时间应连续")


class TestSplitWithRef(unittest.TestCase):
    def _run_case(self, raw: SRT, ref: SRT):
        # 使用参考SRT进行切分
        result = raw.split_with_ref(ref)

        # 验证结果
        assert_srt_text_equal(self, result, raw, "切分后的文本长度应与原始文本相同")
        assert_srt_time_match(self, result, ref, "切分后的时间段应与参考SRT匹配")

    def test_split_with_ref_basic(self):
        cases = [
            (
                new_srt_for_test([(0.0, 10.0, "这是一个长文本, 需要根据参考字幕进行切分")]),
                new_srt_for_test([(0.0, 3.0, ""), (3.0, 5.0, ""), (5.0, 10.0, "")]),
            ),
            (
                new_srt_for_test([(0.0, 10.0, "this is a long text, need to split.")]),
                new_srt_for_test([(0.0, 3.0, ""), (3.0, 5.0, ""), (5.0, 10.0, "")]),
            ),
            (
                new_srt_for_test([(0.0, 5.0, "第一个长句子."), (5.0, 12.0, "第二个更长的句子包含更多的文本内容")]),
                new_srt_for_test([(0.0, 2.0, ""), (2.0, 5.0, ""), (5.0, 7.0, ""), (7.0, 9.0, ""), (9.0, 12.0, "")]),
            ),
        ]
        for raw, ref in cases:
            with self.subTest():
                self._run_case(raw, ref)


if __name__ == "__main__":
    unittest.main()
