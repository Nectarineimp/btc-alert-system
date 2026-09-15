import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class GitSyncer:
    def __init__(self, repo_path: str = "~/projects/BTCSunrise-datashare"):
        # expanduser resolves '~' to /home/<user> under Linux/WSL
        self.repo_path = Path(repo_path).expanduser().resolve()
        self.is_pushing = False

    async def push_updates(self, commit_msg: str = "chore: update microstructure snapshot") -> bool:
        if self.is_pushing:
            return False

        if not (self.repo_path / ".git").exists():
            logger.error("GitSyncer: .git directory not found at %s", self.repo_path)
            return False

        self.is_pushing = True
        try:
            # Stage everything under btc-alerts/ (including archive/, moves, renames, and new files)
            # git diff --cached --quiet exits 1 if changes are staged, 0 if nothing staged
            cmd = (
                f"cd {self.repo_path} && "
                f"git add btc-alerts/ && "
                f"git diff --cached --quiet || "
                f"(git commit -m '{commit_msg}' && git push origin main)"
            )

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                err_msg = stderr.decode().strip()
                logger.error("GitSyncer push failed (code %s): %s", proc.returncode, err_msg)
                return False

            return True
        except Exception as exc:
            logger.error("GitSyncer unexpected exception: %s", exc)
            return False
        finally:
            self.is_pushing = False