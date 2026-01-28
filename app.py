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

# تنسيق CSS عشان يخفي أي حاجة مش مهمة ويخلي الشكل بسيط
st.markdown("""
    <style>
    .main { direction: rtl; }
    h1 { color: #2E86C1; }
    .stDeployButton {display:none;} /* إخفاء زرار النشر */
    </style>
    """, unsafe_allow_html=True)

st.title("🩺 Medical Study Assistant")
st.write("حول صور المحاضرات والكتب إلى ملف Word منسق.")

# --- 1. دالة التحليل الطبي (مثبتة على الموديل الجديد) ---
def call_gemini_medical(api_key, image_bytes, mime_type):
    # تثبيت الموديل اللي نجح معاك
    model_name = "gemini-2.5-flash"
    
    if mime_type == 'image/jpg': mime_type = 'image/jpeg'
        
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
    
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
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
            return f"Error {response.status_code}: {response.text}"
    except Exception as e:
        return f"Connection Error: {str(e)}"

# --- 2. دالة الفيدباك ---
def send_feedback_to_sheet(feedback_text):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        if "gcp_service_account" not in st.secrets:
            return "Missing Credentials"
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Medical_App_Feedback").sheet1 
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, feedback_text])
        return True
    except Exception as e:
        return str(e)

# --- الواجهة الرئيسية (المبسطة) ---

# استدعاء المفتاح من الأسرار فقط (مخفي عن الطالب)
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("System Configuration Error: API Key missing.")
    st.stop()

uploaded_files = st.file_uploader("Upload Medical Images / Slides", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🚀"):
    with st.status("Analyzing Medical Data...", expanded=True):
        doc = Document()
        doc.add_heading('Medical Study Notes', 0)
        full_text_preview = ""
        
        progress_bar = st.progress(0)
        for i, file in enumerate(uploaded_files):
            st.write(f"Processing page {i+1}...")
            # استدعاء الدالة مباشرة بدون تمرير اسم الموديل (لأنه ثابت جوه)
            text = call_gemini_medical(api_key, file.getvalue(), file.type)
            
            doc.add_heading(f'Source: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            full_text_preview += f"--- {file.name} ---\n{text}\n\n"
            progress_bar.progress((i + 1) / len(uploaded_files))
        
        st.success("Completed successfully!")
        bio = io.BytesIO()
        doc.save(bio)
        
        # زر التحميل الكبير الواضح
        st.download_button(
            label="📥 Download Word File Now",
            data=bio.getvalue(),
            file_name="Medical_Notes.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary" 
        )
        
        with st.expander("Show Preview"):
            st.text(full_text_preview)

st.markdown("---")
st.caption("Feedback Box")
with st.form("feedback"):
    fb = st.text_area("واجهت مشكلة؟ أو عندك اقتراح؟ اكتبه هنا:")
    if st.form_submit_button("Send Feedback"):
        res = send_feedback_to_sheet(fb)
        if res == True: st.success("Thanks for your feedback!")
        else: st.error("Error sending feedback.")
