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

# --- دوال التنسيق (زي ما هي) ---
def add_page_borders(doc):
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
        sectPr.append(pgBorders)

def setup_word_styles(doc):
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(12)
    font.bold = False
    rPr = style.element.get_or_add_rPr()
    rPr.rFonts.set(qn('w:ascii'), 'Times New Roman')
    rPr.rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    
    h1_style = doc.styles['Heading 1']
    h1_font = h1_style.font
    h1_font.name = 'Times New Roman'
    h1_font.size = Pt(14)
    h1_font.bold = True
    h1_font.color.rgb = None

# --- دالة التحليل (السريعة مع نظام الطوارئ) ---
def call_gemini_fast(api_key, image_bytes, mime_type="image/jpeg"):
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    
    medical_prompt = """
    You are an expert Medical Scribe. Analyze this medical image.
    1. Extract all text accurately.
    2. **Headings:** If you see a clear TITLE or HEADING, start line with # (e.g., # Anatomy).
    3. **Body Text:** Write normal text as is.
    4. Do NOT use any other markdown.
    """
    
    payload = {
        "contents": [{"parts": [{"text": medical_prompt}, {"inline_data": {"mime_type": mime_type, "data": b64_image}}]}],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    
    # المحاولة 5 مرات في حالة وجود خطأ
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            
            elif response.status_code == 429:
                # لو السيرفر قال "زحمة" (429)، ننتظر وقت متزايد
                wait_time = (attempt + 1) * 8  # المرة الأولى 8 ثواني، التانية 16..
                st.toast(f"⚠️ Server busy. Waiting {wait_time}s to retry...", icon="⏳")
                time.sleep(wait_time)
                continue # نعيد المحاولة
            
            elif response.status_code == 503:
                time.sleep(3)
                continue
            
            else:
                return f"Error {response.status_code}"
                
        except Exception as e:
            time.sleep(2)
            continue

    return "Server failed after multiple retries."

# --- دالة الفيدباك ---
def send_feedback_to_sheet(feedback_text):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        if "gcp_service_account" not in st.secrets: return "Missing Credentials"
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Medical_App_Feedback").sheet1 
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, feedback_text])
        return True
    except Exception as e: return str(e)

# --- الواجهة ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("API Key missing.")
    st.stop()

col1, col2 = st.columns([3, 1])
with col1:
    doc_name_input = st.text_input("اسم الملف (عنوان المذاكرة):", value="Medical Notes")
with col2:
    st.write("") 
    st.write("") 
    hide_img_name = st.checkbox("إخفاء اسم الصورة؟", value=False)

uploaded_files = st.file_uploader("Upload PDF or Images", type=["pdf", "jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🚀"):
    with st.status("Processing...", expanded=True) as status:
        doc = Document()
        setup_word_styles(doc)
        add_page_borders(doc)
        
        title = doc.add_paragraph(doc_name_input, style='Title')
        title.alignment = 1 
        
        full_text_preview = ""
        progress_bar = st.progress(0)
        
        # تجميع كل الصور من كل الملفات لمعرفة العدد الكلي
        all_processing_items = []
        st.write("📂 Preparing files...")
        
        for file in uploaded_files:
            if file.type == "application/pdf":
                try:
                    pdf_images = convert_from_bytes(file.read())
                    for idx, img in enumerate(pdf_images):
                        all_processing_items.append({"type": "pdf_page", "img": img, "name": file.name, "page": idx+1})
                except Exception as e:
                    st.error(f"Error PDF: {e}")
            else:
                 all_processing_items.append({"type": "image", "file": file, "name": file.name})

        total_items = len(all_processing_items)
        
        # بداية المعالجة صورة صورة (بالسرعة العادية)
        for i, item in enumerate(all_processing_items):
            status.update(label=f"Processing {i+1}/{total_items}...", state="running")
            
            # تجهيز الصورة
            if item["type"] == "pdf_page":
                img_byte_arr = io.BytesIO()
                item["img"].save(img_byte_arr, format='JPEG')
                image_bytes = img_byte_arr.getvalue()
                display_name = f"{item['name']} - Page {item['page']}"
            else:
                image_bytes = item["file"].getvalue()
                display_name = item["name"]
            
            # الإرسال لجيميناي
            text = call_gemini_fast(api_key, image_bytes)
            
            # الكتابة في الوورد
            if not hide_img_name:
                doc.add_heading(display_name, level=1)
            
            for line in text.split('\n'):
                line = line.strip()
                if not line: continue
                if line.startswith('#'):
                    doc.add_heading(line.replace('#', '').strip(), level=1)
                else:
                    doc.add_paragraph(line)
            
            doc.add_page_break()
            full_text_preview += f"\n{text}\n"
            progress_bar.progress((i + 1) / total_items)
            
            # راحة قصيرة جداً (ثانية ونص) للحفاظ على استقرار الباقة
            # دي مش هتبطأك أوي بس هتحميك من الـ Error 429
            time.sleep(1.5)

        status.update(label="All Done!", state="complete", expanded=False)
        st.success("تم الانتهاء!")
        
        bio = io.BytesIO()
        doc.save(bio)
        final_filename = f"{doc_name_input}.docx"
        
        st.download_button(
            label=f"📥 Download {final_filename}",
            data=bio.getvalue(),
            file_name=final_filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary"
        )

st.markdown("---")
with st.form("feedback"):
    fb = st.text_area("Feedback:")
    if st.form_submit_button("Send"):
        send_feedback_to_sheet(fb)
