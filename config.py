import os

# Server settings
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5002
SERVER_URL = os.getenv("SERVER_URL", f"http://{SERVER_HOST}:{SERVER_PORT}")

# Database settings
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'orienttrack.db')

# Bot settings
TELEGRAM_TOKEN = "8893441781:AAGTuKYOs5odo-TVQvkPUMJUK8WY1i3ETFs"

# Safety settings
SAFETY_TIMEOUT_SECONDS = 300 # 5 minutes