import streamlit as st
import google.generativeai as genai
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image
import io
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

# --- 1. إعداد الصفحة وإخفاء الهوية ---
st.set_page_config(page_title="المساعد الطبي - Medical Notes", page_icon="🩺", layout="centered")

# كود CSS لإخفاء القوائم، الفوتر، واسم المبرمج
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;} /* إخفاء القائمة العلوية */
            footer {visibility: hidden;}    /* إخفاء فوتر ستريمليت */
            header {visibility: hidden;}    /* إخفاء الشريط الملون العلوي */
            .stDeployButton {display:none;} /* إخفاء زر النشر */
            
            /* تحسينات بصرية عامة */
            .stApp {background-color: #fcfcfc;}
            h1 {color: #0d47a1; font-family: 'Arial';}
            .stButton>button {background-color: #1565c0; color: white; border-radius: 8px;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 2. دوال العمليات الطبية ---

def create_medical_doc():
    doc = Document()
    # تنسيق الخط العادي (Times New Roman)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(12)
    # تنسيق العناوين (Navy Blue & Arial)
    h1 = doc.styles['Heading 1']
    h1.font.name = 'Arial'
    h1.font.size = Pt(16)
    h1.font.bold = True
    h1.font.color.rgb = RGBColor(13, 71, 161)
    return doc

def process_image_with_gemini(image, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
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
        return f"Error: {str(e)}"

# --- 3. الواجهة الجانبية (Sidebar) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=80)
    st.title("إعدادات")
    
    # التعامل مع API Key بذكاء (لو موجود في السيكرتس خده، لو لا اطلبه)
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("المفتاح متصل ✅")
    else:
        api_key = st.text_input("Gemini API Key", type="password")
        st.caption("أدخل المفتاح ليعمل التطبيق")

# --- 4. الواجهة الرئيسية ---
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
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            text = process_image_with_gemini(img, api_key)
            
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            progress.progress((i + 1) / len(uploaded_files))
            
        # الحفظ والتحميل
        bio = io.BytesIO()
        doc.save(bio)
        st.success("تم الانتهاء!")
        
        st.download_button(
            label="📄 تحميل ملف الـ Word",
            data=bio.getvalue(),
            file_name="Medical_Notes_Formatted.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

st.divider()

# --- 5. قسم الدعوات (Google Sheets) ---
st.subheader("💌 اترك أثراً طيباً")
st.write("هذا العمل خيري لوجه الله. إذا استفدت، اترك دعوة طيبة أو اقتراحاً (بدون ذكر اسمك).")

with st.form("feedback"):
    msg = st.text_area("رسالتك:")
    submit = st.form_submit_button("إرسال ❤️")
    
    if submit and msg:
        try:
            conn = st.connection("gsheets", type=GSheetsConnection)
            # جلب البيانات القديمة
            existing = conn.read(worksheet="Sheet1", usecols=[0, 1], ttl=0)
            # إضافة الجديد
            new_data = pd.DataFrame([{"التاريخ": datetime.now().strftime("%Y-%m-%d"), "الرسالة": msg}])
            updated = pd.concat([existing, new_data], ignore_index=True)
            # التحديث
            conn.update(worksheet="Sheet1", data=updated)
            st.success("وصلت دعوتك، ولك بمثلها إن شاء الله!")
        except Exception as e:
            st.warning("حدث خطأ في الاتصال، لكن نيتك وصلت إن شاء الله.")
            # st.error(e) # شيلنا عرض الخطأ عشان المستخدم ميتلخبطش