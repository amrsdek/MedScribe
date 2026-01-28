import streamlit as st

# 1. إعداد الصفحة (لازم يكون أول أمر)
st.set_page_config(page_title="Medical Notes", page_icon="🩺", layout="centered")

# محاولة استيراد المكتبات داخل try-except لكشف سبب الشاشة البيضاء
try:
    import google.generativeai as genai
    from docx import Document
    from PIL import Image
    import io
    import time
except Exception as e:
    st.error(f"حدث خطأ في تحميل المكتبات: {e}")
    st.stop()

# --- الواجهة ---
st.title("🩺 Medical Notes Converter")
st.write("نسخة الإصلاح السريع - Basic Version")

# الشريط الجانبي
with st.sidebar:
    st.header("الإعدادات")
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("المفتاح متصل ✅")
    else:
        api_key = st.text_input("Gemini API Key", type="password")

# دالة التحويل المباشرة (بدون لف ودوران)
def convert_image(image, api_key):
    try:
        genai.configure(api_key=api_key)
        # استخدام الفلاش الرسمي مباشرة
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = "Extract medical text from this image and format it nicely."
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"

# الرفع والتحويل
uploaded_files = st.file_uploader("ارفع الصور", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

if uploaded_files and st.button("بدء التحويل"):
    if not api_key:
        st.warning("⚠️ الرجاء إدخال API Key")
    else:
        progress = st.progress(0)
        # إنشاء ملف وورد بسيط
        doc = Document()
        doc.add_heading('Medical Summary', 0)
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            st.caption(f"جاري معالجة: {file.name}...")
            
            text = convert_image(img, api_key)
            
            doc.add_heading(f'Page: {file.name}', level=1)
            doc.add_paragraph(text)
            doc.add_page_break()
            progress.progress((i + 1) / len(uploaded_files))
            
        # التحميل
        bio = io.BytesIO()
        doc.save(bio)
        st.success("تم الانتهاء!")
        st.download_button("📥 تحميل الملف", bio.getvalue(), "Medical_Notes.docx")
