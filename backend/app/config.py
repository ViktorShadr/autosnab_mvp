from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "АвтоСнаб Backend MVP-4"
    database_url: str = "sqlite:///./autosnab_mvp.db"
    api_prefix: str = "/api/v1"

    # Real OCR + Google Sheets integration.
    # Use GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_FILE
    # for service account auth.
    google_application_credentials: str | None = None
    google_service_account_file: str | None = None
    google_drive_folder_id: str | None = None
    google_sheets_enabled: bool = False
    google_vision_enabled: bool = False
    public_api_base_url: str = "https://YOUR_API_HOST"
    uploaded_invoices_dir: str = "uploads/invoices"
    google_apps_script_enabled: bool = False

    # iiko Server API integration for incoming invoice XML.
    iiko_integration_enabled: bool = False
    iiko_base_url: str | None = None
    iiko_login: str | None = None
    iiko_password_sha1: str | None = None
    iiko_token: str | None = None
    iiko_timeout_seconds: float = 30.0
    iiko_auto_mapping_enabled: bool = True
    iiko_mapping_min_confidence: float = 0.72

    # AI Agent for structuring OCR text into invoice JSON.
    # Compatible with OpenAI-style chat completions endpoints.
    ai_agent_enabled: bool = False
    ai_agent_base_url: str = "https://api.openai.com/v1/chat/completions"
    ai_agent_api_key: str | None = None
    ai_agent_model: str = "gpt-4o-mini"
    ai_agent_temperature: float = 0.1
    ai_agent_timeout_seconds: float = 60.0
    ai_agent_max_ocr_chars: int = 12000

    class Config:
        env_file = ".env"


settings = Settings()
