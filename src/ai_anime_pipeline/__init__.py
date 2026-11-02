"""AI anime local pipeline package."""

from .init_project import init_project
from .scheduler import main as run_pipeline

__all__ = ["init_project", "run_pipeline"]
