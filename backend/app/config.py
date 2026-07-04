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
    google_sheets_enabled: bool = False
    google_apps_script_enabled: bool = False
    google_drive_ocr_enabled: bool = True
    google_drive_ocr_language: str = "ru"
    google_drive_ocr_folder_id: str | None = None
    google_drive_ocr_delete_temp_files: bool = True
    public_api_base_url: str = "https://YOUR_API_HOST"
    uploaded_invoices_dir: str = "uploads/invoices"

    # Document extraction pipeline. OCR remains the default, MinerU is an optional
    # local document parser that can be enabled when it is installed/configured.
    document_extraction_backend: str = "ocr"
    document_extraction_fallback_to_ocr: bool = True
    mineru_command: str | None = "mineru -p {file_path} -o {output_dir} -b pipeline"
    mineru_timeout_seconds: float = 180.0

    # iiko Server API integration for incoming invoice XML.
    iiko_integration_enabled: bool = False
    iiko_base_url: str | None = None
    iiko_login: str | None = None
    iiko_password_sha1: str | None = None
    iiko_token: str | None = None
    iiko_timeout_seconds: float = 30.0
    iiko_auto_mapping_enabled: bool = True
    iiko_mapping_min_confidence: float = 0.72

    # OCR text is structured by the built-in deterministic parser.
    # External AI parsers are not used in the current project version.

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
