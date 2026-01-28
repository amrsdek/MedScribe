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

# --- 2. دالة ذكية لاختيار الموديل المتاح ---
def get_best_model(api_key):
    """دالة تكتشف الموديلات المتاحة وتختار أفضل واحد تلقائياً"""
    genai.configure(api_key=api_key)
    try:
        # نجيب كل الموديلات المتاحة للمفتاح ده
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # ترتيب الأولويات: فلاش الجديد > برو الجديد > القديم
        priorities = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-pro']
        
        # لو لقينا واحد من الأولويات، ناخده
        for priority in priorities:
            for model in available_models:
                if priority in model:
                    return model
        
        # لو ملقيناش المفضلين، ناخد أول واحد شغال وخلاص
        if available_models:
            return available_models[0]
        else:
            return "models/gemini-pro" # احتياطي
            
    except Exception as e:
        return "models/gemini-pro" # لو حصل خطأ في الكشف نرجع للقديم

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

def process_image_with_gemini(image, api_key):
    try:
        # هنا التعديل السحري: بنجيب الموديل الشغال أوتوماتيك
        model_name = get_best_model(api_key)
        
        # إعداد الموديل بالاسم اللي لقيناه
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
        return f"Error ({model_name}): {str(e)}"

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
        progress = st.progress(0)
        doc = create_medical_doc()
        doc.add_heading('Medical Study Summary', 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # عرض الموديل المستخدم (عشان نطمن)
        active_model = get_best_model(api_key)
        st.caption(f"يتم المعالجة باستخدام: {active_model}")
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            text = process_image_with_gemini(img, api_key)
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            progress.progress((i + 1) / len(uploaded_files))
            
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
