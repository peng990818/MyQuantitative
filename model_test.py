import google.generativeai as genai
import os

# 确保环境变量里有代理
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'

genai.configure(api_key="你的KEY")
model = genai.GenerativeModel('gemini-1.5-flash')

try:
    response = model.generate_content("你好，请确认收到信息。")
    print(f"✅ 测试成功: {response.text}")
except Exception as e:
    print(f"❌ 测试失败，请检查代理: {e}")