import os, re, time, json, requests, googlemaps, openai, streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------- secrets & keys ----------
load_dotenv()
openai.api_key = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
openai.project  = "proj_Hdy6TsbuQQy0hictusNM4GAa"   # keep if you use sk‑proj key

GMAPS_KEY = st.secrets.get("GOOGLE_PLACES_KEY", "")  # add in Streamlit → Secrets
gmaps = googlemaps.Client(key=GMAPS_KEY)

MODEL = "gpt-4o"          # or "gpt-4o-mini" for cheaper runs
CHUNK_LIMIT = 12_000      # max chars per website to keep cost sane

# ---------- UI ----------
st.title("SignalScout – MVP")

MASTER_PW = st.secrets.get("MASTER_PASSWORD", "changeme")
pw = st.text_input("Password", type="password")
if pw != MASTER_PW: st.stop()

industry  = st.text_input("Industry (e.g. plumber)")
location  = st.text_input("City, State (e.g. Boston, MA)")

if "seen" not in st.session_state: st.session_state["seen"] = []

col1, col2 = st.columns(2)

# ---------- helpers ----------
@st.cache_data(ttl=86400)
def fetch_places(ind, loc):
    # geocode location
    g_resp = openai.chat.completions.create(
        model=MODEL,
        messages=[{"role":"system","content":f"lat,lng only for '{loc}'"}],
        temperature=0
    )
    coords = g_resp.choices[0].message.content.strip()
    # search nearby
    resp = gmaps.places_nearby(
        location=coords,
        keyword=ind,
        radius=3000
    )
    return resp.get("results", [])

def visible_text(url):
    try:
        html = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla"}).text
    except Exception:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script","style","noscript"]): t.decompose()
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return txt[:CHUNK_LIMIT]

def enrich(biz, raw_html):
    prompt = f"""You are a data extractor.
Return JSON with keys:
name, phone, email, website, socials {{fb, ig, li}}, rating, address.
Use ONLY the provided HTML/text. If missing, output empty string.
###
{raw_html}
###
JSON:"""
    resp = openai.chat.completions.create(
        model=MODEL,
        messages=[{"role":"system","content":prompt}],
        temperature=0,
        response_format={"type":"json_object"},
        max_tokens=400
    )
    return json.loads(resp.choices[0].message.content)

def row_to_pipe(info, fallback):
    name    = info.get("name")    or fallback["name"]
    website = info.get("website") or fallback.get("website", "")
    phone   = info.get("phone")   or fallback.get("formatted_phone_number", "")
    email   = info.get("email", "")
    socials = ",".join(filter(None, [info["socials"].get(k,"") for k in ("fb","ig","li")])) if info.get("socials") else ""
    address = info.get("address") or fallback.get("vicinity", "")
    return f"{name}|{website}|{phone}|{email}|{socials}|{address}"

def rate_limit():
    if "last_hit" in st.session_state and time.time() - st.session_state["last_hit"] < 10:
        st.warning("Slow down — wait a few seconds."); st.stop()
    st.session_state["last_hit"] = time.time()

# ---------- button handlers ----------
if col1.button("Scout") and industry and location:
    rate_limit()
    places = fetch_places(industry, location)
    # drop ones we've already seen
    places = [p for p in places if p["name"] not in st.session_state["seen"]][:3]
    rows = []
    for p in places:
        html = visible_text(p.get("website","")) if p.get("website") else ""
        info = enrich(p["name"], html or p.get("vicinity",""))
        rows.append(row_to_pipe(info, p))
        st.session_state["seen"].append(p["name"])
    data = "\n".join(rows) if rows else "No results."
    st.text(data)
    if rows: st.download_button("Download .txt", data, "signal.txt")

if col2.button("Next 3") and st.session_state["seen"]:
    rate_limit()
    places = fetch_places(industry, location)
    places = [p for p in places if p["name"] not in st.session_state["seen"]][:3]
    rows = []
    for p in places:
        html = visible_text(p.get("website","")) if p.get("website") else ""
        info = enrich(p["name"], html or p.get("vicinity",""))
        rows.append(row_to_pipe(info))
        st.session_state["seen"].append(p["name"])
    data = "\n".join(rows) if rows else "No more results."
    st.text(data)
    if rows: st.download_button("Download .txt", data, "signal.txt")
