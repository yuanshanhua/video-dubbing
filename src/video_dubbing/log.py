import datetime
import logging
import os
import sys


logger = logging.getLogger("dub")
logger.propagate = False
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    fmt="{asctime} [{levelname: ^7}] [{name}] <{funcName}> {message}",
    datefmt="%H:%M:%S",
    style="{",
)
console = logging.StreamHandler(stream=sys.stdout)
console.setFormatter(formatter)
time = datetime.datetime.now()


def log_to_console(level=logging.INFO):
    console.setLevel(level)
    logger.addHandler(console)


def log_to_file(dir: str | None, level=logging.DEBUG):
    if dir is None:
        return
    log_file = f"{dir}/{time.year}-{time.month}-{time.day} {time.hour:02}-{time.minute:02}-{time.second:02}.log"
    os.makedirs(dir, exist_ok=True)
    file = logging.FileHandler(log_file, encoding="utf-8", delay=True)
    file.setFormatter(formatter)
    file.setLevel(level)
    logger.addHandler(file)


def get_llm_msg_logger(dir: str, name: str) -> logging.Logger:
    msg_logger = logger.getChild(name)
    msg_logger.propagate = False
    msg_logger.setLevel("DEBUG")
    formatter = logging.Formatter(fmt="{asctime} | {message}", datefmt="%H:%M:%S", style="{")
    log_file = f"{dir}/{name}-{time.year}-{time.month}-{time.day} {time.hour:02}-{time.minute:02}-{time.second:02}.log"
    os.makedirs(dir, exist_ok=True)
    file = logging.FileHandler(log_file, encoding="utf-8", delay=True)
    file.setFormatter(formatter)
    file.setLevel("DEBUG")
    msg_logger.addHandler(file)
    return msg_logger
