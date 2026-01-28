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

# --- 1. دالة إضافة الإطار (Page Borders) ---
def add_page_borders(doc):
    """
    تضيف إطاراً للصفحة (Box Border) بسمك 1.5 pt
    مطابق للصورة التي أرسلتها.
    """
    sections = doc.sections
    for section in sections:
        sectPr = section._sectPr
        # إنشاء عنصر حدود الصفحة
        pgBorders = OxmlElement('w:pgBorders')
        pgBorders.set(qn('w:offsetFrom'), 'page') # المسافة من حافة الصفحة
        
        # إضافة الحدود الأربعة (فوق، تحت، يمين، يسار)
        for border_name in ('top', 'left', 'bottom', 'right'):
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')  # خط متصل
            border.set(qn('w:sz'), '12')       # الحجم: 12 وحدة = 1.5 نقطة (لأن النقطة = 8 وحدات)
            border.set(qn('w:space'), '24')    # المسافة
            border.set(qn('w:color'), 'auto')  # اللون: تلقائي (أسود)
            pgBorders.append(border)
        
        sectPr.append(pgBorders)

# --- 2. دالة تنسيق الخطوط (Times New Roman) ---
def setup_word_styles(doc):
    # تنسيق النص العادي (12 - Not Bold)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(12)
    font.bold = False
    rPr = style.element.get_or_add_rPr()
    rPr.rFonts.set(qn('w:ascii'), 'Times New Roman')
    rPr.rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    
    # تنسيق العناوين (14 - Bold)
    h1_style = doc.styles['Heading 1']
    h1_font = h1_style.font
    h1_font.name = 'Times New Roman'
    h1_font.size = Pt(14)
    h1_font.bold = True
    h1_font.color.rgb = None # لون أسود

# --- 3. دالة التحليل (مع كشف العناوين) ---
def call_gemini_medical_with_retry(api_key, image_bytes, mime_type):
    model_name = "gemini-2.5-flash"
    if mime_type == 'image/jpg': mime_type = 'image/jpeg'
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    
    # التعديل هنا: نطلب منه استخدام # للعناوين
    medical_prompt = """
    You are an expert Medical Scribe. Analyze this medical image.
    1. Extract all text accurately.
    2. **Headings:** If you see a clear TITLE or HEADING in the image, start that line with a hash symbol (#). Example: "# Anatomy of Heart".
    3. **Body Text:** Write normal text as is.
    4. Do NOT use any other markdown (like **bold** or italics). Just plain text and # for headings.
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
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            elif response.status_code == 503:
                time.sleep(2)
                continue
            else:
                return f"Error {response.status_code}"
        except:
            time.sleep(1)
            continue
    return "Server Error"

# --- 4. دالة الفيدباك ---
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

# --- الواجهة الرئيسية ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("API Key missing.")
    st.stop()

# إعدادات المستخدم
col1, col2 = st.columns([3, 1])
with col1:
    doc_name_input = st.text_input("اسم الملف (عنوان المذاكرة):", value="Medical Notes")
with col2:
    st.write("") # Spacer
    st.write("") 
    # الخيار الجديد لإخفاء اسم الصورة
    hide_img_name = st.checkbox("إخفاء اسم الصورة؟", value=False)

uploaded_files = st.file_uploader("Upload Images", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_files and st.button("Start Processing 🚀"):
    with st.status("Processing...", expanded=True) as status:
        doc = Document()
        setup_word_styles(doc) # تطبيق الخطوط
        add_page_borders(doc)  # تطبيق الإطار (1.5 pt)
        
        # العنوان الرئيسي للملف (ياخد Heading 1 بس نكبره شوية يدوياً لو تحب، أو نسيبه Heading 1)
        # هنا هنخليه Title عشان يبقى مميز في الأول
        title = doc.add_paragraph(doc_name_input, style='Title')
        title.alignment = 1 # Center
        
        full_text_preview = ""
        progress_bar = st.progress(0)
        
        for i, file in enumerate(uploaded_files):
            st.write(f"Analyzing: {file.name}...")
            text = call_gemini_medical_with_retry(api_key, file.getvalue(), file.type)
            
            # 1. هل نعرض اسم الصورة؟
            if not hide_img_name:
                # إضافة اسم الصورة كـ Heading 2 عشان يكون أصغر من العنوان الرئيسي
                # أو Heading 1 حسب طلبك (أنت طلبت العناوين 14 Bold)
                h = doc.add_heading(f'Image: {file.name}', level=1)
            
            # 2. معالجة النص سطر بسطر لاكتشاف العناوين الداخلية
            for line in text.split('\n'):
                line = line.strip()
                if not line: continue
                
                if line.startswith('#'):
                    # ده عنوان فرعي في الورقة -> نخليه Heading 1 (14 Bold)
                    clean_line = line.replace('#', '').strip()
                    doc.add_heading(clean_line, level=1)
                else:
                    # ده نص عادي -> نخليه Normal (12 Regular)
                    doc.add_paragraph(line)
            
            doc.add_page_break()
            full_text_preview += f"\n{text}\n"
            progress_bar.progress((i + 1) / len(uploaded_files))
            time.sleep(1)
        
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
