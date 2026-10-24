"""
VERIFAI frontend.   Run with:  streamlit run frontend.py

Screens: home -> results -> investigating -> report
Data:    USE_SAMPLE = True  uses sample_data.py (shows a SAMPLE DATA badge).
         Set it to False once A and B have connected backend.py.
"""
import html as _html
import time
from urllib.parse import urlparse

import streamlit as st
import sys
from pathlib import Path

sys.path.append(str(Path.cwd().parent))

from backend import backend 
# import backend

from backend import sample_data
from backend.sample_data import (
    AGENT_STEPS, LIVE_SOURCES, POPULAR_SEARCHES, SAMPLE_REPORT
)

USE_SAMPLE = True

st.set_page_config(page_title="VERIFAI", page_icon="🛡️", layout="wide")


# ───────────────────────── helpers ─────────────────────────
def esc(x):
    return _html.escape(str(x))


def md(markup):
    """Render HTML safely: strip indentation so Markdown never treats it as code."""
    st.markdown("".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def shield(size=28):
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none">'
        '<path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z" fill="#2563EB"/>'
        '<path d="m8.5 12 2.5 2.5 4.5-5" stroke="#fff" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def valid_url(u):
    p = urlparse(u.strip())
    return p.scheme in ("http", "https") and bool(p.netloc)


def sample_badge():
    if st.session_state.use_sample:
        md('<span class="sample-badge">SAMPLE DATA</span>')


def notice(title, message, kind="error"):
    md(f'<div class="notice {kind}"><b>{esc(title)}</b><br>{esc(message)}</div>')


STATUS = {
    "pass": ("Pass", "badge-pass"),
    "fail": ("Fail", "badge-fail"),
    "unknown": ("Unknown", "badge-unknown"),
}

# ───────────────────────── CSS ─────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--navy:#0B1B3A;--bg:#F4F6FB;--card:#FFFFFF;--line:#E3E8F2;--ink:#0F1B33;--muted:#64748B;
--blue:#2563EB;--blue-soft:#E8F0FE;--green:#15803D;--green-soft:#DCFCE7;--amber:#B45309;
--amber-soft:#FEF3C7;--red:#B91C1C;--red-soft:#FEE2E2;}
html,body,.stApp,[class*="css"]{font-family:'Inter',sans-serif;color:var(--ink);}
.stApp{background:var(--bg);}
header[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
.block-container{padding-top:1.6rem;max-width:1180px;}

/* sidebar */
[data-testid="stSidebar"]{background:var(--navy);min-width:230px;max-width:230px;}
[data-testid="stSidebar"] *{color:#E2E8F0;}
[data-testid="stSidebar"] .stButton>button{background:transparent;border:none;box-shadow:none;
justify-content:flex-start;width:100%;font-weight:500;padding:.55rem .8rem;border-radius:8px;}
[data-testid="stSidebar"] .stButton>button:hover{background:rgba(255,255,255,.08);}
[data-testid="stSidebar"] .stButton>button[kind="primary"],
[data-testid="stSidebar"] .stButton>button[data-testid="stBaseButton-primary"]{background:rgba(255,255,255,.14);}
.side-brand{display:flex;align-items:center;gap:.6rem;font-weight:800;font-size:1.15rem;
color:#fff;padding:.4rem .5rem 1.2rem;}

/* buttons and inputs */
.stButton>button,.stFormSubmitButton>button{border-radius:10px;border:1px solid var(--line);
background:#fff;color:var(--ink);font-weight:600;}
.stButton>button:hover{border-color:var(--blue);color:var(--blue);}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"],
button[data-testid^="stBaseButton-primary"]{background:var(--blue);border:none;color:#fff;}
.stTextInput input{border-radius:12px;padding:.85rem 1rem;border:1px solid var(--line);background:#fff;}
[data-testid="stForm"]{border:none;padding:0;background:transparent;}

/* home */
.hero{text-align:center;padding:2.2rem 0 1.2rem;}
.brand{font-size:2.6rem;font-weight:800;letter-spacing:.02em;color:var(--navy);margin-top:.3rem;}
.tag{font-size:1.25rem;font-weight:600;color:var(--navy);margin-top:.2rem;}
.feat{text-align:center;padding:.6rem .8rem;}
.feat .ico{font-size:1.5rem;}
.feat .ft{font-weight:700;margin-top:.3rem;}
.feat .fd{color:var(--muted);font-size:.85rem;margin-top:.2rem;}
.sec-title{font-weight:700;margin:1.6rem 0 .5rem;}

/* cards */
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;margin-bottom:.7rem;}
.card h4{margin:0 0 .6rem;font-size:1rem;font-weight:700;}
.result{display:flex;gap:1rem;}
.thumb{flex:0 0 78px;height:78px;border-radius:12px;background:var(--navy);color:#fff;
display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.1rem;}
.result-body{flex:1;min-width:0;}
.result-top{display:flex;justify-content:space-between;gap:.6rem;align-items:flex-start;}
.result-title{font-weight:700;font-size:1.05rem;}
.muted{color:var(--muted);font-size:.85rem;}
.meta{display:flex;flex-wrap:wrap;gap:1rem;margin-top:.6rem;font-size:.85rem;color:#334155;}
.note{margin-top:.6rem;font-size:.82rem;}
.note.good{color:var(--green);}
.note.warn{color:var(--amber);}
.note.bad{color:var(--red);}
.match,.verified,.badge,.pill,.sample-badge{display:inline-block;border-radius:999px;font-weight:600;white-space:nowrap;}
.match{padding:.2rem .6rem;font-size:.78rem;}
.match.hi{background:var(--green-soft);color:var(--green);}
.match.mid{background:var(--amber-soft);color:var(--amber);}
.match.lo{background:var(--red-soft);color:var(--red);}
.verified{padding:.2rem .55rem;font-size:.75rem;background:var(--blue-soft);color:var(--blue);margin-left:.3rem;}
.badge{padding:.18rem .65rem;font-size:.78rem;}
.badge-pass{background:var(--green-soft);color:var(--green);}
.badge-unknown{background:var(--amber-soft);color:var(--amber);}
.badge-fail{background:var(--red-soft);color:var(--red);}
.pill{padding:.3rem .8rem;font-size:.8rem;background:#fff;border:1px solid var(--line);margin:0 .3rem .4rem 0;}
.pill.on{background:var(--blue);color:#fff;border-color:var(--blue);}
.sample-badge{padding:.2rem .7rem;font-size:.72rem;letter-spacing:.06em;background:#FFF4CC;
color:#8A5A00;border:1px dashed #E0A800;margin-bottom:.6rem;}
.querybar{background:#fff;border:1px solid var(--line);border-radius:12px;padding:.7rem 1rem;
margin-bottom:.6rem;font-weight:500;}

/* verification report */
.claim{display:grid;grid-template-columns:170px 90px 1fr;gap:.8rem;align-items:center;
padding:.75rem 0;border-bottom:1px solid var(--line);}
.claim-name{font-weight:600;}
.claim-reason{color:#334155;font-size:.88rem;}
.conflict{background:var(--amber-soft);border:1px solid #F3D48A;border-radius:12px;padding:.8rem 1rem;margin-bottom:.5rem;}
.conflict .cv{background:#fff;border-radius:10px;padding:.6rem .8rem;border:1px solid var(--line);}
.srcl{display:block;padding:.45rem 0;border-bottom:1px solid var(--line);font-size:.85rem;}
.srcl a,.cv a{color:var(--blue);text-decoration:none;}
.srcl a:hover,.cv a:hover{text-decoration:underline;}
.score{text-align:center;background:var(--green-soft);border-radius:12px;padding:.7rem 1rem;color:var(--green);font-weight:800;font-size:1.6rem;}
.score small{display:block;font-weight:600;font-size:.75rem;}
.disclaimer{color:var(--muted);font-size:.78rem;margin-top:.8rem;}

/* notices */
.notice{border-radius:12px;padding:.8rem 1rem;margin:.6rem 0;font-size:.9rem;}
.notice.error{background:var(--red-soft);color:var(--red);border:1px solid #F5B5B5;}
.notice.info{background:var(--blue-soft);color:#1E40AF;border:1px solid #BFD3FA;}
.notice.empty{background:#fff;color:var(--muted);border:1px dashed var(--line);text-align:center;padding:1.6rem;}

/* progress tracker */
.tracker{display:flex;align-items:center;justify-content:center;margin:.8rem 0 1.2rem;}
.step{display:flex;align-items:center;gap:.5rem;font-weight:600;color:var(--muted);}
.step .dot{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;
background:#E2E8F0;color:#64748B;font-size:.85rem;}
.step.done .dot{background:var(--green);color:#fff;}
.step.active .dot{background:var(--blue);color:#fff;}
.step.done,.step.active{color:var(--ink);}
.bar{height:2px;width:60px;background:var(--line);margin:0 .6rem;}
.act{display:flex;gap:.7rem;padding:.55rem 0;}
.act .ai{width:22px;text-align:center;}
.act.todo{opacity:.5;}
.act .at{font-weight:600;font-size:.9rem;}
.act .as{color:var(--muted);font-size:.8rem;}
.src{display:flex;justify-content:space-between;padding:.45rem 0;border-bottom:1px solid var(--line);font-size:.85rem;}
.src .st{color:var(--muted);font-size:.78rem;}
.src .st.now{color:var(--blue);font-weight:600;}
.ext{display:flex;justify-content:space-between;padding:.4rem 0;font-size:.88rem;}
@media (max-width:700px){.claim{grid-template-columns:1fr;gap:.3rem;}.result{flex-direction:column;}}
</style>
"""

# ───────────────────────── state ─────────────────────────
DOMAINS = ["AI/ML", "Web Development", "Data Science", "Cybersecurity", "Others"]
LOCATIONS = ["India", "Remote", "Hybrid"]
ELIGIBILITY = ["Second year (Engineering)", "Other"]
MAIN_DOMAINS = DOMAINS[:4]

FILTER_DEFAULTS = {
    **{f"dom_{d}": d == "AI/ML" for d in DOMAINS},
    **{f"loc_{l}": l == "India" for l in LOCATIONS},
    **{f"eli_{e}": e == ELIGIBILITY[0] for e in ELIGIBILITY},
    "prize_above": True,
    "prize_any": False,
}

DEFAULTS = {
    "page": "home", "query": "", "category": "Hackathons", "url": "",
    "report": None, "selected": None, "results": None, "results_query": None,
    "use_sample": USE_SAMPLE, "home_error": None,
}
for k, v in {**DEFAULTS, **FILTER_DEFAULTS}.items():
    st.session_state.setdefault(k, v)


def go(page):
    st.session_state.page = page


def go_discover():
    st.session_state.page = "results" if st.session_state.query else "home"


def reset_filters():
    for k, v in FILTER_DEFAULTS.items():
        st.session_state[k] = v


def clear_cache():
    st.session_state.results = None
    st.session_state.results_query = None
    st.session_state.report = None


def start_search(query):
    st.session_state.query = query
    st.session_state.home_error = None
    st.session_state.page = "results"


def open_listing(item):
    st.session_state.selected = item
    st.session_state.url = item["url"]
    st.session_state.report = None
    st.session_state.page = "investigating"


# ───────────────────────── sidebar ─────────────────────────
def render_sidebar():
    with st.sidebar:
        md(f'<div class="side-brand">{shield(26)}VERIFAI</div>')
        page = st.session_state.page
        st.button("🏠  Home", key="nav_home", on_click=go, args=("home",),
                  type="primary" if page == "home" else "secondary")
        st.button("🧭  Discover", key="nav_disc", on_click=go_discover,
                  type="primary" if page in ("results", "investigating", "report") else "secondary")
        st.button("🔍  My Searches", key="nav_ms", on_click=go, args=("searches",),
                  type="primary" if page == "searches" else "secondary")
        st.button("🔖  Saved", key="nav_saved", on_click=go, args=("saved",),
                  type="primary" if page == "saved" else "secondary")
        st.markdown("---")
        st.toggle("Use sample data", key="use_sample", on_change=clear_cache)


# ───────────────────────── home ─────────────────────────
def render_home():
    md(f"""<div class="hero">{shield(54)}<div class="brand">VERIFAI</div>
    <div class="tag">Find what fits. Verify what's real.</div></div>""")

    _, mid, _ = st.columns([1, 4, 1])
    with mid:
        with st.form("search_form"):
            c1, c2 = st.columns([6, 1])
            q = c1.text_input("Search", key="home_input", label_visibility="collapsed",
                              placeholder="What opportunity are you looking for? Or paste a listing URL")
            submitted = c2.form_submit_button("Search", type="primary", use_container_width=True)

        st.radio("Category", ["Hackathons", "Internships", "Scholarships"], key="category",
                 horizontal=True, label_visibility="collapsed")
        if st.session_state.category != "Hackathons":
            notice("Hackathons first",
                   "Internships and scholarships are coming next. Searching will look for hackathons for now.",
                   "info")

        if submitted:
            q = q.strip()
            if not q:
                st.session_state.home_error = ("Enter a search", "Describe what you're looking for, or paste a listing URL.")
            elif q.lower().startswith("http") and not valid_url(q):
                st.session_state.home_error = ("That URL doesn't look right", "Use a full link that starts with http:// or https://.")
            elif valid_url(q):
                st.session_state.url = q
                st.session_state.selected = None
                st.session_state.report = None
                st.session_state.home_error = None
                st.session_state.page = "investigating"
                st.rerun()
            else:
                start_search(q)
                st.rerun()
        if st.session_state.home_error:
            notice(*st.session_state.home_error)

    cols = st.columns(4)
    feats = [("🔎", "Discover", "Find relevant opportunities based on your requirements."),
             ("🛡️", "Verify", "Check details against live webpages."),
             ("📄", "Get evidence", "See sources, reasons and verification status."),
             ("⏱️", "Save time", "No more multiple tabs and manual checking.")]
    for col, (ico, t, d) in zip(cols, feats):
        with col:
            md(f'<div class="feat"><div class="ico">{ico}</div><div class="ft">{t}</div><div class="fd">{d}</div></div>')

    md('<div class="sec-title">Popular searches</div>')
    pcols = st.columns(len(POPULAR_SEARCHES))
    for col, ps in zip(pcols, POPULAR_SEARCHES):
        col.button(ps, key=f"pop_{ps}", on_click=start_search, args=(ps,), use_container_width=True)


# ───────────────────────── results ─────────────────────────
def load_results(query):
    if st.session_state.results is not None and st.session_state.results_query == query:
        return st.session_state.results
    if st.session_state.use_sample:
        data = SAMPLE_RESULTS
    else:
        data = backend.search_opportunities(query, {"category": st.session_state.category})
    st.session_state.results, st.session_state.results_query = data, query
    return data


def apply_filters(items):
    ss = st.session_state
    doms = [d for d in DOMAINS if ss[f"dom_{d}"]]
    locs = [l for l in LOCATIONS if ss[f"loc_{l}"]]
    elis = [e for e in ELIGIBILITY if ss[f"eli_{e}"]]
    out = []
    for r in items:
        if doms:
            ok = r["domain"] in doms or ("Others" in doms and r["domain"] not in MAIN_DOMAINS)
            if not ok:
                continue
        if locs and not set(locs) & set(r["location_tags"]):
            continue
        if elis and not set(elis) & set(r["eligibility_tags"]):
            continue
        if ss["prize_above"] and not ss["prize_any"] and r["prize_value"] < 50000:
            continue
        out.append(r)
    return out


def render_result_card(r):
    m = r["match"]
    mcls = "hi" if m >= 85 else "mid" if m >= 60 else "lo"
    ncls = "good" if m >= 85 else "warn" if m >= 60 else "bad"
    verified = '<span class="verified">✓ Verified</span>' if r.get("verified") else ""
    md(f"""<div class="card result"><div class="thumb">{esc(r['icon'])}</div>
    <div class="result-body"><div class="result-top"><div>
    <div class="result-title">{esc(r['title'])}</div><div class="muted">{esc(r['organizer'])}</div></div>
    <div><span class="match {mcls}">{m}% match</span>{verified}</div></div>
    <div class="meta"><span>🏆 {esc(r['prize'])}</span><span>📅 {esc(r['deadline'])}</span>
    <span>🎓 {esc(r['eligibility'])}</span></div>
    <div class="note {ncls}">{esc(r['note'])}</div></div></div>""")
    st.button("View details", key=f"view_{r['id']}", on_click=open_listing, args=(r,))


def render_results():
    ss = st.session_state
    st.button("← Back", key="back_home", on_click=go, args=("home",))
    sample_badge()
    md(f'<div class="querybar">🔎 {esc(ss.query)}</div>')

    chips = [ss.category] + [l for l in LOCATIONS if ss[f"loc_{l}"]] + [e for e in ELIGIBILITY if ss[f"eli_{e}"]]
    if ss.prize_above and not ss.prize_any:
        chips.append("Prize above ₹50,000")
    md("".join(f'<span class="pill on">{esc(c)}</span>' for c in chips))

    try:
        with st.spinner("Loading results..."):
            items = load_results(ss.query)
    except NotImplementedError:
        notice("Search isn't connected yet", "backend.search_opportunities() has no implementation. Switch on sample data in the sidebar to preview the screen.")
        return
    except Exception as e:
        notice("We couldn't load results", "Check your connection and try again. If it keeps happening, switch on sample data in the sidebar.")
        with st.expander("Technical details"):
            st.code(f"{type(e).__name__}: {e}")
        st.button("Try again", key="retry_results", on_click=clear_cache)
        return

    left, right = st.columns([1, 3])
    with left:
        md('<div class="card"><h4>Filters</h4></div>')
        st.button("Reset filters", key="reset_f", on_click=reset_filters)
        st.markdown("**Domain**")
        for d in DOMAINS:
            st.checkbox(d, key=f"dom_{d}")
        st.markdown("**Location**")
        for l in LOCATIONS:
            st.checkbox(l, key=f"loc_{l}")
        st.markdown("**Prize amount**")
        st.checkbox("Above ₹50,000", key="prize_above")
        st.checkbox("Any amount", key="prize_any")
        st.markdown("**Eligibility**")
        for e in ELIGIBILITY:
            st.checkbox(e, key=f"eli_{e}")

    with right:
        shown = apply_filters(items)
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"**{len(shown)} results found**")
        sort = c2.selectbox("Sort by", ["Relevance", "Prize: high to low"], label_visibility="collapsed")
        shown = sorted(shown, key=(lambda r: -r["prize_value"]) if sort.startswith("Prize") else (lambda r: -r["match"]))
        if not shown:
            md('<div class="notice empty"><b>No matches yet</b><br>Remove a filter or reset them to see more listings.</div>')
        for r in shown:
            render_result_card(r)


# ───────────────────────── investigating ─────────────────────────
STEPS = ["Discover", "Inspect", "Cross-check", "Verify"]
TRACKER_FOR_PHASE = [0, 1, 1, 2, 3]


def tracker(active):
    parts = []
    for i, name in enumerate(STEPS):
        state = "done" if i < active else "active" if i == active else "todo"
        mark = "✓" if state == "done" else str(i + 1)
        parts.append(f'<div class="step {state}"><div class="dot">{mark}</div>{name}</div>')
    md('<div class="tracker">' + '<div class="bar"></div>'.join(parts) + "</div>")


def draw_progress(phase):
    tracker(TRACKER_FOR_PHASE[phase])
    left, right = st.columns(2)
    with left:
        rows = []
        for i, (title, sub) in enumerate(AGENT_STEPS):
            if i < phase:
                ico, cls = "✅", ""
            elif i == phase:
                ico, cls = "🔵", ""
            else:
                ico, cls = "⚪", "todo"
            rows.append(f'<div class="act {cls}"><div class="ai">{ico}</div><div><div class="at">{esc(title)}</div><div class="as">{esc(sub)}</div></div></div>')
        md('<div class="card"><h4>Agent activity</h4>' + "".join(rows) + "</div>")
    with right:
        src = []
        for k, s in enumerate(LIVE_SOURCES):
            if phase == 0 or k > phase - 1:
                label, cls = "Queued", ""
            elif k == phase - 1:
                label, cls = "Currently inspecting...", "now"
            else:
                label, cls = "Checked", ""
            src.append(f'<div class="src"><span>{esc(s)}</span><span class="st {cls}">{label}</span></div>')
        md('<div class="card"><h4>Live sources</h4>' + "".join(src) + "</div>")

        reveal_at = [2, 2, 3, 3]
        ext = []
        for (label, value), at in zip(SAMPLE_REPORT["extracted"], reveal_at):
            if phase >= at:
                ext.append(f'<div class="ext"><span class="muted">{esc(label)}</span><b>{esc(value)}</b></div>')
        body = "".join(ext) or '<div class="muted">Waiting for the first details...</div>'
        md('<div class="card"><h4>Extracted information (live)</h4>' + body + "</div>")


def render_investigating():
    ss = st.session_state
    sel = ss.selected
    title = sel["title"] if sel else ss.url
    st.button("← Back", key="back_res", on_click=go, args=("results" if ss.query else "home",))
    sample_badge()
    st.subheader(f"Investigating: {title}")
    st.caption("Our AI agents are visiting official sources to verify the details.")

    if ss.use_sample:
        holder = st.empty()
        for phase in range(len(AGENT_STEPS)):
            with holder.container():
                draw_progress(phase)
            time.sleep(1.0)
        report = {**SAMPLE_REPORT}
        if sel:
            report.update(title=sel["title"], organizer=sel["organizer"], icon=sel["icon"], url=sel["url"])
        ss.report = report
        ss.page = "report"
        st.rerun()
        return

    tracker(1)
    try:
        with st.spinner("Agents are reading the listing and its sources. This can take a minute."):
            report = backend.verify_listing(ss.url)
        if not isinstance(report, dict) or "claims" not in report:
            raise ValueError("The backend returned an unexpected format.")
    except NotImplementedError:
        notice("Verification isn't connected yet", "backend.verify_listing() has no implementation. Switch on sample data in the sidebar to preview the report.")
        return
    except Exception as e:
        notice("We couldn't verify this listing", "The page may be blocked, offline or slow. Check the link and try again.")
        with st.expander("Technical details"):
            st.code(f"{type(e).__name__}: {e}")
        st.button("Try again", key="retry_verify", on_click=go, args=("investigating",))
        return
    ss.report = report
    ss.page = "report"
    st.rerun()


# ───────────────────────── report ─────────────────────────
def render_claim(c):
    label, cls = STATUS.get(c["status"], STATUS["unknown"])
    md(f"""<div class="claim"><div class="claim-name">{esc(c['name'])}</div>
    <div><span class="badge {cls}">{label}</span></div>
    <div class="claim-reason">{esc(c['reason'])}</div></div>""")
    ev = c.get("evidence") or []
    with st.expander(f"View evidence ({len(ev)})" if ev else "No evidence found"):
        if not ev:
            st.write("No source confirmed this claim, so it is not counted as a pass.")
        for e in ev:
            md(f"""<div class="srcl"><b>{esc(e['source'])}</b><br>
            <span class="muted">“{esc(e['snippet'])}”</span><br>
            <a href="{esc(e['url'])}" target="_blank" rel="noopener noreferrer">{esc(e['url'])}</a></div>""")


def render_conflicts(conflicts):
    md('<div class="sec-title">⚠️ Conflicts found</div>')
    for cf in conflicts:
        md(f'<div class="conflict"><b>{esc(cf["field"])}</b><br><span class="muted">{esc(cf["note"])}</span></div>')
        cols = st.columns(len(cf["values"]))
        for col, v in zip(cols, cf["values"]):
            with col:
                md(f"""<div class="cv"><span class="muted">{esc(v['source'])}</span><br>
                <b>{esc(v['value'])}</b><br>
                <a href="{esc(v['url'])}" target="_blank" rel="noopener noreferrer">Open source</a></div>""")


def render_report():
    ss = st.session_state
    rep = ss.report
    if not rep:
        notice("No report yet", "Pick a listing or paste a URL to start a verification.", "info")
        st.button("Go to home", on_click=go, args=("home",))
        return

    claims = rep["claims"]
    n_pass = sum(c["status"] == "pass" for c in claims)
    n_fail = sum(c["status"] == "fail" for c in claims)
    n_unk = sum(c["status"] == "unknown" for c in claims)

    top1, top2 = st.columns([6, 1])
    top1.button("← Back", key="back_from_report", on_click=go, args=("results" if ss.query else "home",))
    sample_badge()

    meta = "".join(f'<span class="pill">{esc(m)}</span>' for m in rep.get("meta", []))
    match = rep.get("match")
    score = f'<div class="score">{match}%<small>match</small></div>' if match is not None else ""
    h1, h2 = st.columns([4, 1])
    with h1:
        md(f"""<div class="card result"><div class="thumb">{esc(rep.get('icon', ''))}</div>
        <div class="result-body"><div class="result-title" style="font-size:1.25rem">{esc(rep['title'])}</div>
        <div class="muted">{esc(rep.get('organizer', ''))}</div><div style="margin-top:.6rem">{meta}</div></div></div>""")
    with h2:
        md(score)

    left, right = st.columns([2, 1])
    with left:
        t1, t2, t3 = st.tabs(["Verification report", "Source links", "Raw data"])
        with t1:
            md('<div class="sec-title" style="margin-top:.4rem">Claim verification</div>')
            for c in claims:
                render_claim(c)
            if rep.get("conflicts"):
                render_conflicts(rep["conflicts"])
        with t2:
            for s in rep.get("sources", []):
                md(f"""<div class="srcl"><b>{esc(s['type'])}</b> · <span class="muted">{esc(s['visited'])}</span><br>
                <a href="{esc(s['url'])}" target="_blank" rel="noopener noreferrer">{esc(s['url'])}</a></div>""")
        with t3:
            st.json(rep)

    with right:
        if n_fail:
            head, cls = "Doesn't match all criteria", "badge-fail"
        elif n_unk:
            head, cls = "Matches, with items to check", "badge-unknown"
        else:
            head, cls = "Matches your criteria", "badge-pass"
        md(f"""<div class="card"><h4>Summary</h4><span class="badge {cls}">{head}</span>
        <div style="margin-top:.7rem" class="claim-reason">
        ✅ {n_pass} passed<br>❌ {n_fail} failed<br>❔ {n_unk} unknown (needs manual review)</div></div>""")
        links = "".join(
            f'<div class="srcl"><b>{esc(s["type"])}</b><br><a href="{esc(s["url"])}" target="_blank" '
            f'rel="noopener noreferrer">{esc(s["label"])}</a><br><span class="muted">{esc(s["visited"])}</span></div>'
            for s in rep.get("sources", [])[:3])
        md(f'<div class="card"><h4>Source links</h4>{links}</div>')
        md(f"""<div class="disclaimer">Checked {esc(rep.get('checked_at', ''))}.
        VERIFAI shows what it found and where. It doesn't guarantee every claim is true.</div>""")


# ───────────────────────── placeholders + router ─────────────────────────
def render_placeholder():
    name = "My searches" if st.session_state.page == "searches" else "Saved"
    st.subheader(name)
    md(f'<div class="notice empty"><b>Nothing here yet</b><br>{name} will list what you save once you run a search.</div>')
    st.button("Start a search", on_click=go, args=("home",))


PAGES = {
    "home": render_home,
    "results": render_results,
    "investigating": render_investigating,
    "report": render_report,
    "searches": render_placeholder,
    "saved": render_placeholder,
}

md(CSS)
render_sidebar()
PAGES.get(st.session_state.page, render_home)()
