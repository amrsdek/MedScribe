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

# --- إعداد الصفحة ---
st.set_page_config(page_title="Medical Notes Converter", page_icon="🩺", layout="centered")

# --- دالة اكتشاف الموديل المتاح (الحل السحري) ---
def get_available_model(api_key):
    """دالة تسأل جوجل عن الموديلات المتاحة وتختار واحد شغال"""
    genai.configure(api_key=api_key)
    try:
        # بنطلب قائمة كل الموديلات المتاحة للمفتاح دا
        models = genai.list_models()
        
        # بنرتبهم حسب الأفضلية (فلاش الجديد، ثم برو، ثم أي حاجة تانية)
        priority_list = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro-vision', 'gemini-pro']
        
        available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # 1. لو لقينا واحد من المفضلين في القائمة المتاحة، ناخده فوراً
        for priority in priority_list:
            for name in available_names:
                if priority in name:
                    return name
        
        # 2. لو ملقيناش المفضلين، ناخد أول واحد متاح وخلاص (عشان ميطلعش ايرور)
        if available_names:
            return available_names[0]
            
        return None
    except Exception as e:
        return None

# --- دالة التحويل ---
def image_to_text(image, api_key):
    # 1. نكتشف الموديل المتاح
    model_name = get_available_model(api_key)
    
    if not model_name:
        return "خطأ: لم يتم العثور على أي موديل متاح لهذا المفتاح. تأكد من صحة API Key."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        prompt = """
        ACT AS A MEDICAL SCRIBE. Analyze this image.
        1. Extract text accurately (drug names, doses).
        2. Format using Bullet points and **Bold** for keys.
        3. Output ONLY the formatted content.
        """
        
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"حدث خطأ مع الموديل ({model_name}): {str(e)}"

# --- الواجهة ---
st.title("🩺 Medical Notes Converter")
st.caption("Auto-Detecting Best Gemini Model 🚀")

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
        # عرض اسم الموديل اللي هنشتغل بيه عشان نطمن
        active_model = get_available_model(api_key)
        st.toast(f"تم الاتصال بالموديل: {active_model}")
        
        progress = st.progress(0)
        doc = Document()
        
        # تنسيق الوورد
        style = doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(12)
        doc.add_heading('Medical Summary', 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            text = image_to_text(img, api_key)
            
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            progress.progress((i + 1) / len(uploaded_files))
            
        bio = io.BytesIO()
        doc.save(bio)
        st.success("تم الانتهاء!")
        st.download_button("📥 تحميل ملف Word", bio.getvalue(), "Medical_Notes.docx", 
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

# جوجل شيت
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
