import unittest

from video_dubbing.srt import SRT, SRTEntry


class TestSplitByLength(unittest.TestCase):
    def test_split_by_length_basic(self):
        # 创建一个包含长文本的SRT对象
        entry = SRTEntry(
            1,
            0.0,
            10.0,
            "这是一段很长的中文文本，需要被分割成多个部分。This is a long English text that needs to be split into multiple parts.",
        )
        srt = SRT([entry])

        # 使用split_by_length进行分割
        split_srt = srt.split_by_length(max_length=30, min_tail_length=10)

        # 检查分割后的SRT对象
        self.assertGreater(len(split_srt), 1, "文本应该被分割成多个部分")
        self.assertEqual(split_srt[0].start, 0.0, "第一段的开始时间应该与原始文本相同")
        self.assertEqual(split_srt[-1].end, 10.0, "最后一段的结束时间应该与原始文本相同")

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


if __name__ == "__main__":
    unittest.main()
