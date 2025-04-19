import streamlit as st
import re
import requests
from bs4 import BeautifulSoup
import time
import pandas as pd
import os
from openai import OpenAI
from io import StringIO, BytesIO
from datetime import datetime
import csv
import logging
import validators
import email_validator

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration and Authentication
def authenticate(password_input):
    master_password = os.environ.get("MASTER_PASSWORD", "supersecret123")
    if password_input == master_password:
        return True
    return False

def setup_api_keys():
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    google_places_key = os.environ.get("GOOGLE_PLACES_KEY", "")
    return openai_api_key, google_places_key

# Email Extraction and Validation Functions
def is_valid_email(email):
    """Enhanced email validation using email-validator library"""
    try:
        # Basic format validation
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return False
        
        # More thorough validation with email_validator
        email_validator.validate_email(email, check_deliverability=False)
        
        # Additional checks
        domain = email.split('@')[1]
        
        # Check against disposable email domains (simplified check)
        disposable_domains = ['mailinator.com', 'tempmail.com', 'fakeinbox.com', 'temp-mail.org']
        if domain.lower() in disposable_domains:
            logger.info(f"Filtered out disposable email: {email}")
            return False
            
        # Filter out certain patterns that might be invalid
        invalid_patterns = [
            r'example\.com$',  # Example domains
            r'test.*@',         # Test emails
            r'noreply@',        # No-reply addresses
            r'donotreply@',     # Do not reply addresses
        ]
        
        for pattern in invalid_patterns:
            if re.search(pattern, email, re.IGNORECASE):
                logger.info(f"Filtered out invalid pattern in email: {email}")
                return False
                
        return True
    except Exception as e:
        logger.warning(f"Email validation error for {email}: {str(e)}")
        return False

def extract_emails_from_text(text):
    """
    Enhanced function to extract emails from text using various regex patterns
    to account for different email formats and obfuscation techniques
    """
    if not text:
        return []
    
    # Standard email pattern
    standard_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
    
    # Pattern for emails with common obfuscation (e.g., "email at domain dot com")
    text_with_replacements = text
    replacements = [
        (r'\s+at\s+', '@'),
        (r'\s+dot\s+', '.'),
        (r'<span class="katex-display"><span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><semantics><mrow><mi>a</mi><mi>t</mi></mrow><annotation encoding="application/x-tex">at</annotation></semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base"><span class="strut" style="height:0.6151em;"></span><span class="mord mathnormal">a</span><span class="mord mathnormal">t</span></span></span></span></span>', '@'),
        (r'<span class="katex-display"><span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><semantics><mrow><mi>d</mi><mi>o</mi><mi>t</mi></mrow><annotation encoding="application/x-tex">dot</annotation></semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base"><span class="strut" style="height:0.6944em;"></span><span class="mord mathnormal">d</span><span class="mord mathnormal">o</span><span class="mord mathnormal">t</span></span></span></span></span>', '.'),
        (r'<span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mrow><mi>a</mi><mi>t</mi></mrow><annotation encoding="application/x-tex">at</annotation></semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base"><span class="strut" style="height:0.6151em;"></span><span class="mord mathnormal">a</span><span class="mord mathnormal">t</span></span></span></span>', '@'),
        (r'<span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mrow><mi>d</mi><mi>o</mi><mi>t</mi></mrow><annotation encoding="application/x-tex">dot</annotation></semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base"><span class="strut" style="height:0.6944em;"></span><span class="mord mathnormal">d</span><span class="mord mathnormal">o</span><span class="mord mathnormal">t</span></span></span></span>', '.'),
        (r' at ', '@'),
        (r' dot ', '.'),
    ]
    
    for old, new in replacements:
        text_with_replacements = re.sub(old, new, text_with_replacements, flags=re.IGNORECASE)
    
    # Extract emails using standard pattern
    emails = re.findall(standard_pattern, text, re.IGNORECASE)
    emails_from_replaced = re.findall(standard_pattern, text_with_replacements, re.IGNORECASE)
    
    # Combine and filter for unique valid emails
    all_emails = list(set(emails + emails_from_replaced))
    valid_emails = [email for email in all_emails if is_valid_email(email)]
    
    return valid_emails

