from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "АвтоСнаб Backend MVP-4"
    database_url: str = "sqlite:///./autosnab_mvp.db"
    api_prefix: str = "/api/v1"

    # Google Drive OCR + Google Sheets integration.
    # Основной режим: OAuth обычного Google-пользователя.
    google_auth_mode: str = "oauth"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_access_token: str | None = None
    google_oauth_refresh_token: str | None = None
    google_oauth_token_expiry: str | None = None
    google_oauth_auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    google_oauth_token_uri: str = "https://oauth2.googleapis.com/token"
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/google-oauth/callback"
    secrets_env_file: str = ".env"

    google_drive_folder_id: str | None = None
    google_target_spreadsheet_id: str | None = None
    google_target_sheet_name: str = "Накладная"
    google_target_header_row_count: int = 2
    google_conversion_exceptions_sheet_name: str | None = None
    google_sheets_enabled: bool = False
    google_apps_script_enabled: bool = False
    google_drive_ocr_enabled: bool = True
    google_drive_ocr_language: str = "ru"
    google_drive_ocr_folder_id: str | None = None
    google_drive_ocr_delete_temp_files: bool = True
    google_api_retry_attempts: int = 3
    google_api_retry_backoff_seconds: float = 0.5
    public_api_base_url: str = "https://YOUR_API_HOST"
    uploaded_invoices_dir: str = "uploads/invoices"

    # Document extraction pipeline. OpenAI is the default structuring layer;
    # PDF text, MinerU, and OCR remain evidence providers.
    document_extraction_backend: str = "openai"
    document_extraction_fallback_to_ocr: bool = True
    mineru_command: str | None = (
        "{python_executable} -m mineru.cli.client "
        "-p {file_path} -o {output_dir} -b pipeline -l cyrillic"
    )
    mineru_timeout_seconds: float = 900.0

    # iiko Server API integration for incoming invoice XML.
    iiko_integration_enabled: bool = False
    iiko_base_url: str | None = None
    iiko_login: str | None = None
    iiko_password_sha1: str | None = None
    iiko_token: str | None = None
    iiko_timeout_seconds: float = 30.0
    iiko_auto_mapping_enabled: bool = True
    iiko_mapping_min_confidence: float = 0.72

    # OpenAI structures extracted evidence. Business rules and sheet writes stay local.
    openai_api_key: str | None = None
    openai_invoice_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = 120.0
    openai_max_evidence_chars: int = 120_000
    openai_max_image_pages: int = 12
    openai_max_image_bytes: int = 12_000_000
    openai_image_detail: str = "high"
    openai_debug_log_enabled: bool = True
    openai_debug_log_dir: str = "exports/openai_debug"
    bot_upload_max_file_bytes: int = 20_000_000
    invoice_allow_header_only_documents: bool = False
    conversion_amount_tolerance: float = 0.01

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
