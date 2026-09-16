import streamlit as st
from config import Config
from utils import send_message
import json

# Custom CSS to reduce sidebar width and adjust padding
st.markdown("""
    <style>
        [data-testid="stSidebar"][aria-expanded="true"]{
            min-width: 250px;
            max-width: 250px;
        }
        [data-testid="stSidebar"][aria-expanded="false"]{
            margin-left: -250px;
        }
        section[data-testid="stSidebarContent"] {
            padding-top: 1rem;
            padding-right: 1rem;
        }
        .stButton button {
            width: 100%;
        }
        div[data-testid="stExpander"] {
            background-color: #262730;
        }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "show_steps" not in st.session_state:
    st.session_state.show_steps = False


def main():
    # Minimal sidebar
    with st.sidebar:
        st.write("### Settings")
        # Compact URL input
        backend_url = st.text_input(
            "Backend URL",
            value=Config.BACKEND_URL,
            key="backend_url",
            label_visibility="collapsed"
        )
        if backend_url:
            Config.BACKEND_URL = backend_url

        # Checkbox in a more compact form
        st.session_state.show_steps = st.checkbox(
            "Show context",
            value=False,
            help="Display supporting information"
        )

        # Add a small divider
        st.divider()

        # Minimal about section
        st.write("##### About")
        st.write("Query employee & business data")

    # Rest of your app code remains the same...
    st.title("Chatbot Interface")

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.markdown(message["content"])
            else:
                try:
                    output_dict = message["content"]
                    st.markdown(output_dict.get(
                        "Answer", "No answer available"))
                    with st.expander("Context Used To Provide Answer", expanded=st.session_state.show_steps):
                        st.json(output_dict.get("Context", []))
                except:  # noqa: E722
                    st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("What would you like to know?"):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            response = send_message(prompt)

            if "response" in response and "output" in response["response"]:
                output_str = response["response"]["output"]
                st.markdown(json.loads(output_str).get(
                    "Answer", "No answer available"))
                with st.expander("Context Used To Provide Answer", expanded=st.session_state.show_steps):
                    st.json(json.loads(output_str).get("Context", []))

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": output_str
                })
            else:
                st.error("Unexpected response format")


if __name__ == "__main__":
    main()