"""Agent 沙箱执行环境。

提供隔离的代码执行环境，防止恶意代码影响系统。
"""

import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("tkp_api.agents.sandbox")


class SandboxExecutor:
    """沙箱执行器。"""

    def __init__(
        self,
        *,
        timeout: int = 30,
        max_memory_mb: int = 512,
        enable_network: bool = False,
        allowed_imports: list[str] | None = None,
    ):
        """初始化沙箱执行器。

        Args:
            timeout: 执行超时时间（秒）
            max_memory_mb: 最大内存限制（MB）
            enable_network: 是否允许网络访问
            allowed_imports: 允许的导入模块列表
        """
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.enable_network = enable_network
        self.allowed_imports = allowed_imports or [
            "math",
            "datetime",
            "json",
            "re",
            "collections",
        ]

    def execute_python(self, code: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """在沙箱中执行 Python 代码。

        Args:
            code: Python 代码
            context: 执行上下文（变量）

        Returns:
            包含 success、result、error、duration 的字典
        """
        start_time = time.time()

        # 验证代码安全性
        if not self._validate_code(code):
            return {
                "success": False,
                "result": None,
                "error": "Code validation failed: potentially unsafe code detected",
                "duration": 0,
            }

        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            temp_file = Path(f.name)
            f.write(code)

        try:
            # 使用 Docker 执行（如果可用）
            if self._is_docker_available():
                result = self._execute_in_docker(temp_file, context)
            else:
                # 回退到受限的本地执行
                result = self._execute_locally(temp_file, context)

            duration = time.time() - start_time
            result["duration"] = duration

            return result
        finally:
            # 清理临时文件
            temp_file.unlink(missing_ok=True)

    def _validate_code(self, code: str) -> bool:
        """验证代码安全性。"""
        # 禁止的关键词
        forbidden_keywords = [
            "import os",
            "import sys",
            "import subprocess",
            "import socket",
            "__import__",
            "eval(",
            "exec(",
            "compile(",
            "open(",
            "file(",
            "input(",
            "raw_input(",
        ]

        code_lower = code.lower()
        for keyword in forbidden_keywords:
            if keyword in code_lower:
                logger.warning("forbidden keyword detected: %s", keyword)
                return False

        # 检查导入
        import ast

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name not in self.allowed_imports:
                            logger.warning("forbidden import: %s", alias.name)
                            return False
                elif isinstance(node, ast.ImportFrom):
                    if node.module not in self.allowed_imports:
                        logger.warning("forbidden import from: %s", node.module)
                        return False
        except SyntaxError as exc:
            logger.warning("syntax error in code: %s", exc)
            return False

        return True

    def _is_docker_available(self) -> bool:
        """检查 Docker 是否可用。"""
        try:
            result = subprocess.run(
                ["docker", "version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _execute_in_docker(self, code_file: Path, context: dict[str, Any] | None) -> dict[str, Any]:
        """在 Docker 容器中执行代码。"""
        try:
            # 构建 Docker 命令
            docker_cmd = [
                "docker",
                "run",
                "--rm",
                f"--memory={self.max_memory_mb}m",
                f"--cpus=0.5",
                "--network=none" if not self.enable_network else "--network=bridge",
                "-v",
                f"{code_file.absolute()}:/code.py:ro",
                "python:3.11-slim",
                "python",
                "/code.py",
            ]

            # 执行
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=self.timeout,
                text=True,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "result": result.stdout.strip(),
                    "error": None,
                }
            else:
                return {
                    "success": False,
                    "result": None,
                    "error": result.stderr.strip(),
                }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "result": None,
                "error": f"Execution timeout after {self.timeout} seconds",
            }
        except Exception as exc:
            logger.exception("docker execution failed: %s", exc)
            return {
                "success": False,
                "result": None,
                "error": str(exc),
            }

    def _execute_locally(self, code_file: Path, context: dict[str, Any] | None) -> dict[str, Any]:
        """在本地受限环境中执行代码。"""
        try:
            # 读取代码
            code = code_file.read_text()

            # 创建受限的全局命名空间
            restricted_globals: dict[str, Any] = {
                "__builtins__": {
                    "print": print,
                    "len": len,
                    "range": range,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                    "tuple": tuple,
                    "set": set,
                },
            }

            # 添加允许的模块
            for module_name in self.allowed_imports:
                try:
                    module = __import__(module_name)
                    restricted_globals[module_name] = module
                except ImportError:
                    pass

            # 添加上下文变量
            if context:
                restricted_globals.update(context)

            # 执行代码
            local_namespace: dict[str, Any] = {}
            exec(code, restricted_globals, local_namespace)

            # 获取结果（假设代码定义了 result 变量）
            result = local_namespace.get("result", "Code executed successfully")

            return {
                "success": True,
                "result": str(result),
                "error": None,
            }
        except Exception as exc:
            logger.exception("local execution failed: %s", exc)
            return {
                "success": False,
                "result": None,
                "error": str(exc),
            }


def create_sandbox_executor(
    *,
    timeout: int = 30,
    max_memory_mb: int = 512,
    enable_network: bool = False,
) -> SandboxExecutor:
    """创建沙箱执行器的工厂函数。"""
    return SandboxExecutor(
        timeout=timeout,
        max_memory_mb=max_memory_mb,
        enable_network=enable_network,
    )
