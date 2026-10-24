"""Streamlit interface for scraping user-provided pages into opportunity listings.

Run from the project root with: streamlit run frontend/frontend.py
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.backend import collect_from_pages
from backend.models import DEFAULT_GOAL


st.set_page_config(page_title="Opportunity Finder", page_icon="🔎", layout="wide")
st.title("Opportunity Finder")
st.write(
    "Provide the pages to search and the maximum number of listings to collect. "
    "TinyFish visits the links in order and stops once it reaches your limit."
)

with st.form("search_opportunities"):
    links_text = st.text_area(
        "Links to search (one URL per line)",
        placeholder="https://example.com/careers\nhttps://another.example/jobs",
        height=140,
    )
    goal = st.text_area("Information to collect", value=DEFAULT_GOAL, height=100)
    result_limit = st.number_input("Maximum listings", min_value=1, max_value=100, value=10)
    submitted = st.form_submit_button("Search links", type="primary", use_container_width=True)

if submitted:
    links = list(dict.fromkeys(line.strip() for line in links_text.splitlines() if line.strip()))
    invalid_links = [
        url for url in links
        if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc
    ]
    if not links:
        st.error("Enter at least one URL to search.")
    elif invalid_links:
        st.error("Every link must be a complete URL beginning with http:// or https://.")
    elif not os.getenv("TINYFISH_API_KEY"):
        st.error("Set TINYFISH_API_KEY in your environment or .env file before searching.")
    else:
        try:
            pages = {url: url for url in links}
            with st.status("Searching supplied links…", expanded=True) as progress:
                progress.write(f"Visiting up to {len(pages)} links until {int(result_limit)} listings are collected.")
                listings = collect_from_pages(
                    pages,
                    goal,
                    int(result_limit),
                    on_progress=progress.write,
                )
                progress.update(label="Search complete", state="complete", expanded=False)
            st.session_state["target_pages"] = list(pages)
            st.session_state["listings"] = listings
            st.session_state["result_limit"] = int(result_limit)
        except Exception as error:
            st.error(f"Could not complete the search: {error}")

pages = st.session_state.get("target_pages")
listings = st.session_state.get("listings")
if pages is not None:
    with st.expander(f"Links provided ({len(pages)})", expanded=False):
        if pages:
            for url in pages:
                parsed_url = urlparse(url)
                if parsed_url.scheme in ("http", "https") and parsed_url.netloc:
                    st.link_button(url, url, use_container_width=False)
                else:
                    st.code(url)
        else:
            st.info("No links have been submitted yet.")

if listings is not None:
    st.subheader(f"Results ({len(listings)} of up to {st.session_state.get('result_limit', 0)})")
    if not listings:
        st.info("No listings were returned from the target pages. Try a broader search or revise the collection instructions.")
    else:
        st.dataframe(listings, use_container_width=True, hide_index=True)
        st.download_button(
            "Download results as JSON",
            data=json.dumps(listings, indent=2, ensure_ascii=False),
            file_name="listings.json",
            mime="application/json",
        )
