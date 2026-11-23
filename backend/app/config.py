from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


class Settings:
    def __init__(self) -> None:
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
        self.answer_detail = os.getenv("ANSWER_DETAIL", "brief").strip().lower()
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_model = os.getenv("LLM_MODEL", "").strip()
        self.llm_judge_model = os.getenv("LLM_JUDGE_MODEL", "").strip()
        self.enable_wikipedia = os.getenv("ENABLE_WIKIPEDIA", "false").lower() in ("1", "true", "yes")
        self.price_in_per_1m = _float("PRICE_IN_PER_1M", 0.0)
        self.price_out_per_1m = _float("PRICE_OUT_PER_1M", 0.0)
        self.demo_word_delay = _float("DEMO_WORD_DELAY", 0.035)
        self.max_rounds = 5
        self.min_question_len = 10
        self.max_question_len = 2000
        self.db_path = os.getenv("DB_PATH", str(BASE_DIR / "data" / "courtroom.db"))
        self.frontend_dist = Path(os.getenv("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist")))
        self.secret_key = os.getenv("SECRET_KEY", "").strip()
        if not self.secret_key:
            import secrets
            self.secret_key = secrets.token_hex(32)
            os.environ["SECRET_KEY"] = self.secret_key
            env_file = BASE_DIR / ".env"
            try:
                content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
                if "SECRET_KEY=" in content:
                    lines = [line if not line.startswith("SECRET_KEY=") else f"SECRET_KEY={self.secret_key}" for line in content.splitlines()]
                    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                else:
                    with env_file.open("a", encoding="utf-8") as f:
                        if content and not content.endswith("\n"):
                            f.write("\n")
                        f.write(f"SECRET_KEY={self.secret_key}\n")
            except Exception:
                pass

    @property
    def cloud_ready(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)


settings = Settings()