def extract_emails_from_html(html_content):
    """Extract emails from HTML content, including mailto links and data attributes"""
    emails = []
    
    if not html_content:
        return emails
    
    # Extract standard emails from text
    text_emails = extract_emails_from_text(html_content)
    emails.extend(text_emails)
    
    # Parse HTML and look for mailto links
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract from mailto links
        mailto_links = soup.select('a[href^="mailto:"]')
        for link in mailto_links:
            href = link.get('href', '')
            email_match = re.search(r'mailto:([\w\.-]+@[\w\.-]+\.\w+)', href)
            if email_match:
                emails.append(email_match.group(1))
                
        # Extract from data-email attributes (common in protected emails)
        elements_with_data_email = soup.select('[data-email]')
        for element in elements_with_data_email:
            email = element.get('data-email', '')
            if '@' in email and '.' in email:
                emails.append(email)
                
        # Look for obfuscated emails in scripts (common technique)
        scripts = soup.find_all('script')
        for script in scripts:
            script_text = script.string if script.string else ""
            if script_text and ('email' in script_text.lower() or '@' in script_text):
                # Look for patterns like var email = 'user' + '@' + 'domain.com';
                email_parts = re.findall(r'[\'"]([\w\.-]+)[\'"][\s]*\+[\s]*[\'"]@[\'"][\s]*\+[\s]*[\'"]([\w\.-]+\.\w+)[\'"]', script_text)
                for parts in email_parts:
                    if len(parts) == 2:
                        emails.append(f"{parts[0]}@{parts[1]}")
    except Exception as e:
        logger.error(f"HTML parsing error: {str(e)}")
    
    # Filter for unique valid emails
    unique_valid_emails = []
    for email in emails:
        if email not in unique_valid_emails and is_valid_email(email):
            unique_valid_emails.append(email)
    
    return unique_valid_emails

