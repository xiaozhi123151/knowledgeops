"""Create ignored private Compose env files without printing credentials."""

import os
import secrets

from dotenv import dotenv_values

from scripts.common import ROOT


def main():
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    key = values.get("DEEPSEEK_API_KEY") or values.get("KO_DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("DeepSeek API key required in environment or private .env")
    folder = ROOT / "data" / "acceptance"
    folder.mkdir(parents=True, exist_ok=True)
    private = folder / "service.env"
    # Re-running retains the application's access key; rotation is explicit.
    prior = dotenv_values(private) if private.exists() else {}
    api_key = prior.get("KO_API_KEY") or secrets.token_urlsafe(32)
    private.write_text(f"DEEPSEEK_API_KEY={key}\nKO_API_KEY={api_key}\n", encoding="utf-8")
    if os.name != "nt":
        private.chmod(0o600)
    path = ROOT.as_posix()
    if os.name == "nt":
        path = "/mnt/" + path[0].lower() + path[2:]
    (folder / "compose.env").write_text(
        f"KO_ACCEPTANCE_ENV={path}/data/acceptance/service.env\n"
        f"KO_MODEL_DIR={path}/data/models\nKO_ACCEPTANCE_PORT=18000\n", encoding="utf-8")
    print("Private files ready under data/acceptance (Git ignored). No credentials printed.")


if __name__ == "__main__":
    main()
