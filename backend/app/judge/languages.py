"""
Per-language build/run recipe. Everything here runs INSIDE the sandbox
container (see /sandbox/Dockerfile.*), never on the host.
"""
from app.config import settings


def _get_image(language: str) -> str:
    return settings.JUDGE_DOCKER_IMAGES.get(language, f"judge-sandbox-{language}:latest")


LANGUAGE_CONFIG = {
    "python": {
        "image": _get_image("python"),
        "source_filename": "main.py",
        "compile_cmd": None,
        "run_cmd": ["python3", "main.py"],
    },
    "cpp": {
        "image": _get_image("cpp"),
        "source_filename": "main.cpp",
        "compile_cmd": ["g++", "-O2", "-std=c++17", "-o", "main", "main.cpp"],
        "run_cmd": ["./main"],
    },
    "java": {
        "image": _get_image("java"),
        "source_filename": "Main.java",
        "compile_cmd": ["javac", "Main.java"],
        "run_cmd": ["java", "-XX:+UseSerialGC", "-Xmx{memory}m", "-Xms{memory}m", "Main"],
    },
}


def get_language_config(language: str) -> dict:
    if language not in LANGUAGE_CONFIG:
        raise ValueError(f"Unsupported language: {language}")
    config = LANGUAGE_CONFIG[language].copy()
    if language == "java":
        config["run_cmd"] = [cmd.format(memory=settings.JUDGE_MEMORY_LIMIT_MB) if "{memory}" in cmd else cmd for cmd in config["run_cmd"]]
    return config