def crawl_contact_pages(base_url):
    """
    Enhanced function to crawl potential contact pages of a given website
    to find email addresses
    """
    emails = []
    if not base_url:
        return emails
        
    # Ensure the base URL has a trailing slash for path joining
    if not base_url.endswith('/'):
        base_url += '/'
        
    # Remove protocol for checking
    clean_base = base_url.split('://')[-1]
    
    # Common contact page paths
    contact_paths = [
        'contact', 'contact-us', 'contacts', 'about', 'about-us', 'get-in-touch',
        'reach-us', 'connect', 'support', 'help', 'info', 'team', 'our-team', 
        'people', 'staff', 'directory', 'meet-the-team', 'meet-our-team',
        'company/team', 'company/contact', 'company/about',
        'about/contact', 'about/team', 'en/contact', 'en/about',
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # First crawl the homepage
    try:
        logger.info(f"Checking homepage at {base_url}")
        response = requests.get(base_url, headers=headers, timeout=10)
        if response.status_code == 200:
            page_emails = extract_emails_from_html(response.text)
            emails.extend([e for e in page_emails if e not in emails])
            
            # Also extract contact page links from homepage
            soup = BeautifulSoup(response.text, 'html.parser')
            contact_links = []
            
            # Look for links containing "contact" or similar terms
            for link in soup.find_all('a', href=True):
                href = link.get('href', '').lower()
                link_text = link.text.lower()
                
                if any(term in link_text for term in ['contact', 'email', 'reach', 'connect']):
                    if href.startswith('/'):
                        contact_links.append(base_url.rstrip('/') + href)
                    elif href.startswith('http'):
                        if clean_base in href:  # Only if it's the same domain
                            contact_links.append(href)
                    else:
                        contact_links.append(base_url.rstrip('/') + '/' + href)
            
            # Add these discovered links to our contact paths (but avoid duplicates)
            for link in contact_links:
                if link not in [base_url + path for path in contact_paths]:
                    contact_paths.append(link.replace(base_url, '').lstrip('/'))
    except Exception as e:
        logger.error(f"Error crawling homepage: {str(e)}")
    
    # Now check all the contact paths
    for path in contact_paths:
        if path.startswith('http'):
            # This is a full URL we discovered earlier
            contact_url = path
        else:
            # This is a path we need to append to the base_url
            contact_url = base_url + path
        
        try:
            logger.info(f"Checking contact page at {contact_url}")
            response = requests.get(contact_url, headers=headers, timeout=10)
            if response.status_code == 200:
                page_emails = extract_emails_from_html(response.text)
                emails.extend([e for e in page_emails if e not in emails])
        except Exception as e:
            logger.error(f"Error crawling {contact_url}: {str(e)}")
        
        # Be nice to the server
        time.sleep(1)
    
    # Filter for unique valid emails
    unique_valid_emails = []
    for email in emails:
        if email not in unique_valid_emails and is_valid_email(email):
            unique_valid_emails.append(email)
    
    return unique_valid_emails

def extract_businesses_from_query(query, google_places_key, num_results=5):
    if not query or not google_places_key:
        return []

    url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={query}&key={google_places_key}"
    response = requests.get(url)
    data = response.json()
    
    if data.get("status") != "OK":
        logger.error(f"Google Places API error: {data.get('status')}")
        return []
        
    results = data.get("results", [])[:num_results]
    businesses = []
    
    for result in results:
        business = {
            "name": result.get("name", ""),
            "address": result.get("formatted_address", ""),
            "place_id": result.get("place_id", ""),
            "types": result.get("types", []),
            "website": "",
            "phone": "",
            "email": []
        }
        
        # Get additional details for each business
        details_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={business['place_id']}&fields=website,formatted_phone_number&key={google_places_key}"
        details_response = requests.get(details_url)
        details_data = details_response.json()
        
        if details_data.get("status") == "OK" and "result" in details_data:
            business["website"] = details_data["result"].get("website", "")
            business["phone"] = details_data["result"].get("formatted_phone_number", "")
            
            # Extract emails from website if available
            if business["website"]:
                try:
                    # Try to get the website content
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    website_response = requests.get(business["website"], headers=headers, timeout=10)
                    if website_response.status_code == 200:
                        # Extract emails from the website content
                        business["email"] = extract_emails_from_html(website_response.text)
                        
                        # If no emails found on the main page, try contact pages
                        if not business["email"]:
                            business["email"] = crawl_contact_pages(business["website"])
                except Exception as e:
                    logger.error(f"Error fetching website {business['website']}: {str(e)}")
        
        businesses.append(business)
        time.sleep(1)  # Be nice to the API
        
    return businesses

# LLM Functions for Email Extraction
def format_business_data_for_llm(business):
    """Format business data as context for the LLM"""
    context = f"""
Name: {business.get('name', 'Unknown')}
Address: {business.get('address', 'Unknown')}
Website: {business.get('website', 'Unknown')}
Phone: {business.get('phone', 'Unknown')}
Business Types: {', '.join(business.get('types', ['Unknown']))}
Emails Found: {', '.join(business.get('email', []))}
    """
    return context

def extract_potential_emails_with_llm(business, openai_client):
    """Use LLM to deduce or extract possible email addresses based on business context"""
    if not openai_client:
        return business.get("email", [])
    
    # If we already have emails, return them
    if business.get("email"):
        return business.get("email")
    
    context = format_business_data_for_llm(business)
    
    prompt = f"""You are an expert at deducing business email addresses. Based on the following business information, 
    suggest the most likely email address formats for contacting this business. 
    
    {context}
    
    Based on common patterns for businesses of this type, suggest the 2 most likely email addresses. 
    If you can't make a good suggestion, reply with "No email suggestion available."
    Only provide email addresses that follow standard conventions and avoid any that might be incorrect.
    If you previously found emails, prioritize those found emails. Do not make up emails that couldn't be correct.
    
    Most likely email addresses:
    """
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that deduces business email addresses based on patterns."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=150
        )
        
        suggestions_text = response.choices[0].message.content.strip()
        
        # Extract valid email patterns from the response
        extracted_emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', suggestions_text)
        valid_emails = [email for email in extracted_emails if is_valid_email(email)]
        
        # If we already had emails found by crawling, prioritize those
        existing_emails = business.get("email", [])
        if existing_emails:
            combined_emails = existing_emails + [e for e in valid_emails if e not in existing_emails]
            return combined_emails
        
        return valid_emails
    except Exception as e:
        logger.error(f"Error using LLM for email suggestion: {str(e)}")
        return business.get("email", [])

# Export Functions
def export_businesses_to_csv(businesses, filename="business_data.csv"):
    """Export business data to CSV file"""
    if not businesses:
        return None
        
    # Prepare data for CSV
    csv_data = []
    for business in businesses:
        row = {
            'Name': business.get('name', ''),
            'Address': business.get('address', ''),
            'Website': business.get('website', ''),
            'Phone': business.get('phone', ''),
            'Types': ', '.join(business.get('types', [])),
            'Emails': ', '.join(business.get('email', []))
        }
        csv_data.append(row)
    
    # Create DataFrame and export to CSV
    df = pd.DataFrame(csv_data)
    
    # For in-memory file (Streamlit download)
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_data = csv_buffer.getvalue()
    
    return csv_data

