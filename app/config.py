from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "gemma4:e2b"
    changedetection_url: str = "http://changedetection:5000"
    changedetection_api_key: str = "localkey123"
    poll_interval: int = 60  # seconds
    database_path: str = "/app/data/noticeping.db"
    ignore_top_lines: int = 10  # 텍스트 상위 N줄 변경 무시 (헤더·배너 노이즈 방지)

    class Config:
        env_file = ".env"


settings = Settings()
