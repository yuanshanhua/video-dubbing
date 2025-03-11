# Video Dubbing - 视频译配自动化工具

![Python版本](https://img.shields.io/badge/python-3.11-blue)
![许可协议](https://img.shields.io/badge/license-MIT-green)

简体中文 | [English](./README_EN.md)

Video Dubbing 是一款 AI 驱动的命令行视频译配工具, 可进行语音识别 (ASR)、文本翻译、语音生成 (TTS), 实现端到端视频译配, 并支持批量处理视频文件, 一键生成多语言配音视频.

成品展示:

- [CMU15-445 数据库系统导论](https://www.bilibili.com/video/BV1Xh91YoEkt)
- [CMU15-721 高级数据库系统](https://www.bilibili.com/video/BV12291Y2E7u)
- [CS149 并行计算](https://www.bilibili.com/video/BV1d2R8YsEu8)

## ✨ 功能特性

- **功能全面**: ASR → 翻译 → TTS 全链路自动化
  - 高精度语音识别 powered by [OpenAI-Whipser](https://github.com/openai/whisper)
  - 支持使用兼容 OpenAI 的任意 LLM API 进行翻译
  - 基于 Edge-TTS 的高质量语音合成
- **配置高度灵活**: 各功能可独立开关, 以用于**字幕批量翻译**、**语音合成**等场景
- **丰富的后处理选项**: 内置音轨/字幕添加功能, 支持字幕格式自定义
- **批量处理**: 支持 glob 匹配, 一键批处理
- **多硬件支持**: 支持在 CPU/CUDA/NPU 平台上运行

## 🚀 快速开始

### 配置运行环境

**要求**: Python 3.11, ffmpeg, ffprobe

推荐使用优秀的 Python 环境管理工具 [astral-sh/uv](https://github.com/astral-sh/uv)

**安装 ffmpeg & ffprobe**:

- Windows: 下载 [此链接](https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip) 并解压, 将 `bin/ffmpeg.exe` 和 `bin/ffprobe.exe` 复制到某个位于 `PATH` 中的目录
- MacOS: `brew install ffmpeg`
- Linux: ...

### 安装 Video Dubbing

按需选择以下安装方式:

**最小安装**:

适用于无须 ASR, 仅需翻译和 TTS 的场景, 可避免安装 `pytorch, pandas` 等大型依赖项, 占用空间仅 ~20MB

```bash
pip install video-dubbing
# or
uv tool install -p 3.11 video-dubbing # with uv
```

**基础安装**:

```bash
pip install video-dubbing[asr]
# or
uv tool install -p 3.11 video-dubbing[asr] # with uv
```

**华为 NPU**:

```bash
pip install video-dubbing[npu]
# or
uv tool install -p 3.11 video-dubbing[npu] # with uv
```

理论上只要 [torch_npu](https://gitee.com/ascend/pytorch) 支持的平台都可以运行, 在 Ascend 910B3 上测试通过, 若你成功在其他平台上运行, 欢迎提交 PR 更新此处.

### 基础用法

由于配置项较多, 推荐使用配置文件设定大多数配置项. 首先生成默认配置文件:

**生成配置文件**:

```bash
dub -gc # 将在当前目录下生成 config.json, 包含默认配置
```

而后在执行时, 通过 `-c` 参数指定配置文件, 并添加其他参数覆盖配置文件中的设置:

**加载配置文件**:

```bash
dub -c config.json # 后加其他命令行参数
```

### 示例

**示例 1**: 批量转译 videos 目录下所有 mp4 文件为中文:

```bash
dub -c config.json --input-videos videos/*.mp4 --use-html
```

**示例 2**: 批量翻译 subs 目录下的字幕为中文:

```bash
dub -c config.json --input-subtitles subs/*.srt --asr False --tts False
```

## ⚠️ 注意事项

- 不建议一开始就直接批处理大量文件, 建议先尝试单个文件, 确保配置正确
- 可设置 `--debug` 及 `--log_dir` 打开调试模式并保存日志, 以便排查问题
- 上报 Issue 时请提供详细的配置信息及日志, 以便更快定位问题

文件限制:

- 视频文件支持格式取决于 ffmpeg, 常见格式如 mp4, mkv, webm 等均支持
- 字幕文件仅支持 srt 格式, 其他格式可使用 ffmpeg 转换为 srt
- 确保字幕文件编码为 UTF-8, 否则可能导致乱码问题
- 若仅指定视频, 必须开启 ASR; 若仅指定字幕, 无法开启 ASR; 若同时指定, 则二者数量和顺序必须一一对应

NPU 相关:

- 使用 NPU 时, `--device` 保持为 `cuda` 即可, 无需修改

LLM 相关:

- `--use_html` 选项当原文字幕分句良好时推荐开启(即每行都基本以句号结尾), 否则推荐关闭. 使用 whisper 转译英文视频生成的字幕一般都符合此要求.

## ⚙️ 全部配置参数

```bash
options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        加载 JSON 或 YAML 格式的配置文件 (default: None)
  -gc, --gen-config     生成默认配置文件 (default: False)
  -v, --version         show program's version number and exit

General:
  --input_videos INPUT_VIDEOS [INPUT_VIDEOS ...], --input-videos INPUT_VIDEOS [INPUT_VIDEOS ...]
                        待处理的视频文件 (default: [])
  --input_subtitles INPUT_SUBTITLES [INPUT_SUBTITLES ...], --input-subtitles INPUT_SUBTITLES [INPUT_SUBTITLES ...]
                        待处理的字幕文件 (srt 格式) (default: [])
  --asr [ASR]           语音识别开关 (default: True)
  --translate [TRANSLATE]
                        翻译开关 (default: True)
  --tts [TTS]           语音合成开关 (default: True)
  --debug [DEBUG]       调试模式 (default: False)
  --log_dir LOG_DIR, --log-dir LOG_DIR
                        日志目录, 若为空则不保存 (default: None)

ASR:
  --model MODEL         whisper 模型型号 (default: turbo)
  --model_dir MODEL_DIR, --model-dir MODEL_DIR
                        whisper 模型存储目录 (default: None)
  --device DEVICE       用于运行 ASR 相关模型的硬件设备 (default: cuda)
  --align [ALIGN]       进行词汇对齐 (default: False)
  --diarize [DIARIZE]   进行说话者分离 (default: False)
  --hf_token HF_TOKEN, --hf-token HF_TOKEN
                        Hugging Face token. 用于下载需同意用户协议的某些模型 (default: )

Translate:
  --target_lang TARGET_LANG, --target-lang TARGET_LANG
                        目标语言 (default: 简体中文)
  --base_url BASE_URL, --base-url BASE_URL
                        LLM API 地址 (default: https://api.openai.com/v1)
  --api_key API_KEY, --api-key API_KEY
                        LLM API key (default: )
  --llm_model LLM_MODEL, --llm-model LLM_MODEL
                        LLM 模型 (default: )
  --use_html [USE_HTML], --use-html [USE_HTML]
                        使用 HTML 标记请求多行翻译. 当字幕分句良好时推荐开启, 否则推荐关闭 (default: False)
  --remove_ellipsis [REMOVE_ELLIPSIS], --remove-ellipsis [REMOVE_ELLIPSIS]
                        移除字幕行尾的省略号 (default: False)
  --llm_req_rate LLM_REQ_RATE, --llm-req-rate LLM_REQ_RATE
                        LLM 请求速率 (r/s) (default: 5)
  --batch_size BATCH_SIZE, --batch-size BATCH_SIZE
                        单次请求 LLM 翻译的最大行数. 过大会提高失败率 (default: 10)

TTS:
  --voice VOICE         TTS 声音. 参考 https://gist.github.com/BettyJJ/17cbaa1de96235a7f5773b8690a20462 (default: zh-CN-YunyangNeural)
  --tts_req_rate TTS_REQ_RATE, --tts-req-rate TTS_REQ_RATE
                        TTS 请求速率 (r/10s) (default: 3)
  --audio_format AUDIO_FORMAT, --audio-format AUDIO_FORMAT
                        音频输出格式 (default: aac)
  --add_track [ADD_TRACK], --add-track [ADD_TRACK]
                        添加 TTS 音频到视频 (default: True)
  --track_title TRACK_TITLE, --track-title TRACK_TITLE
                        TTS 音轨标题. 默认使用 voice 名称 (default: None)

Subtitle:
  --soft [SOFT]         添加字幕方式 (True: 软 / False: 硬) (目前仅支持软字幕) (default: True)
  --add_asr_sub [ADD_ASR_SUB], --add-asr-sub [ADD_ASR_SUB]
                        将语音识别字幕添加到视频 (default: True)
  --asr_sub_title ASR_SUB_TITLE, --asr-sub-title ASR_SUB_TITLE
                        语音识别字幕标题 (default: None)
  --asr_sub_style ASR_SUB_STYLE, --asr-sub-style ASR_SUB_STYLE
                        语音识别字幕样式. 参考 https://github.com/yuanshanhua/video-dubbing/blob/main/docs/subtitle_style_zh.md (default: None)
  --add_trans_sub [ADD_TRANS_SUB], --add-trans-sub [ADD_TRANS_SUB]
                        将译文字幕添加到视频 (default: True)
  --trans_sub_title TRANS_SUB_TITLE, --trans-sub-title TRANS_SUB_TITLE
                        译文字幕标题 (default: None)
  --trans_sub_style TRANS_SUB_STYLE, --trans-sub-style TRANS_SUB_STYLE
                        译文字幕样式 (default: None)
  --add_bilingual_sub [ADD_BILINGUAL_SUB], --add-bilingual-sub [ADD_BILINGUAL_SUB]
                        将双语字幕添加到视频 (default: True)
  --bilingual_sub_title BILINGUAL_SUB_TITLE, --bilingual-sub-title BILINGUAL_SUB_TITLE
                        双语字幕标题 (default: None)
  --bilingual_sub_style BILINGUAL_SUB_STYLE, --bilingual-sub-style BILINGUAL_SUB_STYLE
                        双语字幕样式 (default: None)
```

## 🙏 致谢

本项目基于以下优秀开源项目:

- [OpenAI-Whisper](https://github.com/openai/whisper)
- [FFmpeg](https://ffmpeg.org/)
- [whisperX](https://github.com/m-bain/whisperX)
- [edge-tts](https://github.com/rany2/edge-tts)
- [aiolimiter](https://github.com/mjpieters/aiolimiter)
