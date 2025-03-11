"""
此模块将 whisperx 的后端由 faster-whisper 更换为 openai-whisper 而保持接口兼容.
其主要意义是在 faster-whisper 不支持的硬件 (如 Ascend NPU) 上运行, 而仍可用 whisperx 的其他功能特性.
已验证可在 Ascend 910B3 运行.
"""

import os
from typing import List, Optional, Union

import numpy as np
import torch
from whisper import Whisper, transcribe
from whisper import load_model as load_whisper
from whisperx import load_audio
from whisperx.audio import SAMPLE_RATE
from whisperx.types import SingleSegment, TranscriptionResult
from whisperx.vad import VoiceActivitySegmentation, load_vad_model, merge_chunks

from transformers import Pipeline
from transformers.pipelines.pt_utils import PipelineIterator


class FasterWhisperPipeline(Pipeline):
    """
    Huggingface Pipeline wrapper for FasterWhisperModel.
    """

    # TODO:
    # - add support for timestamp mode
    # - add support for custom inference kwargs

    def __init__(
        self,
        model: Whisper,
        vad: VoiceActivitySegmentation,
        vad_params: dict,
        options: dict,
        device: Union[int, str, "torch.device"] = -1,
        framework="pt",
        **kwargs,
    ):
        self.model = model
        self.options = options
        self._batch_size = kwargs.pop("batch_size", None)
        self._num_workers = 1
        self._preprocess_params, self._forward_params, self._postprocess_params = self._sanitize_parameters(**kwargs)
        self.call_count = 0
        self.framework = framework
        if self.framework == "pt":
            if isinstance(device, torch.device):
                self.device = device
            elif isinstance(device, str):
                self.device = torch.device(device)
            elif device < 0:
                self.device = torch.device("cpu")
            else:
                self.device = torch.device(f"cuda:{device}")
        else:
            self.device = device

        super(Pipeline, self).__init__()
        self.vad_model = vad
        self._vad_params = vad_params

    def _sanitize_parameters(self, **kwargs):
        return {}, kwargs, {}

    def preprocess(self, input_, **kwargs):
        return input_

    def _forward(self, input_tensors, **kwargs) -> dict[str, str | list]:  # type: ignore
        return transcribe(self.model, input_tensors["inputs"], **kwargs)

    def postprocess(self, model_outputs, **kwargs):
        return model_outputs

    def get_iterator(
        self,
        inputs,
        num_workers: int,
        batch_size: int,
        preprocess_params: dict,
        forward_params: dict,
        postprocess_params: dict,
    ):
        dataset = PipelineIterator(inputs, self.preprocess, preprocess_params)
        if "TOKENIZERS_PARALLELISM" not in os.environ:
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
        # TODO hack by collating feature_extractor and image_processor

        def stack(items):
            return {"inputs": np.concatenate([x["inputs"] for x in items])}

        dataloader = torch.utils.data.DataLoader(
            dataset, num_workers=num_workers, batch_size=batch_size, collate_fn=stack
        )
        model_iterator = PipelineIterator(dataloader, self.forward, forward_params, loader_batch_size=batch_size)
        final_iterator = PipelineIterator(model_iterator, self.postprocess, postprocess_params)
        return final_iterator

    def transcribe(
        self,
        audio: Union[str, np.ndarray],
        batch_size: Optional[int] = None,
        num_workers=0,
        language: Optional[str] = None,
        chunk_size=30,
        print_progress=False,
        combined_progress=False,
        verbose=False,
    ) -> TranscriptionResult:
        if isinstance(audio, str):
            audio = load_audio(audio)

        def data(audio, segments):
            for seg in segments:
                f1 = int(seg["start"] * SAMPLE_RATE)
                f2 = int(seg["end"] * SAMPLE_RATE)
                # print(f2-f1)
                yield {"inputs": audio[f1:f2]}

        vad_segments = self.vad_model(
            {
                "waveform": torch.from_numpy(audio).unsqueeze(0),
                "sample_rate": SAMPLE_RATE,
            }
        )
        vad_segments = merge_chunks(
            vad_segments,
            chunk_size,
            onset=self._vad_params["vad_onset"],
            offset=self._vad_params["vad_offset"],
        )

        segments: List[SingleSegment] = []
        total_segments = len(vad_segments)
        decode_options = self.options
        for idx, out in enumerate(
            self.__call__(
                # type: ignore
                inputs=data(audio, vad_segments),
                num_workers=num_workers,
                **decode_options,
            )
        ):
            if print_progress:
                base_progress = ((idx + 1) / total_segments) * 100
                percent_complete = base_progress / 2 if combined_progress else base_progress
                print(f"Progress: {percent_complete:.2f}%...")
            text: str = out["text"]  # type: ignore
            language = language or out["language"]  # type: ignore
            if decode_options["language"] is None:
                decode_options["language"] = language
            if verbose:
                print(
                    f"Transcript: [{round(vad_segments[idx]['start'], 3)} --> {round(vad_segments[idx]['end'], 3)}] {text}"
                )
            segments.append(
                {
                    "text": text,
                    "start": round(vad_segments[idx]["start"], 3),
                    "end": round(vad_segments[idx]["end"], 3),
                }
            )

        return {"segments": segments, "language": decode_options["language"]}  # type: ignore


