from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "gemma4:e2b"
    changedetection_url: str = "http://changedetection:5000"
    changedetection_api_key: str = "localkey123"
    poll_interval: int = 60  # seconds
    database_path: str = "/app/data/visualmonitor.db"

    class Config:
        env_file = ".env"


settings = Settings()
