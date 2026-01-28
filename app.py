import streamlit as st
import google.generativeai as genai
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image
import io
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import time

# --- إعداد الصفحة ---
st.set_page_config(page_title="Medical Notes Converter", page_icon="🩺", layout="centered")

# --- دالة التحويل باستخدام الموديل الكلاسيكي ---
def image_to_text(image, api_key):
    try:
        genai.configure(api_key=api_key)
        
        # استخدام الموديل القديم المخصص للصور (Vision)
        # هذا الموديل مستقر جداً ونادراً ما يسبب مشاكل 404
        model = genai.GenerativeModel('gemini-pro-vision')
        
        prompt = """
        You are a medical scribe. Analyze this image and extract the text.
        Format it with bullet points and bold headers.
        """
        
        # الموديل القديم يحتاج للصورة والقائمة في مصفوفة
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        # لو حتى القديم فشل، يبقى المشكلة في مفتاح API نفسه
        if "404" in str(e):
            return "خطأ: المفتاح لا يدعم هذا الموديل. يرجى إنشاء مفتاح API جديد في مشروع جديد."
        return f"حدث خطأ: {str(e)}"

# --- الواجهة ---
st.title("🩺 Medical Notes (Classic Edition)")
st.info("يعمل باستخدام Gemini Pro Vision (الإصدار المستقر)")

with st.sidebar:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("المفتاح متصل ✅")
    else:
        api_key = st.text_input("Gemini API Key", type="password")

uploaded_files = st.file_uploader("ارفع الصور", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

if uploaded_files and st.button("بدء التحويل"):
    if not api_key:
        st.error("الرجاء إدخال API Key")
    else:
        progress = st.progress(0)
        doc = Document()
        
        style = doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(12)
        doc.add_heading('Medical Summary', 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            
            # محاولة التحويل
            text = image_to_text(img, api_key)
            
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            
            progress.progress((i + 1) / len(uploaded_files))
            time.sleep(1) # راحة للقديم
            
        bio = io.BytesIO()
        doc.save(bio)
        st.success("تم الانتهاء!")
        st.download_button("📥 تحميل الملف", bio.getvalue(), "Medical_Notes.docx")

# جوجل شيت (نفس الكود السابق)
st.divider()
with st.expander("💌 اترك دعوة"):
    with st.form("feedback"):
        msg = st.text_area("الرسالة:")
        if st.form_submit_button("إرسال"):
            try:
                scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
                secrets = dict(st.secrets["connections"]["gsheets"])
                if "\\n" in secrets["private_key"]:
                    secrets["private_key"] = secrets["private_key"].replace("\\n", "\n")
                creds = Credentials.from_service_account_info(secrets, scopes=scope)
                client = gspread.authorize(creds)
                sheet = client.open_by_url(st.secrets["connections"]["gsheets"]["spreadsheet"]).sheet1
                sheet.append_row([datetime.now().strftime("%Y-%m-%d"), msg])
                st.success("شكراً لك!")
            except:
                st.success("وصلت نيتك!")
