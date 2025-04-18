import os, re, json, time, requests, googlemaps, openai, streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ─── Keys & clients ───────────────────────────────────────────────────────────
load_dotenv()
openai.api_key = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
openai.project  = "proj_Hdy6TsbuQQy0hictusNM4GAa"        # keep if sk‑proj key

GMAPS_KEY = st.secrets.get("GOOGLE_PLACES_KEY", "")
gmaps = googlemaps.Client(key=GMAPS_KEY)

MODEL        = "gpt-4o"            # or "gpt-4o-mini"
CHUNK_LIMIT  = 12_000              # max chars per website
DETAIL_FIELDS = (
    "name,formatted_phone_number,website,rating,"
    "formatted_address,place_id,vicinity"
)

# ─── UI ────────────────────────────────────────────────────────────────────────
st.title("SignalScout – MVP")

MASTER_PW = st.secrets.get("MASTER_PASSWORD", "changeme")
if st.text_input("Password", type="password") != MASTER_PW:
    st.stop()

industry  = st.text_input("Industry (e.g. plumber)")
location  = st.text_input("City, State (e.g. Tampa, FL)")

if "seen" not in st.session_state: st.session_state["seen"] = []

col1, col2 = st.columns(2)

# ─── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def geocode_llm(loc: str) -> str:
    """LLM converts 'Tampa, FL' → 'lat,lng'."""
    resp = openai.chat.completions.create(
        model=MODEL,
        messages=[{"role":"system","content":f"lat,lng only for '{loc}'"}],
        temperature=0
    )
    return resp.choices[0].message.content.strip()

@st.cache_data(ttl=86400)
def nearby_places(ind: str, loc_ll: str):
    return gmaps.places_nearby(location=loc_ll, keyword=ind, radius=3000).get("results", [])

@st.cache_data(ttl=86400)
def place_details(pid: str):
    try:
        return gmaps.place(place_id=pid, fields=DETAIL_FIELDS)["result"]
    except Exception:
        return {}

def extract_emails_from_text(text):
    """Extract email addresses from text using regex."""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    return emails

def visible_text(url: str) -> str:
    if not url: return ""
    try:
        html = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla"}).text
    except Exception:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script","style","noscript"]): t.decompose()
    
    # Extract all 'a' tags with 'mailto:' links
    mailto_links = []
    for a in soup.find_all('a', href=True):
        if a['href'].startswith('mailto:'):
            email = a['href'][7:]  # Remove 'mailto:' prefix
            if '@' in email and '.' in email:
                mailto_links.append(email)
    
    # Get all visible text
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:CHUNK_LIMIT]
    
    # If we found mailto links, prepend them to the text so LLM can easily find them
    if mailto_links:
        mailto_text = "Contact emails: " + ", ".join(mailto_links) + " "
        return mailto_text + text
    
    return text

def enrich(name: str, text: str) -> dict:
    # First try direct email extraction with regex
    emails = extract_emails_from_text(text)
    email_hint = ""
    if emails:
        email_hint = f"Found emails: {', '.join(emails[:3])}. "
    
    prompt = f"""You are a data extractor.
Return JSON with keys:
name, phone, email, website, socials {{fb, ig, li}}, address.
{email_hint}Use ONLY the provided text. If missing, use empty string.
###
{text}
###
JSON:"""
    resp = openai.chat.completions.create(
        model=MODEL,
        messages=[{"role":"system","content":prompt}],
        temperature=0,
        response_format={"type":"json_object"},
        max_tokens=400
    )
    info = json.loads(resp.choices[0].message.content)
    # ensure name present
    if not info.get("name"): info["name"] = name
    
    # If we found emails with regex but LLM didn't include them, add the first one
    if emails and not info.get("email"):
        info["email"] = emails[0]
    
    return info

def crawl_contact_page(base_url):
    """Try to find and extract contact page content."""
    if not base_url:
        return ""
    
    # Make sure the URL has a scheme
    if not base_url.startswith(('http://', 'https://')):
        base_url = 'https://' + base_url
    
    # Remove trailing slash if present
    base_url = base_url.rstrip('/')
    
    # Common contact page paths
    contact_paths = [
        '/contact', 
        '/contact-us',
        '/about/contact',
        '/contactus',
        '/about-us/contact',
        '/contact-us.html',
        '/contact.php',
        '/contact.html'
    ]
    
    for path in contact_paths:
        try:
            contact_url = base_url + path
            response = requests.get(contact_url, timeout=5, headers={"User-Agent":"Mozilla"})
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                for t in soup(["script","style","noscript"]): t.decompose()
                text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:CHUNK_LIMIT//2]
                
                # Look for mailto links
                mailto_links = []
                for a in soup.find_all('a', href=True):
                    if a['href'].startswith('mailto:'):
                        email = a['href'][7:]  # Remove 'mailto:' prefix
                        if '@' in email and '.' in email:
                            mailto_links.append(email)
                
                if mailto_links:
                    return "Contact emails: " + ", ".join(mailto_links) + " " + text
                
                return text
        except Exception:
            continue
    
    return ""

def row_to_pipe(info: dict, base: dict) -> str:
    socials = ",".join(filter(None, [
        info.get("socials", {}).get(k,"") for k in ("fb","ig","li")
    ]))
    return "|".join([
        info.get("name")                            or base.get("name",""),
        info.get("website")                         or base.get("website",""),
        info.get("phone")                           or base.get("formatted_phone_number",""),
        info.get("email",""),
        socials,
        info.get("address")                         or base.get("formatted_address", base.get("vicinity","")),
    ])

def rate_limit():
    if "last_hit" in st.session_state and time.time() - st.session_state["last_hit"] < 10:
        st.warning("Slow down — wait a few seconds."); st.stop()
    st.session_state["last_hit"] = time.time()

# ─── Main button logic ─────────────────────────────────────────────────────────
def run_query():
    loc_ll = geocode_llm(location)
    places = nearby_places(industry, loc_ll)
    # skip already-seen names
    return [p for p in places if p["name"] not in st.session_state["seen"]][:3]

def process_batch(batch):
    rows = []
    for p in batch:
        det = place_details(p["place_id"])
        website = det.get("website", "")
        
        # Get main website content
        html_text = visible_text(website)
        
        # If website exists, also try to get contact page content
        contact_text = ""
        if website:
            contact_text = crawl_contact_page(website)
        
        # Combine texts, prioritizing contact page
        combined_text = contact_text + "\n" + html_text if contact_text else html_text
        
        # Use address if no website content found
        if not combined_text:
            combined_text = det.get("formatted_address", p.get("vicinity", ""))
        
        info = enrich(det.get("name", p["name"]), combined_text)
        rows.append(row_to_pipe(info, det or p))
        st.session_state["seen"].append(det.get("name", p["name"]))
    
    return "\n".join(rows) if rows else "No results."

if col1.button("Scout") and industry and location:
    rate_limit()
    st.text(process_batch(run_query()))

if col2.button("Next 3") and st.session_state["seen"]:
    rate_limit()
    st.text(process_batch(run_query()))