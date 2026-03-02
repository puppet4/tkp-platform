from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
PRE_COMMIT_GATE_SCRIPT = REPO_ROOT / "scripts" / "pre_commit_ci_gate.sh"


def test_pre_commit_config_exists_and_wires_ci_gate() -> None:
    assert PRE_COMMIT_CONFIG.exists(), "缺少 .pre-commit-config.yaml"
    content = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
    assert "repo: local" in content
    assert "id: ci-gate" in content
    assert "entry: bash scripts/pre_commit_ci_gate.sh" in content
    assert "pass_filenames: false" in content


def test_pre_commit_gate_script_exists() -> None:
    assert PRE_COMMIT_GATE_SCRIPT.exists(), "缺少 pre-commit CI 门禁脚本"


def test_pre_commit_gate_script_supports_dry_run() -> None:
    env = os.environ.copy()
    env["PRE_COMMIT_DRY_RUN"] = "1"
    result = subprocess.run(
        ["bash", str(PRE_COMMIT_GATE_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "pre-commit 门禁脚本 dry-run 应成功。\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "SQL governance" in result.stdout
    assert "API full (postgres)" in result.stdout
