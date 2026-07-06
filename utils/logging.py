from __future__ import annotations
import logging
import sys

def setup_logging(level: int = logging.INFO) -> None:
    # Unified log format: module + timestamp + request_id/job_id (when included in message or extra)
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
