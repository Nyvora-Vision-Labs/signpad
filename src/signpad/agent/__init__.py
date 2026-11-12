"""The signing agent. ``run_agent`` needs the ``anthropic`` package and credentials."""
from .session import Session


def run_agent(*args, **kwargs):
    from .runner import run_agent as _run  # imported lazily: needs the anthropic SDK
    return _run(*args, **kwargs)


__all__ = ["Session", "run_agent"]
