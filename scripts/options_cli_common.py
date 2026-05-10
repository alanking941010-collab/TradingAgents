"""Shared helpers for side-effect-free options CLI scripts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_OPTIONS_OUTPUT_ROOT = Path("~/.tradingagents/outputs/options").expanduser()
SENSITIVE_ENV_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "AUTH")


def options_output_root() -> Path:
    """Return configurable root for local options artifacts."""
    return Path(os.getenv("TRADINGAGENTS_OPTIONS_OUTPUT_ROOT", str(DEFAULT_OPTIONS_OUTPUT_ROOT))).expanduser()


def default_output_dir(kind: str) -> Path:
    """Return default output directory for one artifact kind under the configurable root."""
    env_name = f"TRADINGAGENTS_OPTIONS_{kind.upper()}_OUTPUT_DIR"
    configured = os.getenv(env_name)
    if configured:
        return Path(configured).expanduser()
    return options_output_root() / kind


def resolve_output_dir(value: str | None, *, kind: str) -> Path:
    """Resolve a CLI ``--output-dir`` value or fallback to configurable defaults."""
    if value:
        return Path(value).expanduser()
    return default_output_dir(kind)


def sanitized_subprocess_env(extra: Mapping[str, str] | None = None, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an env copy with common secret-bearing variables removed.

    Tests and local CLI wrappers only need explicit DB/output-path variables. This
    helper avoids accidentally leaking provider keys into subprocess snapshots.
    """
    source = dict(os.environ if base is None else base)
    sanitized = {
        key: value
        for key, value in source.items()
        if not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
    }
    if extra:
        sanitized.update({str(key): str(value) for key, value in extra.items()})
    return sanitized


def run_subprocess_checked(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env_extra: Mapping[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with sanitized env, text pipes, timeout, and check=True."""
    return subprocess.run(
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        env=sanitized_subprocess_env(env_extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=True,
    )
