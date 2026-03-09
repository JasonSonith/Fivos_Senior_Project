import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class CredentialManager:
    @staticmethod
    def get_credential(manufacturer: str, field: str) -> str | None:
        key = f"FIVOS_{manufacturer.upper()}_{field.upper()}"
        value = os.getenv(key)
        if value is None:
            logger.warning("Credential not found: %s", key)
        return value

    @staticmethod
    def get_db_uri() -> str:
        return os.getenv("FIVOS_MONGO_URI", "mongodb://localhost:27017/fivos")
