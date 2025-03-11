import datetime
import logging
import os
import sys


logger = logging.getLogger("dub")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    fmt="{asctime} [{levelname: ^7}] [{name}] <{funcName}> {message}",
    datefmt="%H:%M:%S",
    style="{",
)
console = logging.StreamHandler(stream=sys.stdout)
console.setFormatter(formatter)


def log_to_console(level=logging.INFO):
    console.setLevel(level)
    logger.addHandler(console)


def log_to_file(dir: str | None, level=logging.DEBUG):
    if dir is None:
        return
    time = datetime.datetime.now()
    log_file = f"{dir}/{time.year}-{time.month}-{time.day} {time.hour:02}-{time.minute:02}-{time.second:02}.log"
    os.makedirs(dir, exist_ok=True)
    file = logging.FileHandler(log_file, encoding="utf-8", delay=True)
    file.setFormatter(formatter)
    file.setLevel(level)
    logger.addHandler(file)
