import os
from dotenv import load_dotenv


# Load environment variables from .env file
load_dotenv()


class AuthConfig:
    # our code environment
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")           # user: @umotc_admin_bot
    TELEGRAM_BOT_DEV_TOKEN = os.environ.get("TELEGRAM_BOT_DEV_TOKEN", "")   # user: @umotc_admin_dev_bot
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    X_API_KEY = os.environ.get("X_API_KEY", "")
    X_API_SECRET = os.environ.get("X_API_SECRET", "")
    X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
    X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET", "")
    POST_TO_X = False


appconfig: AuthConfig = AuthConfig()
