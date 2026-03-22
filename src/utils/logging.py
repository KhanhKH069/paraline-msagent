"""
src/utils/logging.py — Rich-based logger cho training pipeline.
"""

import logging
from rich.logging import RichHandler
from rich.console import Console

console = Console()


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    return logging.getLogger(name)


def log_config(config: dict, title: str = "Config"):
    from rich.table import Table
    table = Table(title=title)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    for k, v in config.items():
        table.add_row(str(k), str(v))
    console.print(table)
