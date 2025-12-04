import streamlit as st
import requests
import json
import time

# Page configuration
st.set_page_config(
    page_title="Proxy MCP Client",
    page_icon="🤖",
    layout="wide"
)

# Constants
API_URL = "http://localhost:8000/api/chat"

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Main Chat Interface
col1, col2 = st.columns([0.8, 0.2])
with col1:
    st.title("Proxy MCP Client")
with col2:
    if st.button("Clear Chat History"):
        st.session_state.messages = []
        st.rerun()

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        # Display tool calls if present
        if "tool_calls" in message:
            for tool_call in message["tool_calls"]:
                with st.expander(f"🛠️ Tool Call: {tool_call['name']}", expanded=False):
                    st.code(json.dumps(tool_call['args'], indent=2), language="json")
                    
        # Display tool outputs if present (usually in a separate message or attached)
        # In this simple chat model, we might receive tool outputs as separate messages or part of the flow.
        # For now, let's assume the backend handles the conversation flow and returns the final response or tool steps.

# Chat Input
if prompt := st.chat_input("What would you like to do?"):
    # Add user message to state
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call Backend API
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            # Prepare payload
            # We send the full history to keep context, or just the new message depending on backend logic.
            # The current backend expects a list of messages.
            payload = {"messages": st.session_state.messages}
            
            with st.spinner("Thinking..."):
                response = requests.post(API_URL, json=payload)
                response.raise_for_status()
                data = response.json()
                
                # The backend returns a list of messages or the last message?
                # Looking at web_server.py, it returns: {"role": "assistant", "content": ...}
                # It seems to return the FINAL response after processing tools.
                # However, to show tool calls, we might need the backend to return intermediate steps.
                # The current `web_server.py` implementation of `/api/chat` calls `client.process_message(last_message)`.
                # `interactive_client.py`'s `process_message` returns the final response string.
                # It does NOT return the tool calls explicitly in the return value currently.
                
                # WAIT: I need to check `interactive_client.py` to see if I can get tool calls.
                # If not, I might need to modify the backend to return them.
                # For now, I will display the content returned.
                
                assistant_response = data.get("content", "")
                tool_calls = data.get("tool_calls", [])
                
                # Display tool calls immediately
                if tool_calls:
                    for tool_call in tool_calls:
                        with st.expander(f"🛠️ Tool Call: {tool_call['name']}", expanded=False):
                            st.code(json.dumps(tool_call['args'], indent=2), language="json")

                # Simulate stream or just show it
                message_placeholder.markdown(assistant_response)
                
                # Add assistant response to state
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": assistant_response,
                    "tool_calls": tool_calls
                })
                
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            message_placeholder.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})

