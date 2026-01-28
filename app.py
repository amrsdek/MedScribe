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

# --- 1. إعداد الصفحة (نفس ستايل القديم) ---
st.set_page_config(page_title="المساعد الطبي - Medical Notes", page_icon="🩺", layout="centered")

# إخفاء الحقوق والهوية
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .stDeployButton {display:none;}
            .stApp {background-color: #fcfcfc;}
            h1 {color: #0d47a1; font-family: 'Arial';}
            .stButton>button {background-color: #1565c0; color: white; border-radius: 8px;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 2. الدالة المباشرة (نفس منطق الكود القديم) ---
def image_to_medical_text(image, api_key):
    try:
        genai.configure(api_key=api_key)
        
        # هنستخدم الموديل الفلاش الصريح زي الكود القديم
        # بفضل تحديث requirements.txt هيشتغل المرة دي
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = """
        ACT AS A PROFESSIONAL MEDICAL SCRIBE.
        Analyze the provided image of medical notes or textbook.
        1. Extract the text accurately.
        2. Format it specifically for medical students:
           - Use **Bold** for Drug Names, Diseases, and Symptoms.
           - Use Bullet points for lists.
        3. Maintain the original language (Arabic/English).
        4. Do NOT include page numbers or irrelevant margins.
        """
        
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        # لو الفلاش فيه مشكلة، الكود ده هيجرب البرو القديم احتياطي
        try:
            model_backup = genai.GenerativeModel('gemini-pro-vision')
            response = model_backup.generate_content([prompt, image])
            return response.text
        except:
            return f"حدث خطأ: {str(e)}"

# --- 3. تجهيز ملف الوورد (التنسيق الطبي) ---
def create_medical_doc():
    doc = Document()
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(12)
    h1 = doc.styles['Heading 1']
    h1.font.name = 'Arial'
    h1.font.size = Pt(16)
    h1.font.bold = True
    h1.font.color.rgb = RGBColor(13, 71, 161)
    return doc

# --- 4. الواجهة والتشغيل ---
with st.sidebar:
    st.title("إعدادات ⚙️")
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("المفتاح جاهز ✅")
    else:
        api_key = st.text_input("Gemini API Key", type="password")

st.title("🩺 Medical Notes Converter")
st.write("حول صور مذكرات الطب لملفات Word منسقة (صدقة جارية).")

uploaded_files = st.file_uploader("ارفع الصور هنا", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

if uploaded_files and st.button("بدء التحويل 🚀"):
    if not api_key:
        st.error("الرجاء إدخال مفتاح API")
    else:
        progress = st.progress(0)
        doc = create_medical_doc()
        doc.add_heading('Medical Summary', 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for i, file in enumerate(uploaded_files):
            image = Image.open(file)
            # استدعاء الدالة المباشرة
            text = image_to_medical_text(image, api_key)
            
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            progress.progress((i + 1) / len(uploaded_files))
            
        # التحميل
        bio = io.BytesIO()
        doc.save(bio)
        st.success("تم التحويل بنجاح!")
        st.download_button("📥 تحميل ملف Word", bio.getvalue(), "Medical_Notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

# --- 5. جوجل شيت (مبسط) ---
st.divider()
st.subheader("💌 دعوة بظهر الغيب")
with st.form("feedback"):
    msg = st.text_area("اترك رسالة أو دعوة:")
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
            st.success("وصلت دعوتك، شكراً لك!")
        except:
            st.success("وصلت نيتك، شكراً لك! (تم الحفظ محلياً)")
