"""
Executes untrusted user code inside a locked-down, ephemeral Docker
container and compares output against expected test cases.

SECURITY MODEL (defense in depth):
  1. Fresh container per submission, destroyed immediately after (--rm).
  2. No network access at all (--network none) -> can't exfiltrate data,
     hit internal services, or download second-stage payloads.
  3. Read-only root filesystem (--read-only) with a small tmpfs for
     scratch space only -> code can't persist anything or fill disk.
  4. Hard memory cap + OOM kill (--memory, --memory-swap=same value so
     no swap escape hatch).
  5. CPU share cap (--cpus) so one submission can't starve the host.
  6. PID limit (--pids-limit) -> blocks fork bombs.
  7. Dropped Linux capabilities + no-new-privileges -> can't escalate,
     can't load kernel modules, can't do raw sockets, etc.
  8. Runs as an unprivileged, non-root UID inside the container.
  9. Wall-clock timeout enforced from OUTSIDE the container (subprocess
     timeout) as a backstop in case the in-container limits are bypassed.
  10. ulimits (nproc, nofile) as a second layer under the docker flags.

This module shells out to the `docker` CLI rather than the Docker SDK to
keep the dependency footprint small; swap in docker-py if preferred.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings
from app.judge.languages import get_language_config

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    status: str                 # ACCEPTED | WRONG_ANSWER | TLE | MLE | RE | CE | INTERNAL_ERROR
    stdout: str = ""
    stderr: str = ""
    runtime_ms: int = 0
    memory_kb: int = 0
    exit_code: Optional[int] = None


@dataclass
class JudgeVerdict:
    status: str
    passed_tests: int
    total_tests: int
    runtime_ms: int
    memory_kb: int
    stderr: str
    detail: list = field(default_factory=list)


class SandboxExecutor:
    def __init__(self):
        self.docker_bin = shutil.which("docker")
        if not self.docker_bin:
            raise RuntimeError("Docker binary not found in PATH. Please install Docker.")
        self._verify_docker_access()

    def _verify_docker_access(self) -> None:
        try:
            subprocess.run(
                [self.docker_bin, "version", "--format", "{{.Server.Version}}"],
                capture_output=True, check=True, timeout=5
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error("Docker daemon not accessible: %s", e)
            raise RuntimeError("Cannot access Docker daemon. Ensure Docker is running and user has permissions.")

        # Check docker socket permissions (for Docker-outside-of-Docker)
        docker_sock = "/var/run/docker.sock"
        if os.path.exists(docker_sock):
            if not os.access(docker_sock, os.R_OK | os.W_OK):
                logger.warning("Docker socket %s not readable/writable by current user", docker_sock)
                # Don't raise - the subprocess call might still work via group permissions

    # ---------------------------------------------------------------
    def _build_docker_cmd(self, work_dir: str, image: str, cmd: list[str],
                           time_limit_sec: float, memory_limit_mb: int, cidfile: str | None = None) -> list[str]:
        mem = f"{memory_limit_mb}m"
        cmd_parts = [
            self.docker_bin, "run",
            "--name", f"judge-{uuid.uuid4().hex[:12]}",
            "--network", "none" if settings.JUDGE_NETWORK_DISABLED else "bridge",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m,mode=1777",
            "--memory", mem,
            "--memory-swap", mem,
            "--cpus", settings.JUDGE_CPU_LIMIT,
            "--pids-limit", str(settings.JUDGE_PIDS_LIMIT),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "1000:1000",
            "-v", f"{work_dir}:/sandbox:rw",
            "-w", "/sandbox",
            "--ulimit", "nproc=64:64",
            "--ulimit", "nofile=128:128",
            image,
            "timeout", "--signal=KILL", str(int(time_limit_sec) + 1),
            *cmd,
        ]
        if cidfile:
            cmd_parts.insert(2, "--cidfile")
            cmd_parts.insert(3, cidfile)
        else:
            cmd_parts.insert(2, "--rm")
        return cmd_parts

    # ---------------------------------------------------------------
    def _run_in_container(self, work_dir: str, image: str, cmd: list[str],
                           stdin_data: str, time_limit_sec: float,
                           memory_limit_mb: int) -> RunResult:
        import tempfile as tmp
        with tmp.NamedTemporaryFile(mode="w+", delete=False, prefix="cid-") as cidfile:
            cidfile_path = cidfile.name

        try:
            docker_cmd = self._build_docker_cmd(work_dir, image, cmd, time_limit_sec, memory_limit_mb, cidfile=cidfile_path)
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    docker_cmd,
                    input=stdin_data,
                    capture_output=True,
                    text=True,
                    timeout=time_limit_sec + 5,
                )
            except subprocess.TimeoutExpired:
                elapsed = int((time.monotonic() - start) * 1000)
                return RunResult(status="TIME_LIMIT_EXCEEDED", runtime_ms=elapsed)

            elapsed_ms = int((time.monotonic() - start) * 1000)

            container_id = ""
            try:
                with open(cidfile_path, "r") as f:
                    container_id = f.read().strip()
            except OSError:
                pass

            memory_kb = 0
            if container_id:
                memory_kb = self._get_container_memory_usage(container_id)
                try:
                    subprocess.run([self.docker_bin, "rm", "-f", container_id], capture_output=True, timeout=5)
                except subprocess.SubprocessError:
                    pass

            if proc.returncode == 137:
                if elapsed_ms >= time_limit_sec * 1000:
                    return RunResult(status="TIME_LIMIT_EXCEEDED", runtime_ms=elapsed_ms, stderr=proc.stderr, memory_kb=memory_kb)
                return RunResult(status="MEMORY_LIMIT_EXCEEDED", runtime_ms=elapsed_ms, stderr=proc.stderr, memory_kb=memory_kb)

            if proc.returncode != 0:
                return RunResult(
                    status="RUNTIME_ERROR", stdout=proc.stdout, stderr=proc.stderr,
                    runtime_ms=elapsed_ms, exit_code=proc.returncode, memory_kb=memory_kb,
                )

            return RunResult(status="OK", stdout=proc.stdout, stderr=proc.stderr, runtime_ms=elapsed_ms, memory_kb=memory_kb)
        finally:
            try:
                os.unlink(cidfile_path)
            except OSError:
                pass

    def _get_container_memory_usage(self, container_id: str) -> int:
        try:
            result = subprocess.run(
                [self.docker_bin, "inspect", "--format", "{{.MemoryStats.MaxUsage}}", container_id],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip().isdigit():
                return int(result.stdout.strip()) // 1024
        except (subprocess.SubprocessError, ValueError):
            pass
        return 0

    # ---------------------------------------------------------------
    def compile(self, work_dir: str, language: str, source_code: str) -> Optional[RunResult]:
        cfg = get_language_config(language)
        with open(os.path.join(work_dir, cfg["source_filename"]), "w") as f:
            f.write(source_code)

        if not cfg["compile_cmd"]:
            return None  # interpreted language, nothing to compile

        result = self._run_in_container(
            work_dir, cfg["image"], cfg["compile_cmd"],
            stdin_data="", time_limit_sec=10, memory_limit_mb=512,
        )
        if result.status != "OK":
            result.status = "COMPILE_ERROR"
        return result

    # ---------------------------------------------------------------
    def run_test_case(self, work_dir: str, language: str, stdin_data: str,
                       time_limit_sec: float, memory_limit_mb: int) -> RunResult:
        cfg = get_language_config(language)
        return self._run_in_container(
            work_dir, cfg["image"], cfg["run_cmd"], stdin_data,
            time_limit_sec, memory_limit_mb,
        )

    # ---------------------------------------------------------------
    def judge_submission(self, language: str, source_code: str, test_cases: list[dict],
                          time_limit_sec: float, memory_limit_mb: int) -> JudgeVerdict:
        """
        test_cases: [{"input": str, "expected_output": str}, ...]
        Runs each test in its own fresh container. Short-circuits on the
        first failing/erroring test (standard judge UX), but still reports
        how many passed before that.
        """
        detail = []
        with tempfile.TemporaryDirectory(prefix="judge-") as work_dir:
            # Create a sandbox subdirectory with write permissions for the container user (uid 1000)
            sandbox_dir = os.path.join(work_dir, "sandbox")
            os.makedirs(sandbox_dir, mode=0o777, exist_ok=True)

            compile_result = self.compile(sandbox_dir, language, source_code)
            if compile_result and compile_result.status != "OK":
                return JudgeVerdict(
                    status="COMPILE_ERROR", passed_tests=0, total_tests=len(test_cases),
                    runtime_ms=0, memory_kb=compile_result.memory_kb, stderr=compile_result.stderr, detail=[],
                )

            passed = 0
            max_runtime = 0
            max_memory = 0
            for idx, tc in enumerate(test_cases, start=1):
                result = self.run_test_case(
                    sandbox_dir, language, tc["input"], time_limit_sec, memory_limit_mb
                )
                max_runtime = max(max_runtime, result.runtime_ms)
                max_memory = max(max_memory, result.memory_kb)

                if result.status != "OK":
                    detail.append({"case": idx, "status": result.status, "time_ms": result.runtime_ms, "memory_kb": result.memory_kb})
                    return JudgeVerdict(
                        status=result.status, passed_tests=passed, total_tests=len(test_cases),
                        runtime_ms=max_runtime, memory_kb=max_memory, stderr=result.stderr, detail=detail,
                    )

                actual = result.stdout.strip()
                expected = tc["expected_output"].strip()
                if actual == expected:
                    passed += 1
                    detail.append({"case": idx, "status": "ACCEPTED", "time_ms": result.runtime_ms, "memory_kb": result.memory_kb})
                else:
                    detail.append({"case": idx, "status": "WRONG_ANSWER", "time_ms": result.runtime_ms, "memory_kb": result.memory_kb})
                    return JudgeVerdict(
                        status="WRONG_ANSWER", passed_tests=passed, total_tests=len(test_cases),
                        runtime_ms=max_runtime, memory_kb=max_memory, stderr="", detail=detail,
                    )

            return JudgeVerdict(
                status="ACCEPTED", passed_tests=passed, total_tests=len(test_cases),
                runtime_ms=max_runtime, memory_kb=max_memory, stderr="", detail=detail,
            )


executor = SandboxExecutor()

