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

# --- إعداد الصفحة (Theme طبي) ---
st.set_page_config(page_title="Medical Study Assistant", page_icon="🩺", layout="centered")

st.markdown("""
    <style>
    .main { direction: rtl; }
    h1 { color: #2E86C1; }
    </style>
    """, unsafe_allow_html=True)

st.title("🩺 مساعد المذاكرة لطلبة طب")
st.write("ارفع صور الكتب أو المحاضرات (Anatomy, Pharma, Pathology...) وسيتم تحويلها لملف Word منسق.")

# --- 1. دالة الاتصال المباشر (Prompt طبي مخصص) ---
def call_gemini_medical(api_key, model_name, image_bytes, mime_type="image/jpeg"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    
    # الـ Prompt المخصص لطلبة الطب
    medical_prompt = """
    Act as an expert Medical Scribe and Study Assistant for medical students.
    Analyze the provided image (textbook page, slides, or handwritten notes).
    1. Extract the text accurately, paying extreme attention to Medical Terminology (Latin/English names).
    2. Format the output professionally:
       - Use bold for Disease Names, Drug Classes, or Anatomical Structures.
       - Use bullet points for Symptoms, Side Effects, or Contraindications.
    3. If there are tables, try to represent them clearly.
    4. Correct any OCR errors related to complex medical terms.
    5. Keep the language as is (English or Mix), but ensure clarity.
    """
    
    payload = {
        "contents": [{
            "parts": [
                {"text": medical_prompt},
                {"inline_data": {"mime_type": mime_type, "data": b64_image}}
            ]
        }]
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"Error: {response.status_code}"
    except Exception as e:
        return f"Connection Error: {str(e)}"

# --- 2. دالة إرسال الفيدباك لجوجل شيت ---
def send_feedback_to_sheet(feedback_text):
    try:
        # قراءة بيانات الاعتماد من Secrets
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # تحويل البيانات من الـ Secrets إلى Dictionary
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # فتح الشيت (تأكد أنك شاركت الشيت مع الايميل الموجود في ملف الـ JSON)
        # استبدل 'Medical_App_Feedback' باسم الشيت بتاعك بالظبط
        sheet = client.open("Medical_App_Feedback").sheet1 
        
        # إضافة الصف (التاريخ + الفيدباك)
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

# --- الواجهة الرئيسية ---

# التحقق من مفتاح Gemini
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

uploaded_files = st.file_uploader("Upload Medical Notes/Slides", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🧬"):
    if not api_key:
        st.error("Please provide API Key.")
    else:
        with st.status("Processing Medical Data...", expanded=True):
            model_name = get_available_model(api_key)
            doc = Document()
            doc.add_heading('Medical Study Notes', 0)
            full_text = ""
            
            progress_bar = st.progress(0)
            for i, file in enumerate(uploaded_files):
                st.write(f"Analyzing: {file.name}")
                text = call_gemini_medical(api_key, model_name, file.getvalue(), file.type)
                doc.add_heading(f'Source: {file.name}', level=1)
                doc.add_paragraph(text)
                doc.add_page_break()
                full_text += f"--- {file.name} ---\n{text}\n\n"
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            st.success("Done! Ready for download.")
            bio = io.BytesIO()
            doc.save(bio)
            st.download_button("📥 Download Word File", bio.getvalue(), "Medical_Notes.docx")
            
            with st.expander("Preview Text"):
                st.text(full_text)

st.markdown("---")

# --- قسم الفيدباك ---
st.header("📝 Feedback / Suggestions")
with st.form("feedback_form"):
    user_feedback = st.text_area("رأيك يهمنا لتطوير الأداة:")
    submitted = st.form_submit_button("إرسال الفيدباك")
    
    if submitted and user_feedback:
        if "gcp_service_account" in st.secrets:
            result = send_feedback_to_sheet(user_feedback)
            if result == True:
                st.success("شكراً! وصل الفيدباك.")
            else:
                st.error(f"حدث خطأ في الإرسال: {result}")
        else:
            st.warning("خاصية الفيدباك غير مفعلة حالياً (Credentials missing).")
