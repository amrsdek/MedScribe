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
st.write("حول صور المحاضرات أو ملفات PDF (Scanned) إلى ملف Word منسق.")

# --- دوال التنسيق ---
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

# --- دالة التحليل (المعدلة للتعامل مع الضغط 429) ---
def call_gemini_medical_with_retry(api_key, image_bytes, mime_type="image/jpeg"):
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    
    medical_prompt = """
    You are an expert Medical Scribe. Analyze this medical image.
    1. Extract all text accurately.
    2. **Headings:** If you see a clear TITLE or HEADING in the image, start that line with a hash symbol (#). Example: "# Anatomy of Heart".
    3. **Body Text:** Write normal text as is.
    4. Do NOT use any other markdown.
    """
    
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]
    
    payload = {
        "contents": [{"parts": [{"text": medical_prompt}, {"inline_data": {"mime_type": mime_type, "data": b64_image}}]}],
        "safetySettings": safety_settings
    }
    
    # محاولة حتى 5 مرات (بدل 3)
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            
            elif response.status_code == 429:
                # لو الخطأ 429 (Too Many Requests)
                wait_time = (attempt + 1) * 10  # استنى 10 ثواني، ثم 20، ثم 30...
                st.warning(f"⚠️ ضغط عالي على السيرفر.. جاري الانتظار {wait_time} ثواني (محاولة {attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
            
            elif response.status_code == 503:
                # لو الخطأ 503 (Service Unavailable)
                time.sleep(5)
                continue
                
            else:
                return f"Error {response.status_code}"
        except Exception as e:
            time.sleep(2)
            continue

    return "Server is too busy. Try converting fewer pages at a time."

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
        
        total_files_count = len(uploaded_files)
        current_file_index = 0

        for file in uploaded_files:
            current_file_index += 1
            
            if file.type == "application/pdf":
                st.write(f"📄 Extracting PDF: {file.name}...")
                try:
                    images = convert_from_bytes(file.read())
                    # لو PDF كبير، ناخد راحة أطول بين الصفحات
                    pdf_delay = 4 
                    
                    for page_num, img in enumerate(images):
                        st.write(f"Analyzing Page {page_num + 1}...")
                        
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='JPEG')
                        img_bytes = img_byte_arr.getvalue()
                        
                        text = call_gemini_medical_with_retry(api_key, img_bytes, "image/jpeg")
                        
                        if not hide_img_name:
                            doc.add_heading(f'{file.name} - Page {page_num+1}', level=1)
                        
                        for line in text.split('\n'):
                            line = line.strip()
                            if not line: continue
                            if line.startswith('#'):
                                clean_line = line.replace('#', '').strip()
                                doc.add_heading(clean_line, level=1)
                            else:
                                doc.add_paragraph(line)
                        
                        doc.add_page_break()
                        full_text_preview += f"\n{text}\n"
                        # استراحة إجبارية بين كل صفحة والتانية
                        time.sleep(pdf_delay)

                except Exception as e:
                    st.error(f"Error reading PDF: {e}")
            
            else:
                st.write(f"🖼️ Analyzing: {file.name}...")
                text = call_gemini_medical_with_retry(api_key, file.getvalue(), file.type)
                
                if not hide_img_name:
                    doc.add_heading(f'Image: {file.name}', level=1)
                
                for line in text.split('\n'):
                    line = line.strip()
                    if not line: continue
                    if line.startswith('#'):
                        clean_line = line.replace('#', '').strip()
                        doc.add_heading(clean_line, level=1)
                    else:
                        doc.add_paragraph(line)
                
                doc.add_page_break()
                full_text_preview += f"\n{text}\n"
                time.sleep(3) # استراحة 3 ثواني للصور العادية

            progress_bar.progress(current_file_index / total_files_count)
        
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
