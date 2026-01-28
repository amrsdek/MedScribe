import streamlit as st
import requests
import json
import base64
from docx import Document
from PIL import Image
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- إعداد الصفحة ---
st.set_page_config(page_title="Medical Study Assistant", page_icon="🩺", layout="centered")

st.markdown("""
    <style>
    .main { direction: rtl; }
    h1 { color: #2E86C1; }
    </style>
    """, unsafe_allow_html=True)

st.title("🩺 مساعد المذاكرة لطلبة طب")
st.info("ملاحظة: تم تفعيل وضع 'Medical Mode' لقبول صور التشريح والأمراض.")

# --- 1. دالة الاتصال (مع إعدادات الأمان الطبية) ---
def call_gemini_medical(api_key, model_name, image_bytes, mime_type):
    # تصحيح نوع الصورة لتجنب أخطاء السيرفر
    if mime_type == 'image/jpg':
        mime_type = 'image/jpeg'
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    
    medical_prompt = """
    You are an expert Medical Scribe. 
    Analyze this medical image (Anatomy, Pathology, or Slides). 
    Extract all text, tables, and labels accurately. 
    - Handle Latin medical terms with high precision.
    - If the image contains anatomical diagrams, describe the labels.
    - Format output with clear headings and bullet points.
    """
    
    # إعدادات الأمان (مهمة جداً للصور الطبية)
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"}, # عشان صور التشريح
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]
    
    payload = {
        "contents": [{
            "parts": [
                {"text": medical_prompt},
                {"inline_data": {"mime_type": mime_type, "data": b64_image}}
            ]
        }],
        "safetySettings": safety_settings
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            # هنا بنطبع تفاصيل الخطأ عشان نعرف السبب لو حصل تاني
            return f"Error {response.status_code}: {response.text}"
            
    except Exception as e:
        return f"Connection Error: {str(e)}"

# --- 2. دالة الفيدباك (زي ما هي) ---
def send_feedback_to_sheet(feedback_text):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        if "gcp_service_account" not in st.secrets:
            return "بيانات الدخول للشيت غير موجودة في Secrets"
            
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Medical_App_Feedback").sheet1 
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, feedback_text])
        return True
    except Exception as e:
        return str(e)

# --- 3. اكتشاف الموديل ---
def get_available_model(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            for m in data.get('models', []):
                if 'gemini-1.5-flash' in m['name']: return m['name'].replace('models/', '')
        return "gemini-1.5-flash"
    except:
        return "gemini-1.5-flash"

# --- الواجهة ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

uploaded_files = st.file_uploader("Upload Medical Images", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🧬"):
    if not api_key:
        st.error("Please provide API Key.")
    else:
        with st.status("Analyzing Medical Data...", expanded=True):
            model_name = get_available_model(api_key)
            doc = Document()
            doc.add_heading('Medical Notes', 0)
            full_text_preview = ""
            
            progress_bar = st.progress(0)
            for i, file in enumerate(uploaded_files):
                st.write(f"Processing: {file.name}")
                
                # إرسال الصورة للدالة المعدلة
                text = call_gemini_medical(api_key, model_name, file.getvalue(), file.type)
                
                doc.add_heading(f'Source: {file.name}', level=1)
                doc.add_paragraph(text)
                doc.add_page_break()
                full_text_preview += f"--- {file.name} ---\n{text}\n\n"
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            st.success("Done! Ready for download.")
            bio = io.BytesIO()
            doc.save(bio)
            st.download_button("📥 Download Word File", bio.getvalue(), "Medical_Notes.docx")
            
            with st.expander("Preview"):
                st.text(full_text_preview)

st.markdown("---")
st.header("📝 Feedback")
with st.form("feedback"):
    fb = st.text_area("Your feedback:")
    if st.form_submit_button("Send"):
        res = send_feedback_to_sheet(fb)
        if res == True: st.success("Sent!")
        else: st.error(f"Error: {res}")
