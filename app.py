import json
import urllib.parse
from google import genai
from google.genai import types
import streamlit as st
from twilio.rest import Client
from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE, SUMMARY_REQUEST_PROMPT

# Load Secrets
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID = st.secrets["TWILIO_CONTENT_SID"]

# Cache client instances to avoid redundant connections on reruns
@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)

@st.cache_resource
def get_twilio_client():
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

gemini_client = get_gemini_client()
twilio_client = get_twilio_client()
MODEL_NAME = "gemini-3.8-flash"

# Helper Functions
def clean_whatsapp_text(text): 
    if not text: 
        return "No outfit summary available." 
    text = " ".join(text.split()) 
    return text[:1500] + "..." if len(text) > 1500 else text 

def send_whatsapp(to_number, user_name, summary): 
    try: 
        # Format destination number to international E.164 (+ followed by digits)
        digits_only = "".join(filter(str.isdigit, to_number))
        clean_to = f"+{digits_only}"
        
        # Populate {{1}} with user name, {{2}} with outfit summary
        content_variables = json.dumps( 
            {"1": user_name, "2": clean_whatsapp_text(summary)}, 
            ensure_ascii=False 
        ) 

        # Send via standard Content SID template
        message = twilio_client.messages.create( 
            from_=TWILIO_WHATSAPP_FROM, 
            to=f"whatsapp:{clean_to}", 
            content_sid=TWILIO_CONTENT_SID, 
            content_variables=content_variables, 
        ) 
        return True, message.sid 

    except Exception as error: 
        return False, str(error)

def render_message(message): 
    with st.chat_message(message["role"]): 
        if message["kind"] == "text": 
            st.write(message["content"]) 
        elif message["kind"] == "image": 
            st.image(message["content"]) 

def add_message(role, kind, content): 
    if "messages" not in st.session_state:
        st.session_state.messages = []
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})

def ask_gemini(parts): 
    try: 
        return st.session_state.chat.send_message(parts).text 
    except Exception as error: 
        return f"Sorry, something went wrong: {error}" 

# Onboarding screen
if "onboarded" not in st.session_state: 
    st.title("👔 FitSnap") 
    st.caption("Snap your wardrobe. Match it. Text yourself the best outfit combos.") 
    
    with st.form("onboarding_form"): 
        name = st.text_input("Your name") 
        whatsapp_number = st.text_input( 
            "WhatsApp number (with country code)", 
            placeholder="+91XXXXXXXXXX", 
        ) 
        submitted = st.form_submit_button("Let's go 🚀") 
        
    if submitted: 
        if not name.strip() or not whatsapp_number.strip(): 
            st.warning("Please fill in both your name and WhatsApp number.") 
        else: 
            st.session_state.name = name.strip() 
            st.session_state.whatsapp_number = whatsapp_number.strip() 
            st.session_state.chat = gemini_client.chats.create( 
                model=MODEL_NAME, 
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT), 
            ) 
            st.session_state.messages = [] 
            st.session_state.onboarded = True 
            st.rerun() 
            
    st.stop()

# Ensure chat session & message list exist across page refreshes
if "chat" not in st.session_state:
    st.session_state.chat = gemini_client.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )

if "messages" not in st.session_state:
    st.session_state.messages = []

user_name = st.session_state.get("name", "Friend")
user_number = st.session_state.get("whatsapp_number", "")

# Header UI
header_col, button_col = st.columns([5, 2], vertical_alignment="center") 

with header_col: 
    st.title("👔 FitSnap") 

with button_col: 
    send_disabled = len(st.session_state.messages) <= 1
    if st.button("📤 Send to WhatsApp", disabled=send_disabled, use_container_width=True): 
        with st.spinner("Summarizing your outfit choices..."): 
            summary = ask_gemini([SUMMARY_REQUEST_PROMPT]) 
        success, info = send_whatsapp(user_number, user_name, summary) 
        if success: 
            st.success("Sent! Check your WhatsApp 📲") 
        else: 
            st.error(f"Couldn't send that: {info}")

# Render initial welcome message
if not st.session_state.messages: 
    add_message("assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=user_name)) 

# Render conversation history
for message in st.session_state.messages: 
    render_message(message)

# Sidebar
with st.sidebar:
    st.write(f"Logged in as: **{user_name}**")
    st.write(f"Target Number: `{user_number}`")

# Chat Input with Attachment Support
chat_payload = st.chat_input( 
    "Ask a question or attach a photo of your wardrobe...", 
    accept_file=True, 
    file_type=["jpg", "jpeg", "png"], 
) 

if chat_payload: 
    photo = chat_payload.files[0] if chat_payload.files else None 
    text = chat_payload.text 
    parts = [] 

    if photo is not None: 
        photo_bytes = photo.getvalue() 
        add_message("user", "image", photo_bytes) 
        parts.append(types.Part.from_bytes(data=photo_bytes, mime_type=photo.type)) 
        
    if text: 
        add_message("user", "text", text) 
        parts.append(text) 
    elif photo is not None: 
        parts.append("Analyze these clothes and give me the best outfit combinations.") 

    with st.spinner("Matching outfit combinations..."): 
        answer = ask_gemini(parts) 
        add_message("assistant", "text", answer) 
        
    st.rerun()