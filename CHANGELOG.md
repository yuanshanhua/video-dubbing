# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-03-14

### Added

- 允许通过 output_dir 参数指定输出目录
- 当任何 FFmpeg 命令失败时，抛出异常并报告错误

### Fixed

- 合成 MKV 时忽略不支持的流

### Changed

- tts 结果分割使用容错更好的方法
- 对 LLM 输出的检查更加严格
- 当设置 debug 时, 不删除中间文件和临时文件
- 改进日志输出

## [1.0.0] - 2025-03-11

- 发布第一个版本

[1.1.0]: https://github.com/yuanshanhua/video-dubbing/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/yuanshanhua/video-dubbing/tree/v1.0.0
