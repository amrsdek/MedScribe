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
import concurrent.futures # مكتبة المعالجة المتوازية

# --- إعداد الصفحة ---
st.set_page_config(page_title="Medical Study Assistant", page_icon="🩺", layout="centered")

st.markdown("""
    <style>
    .main { direction: rtl; }
    h1 { color: #2E86C1; }
    .stDeployButton {display:none;}
    </style>
    """, unsafe_allow_html=True)

st.title("🩺 Medical Study Assistant (Parallel Mode ⚡)")

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

# --- دالة العامل الواحد (Worker Function) ---
def process_single_image_task(api_key, image_bytes, index, file_name):
    """
    وظيفة العامل الواحد: ياخد صورة ويبعتها ويرجع بالنص.
    الـ index مهم عشان الترتيب ميبوظش لما نجمعهم.
    """
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        b64_image = base64.b64encode(image_bytes).decode('utf-8')
    except:
        return index, f"Error processing image {file_name}"

    headers = {'Content-Type': 'application/json'}
    
    medical_prompt = """
    You are an expert Medical Scribe. Analyze this medical image.
    1. Extract all text accurately.
    2. **Headings:** If you see a clear TITLE or HEADING, start line with # (e.g., # Anatomy).
    3. **Body Text:** Write normal text as is.
    4. Do NOT use any other markdown.
    """
    
    payload = {
        "contents": [{"parts": [{"text": medical_prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": b64_image}}]}],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    
    # محاولة مع إعادة المحاولة الذكية لكل عامل
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                text = response.json()['candidates'][0]['content']['parts'][0]['text']
                return index, text # بنرجع الرقم مع النص عشان الترتيب
            elif response.status_code == 429:
                time.sleep(2 + attempt) # كل عامل يستنى شوية لو الدنيا زحمة
                continue
            elif response.status_code == 503:
                time.sleep(1)
                continue
            else:
                return index, f"Error {response.status_code}"
        except Exception as e:
            time.sleep(1)
            continue

    return index, "Failed after retries."

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
    with st.status("Initializing Parallel Workers...", expanded=True) as status:
        doc = Document()
        setup_word_styles(doc)
        add_page_borders(doc)
        
        title = doc.add_paragraph(doc_name_input, style='Title')
        title.alignment = 1 
        
        # 1. تجهيز قائمة المهام (Tasks)
        tasks_data = [] # هنخزن هنا الصور عشان نبعتها للعمال
        st.write("📂 Preparing files...")
        
        global_index = 0
        for file in uploaded_files:
            if file.type == "application/pdf":
                try:
                    pdf_images = convert_from_bytes(file.read())
                    for img in pdf_images:
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='JPEG')
                        tasks_data.append({
                            "index": global_index,
                            "bytes": img_byte_arr.getvalue(),
                            "name": f"{file.name} (Page {global_index+1})"
                        })
                        global_index += 1
                except Exception as e:
                    st.error(f"Error PDF: {e}")
            else:
                 tasks_data.append({
                     "index": global_index,
                     "bytes": file.getvalue(),
                     "name": file.name
                 })
                 global_index += 1

        total_tasks = len(tasks_data)
        st.write(f"⚡ Launching 4 parallel workers for {total_tasks} pages...")
        
        # 2. التشغيل المتوازي (Multithreading)
        results = [None] * total_tasks # مصفوفة فاضية نحط فيها النتايج بالترتيب
        completed_count = 0
        progress_bar = st.progress(0)
        
        # max_workers=4 (أفضل رقم للباقة المجانية عشان ميعملش Limit بسرعة)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            # إرسال المهام
            future_to_index = {
                executor.submit(process_single_image_task, api_key, task["bytes"], task["index"], task["name"]): task["index"]
                for task in tasks_data
            }
            
            # استقبال النتائج أول بأول
            for future in concurrent.futures.as_completed(future_to_index):
                idx, text = future.result()
                results[idx] = text # تخزين النتيجة في مكانها الصحيح
                
                completed_count += 1
                progress_bar.progress(completed_count / total_tasks)
                # تحديث الحالة كل شوية
                if completed_count % 2 == 0:
                     st.write(f"✅ Finished page {completed_count}/{total_tasks}")

        # 3. كتابة النتائج في ملف الوورد (بالترتيب الصحيح)
        st.write("📝 Writing to Word document...")
        for i, text in enumerate(results):
            task_info = tasks_data[i]
            
            if not hide_img_name:
                doc.add_heading(task_info["name"], level=1)
            
            if text:
                for line in text.split('\n'):
                    line = line.strip()
                    if not line: continue
                    if line.startswith('#'):
                        doc.add_heading(line.replace('#', '').strip(), level=1)
                    else:
                        doc.add_paragraph(line)
                doc.add_page_break()

        status.update(label="All Done!", state="complete", expanded=False)
        st.success(f"تم الانتهاء من {total_tasks} صفحة بسرعة!")
        
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
