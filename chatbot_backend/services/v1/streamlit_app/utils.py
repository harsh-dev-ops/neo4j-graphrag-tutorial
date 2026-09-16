import requests
import streamlit as st
from config import Config

def send_message(message: str) -> str:
    """
    Send message to the FastAPI backend and handle response
    """
    try:
        response = requests.post(
            f"{Config.BACKEND_URL}/chat",
            params={"query": message},
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        
        # Simply return the response dict
        return data
        
    except requests.exceptions.ConnectionError:
        error_msg = f"Unable to connect to backend at {Config.BACKEND_URL}"
        st.error(error_msg)
        return {"error": error_msg}
    except requests.exceptions.RequestException as e:
        error_msg = f"Error: {str(e)}"
        st.error(error_msg)
        return {"error": error_msg}