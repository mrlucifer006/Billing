from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SHEET_URL: str
    ADMIN_PHONE: str
    WHATSAPP_SESSION_NAME: str = "my_session"
    MAX_RETRIES: int = 3
    RETRY_DELAY_SECONDS: int = 5
    WARNING_BUFFER_MINUTES: int = 5
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str
    
    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()

import datetime
import os

def log_debug(msg):
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("debug_output.txt", "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception as e:
        print(f"Logging failed: {e}")
