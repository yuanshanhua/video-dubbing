from typing import Dict, Optional, Union

import numpy as np
import whisperx
from whisperx.types import AlignedTranscriptionResult, TranscriptionResult

from transformers.utils import is_torch_npu_available

from .types import DiarizationResult


if is_torch_npu_available():
    import torch_npu.contrib.transfer_to_npu  # type: ignore # noqa: F401

    from .wrapper import FasterWhisperPipeline, load_model
else:
    from whisperx.asr import FasterWhisperPipeline, load_model


class ASRProcessor:
    def __init__(self, device: str, model_dir: str | None):
        self.device = device
        self.model_dir = model_dir
        self.transcribe_model: Optional[FasterWhisperPipeline] = None
        self.align_models: Dict[str, tuple] = {}
        self.diarize_model = None

    def _load_transcribe_model(self, whisper_model: str, compute_type: str = "int8") -> FasterWhisperPipeline:
        """加载转写模型"""
        if self.transcribe_model is None:
            self.transcribe_model = load_model(
                whisper_arch=whisper_model,
                device=self.device,
                compute_type=compute_type,
                download_root=self.model_dir,
            )
        return self.transcribe_model

    def _load_align_model(self, language_code: str):
        """加载对齐模型"""
        if language_code not in self.align_models:
            self.align_models[language_code] = whisperx.load_align_model(
                language_code=language_code,
                device=self.device,
                model_dir=self.model_dir,
            )
        return self.align_models[language_code]

    def _load_diarize_model(self, hf_token: str):
        """加载说话者分离模型"""
        if self.diarize_model is None:
            self.diarize_model = whisperx.DiarizationPipeline(
                model_name="pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
                device=self.device,
                # todo whisperx 未暴露此处 model_dir 设置
            )
        return self.diarize_model

    def transcribe(
        self,
        *,
        audio: Union[str, np.ndarray],
        whisper_model: str,
        batch_size: int = 8,
        compute_type: str = "int8",
    ) -> TranscriptionResult:
        """
        使用 whisper 模型进行语音转文本.
        """
        if isinstance(audio, str):
            audio = whisperx.load_audio(audio)
        # 1. Transcribe with original whisper (batched)
        model = self._load_transcribe_model(whisper_model, compute_type)
        result = model.transcribe(
            audio,
            batch_size=batch_size,
            chunk_size=10,  # chunk_size 可用于控制 VAD 句长, 单位为秒. 由于 whisper 特性, 最大不超过 30.
            verbose=True,
        )
        return result

    def align(
        self,
        *,
        t_result: TranscriptionResult,
        audio: Union[str, np.ndarray],
    ) -> AlignedTranscriptionResult:
        """
        产生词汇级时间戳. 支持的语言及对应使用的具体模型参见 whisperx/alignment.py

        Args:
            t_result (TranscriptionResult): 语音转文本结果.
            audio (Union[str, np.ndarray]): 音频文件路径或 numpy 数组.

        Returns:
            AlignedTranscriptionResult: 对齐后的结果.
        """
        model_a, metadata = self._load_align_model(t_result["language"])
        result = whisperx.align(
            t_result["segments"],
            model_a,
            metadata,
            audio,
            self.device,
            return_char_alignments=False,
            print_progress=True,
        )
        return result

    def diarize(
        self,
        *,
        audio: Union[str, np.ndarray],
        t_result: Union[AlignedTranscriptionResult, TranscriptionResult],
        hf_token: str,
    ) -> DiarizationResult:
        """
        进行说话者分离.

        Args:
            t_result: 语音转文本结果或对齐后的结果.

        Returns:
            DiarizationResult: 若输入包含词汇级时间戳, 则返回结果也包含词汇级说话者信息.
        """
        if isinstance(audio, str):
            audio = whisperx.load_audio(audio)

        diarize_model = self._load_diarize_model(hf_token)
        # add min/max number of speakers if known
        diarize_segments = diarize_model(audio)
        # diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers)
        result = whisperx.assign_word_speakers(diarize_segments, t_result)
        print(diarize_segments)

        return result  # type: ignore
