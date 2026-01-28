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
st.write("النسخة الصبورة (تعالج خطأ 429 تلقائياً).")

# --- 1. دالة التنسيق ---
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

# --- 2. دالة الاتصال (مع فرامل للطوارئ) ---
def call_gemini_retry(api_key, image_bytes, mime_type="image/jpeg"):
    # نستخدم 1.5-flash لأنه الأوفر والأسرع
    model_name = "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        b64_image = base64.b64encode(image_bytes).decode('utf-8')
    except:
        return "Error encoding image."

    headers = {'Content-Type': 'application/json'}
    
    medical_prompt = """
    You are an expert Medical Scribe. Analyze this medical image.
    1. Extract all text accurately.
    2. **Headings:** If you see a clear TITLE or HEADING, start the line with # (e.g., # Anatomy).
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
    
    # هنا السر: نحاول 5 مرات لو فشل
    for attempt in range(5):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            
            elif response.status_code == 429: # لو قالك استنى (Too Many Requests)
                wait_time = (attempt + 1) * 5 # استنى 5 ثواني، ثم 10، ثم 15...
                st.toast(f"⚠️ زحمة (429).. جاري الانتظار {wait_time} ثواني...", icon="⏳")
                time.sleep(wait_time)
                continue # عيد تاني
                
            else: # أي خطأ تاني
                time.sleep(2)
                continue
                
        except Exception as e:
            time.sleep(2)
            continue

    return f"Error: Failed after retries (Status: {response.status_code if 'response' in locals() else 'Unknown'})"

# --- 3. دالة الفيدباك ---
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
        
        # متغير عشان نحسب النسبة المئوية
        total_steps = len(uploaded_files) 
        
        for i, file in enumerate(uploaded_files):
            st.write(f"📂 Reading: {file.name}")
            
            if file.type == "application/pdf":
                try:
                    images = convert_from_bytes(file.read())
                    # لو PDF بنزود وقت الراحة شوية
                    for page_idx, img in enumerate(images):
                        st.write(f"📄 Analyzing Page {page_idx+1}...")
                        
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='JPEG')
                        
                        text = call_gemini_retry(api_key, img_byte_arr.getvalue(), "image/jpeg")
                        
                        if not hide_img_name:
                            doc.add_heading(f"{file.name} (Page {page_idx+1})", level=1)
                        
                        if "Error:" in text:
                             st.error(f"Failed page {page_idx+1}: {text}")
                        else:
                            for line in text.split('\n'):
                                line = line.strip()
                                if not line: continue
                                if line.startswith('#'):
                                    doc.add_heading(line.replace('#', '').strip(), level=1)
                                else:
                                    doc.add_paragraph(line)
                        
                        doc.add_page_break()
                        full_text_preview += f"\n{text}\n"
                        
                        # --- أهم سطر: راحة 4 ثواني إجبارية بين كل صفحة ---
                        time.sleep(4) 
                        
                except Exception as e:
                    st.error(f"Error reading PDF: {e}")
            
            else:
                st.write(f"🖼️ Analyzing Image...")
                text = call_gemini_retry(api_key, file.getvalue(), file.type)
                
                if not hide_img_name:
                    doc.add_heading(file.name, level=1)
                
                if "Error:" in text:
                     st.error(f"Failed image: {text}")
                else:
                    for line in text.split('\n'):
                        line = line.strip()
                        if not line: continue
                        if line.startswith('#'):
                            doc.add_heading(line.replace('#', '').strip(), level=1)
                        else:
                            doc.add_paragraph(line)
                
                doc.add_page_break()
                full_text_preview += f"\n{text}\n"
                
                # --- أهم سطر: راحة 3 ثواني بين الصور ---
                time.sleep(3)

            progress_bar.progress((i + 1) / total_steps)
        
        status.update(label="Done!", state="complete", expanded=False)
        st.success("تم الانتهاء بنجاح!")
        
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
