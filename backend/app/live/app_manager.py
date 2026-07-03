"""Runs the target app as a child process and deploys git refs into it.

This is the layer that makes fault injection real: "inject a fault" means
"check out a branch whose history contains the bad commit and restart the
service", and remediation means "git revert the suspected commit and
redeploy". The running service genuinely degrades and genuinely recovers.
"""

import logging
import subprocess
import sys
import threading
import time

import httpx
from git import GitCommandError, Repo

from app.config import settings
from app.seed.fault_scenarios import FAULT_SCENARIOS, FaultScenario

logger = logging.getLogger(__name__)

START_TIMEOUT_S = 20


class TargetAppError(RuntimeError):
    pass


class RevertFailedError(RuntimeError):
    """The revert did not apply cleanly — commonly a sign the diagnosis is
    wrong (the suspected commit is entangled with later changes)."""


class TargetAppManager:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self.deployed_branch: str = "main"
        self.deployed_scenario_id: str | None = None
        self.last_deploy_ts: float = 0.0

    # -- process control ----------------------------------------------------

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            self._proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "main:app",
                    "--port",
                    str(settings.target_app_port),
                    "--log-level",
                    "warning",
                ],
                cwd=settings.ecommerce_repo_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._wait_healthy()
            logger.info("target app started on port %s", settings.target_app_port)

    def _wait_healthy(self) -> None:
        deadline = time.monotonic() + START_TIMEOUT_S
        url = f"{settings.target_app_url}/health"
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise TargetAppError("target app process exited during startup")
            try:
                if httpx.get(url, timeout=0.5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        raise TargetAppError("target app did not become healthy in time")

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            self._proc = None

    # -- deployment ---------------------------------------------------------

    def _repo(self) -> Repo:
        return Repo(settings.ecommerce_repo_path)

    def ensure_seeded(self) -> None:
        if not (settings.ecommerce_repo_path / ".git").exists():
            from app.seed.seed_ecommerce_repo import seed

            seed()

    def deploy_scenario(self, scenario: FaultScenario) -> dict:
        """Reseed the repo (restores pristine branches), check out the
        scenario's deploy branch, and restart the service on it."""
        from app.seed.seed_ecommerce_repo import seed

        with self._lock:
            self.stop()
            seed()
            self._repo().git.checkout(scenario.deploy_branch)
            self.deployed_branch = scenario.deploy_branch
            self.deployed_scenario_id = scenario.id
            self.start()
            self.last_deploy_ts = time.time()
            return self.status()

    def revert_commit(self, sha: str) -> str:
        """git-revert a commit on the currently deployed branch and redeploy.
        Returns the sha of the revert commit. On conflict, aborts the revert
        and brings the app back up on the unchanged code."""
        with self._lock:
            self.stop()
            repo = self._repo()
            try:
                repo.git.revert(sha, "--no-edit")
            except GitCommandError as exc:
                try:
                    repo.git.revert("--abort")
                except GitCommandError:
                    pass
                self.start()
                raise RevertFailedError(
                    f"git revert {sha[:7]} did not apply cleanly (merge conflict). "
                    "This usually means the suspected commit is entangled with "
                    "later changes — or the diagnosis is wrong."
                ) from exc
            revert_sha = repo.head.commit.hexsha
            self.start()
            self.last_deploy_ts = time.time()
            return revert_sha

    def reset(self) -> dict:
        """Back to a pristine healthy main."""
        from app.seed.seed_ecommerce_repo import seed

        with self._lock:
            self.stop()
            seed()
            self.deployed_branch = "main"
            self.deployed_scenario_id = None
            self.start()
            self.last_deploy_ts = time.time()
            return self.status()

    # -- introspection ------------------------------------------------------

    def ground_truth_commit_sha(self) -> str | None:
        """Sha of the seeded bad commit on the deployed branch, if any.
        Used only to score the diagnosis after the fact."""
        if self.deployed_scenario_id is None:
            return None
        target = FAULT_SCENARIOS[self.deployed_scenario_id].target_commit_message
        for commit in self._repo().iter_commits(self.deployed_branch, max_count=50):
            if commit.message.strip() == target:
                return commit.hexsha
        return None

    def status(self) -> dict:
        head_sha = head_message = None
        try:
            head = self._repo().head.commit
            head_sha, head_message = head.hexsha, head.message.strip()
        except Exception:  # noqa: BLE001 — repo may not be seeded yet
            pass
        return {
            "running": self.is_running(),
            "branch": self.deployed_branch,
            "head_sha": head_sha,
            "head_message": head_message,
            "port": settings.target_app_port,
            "seconds_since_deploy": (
                round(time.time() - self.last_deploy_ts) if self.last_deploy_ts else None
            ),
        }


manager = TargetAppManager()
