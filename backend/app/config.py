from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "АвтоСнаб Backend MVP-2"
    database_url: str = "sqlite:///./autosnab_mvp.db"
    api_prefix: str = "/api/v1"

    class Config:
        env_file = ".env"


settings = Settings()
