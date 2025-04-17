import streamlit as st, os, openai
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-4.1-mini"

st.title("SignalScout – MVP")
industry = st.text_input("Industry (e.g. plumber)")
location = st.text_input("City, State (e.g. Boston, MA)")

def ask_llm(ind, loc):
    prompt = f"""<task>
<instructions>
1. Return EXACTLY 3 businesses.
2. Pipe-delimit: Name|Website|Phone|Location
3. End with <finished>true</finished>
</instructions>
<query>{ind} in {loc}</query>
</task>"""
    resp = openai.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": prompt}],
        max_tokens=500,
        temperature=0
    )
    return resp.choices[0].message.content.strip()

if st.button("Scout") and industry and location:
    data = ask_llm(industry, location)
    st.text(data)
    st.download_button("Download .txt", data, "signal.txt")
