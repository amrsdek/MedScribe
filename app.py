import streamlit as st
import requests
import json
import base64
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from PIL import Image
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
from pdf2image import convert_from_bytes

# ==========================================
# 1. إعدادات الصفحة
# ==========================================
st.set_page_config(page_title="Medical Notes Converter", page_icon="🩺", layout="centered")

st.markdown("""
    <style>
    .main { direction: rtl; }
    .stButton>button { width: 100%; border-radius: 10px; }
    h1 { color: #0e76a8; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

st.title("🩺 المساعد الطبي الذكي")
st.markdown("---")

# ==========================================
# 2. العقل المدبر (حل مشكلة 404)
# ==========================================
def get_best_model_name(api_key):
    """
    تتصل بجوجل وتجيب الاسم الرسمي للموديل 1.5 Flash المتاح حالياً
    عشان نتفادى خطأ 404 ونبعد عن موديل 2.5 محدود الباقة.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            
            # ترتيب الأولويات (بندور على 1.5 Flash بكل أشكاله)
            priorities = [
                'gemini-1.5-flash-latest',
                'gemini-1.5-flash-001',
                'gemini-1.5-flash-002',
                'gemini-1.5-flash'
            ]
            
            # 1. البحث بالاسم الدقيق
            for priority in priorities:
                for m in models:
                    if priority in m['name']:
                        return m['name'].replace('models/', '')

            # 2. لو ملقاش، هات أي حاجة فيها 1.5 وفلاش
            for m in models:
                if 'flash' in m['name'] and '1.5' in m['name']:
                    return m['name'].replace('models/', '')
            
            # 3. لو الدنيا قفلت خالص، هات أي فلاش (بس دي نادرة)
            for m in models:
                if 'flash' in m['name'] and '2.5' not in m['name']: # ابعد عن 2.5
                    return m['name'].replace('models/', '')

        return "gemini-1.5-flash" # اسم احتياطي أخير
    except:
        return "gemini-1.5-flash"

# ==========================================
# 3. الدوال الأساسية (تنسيق + اتصال)
# ==========================================

def create_medical_doc():
    doc = Document()
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(12)
    rPr = style.element.get_or_add_rPr()
    rPr.rFonts.set(qn('w:ascii'), 'Times New Roman')
    rPr.rFonts.set(qn('w:hAnsi'), 'Times New Roman')

    h1_style = doc.styles['Heading 1']
    h1_font = h1_style.font
    h1_font.name = 'Times New Roman'
    h1_font.size = Pt(14)
    h1_font.bold = True
    h1_font.color.rgb = None 

    sections = doc.sections
    for section in sections:
        sectPr = section._sectPr
        pgBorders = OxmlElement('w:pgBorders')
        pgBorders.set(qn('w:offsetFrom'), 'page')
        for border_name in ('top', 'left', 'bottom', 'right'):
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '12') 
            border.set(qn('w:space'), '24')
            border.set(qn('w:color'), 'auto')
            pgBorders.append(border)
    return doc

def ask_gemini(api_key, model_name, image_bytes, mime_type="image/jpeg"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        b64_image = base64.b64encode(image_bytes).decode('utf-8')
    except:
        return None, "فشل قراءة الصورة"

    headers = {'Content-Type': 'application/json'}
    
    prompt = """
    You are a professional Medical Scribe.
    1. Transcribe the text from this medical image exactly.
    2. Format HEADINGS by starting the line with # (e.g., # Diagnosis).
    3. Keep body text as normal paragraphs.
    4. Do not use Markdown bold (**) or italics (*).
    """
    
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": b64_image}}]}],
        "safetySettings": [
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    
    # 3 محاولات للأمان (لو حصل خطأ بسيط)
    for _ in range(3):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text'], None
            elif response.status_code == 429:
                time.sleep(5) # استنى 5 ثواني وجرب تاني
                continue
            elif response.status_code == 404:
                return None, f"خطأ 404: الموديل {model_name} غير متاح."
            else:
                time.sleep(2)
                continue
        except Exception as e:
            return None, str(e)
            
    return None, "فشل الاتصال بعد عدة محاولات (تأكد من النت)"

def save_feedback(text):
    if "gcp_service_account" in st.secrets:
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            sheet = client.open("Medical_App_Feedback").sheet1 
            sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text])
            return True
        except: return False
    return False

