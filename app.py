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

st.title("🩺 Medical Study Assistant (Turbo Mode 🚀)")
st.write("حول صور المحاضرات والكتب بسرعة عالية باستخدام تقنية Batching.")

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

# --- دالة التحليل (بنظام الدفعات Batching) ---
def call_gemini_batch(api_key, images_list, start_index):
    """
    ترسل مجموعة صور مرة واحدة لجيميناي لتقليل عدد الطلبات وتسريع العملية.
    """
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    
    # 1. تجهيز الرسالة (Prompt)
    prompt_text = """
    You are an expert Medical Scribe. I am sending you a batch of medical notes pages.
    Process them ONE BY ONE in order.
    
    For EACH page image, follow these rules:
    1. Start with a separator line: "--- PAGE [Number] ---"
    2. Extract all text accurately.
    3. **Headings:** If you see a clear TITLE or HEADING, start the line with # (e.g., # Diagnosis).
    4. **Body Text:** Plain text.
    5. Do NOT summarize. Transcribe full content.
    """
    
    # 2. تجميع الصور في الرسالة
    parts = [{"text": prompt_text}]
    
    for img_bytes in images_list:
        b64_image = base64.b64encode(img_bytes).decode('utf-8')
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": b64_image
            }
        })
    
    payload = {
        "contents": [{"parts": parts}],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    
    # 3. الإرسال مع إعادة المحاولة الذكية
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            elif response.status_code == 429:
                time.sleep(5) # انتظار بسيط عند الزحمة
                continue
            else:
                return f"Error {response.status_code}"
        except:
            time.sleep(2)
            continue
            
    return "Failed to process batch."

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
    hide_img_name = st.checkbox("إخفاء فواصل الصفحات؟", value=False)

uploaded_files = st.file_uploader("Upload PDF or Images", type=["pdf", "jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🚀"):
    with st.status("Processing in Turbo Mode...", expanded=True) as status:
        doc = Document()
        setup_word_styles(doc)
        add_page_borders(doc)
        
        title = doc.add_paragraph(doc_name_input, style='Title')
        title.alignment = 1 
        
        # 1. تجميع كل الصور من كل الملفات في قائمة واحدة الأول
        all_images_bytes = []
        original_filenames = [] # عشان نعرف المصدر لو احتاجنا
        
        progress_bar = st.progress(0)
        st.write("📂 Preparing files...")
        
        for file in uploaded_files:
            if file.type == "application/pdf":
                try:
                    pdf_images = convert_from_bytes(file.read())
                    for img in pdf_images:
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='JPEG')
                        all_images_bytes.append(img_byte_arr.getvalue())
                        original_filenames.append(file.name)
                except Exception as e:
                    st.error(f"Error in PDF: {e}")
            else:
                all_images_bytes.append(file.getvalue())
                original_filenames.append(file.name)

        # 2. تقسيم الصور لمجموعات (Batches) - كل مجموعة 5 صور
        batch_size = 5
        total_batches = (len(all_images_bytes) + batch_size - 1) // batch_size
        
        full_text_preview = ""
        
        for i in range(0, len(all_images_bytes), batch_size):
            batch_images = all_images_bytes[i : i + batch_size]
            current_batch_num = (i // batch_size) + 1
            
            st.write(f"⚡ Processing Batch {current_batch_num}/{total_batches} (Pages {i+1}-{i+len(batch_images)})...")
            
            # إرسال الدفعة لجيميناي
            batch_text = call_gemini_batch(api_key, batch_images, i+1)
            
            # معالجة النص القادم
            lines = batch_text.split('\n')
            for line in lines:
                line = line.strip()
                if not line: continue
                
                # التعامل مع الفواصل اللي جيميناي بيحطها
                if "--- PAGE" in line:
                    if not hide_img_name:
                         # استخراج رقم الصفحة أو كتابة فاصل
                         doc.add_heading(line.replace('---', '').strip(), level=1)
                    else:
                        doc.add_page_break() # لو مخفي، بس افصل بصفحة جديدة
                elif line.startswith('#'):
                    clean_line = line.replace('#', '').strip()
                    doc.add_heading(clean_line, level=1)
                else:
                    doc.add_paragraph(line)
            
            full_text_preview += f"\n{batch_text}\n"
            progress_bar.progress(current_batch_num / total_batches)
            
            # راحة صغيرة جداً (ثانيتين) بين كل دفعة (5 صور) مش كل صورة
            if current_batch_num < total_batches:
                time.sleep(2) 
        
        status.update(label="Done!", state="complete", expanded=False)
        st.success(f"تم تحويل {len(all_images_bytes)} صفحة بنجاح!")
        
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
        
        with st.expander("Preview Content"):
            st.text(full_text_preview)

st.markdown("---")
with st.form("feedback"):
    fb = st.text_area("Feedback:")
    if st.form_submit_button("Send"):
        send_feedback_to_sheet(fb)
