from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ai_api_key: str = ""
    ai_api_base: str = "https://factchat-cloud.mindlogic.ai/v1/gateway"
    ai_model: str = "gpt-5.4-mini"
    poll_interval: int = 60  # seconds — 크롤 체크 주기
    database_path: str = "/app/data/noticeping.db"

    class Config:
        env_file = ".env"


settings = Settings()
