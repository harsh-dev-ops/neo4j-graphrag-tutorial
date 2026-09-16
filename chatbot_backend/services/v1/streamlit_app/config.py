import os

class Config:
    # Use container name when running in Docker, fallback to localhost for local development
    BACKEND_URL = os.getenv("BACKEND_URL", "http://fastapi_app:8000")
    APP_TITLE = "Chatbot Interface"
    APP_DESCRIPTION = "This chatbot helps you query information about employees and other business data."