from typing import NotRequired, TypedDict


class Word(TypedDict):
    word: str
    start: float
    end: float
    score: float
    speaker: str


class Segment(TypedDict):
    text: str
    start: float
    end: float
    speaker: str
    words: NotRequired[list[Word]]  # 仅包含本句的词信息


class DiarizationResult(TypedDict):
    segments: list[Segment]
    word_segments: NotRequired[list[Word]]
    language: str
