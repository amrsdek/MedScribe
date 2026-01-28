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
    .stSelectbox { direction: ltr; } 
    </style>
    """, unsafe_allow_html=True)

st.title("🩺 مساعد المذاكرة لطلبة طب")
st.info("نظام اختيار الموديل الذكي: اختر الموديل المتاح من القائمة أدناه لتجنب الأخطاء.")

# --- 1. دالة جلب الموديلات المتاحة (الحل الجذري) ---
def get_working_models(api_key):
    """تجلب قائمة الموديلات المتاحة فعلياً لهذا المفتاح"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # نختار فقط الموديلات اللي بتدعم التخاطب (generateContent)
            models = [
                m['name'].replace('models/', '') 
                for m in data.get('models', []) 
                if 'generateContent' in m.get('supportedGenerationMethods', [])
            ]
            return models
        else:
            return []
    except:
        return []

# --- 2. دالة التحليل الطبي ---
def call_gemini_medical(api_key, model_name, image_bytes, mime_type):
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
    
    # إعدادات الأمان لفتح صور التشريح
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

# --- 3. دالة الفيدباك ---
def send_feedback_to_sheet(feedback_text):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        if "gcp_service_account" not in st.secrets:
            return "بيانات الشيت غير موجودة"
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Medical_App_Feedback").sheet1 
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, feedback_text])
        return True
    except Exception as e:
        return str(e)

# --- الواجهة الرئيسية ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

# --- قائمة اختيار الموديل (الجزء الجديد) ---
available_models = []
if api_key:
    available_models = get_working_models(api_key)

if available_models:
    # محاولة اختيار Flash تلقائياً لو موجود
    default_index = 0
    for i, m in enumerate(available_models):
        if 'flash' in m and '1.5' in m:
            default_index = i
            break
    
    selected_model = st.selectbox(
        "اختر الموديل (تأكد من اختيار موديل يدعم الرؤية Vision):", 
        available_models, 
        index=default_index
    )
    st.caption(f"✅ سيتم استخدام الموديل: {selected_model}")
else:
    if api_key:
        st.error("⚠️ لم يتم العثور على موديلات متاحة لهذا المفتاح. تأكد من صلاحية الـ API Key.")
    selected_model = "gemini-1.5-flash" # احتياطي

uploaded_files = st.file_uploader("ارفع الصور الطبية", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🧬"):
    if not api_key:
        st.error("الرجاء التأكد من وجود API Key")
    else:
        with st.status("جاري تحليل البيانات الطبية...", expanded=True):
            doc = Document()
            doc.add_heading('Medical Notes', 0)
            full_text_preview = ""
            
            progress_bar = st.progress(0)
            for i, file in enumerate(uploaded_files):
                st.write(f"Analyzing: {file.name}")
                text = call_gemini_medical(api_key, selected_model, file.getvalue(), file.type)
                
                doc.add_heading(f'Source: {file.name}', level=1)
                doc.add_paragraph(text)
                doc.add_page_break()
                full_text_preview += f"--- {file.name} ---\n{text}\n\n"
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            st.success("تم الانتهاء! جاهز للتحميل.")
            bio = io.BytesIO()
            doc.save(bio)
            st.download_button("📥 Download Word File", bio.getvalue(), "Medical_Notes.docx")
            
            with st.expander("Preview"):
                st.text(full_text_preview)

st.markdown("---")
st.header("📝 Feedback")
with st.form("feedback"):
    fb = st.text_area("ملاحظاتك:")
    if st.form_submit_button("إرسال"):
        res = send_feedback_to_sheet(fb)
        if res == True: st.success("تم الإرسال!")
        else: st.error(f"خطأ: {res}")
