import streamlit as st
import requests
import json
import base64
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
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
    .stDeployButton {display:none;}
    </style>
    """, unsafe_allow_html=True)

st.title("🩺 Medical Study Assistant")
st.write("حول صور المحاضرات والكتب إلى ملف Word منسق.")

# --- دالة ضبط تنسيق ملف الوورد (الجزء الجديد) ---
def setup_word_styles(doc):
    # 1. ضبط الخط الأساسي للنص العادي (Normal)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(12)
    font.bold = False
    # إجبار الوورد على استخدام Times New Roman للعربي والإنجليزي
    rPr = style.element.get_or_add_rPr()
    rPr.rFonts.set(qn('w:ascii'), 'Times New Roman')
    rPr.rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')
    rPr.rFonts.set(qn('w:cs'), 'Times New Roman')

    # 2. ضبط العناوين الرئيسية (Heading 1) لتكون 14 و Bold
    h1_style = doc.styles['Heading 1']
    h1_font = h1_style.font
    h1_font.name = 'Times New Roman'
    h1_font.size = Pt(14)
    h1_font.bold = True
    h1_font.color.rgb = None # جعل اللون أسود تلقائي (بدل الأزرق الافتراضي)
    
    # 3. ضبط عنوان المستند (Title)
    title_style = doc.styles['Title']
    title_font = title_style.font
    title_font.name = 'Times New Roman'
    title_font.size = Pt(16) # ممكن نخليه أكبر سنة للعنوان الرئيسي
    title_font.bold = True
    title_font.color.rgb = None

# --- دالة التحليل الطبي ---
def call_gemini_medical(api_key, image_bytes, mime_type):
    model_name = "gemini-2.5-flash"
    if mime_type == 'image/jpg': mime_type = 'image/jpeg'
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    
    # نطلب من الموديل يرجع نص صافي عشان التنسيق يظبط معانا
    medical_prompt = """
    You are an expert Medical Scribe. 
    Analyze this medical image. Extract all text accurately.
    - Do NOT use Markdown formatting (like ## or **). 
    - Just provide clean, plain text with natural paragraphs.
    - Maintain the logical structure of the content.
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
            return f"Error {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

# --- دالة الفيدباك ---
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

# --- الواجهة الرئيسية ---

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("API Key missing.")
    st.stop()

# 1. إدخال اسم الملف (عنوان المستند)
doc_name_input = st.text_input("اسم الملف (عنوان المذاكرة):", value="Medical Notes")

uploaded_files = st.file_uploader("Upload Images", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🚀"):
    with st.status("Processing...", expanded=True):
        doc = Document()
        # استدعاء دالة التنسيق لتطبيق الخطوط
        setup_word_styles(doc)
        
        # استخدام الاسم المدخل كعنوان رئيسي للملف
        doc.add_heading(doc_name_input, 0)
        
        full_text_preview = ""
        progress_bar = st.progress(0)
        
        for i, file in enumerate(uploaded_files):
            st.write(f"Processing: {file.name}")
            text = call_gemini_medical(api_key, file.getvalue(), file.type)
            
            # إضافة اسم الصورة كعنوان فرعي (يأخذ تنسيق Heading 1 - 14 Bold)
            doc.add_heading(f'Page: {i+1} ({file.name})', level=1)
            
            # إضافة النص المستخرج (يأخذ تنسيق Normal - 12 Regular)
            doc.add_paragraph(text)
            
            # فاصل صفحات
            doc.add_page_break()
            
            full_text_preview += f"--- {file.name} ---\n{text}\n\n"
            progress_bar.progress((i + 1) / len(uploaded_files))
        
        st.success("Done!")
        bio = io.BytesIO()
        doc.save(bio)
        
        # تجهيز اسم الملف للتحميل (.docx)
        final_filename = f"{doc_name_input}.docx"
        
        st.download_button(
            label=f"📥 Download {final_filename}",
            data=bio.getvalue(),
            file_name=final_filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary"
        )
        
        with st.expander("Preview Text"):
            st.text(full_text_preview)

st.markdown("---")
with st.form("feedback"):
    fb = st.text_area("Feedback:")
    if st.form_submit_button("Send"):
        send_feedback_to_sheet(fb)