def export_businesses_to_excel(businesses, filename="business_data.xlsx"):
    """Export business data to Excel file"""
    if not businesses:
        return None
        
    # Prepare data for Excel
    excel_data = []
    for business in businesses:
        row = {
            'Name': business.get('name', ''),
            'Address': business.get('address', ''),
            'Website': business.get('website', ''),
            'Phone': business.get('phone', ''),
            'Types': ', '.join(business.get('types', [])),
            'Emails': ', '.join(business.get('email', []))
        }
        excel_data.append(row)
    
    # Create DataFrame and export to Excel
    df = pd.DataFrame(excel_data)
    
    # For in-memory file (Streamlit download)
    excel_buffer = BytesIO()
    df.to_excel(excel_buffer, index=False)
    excel_data = excel_buffer.getvalue()
    
    return excel_data

# Streamlit App Components
def display_login_page():
    st.title("SignalScout - Login")
    st.markdown("Please log in to continue.")
    password = st.text_input("Password", type="password")
    login_button = st.button("Login")
    
    if login_button:
        if authenticate(password):
            st.session_state["authenticated"] = True
            st.experimental_rerun()
        else:
            st.error("Invalid password!")

def display_main_app():
    openai_api_key, google_places_key = setup_api_keys()
    
    st.title("SignalScout - Business Lead Generator")
    st.markdown("Extract business information and contact details from Google Places")
    
    # Initialize OpenAI client if key is available
    openai_client = None
    if openai_api_key:
        openai_client = OpenAI(api_key=openai_api_key)
    
    # Search form
    with st.form("search_form"):
        query = st.text_input("Enter search query (e.g., 'restaurants in Chicago')")
        num_results = st.slider("Number of results", 1, 20, 5)
        submitted = st.form_submit_button("Search")
    
    # Process search if submitted
    if submitted and query and google_places_key:
        with st.spinner("Searching for businesses..."):
            businesses = extract_businesses_from_query(query, google_places_key, num_results)
            
            if not businesses:
                st.error("No businesses found. Please try another search query.")
            else:
                # Store businesses in session state
                st.session_state["businesses"] = businesses
                
                # Use LLM to enhance email extraction where needed
                enhanced_businesses = []
                for business in businesses:
                    if openai_client:
                        business["email"] = extract_potential_emails_with_llm(business, openai_client)
                    enhanced_businesses.append(business)
                
                st.session_state["businesses"] = enhanced_businesses
                st.success(f"Found {len(enhanced_businesses)} businesses!")
    
    # Display results if available
    if "businesses" in st.session_state and st.session_state["businesses"]:
        businesses = st.session_state["businesses"]
        
        # Export options
        st.subheader("Export Results")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Export to CSV"):
                csv_data = export_businesses_to_csv(businesses)
                if csv_data:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"business_data_{timestamp}.csv"
                    st.download_button(
                        label="Download CSV",
                        data=csv_data,
                        file_name=filename,
                        mime="text/csv"
                    )
        
        with col2:
            if st.button("Export to Excel"):
                excel_data = export_businesses_to_excel(businesses)
                if excel_data:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"business_data_{timestamp}.xlsx"
                    st.download_button(
                        label="Download Excel",
                        data=excel_data,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        
        # Display business details
        st.subheader("Search Results")
        for i, business in enumerate(businesses):
            with st.expander(f"{i+1}. {business['name']}"):
                st.write(f"**Address:** {business['address']}")
                st.write(f"**Business Types:** {', '.join(business['types'])}")
                
                if business['website']:
                    st.write(f"**Website:** [{business['website']}]({business['website']})")
                else:
                    st.write("**Website:** Not available")
                    
                if business['phone']:
                    st.write(f"**Phone:** {business['phone']}")
                else:
                    st.write("**Phone:** Not available")
                
                if business['email']:
                    st.write(f"**Emails:** {', '.join(business['email'])}")
                else:
                    st.write("**Emails:** Not found")

# Main App Flow
def main():
    # Check if the user is authenticated
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    
    # Show login page or main app based on authentication status
    if not st.session_state["authenticated"]:
        display_login_page()
    else:
        display_main_app()

if __name__ == "__main__":
    main()
