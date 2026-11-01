import streamlit as st
import pandas as pd
import requests
import re
from duckduckgo_search import DDGS
import time
import io

st.set_page_config(page_title="Contact Enrichment Tool", layout="wide")
st.title("Lead Enrichment Web App")
st.write("Upload your Excel file to find websites and emails securely from your local network.")

uploaded_file = st.file_uploader("Upload Excel File", type=['xlsx'])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file, sheet_name=0)
    if "Website" not in df.columns: df["Website"] = None
    if "Scraped_Email" not in df.columns: df["Scraped_Email"] = None
    
    if st.button("Start Enrichment"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        ddgs = DDGS()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        
        for index, row in df.iterrows():
            company = str(row['Company'])
            status_text.text(f"Processing [{index + 1}/{len(df)}]: {company}...")
            
            # Find Website
            if company != "nan" and pd.isna(row['Website']):
                try:
                    res = ddgs.text(f"{company} UK accounting website", max_results=3)
                    for r in (res or []):
                        if "bing.com" not in r.get('href', '') and "duckduckgo.com" not in r.get('href', ''):
                            df.at[index, 'Website'] = r.get('href')
                            break
                    time.sleep(1.5)
                except: pass
            
            # Find Email
            url = str(df.at[index, 'Website'])
            if url.startswith("http") and pd.isna(row['Scraped_Email']):
                try:
                    html = requests.get(url, headers=headers, timeout=5).text
                    emails = set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html))
                    valid = [e.lower() for e in emails if not any(e.lower().endswith(x) for x in ['.png', '.jpg', '.css', '.js', '.svg'])]
                    df.at[index, 'Scraped_Email'] = ", ".join(valid[:2]) if valid else "None found"
                except: df.at[index, 'Scraped_Email'] = "Connection failed"
            
            progress_bar.progress((index + 1) / len(df))
            
        status_text.text("Complete!")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Download Enriched Data", data=output.getvalue(), file_name="enriched_contacts_local.xlsx")
