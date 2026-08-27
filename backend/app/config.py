"""
Central configuration. All values overridable via environment variables,
which is how docker-compose / k8s / CI inject real secrets.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Core ---
    APP_NAME: str = "Online Judge"
    ENV: str = "development"

    # --- Database ---
    # Defaults to local SQLite for zero-config dev; docker-compose points
    # this at Postgres in real deployments.
    DATABASE_URL: str = "sqlite:///./judge.db"

    # --- Auth ---
    # SECURITY: Must be set via environment variable in production!
    # No default provided - will raise validation error if not set.
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # --- Redis / Queue ---
    REDIS_URL: str = "redis://localhost:6379/0"
    SUBMISSION_QUEUE: str = "submissions"
    # Job timeout for RQ worker (seconds)
    JOB_TIMEOUT: int = 120

    # --- Judge sandbox limits ---
    JUDGE_TIME_LIMIT_SEC: int = 5
    JUDGE_MEMORY_LIMIT_MB: int = 256
    JUDGE_CPU_LIMIT: str = "1.0"        # docker --cpus
    JUDGE_PIDS_LIMIT: int = 64          # fork-bomb protection
    JUDGE_NETWORK_DISABLED: bool = True
    JUDGE_DOCKER_IMAGES: dict = {
        "python": "judge-sandbox-python:latest",
        "cpp": "judge-sandbox-cpp:latest",
        "java": "judge-sandbox-java:latest",
    }

    class Config:
        env_file = ".env"


settings = Settings()

