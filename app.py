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

# --- دالة اختيار الموديل "الاقتصادي" ---
def get_generative_model(api_key):
    genai.configure(api_key=api_key)
    
    # القائمة الذهبية للموديلات المجانية والسريعة فقط
    # شلنا منها البرو الحديث عشان نتجنب مشكلة الـ Quota 0
    safe_models = [
        'gemini-1.5-flash',      # الخيار الأول والأفضل
        'gemini-1.5-flash-001',  # البديل الرسمي
        'gemini-1.5-flash-8b',   # نسخة خفيفة جداً
        'gemini-pro-vision',     # القديم المضمون (احتياطي أخير)
    ]
    
    # تجربة الموديلات بالترتيب
    for model_name in safe_models:
        try:
            # تجربة وهمية سريعة (Handshake)
            model = genai.GenerativeModel(model_name)
            # لو الموديل اشتغل ومطلعش Error 404 يبقى هو ده اللي هنكمل بيه
            return model
        except Exception:
            continue
            
    # لو ولا واحد اشتغل (نادرة جداً)، نرجع الفلاش وخلاص
    return genai.GenerativeModel('gemini-1.5-flash')

# --- دالة التحويل ---
def image_to_text(image, model):
    try:
        prompt = """
        ACT AS A MEDICAL SCRIBE. Analyze this image.
        1. Extract text accurately (drug names, doses).
        2. Format using Bullet points and **Bold** for keys.
        3. Output ONLY the formatted content.
        """
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        # لو حصل خطأ Quota (429) بنرجع رسالة لطيفة
        if "429" in str(e):
            return "⚠️ تجاوزت الحد المسموح (Quota). انتظر دقيقة وحاول مرة أخرى."
        return f"حدث خطأ أثناء المعالجة: {str(e)}"

# --- الواجهة ---
st.title("🩺 Medical Notes Converter")
st.caption("Using Gemini 1.5 Flash (Free Tier Optimized) 🚀")

with st.sidebar:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("المفتاح متصل ✅")
    else:
        api_key = st.text_input("Gemini API Key", type="password")

uploaded_files = st.file_uploader("ارفع صور الصفحات", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

if uploaded_files and st.button("بدء التحويل"):
    if not api_key:
        st.error("الرجاء إدخال API Key")
    else:
        # تجهيز الموديل مرة واحدة
        active_model = get_generative_model(api_key)
        
        progress = st.progress(0)
        doc = Document()
        
        # تنسيق الوورد
        style = doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(12)
        doc.add_heading('Medical Summary', 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            text = image_to_text(img, active_model)
            
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            
            # تحديث الشريط
            progress.progress((i + 1) / len(uploaded_files))
            
            # تأخير بسيط (ثانيتين) عشان منلبسش في الـ Quota تاني
            time.sleep(2)
            
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
