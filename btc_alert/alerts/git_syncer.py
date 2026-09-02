import asyncio
from pathlib import Path

class GitSyncer:
    def __init__(self, repo_path: str = "/mnt/c/Users/manra/var/BTCSunrise"):
        self.repo_path = Path(repo_path)
        self.is_pushing = False

    async def push_updates(self, commit_msg: str = "chore: update microstructure snapshot") -> bool:
        if self.is_pushing or not (self.repo_path / ".git").exists():
            return False

        self.is_pushing = True
        try:
            cmd = (
                f"cd {self.repo_path} && "
                f"git add btc-alert/microstructure.svg btc-alert/latest_regime.json && "
                f"git diff --cached --quiet || "
                f"(git commit -m '{commit_msg}' && git push origin main)"
            )

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        finally:
            self.is_pushing = False