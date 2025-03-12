import itertools
from dataclasses import dataclass, field

from .utils import safe_glob
from .version import __version__


USAGE = f"""%(prog)s v{__version__} by @yuanshanhua
建议首先使用 -gc 生成默认配置文件并进行自定义.
而后可通过 -c <file> 加载配置文件, 并使用命令行参数覆盖必要的配置项.
使用 -h 查看所有配置项的帮助信息.

本工具通过 --input-videos 和 --input-subtitles 接收多个待处理的视频/字幕文件,
可完成 ASR(语音识别), 字幕翻译, TTS(语音合成) 及相关音频/视频/字幕的合并.
每个功能均可独立开启或关闭, 但有一定限制:
    1. 若仅输入视频, 必须开启 ASR
    2. 若仅输入字幕, 无法开启 ASR
    3. 若同时指定, 则二者数量和顺序必须一一对应
"""


@dataclass
class ASRArgument:
    _argument_group_name = "ASR"
    model: str = field(metadata={"help": "whisper 模型型号"}, default="turbo")
    model_dir: str | None = field(metadata={"help": "whisper 模型存储目录"}, default=None)
    device: str = field(metadata={"help": "用于运行 ASR 相关模型的硬件设备"}, default="cuda")
    align: bool = field(metadata={"help": "进行词汇对齐"}, default=False)
    diarize: bool = field(metadata={"help": "进行说话者分离"}, default=False)
    hf_token: str = field(metadata={"help": "Hugging Face token. 用于下载需同意用户协议的某些模型"}, default="")


@dataclass
class TranslateArgument:
    _argument_group_name = "Translate"
    target_lang: str = field(metadata={"help": "目标语言"}, default="简体中文")
    base_url: str = field(metadata={"help": "LLM API 地址"}, default="https://api.openai.com/v1")
    api_key: str = field(metadata={"help": "LLM API key"}, default="")
    llm_model: str = field(metadata={"help": "LLM 模型"}, default="")
    use_html: bool = field(
        metadata={"help": "使用 HTML 标记请求多行翻译. 当字幕分句良好时推荐开启, 否则推荐关闭"}, default=False
    )
    remove_ellipsis: bool = field(metadata={"help": "移除字幕行尾的省略号"}, default=False)
    llm_req_rate: float = field(metadata={"help": "LLM 请求速率 (r/s)"}, default=5)
    batch_size: int = field(metadata={"help": "单次请求 LLM 翻译的最大行数. 过大会提高失败率"}, default=10)


@dataclass
class TTSArgument:
    _argument_group_name = "TTS"
    voice: str = field(
        metadata={"help": "TTS 声音. 参考 https://gist.github.com/BettyJJ/17cbaa1de96235a7f5773b8690a20462"},
        default="zh-CN-YunyangNeural",
    )
    tts_req_rate: float = field(metadata={"help": "TTS 请求速率 (r/10s)"}, default=3)
    audio_format: str = field(metadata={"help": "音频输出格式"}, default="aac")
    add_track: bool = field(metadata={"help": "添加 TTS 音频到视频"}, default=True)
    track_title: str | None = field(metadata={"help": "TTS 音轨标题. 默认使用 voice 名称"}, default=None)

    def __post_init__(self):
        if self.track_title is None:
            self.track_title = self.voice


@dataclass
class SubtitleArgument:
    _argument_group_name = "Subtitle"
    soft: bool = field(metadata={"help": "添加字幕方式 (True: 软 / False: 硬) (目前仅支持软字幕)"}, default=True)
    add_asr_sub: bool = field(metadata={"help": "将语音识别字幕添加到视频"}, default=True)
    asr_sub_title: str | None = field(metadata={"help": "语音识别字幕标题"}, default=None)
    asr_sub_style: str | None = field(
        metadata={
            "help": "语音识别字幕样式. 详情参考 https://github.com/yuanshanhua/video-dubbing/blob/main/docs/subtitle_style_zh.md"
        },
        default=None,
    )
    add_trans_sub: bool = field(metadata={"help": "将译文字幕添加到视频"}, default=True)
    trans_sub_title: str | None = field(metadata={"help": "译文字幕标题"}, default=None)
    trans_sub_style: str | None = field(metadata={"help": "译文字幕样式"}, default=None)
    add_bilingual_sub: bool = field(metadata={"help": "将双语字幕添加到视频"}, default=True)
    bilingual_sub_title: str | None = field(metadata={"help": "双语字幕标题"}, default=None)
    bilingual_sub_style: str | None = field(metadata={"help": "双语字幕样式"}, default=None)

    def __post_init__(self):
        self.soft = True  # 目前仅支持软字幕


@dataclass
class GeneralArgument:
    _argument_group_name = "General"
    input_videos: list[str] = field(metadata={"help": "待处理的视频文件. 支持 glob 模式"}, default_factory=list)
    input_subtitles: list[str] = field(
        metadata={"help": "待处理的字幕文件 (srt 格式). 支持 glob 模式"}, default_factory=list
    )
    output_dir: str | None = field(metadata={"help": "输出目录. 留空则使用输入文件所在目录"}, default=None)
    asr: bool = field(metadata={"help": "语音识别开关"}, default=True)
    translate: bool = field(metadata={"help": "翻译开关"}, default=True)
    tts: bool = field(metadata={"help": "语音合成开关"}, default=True)
    debug: bool = field(metadata={"help": "调试模式"}, default=False)
    log_dir: str | None = field(metadata={"help": "日志目录, 若为空则不保存"}, default=None)

    def __post_init__(self):
        self._check_input()

    def _check_input(self):
        # 合法情况:
        # 1. videos>0, subtitles==0, asr=True
        # 2. videos==0, subtitles>0, asr=False
        # 3. videos==subtitles
        self.videos = list(itertools.chain.from_iterable([safe_glob(p) for p in self.input_videos]))
        self.subtitles = list(itertools.chain.from_iterable([safe_glob(p) for p in self.input_subtitles]))
        if not all(f.suffix == ".srt" for f in self.subtitles):
            raise ValueError("Only .srt files are supported")
        if self.videos and self.subtitles:  # 同时输入视频和字幕
            if len(self.videos) != len(self.subtitles):
                raise ValueError("Number of input videos and subtitles must match")
        elif self.videos:  # 只输入视频, 必须进行 ASR
            if not self.asr:
                raise ValueError("ASR must be enabled to process videos")
        elif self.subtitles:  # 只输入字幕, 无法进行 ASR
            if self.asr:
                raise ValueError("ASR cannot be enabled without input videos")
        else:
            self.asr = self.translate = self.tts = False
