from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_sql_governance.sh"


def _run_check_sql_governance(env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_sql_governance_passes_on_repo_baseline() -> None:
    result = _run_check_sql_governance()
    assert result.returncode == 0, (
        "当前仓库基线应通过 SQL 治理校验。\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_check_sql_governance_works_without_ripgrep() -> None:
    # 在 CI 环境可能没有 rg，脚本需要自动降级到 grep。
    result = _run_check_sql_governance(env={"PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, (
        "当环境缺少 rg 时，SQL 治理脚本应可降级执行并通过。\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
