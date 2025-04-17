import streamlit as st, os, openai
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-4.1-mini"

st.title("SignalScout – MVP")

industry = st.text_input("Industry (e.g. plumber)")
location = st.text_input("City, State (e.g. Boston, MA)")

if "seen" not in st.session_state:
    st.session_state["seen"] = []

def ask_llm(ind, loc, exclude):
    excl = "; ".join(exclude) or "none yet"
    prompt = f"""<task>
<instructions>
1. Return EXACTLY 3 businesses **NOT IN THIS LIST**: {excl}
2. Pipe‑delimit: Name|Website|Phone|Location
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

def show_results(text):
    st.text(text)
    st.download_button("Download .txt", text, "signal.txt")

col1, col2 = st.columns(2)
if col1.button("Scout") and industry and location:
    data = ask_llm(industry, location, st.session_state["seen"])
    show_results(data)
    # log the names we got
    names = [line.split("|")[0] for line in data.splitlines() if "|" in line]
    st.session_state["seen"].extend(names)

if col2.button("Next 3") and st.session_state["seen"]:
    data = ask_llm(industry, location, st.session_state["seen"])
    show_results(data)
    names = [line.split("|")[0] for line in data.splitlines() if "|" in line]
    st.session_state["seen"].extend(names)