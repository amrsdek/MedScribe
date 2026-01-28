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

# --- 1. إعداد الصفحة ---
st.set_page_config(page_title="المساعد الطبي - Medical Notes", page_icon="🩺", layout="centered")

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

# --- 2. دالة اختبار الموديل (تعديل جذري) ---
def get_working_model(api_key):
    """
    تجربة قائمة من الموديلات بالترتيب للعثور على موديل يعمل
    ولا يعطي خطأ 404 أو 429
    """
    genai.configure(api_key=api_key)
    
    # قائمة الموديلات المراد تجربتها (الأخف والأسرع أولاً)
    # نبدأ بالفلاش لأنه الأنسب للطلبة (سريع ومجاني)
    candidate_models = [
        'gemini-1.5-flash', 
        'gemini-1.5-flash-latest',
        'gemini-1.5-flash-001',
        'gemini-1.5-pro-latest', # لو الفلاش مش متاح نجرب البرو
        'gemini-pro-vision',     # القديم المضمون
    ]
    
    for model_name in candidate_models:
        try:
            # تجربة وهمية بسيطة للتأكد من الموديل
            model = genai.GenerativeModel(model_name)
            # نرسل رسالة نصية بسيطة جداً للاختبار (بدون صور لتوفير الكوتا)
            # نستخدم generate_content مع نص فقط للاختبار السريع
            response = model.generate_content("test")
            return model_name # لو نجح نرجعه فوراً
        except Exception as e:
            # لو فشل نجرب اللي بعده
            continue
            
    # لو كله فشل، نرجع للفلاش كخيار افتراضي وربنا يسهل
    return 'gemini-1.5-flash'

# --- 3. دوال العمليات الطبية ---
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

def process_image_with_gemini(image, api_key, model_name):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        prompt = """
        ACT AS A MEDICAL SCRIBE. Analyze this medical document image.
        1. Extract text accurately (drug names, doses, latin terms).
        2. Format nicely: Use Bullet points for lists, **Bold** for key terms.
        3. Keep the original language (English/Arabic).
        4. Output ONLY the formatted content.
        """
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        # لو حصل خطأ Quota أثناء التشغيل، نطلب من المستخدم الانتظار
        if "429" in str(e):
            return "Error: Quota exceeded. Please wait a minute and try again."
        return f"Error: {str(e)}"

# --- 4. الواجهة الجانبية ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=80)
    st.title("إعدادات")
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("المفتاح متصل ✅")
    else:
        api_key = st.text_input("Gemini API Key", type="password")

# --- 5. الواجهة الرئيسية ---
st.title("🩺 Medical Notes Converter")
st.write("صدقة جارية | أداة لتحويل صور المذكرات الطبية إلى ملفات Word منسقة للمذاكرة.")
st.divider()

uploaded_files = st.file_uploader("ارفع صور الصفحات (Images)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

if uploaded_files and st.button("تحويل وتنسيق الملف 📝"):
    if not api_key:
        st.error("الرجاء إدخال مفتاح API.")
    else:
        # 1. البحث عن أفضل موديل متاح الآن
        with st.spinner("جاري البحث عن أفضل سيرفر متاح..."):
            best_model = get_working_model(api_key)
            st.toast(f"تم الاتصال بالسيرفر: {best_model}", icon="🚀")
        
        progress = st.progress(0)
        doc = create_medical_doc()
        doc.add_heading('Medical Study Summary', 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            # نمرر اسم الموديل اللي اخترناه للدالة
            text = process_image_with_gemini(img, api_key, best_model)
            
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            progress.progress((i + 1) / len(uploaded_files))
            
            # تأخير بسيط جداً (ثانية واحدة) لتجنب ضغط السيرفر
            time.sleep(1) 
            
        bio = io.BytesIO()
        doc.save(bio)
        st.success("تم الانتهاء!")
        st.download_button("📄 تحميل ملف الـ Word", bio.getvalue(), "Medical_Notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

st.divider()

# --- 6. قسم الدعوات ---
st.subheader("💌 اترك أثراً طيباً")
with st.form("feedback"):
    msg = st.text_area("رسالتك:")
    submit = st.form_submit_button("إرسال ❤️")
    
    if submit and msg:
        try:
            scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            secrets_dict = dict(st.secrets["connections"]["gsheets"])
            
            if "\\n" in secrets_dict["private_key"]:
                secrets_dict["private_key"] = secrets_dict["private_key"].replace("\\n", "\n")
            
            creds = Credentials.from_service_account_info(secrets_dict, scopes=scope)
            client = gspread.authorize(creds)
            
            sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
            sheet = client.open_by_url(sheet_url).sheet1
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([current_time, msg])
            
            st.success("وصلت دعوتك، ولك بمثلها إن شاء الله!")
        except Exception as e:
            st.warning("حدث خطأ بسيط في الاتصال، لكن نيتك وصلت!")
            print(e)