# ==========================================
# 4. واجهة التطبيق
# ==========================================

if "GEMINI_API_KEY" not in st.secrets:
    st.error("⚠️ المفتاح GEMINI_API_KEY غير موجود في Secrets.")
    st.stop()

api_key = st.secrets["GEMINI_API_KEY"]

col1, col2 = st.columns([2, 1])
with col1:
    doc_title = st.text_input("اسم الملف:", value="Medical Notes")
with col2:
    st.write("")
    st.write("")
    hide_names = st.checkbox("إخفاء أسماء الصور؟", value=False)

uploaded_files = st.file_uploader("ارفع الصور أو PDF", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files and st.button("🚀 ابدأ التحويل"):
    
    # --- الخطوة الأولى: اكتشاف الموديل الصحيح ---
    with st.spinner("جاري الاتصال بجوجل وتحديد أفضل موديل..."):
        valid_model = get_best_model_name(api_key)
    
    st.toast(f"تم الاتصال بنجاح باستخدام: {valid_model}", icon="✅")
    
    # --- الخطوة الثانية: المعالجة ---
    doc = create_medical_doc()
    title_para = doc.add_paragraph(doc_title, style='Title')
    title_para.alignment = 1 
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # تجهيز القائمة
    all_images = []
    with st.spinner("جاري قراءة الملفات..."):
        for file in uploaded_files:
            if file.type == "application/pdf":
                try:
                    pdf_pages = convert_from_bytes(file.read())
                    for i, page in enumerate(pdf_pages):
                        img_byte_arr = io.BytesIO()
                        page.save(img_byte_arr, format='JPEG')
                        all_images.append({"bytes": img_byte_arr.getvalue(), "name": f"{file.name} (P{i+1})", "type": "image/jpeg"})
                except Exception as e: st.error(f"خطأ PDF: {e}")
            else:
                all_images.append({"bytes": file.getvalue(), "name": file.name, "type": file.type})

    total_count = len(all_images)
    
    for i, item in enumerate(all_images):
        current_step = i + 1
        status_text.write(f"⏳ ({current_step}/{total_count}) جاري معالجة: **{item['name']}**...")
        
        # نستخدم الموديل اللي اكتشفناه (valid_model)
        text, error = ask_gemini(api_key, valid_model, item['bytes'], item['type'])
        
        if error:
            st.error(f"خطأ في {item['name']}: {error}")
            doc.add_paragraph(f"[Error in {item['name']}: {error}]")
        else:
            if not hide_names: doc.add_heading(item['name'], level=1)
            for line in text.split('\n'):
                line = line.strip()
                if not line: continue
                if line.startswith('#'): doc.add_heading(line.replace('#', '').strip(), level=1)
                else: doc.add_paragraph(line)
            doc.add_page_break()
        
        progress_bar.progress(current_step / total_count)
        
        # استراحة المجانية (4 ثواني)
        if current_step < total_count:
            time.sleep(4) 

    status_text.success("✅ تم الانتهاء!")
    
    bio = io.BytesIO()
    doc.save(bio)
    st.download_button(label="📥 تحميل الملف", data=bio.getvalue(), file_name=f"{doc_title}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", type="primary")

st.markdown("---")
with st.expander("💬 ملاحظات"):
    with st.form("fb"):
        txt = st.text_area("رأيك:")
        if st.form_submit_button("إرسال"):
            if save_feedback(txt): st.success("شكراً!")
