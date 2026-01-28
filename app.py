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

# --- دالة العثور على الموديل الشغال (خطة أ، ب، ج) ---
def get_working_model(api_key):
    genai.configure(api_key=api_key)
    
    # هذه القائمة مرتبة من الأحدث للأقدم
    # الكود سيجربهم واحداً تلو الآخر حتى يجد واحداً يعمل
    models_to_test = [
        'gemini-1.5-flash-001', # الاسم الرسمي الكامل (غالباً هو الحل)
        'gemini-1.5-flash',     # الاسم المختصر
        'gemini-1.5-pro',       # الخيار القوي البديل
        'gemini-pro-vision',    # القديم المضمون (يعمل دائماً)
    ]
    
    for model_name in models_to_test:
        try:
            # تجربة سريعة جداً للتأكد أن الموديل "حي" ولا يعطي 404
            model = genai.GenerativeModel(model_name)
            # نطلب منه كلمة واحدة فقط للاختبار
            model.generate_content("test")
            return model # إذا نجح، نستخدمه ونخرج من الدالة فوراً
        except Exception:
            continue # لو فشل، نجرب اللي بعده بصمت
            
    # لو كل دول فشلوا (مستحيل يحصل)، نرجع القديم وخ