def load_model(
    whisper_arch: str,
    device: str,
    device_index=0,
    compute_type="float16",
    asr_options: Optional[dict] = None,
    language: Optional[str] = None,
    vad_model: Optional[VoiceActivitySegmentation] = None,
    vad_options: Optional[dict] = None,
    model: Optional[Whisper] = None,
    task="transcribe",
    download_root: Optional[str] = None,
    local_files_only=False,
    threads=4,
) -> FasterWhisperPipeline:
    """Load a Whisper model for inference.
    Args:
        whisper_arch - The name of the Whisper model to load.
        device - The device to load the model on.
        compute_type - The compute type to use for the model.
        options - A dictionary of options to use for the model.
        language - The language of the model. (use English for now)
        model - The WhisperModel instance to use.
        download_root - The root directory to download the model to.
        local_files_only - If `True`, avoid downloading the file and return the path to the local cached file if it exists.
        threads - The number of cpu threads to use per worker, e.g. will be multiplied by num workers.
    Returns:
        A Whisper pipeline.
    """
    model = model or load_whisper(
        name=whisper_arch,
        device=device,
        download_root=download_root,  # type: ignore
    )

    default_asr_options: dict = {
        # 以下为 transcribe 参数
        "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        "compression_ratio_threshold": 2.4,
        "logprob_threshold": -1.0,
        "no_speech_threshold": 0.6,
        "condition_on_previous_text": False,
        "initial_prompt": None,
        "word_timestamps": False,
        "prepend_punctuations": "\"'“¿([{-",
        "append_punctuations": "\"'.。,，!！?？:：”)]}、",
        "clip_timestamps": "0",
        "hallucination_silence_threshold": None,
        # 以下为 DecodingOptions
        "task": task,
        "language": language,
        "beam_size": 5,
        "best_of": 5,
        "patience": 1,
        "length_penalty": 1,
        "prompt": None,
        "prefix": None,
        "suppress_blank": True,
        "suppress_tokens": [-1],
        "without_timestamps": True,
        "max_initial_timestamp": 0.0,
        "fp16": True,
        # 以下为 openai-whisper 不支持的参数
        # "repetition_penalty": 1,
        # "no_repeat_ngram_size": 0,
        # "prompt_reset_on_temperature": 0.5,
        # "multilingual": model.is_multilingual,
        # "max_new_tokens": None,
        # "hotwords": None,
    }

    if asr_options is not None:
        default_asr_options.update(asr_options)

    default_vad_options = {"vad_onset": 0.500, "vad_offset": 0.363}

    if vad_options is not None:
        default_vad_options.update(vad_options)

    if vad_model is not None:
        vad_model = vad_model
    else:
        vad_model = load_vad_model(torch.device(device), use_auth_token=None, **default_vad_options)

    return FasterWhisperPipeline(
        model=model,
        vad=vad_model,
        options=default_asr_options,
        vad_params=default_vad_options,
    )
