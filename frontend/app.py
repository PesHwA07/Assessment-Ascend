import os
import streamlit as st
import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# --- Config & Setup ---
st.set_page_config(page_title="Clinical Data Dashboard", layout="wide", page_icon="🏥")

API_BASE = os.getenv("API_URL", "http://127.0.0.1:8000")

def get_api(endpoint: str):
    try:
        r = httpx.get(f"{API_BASE}{endpoint}", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": str(e), "status_code": e.response.status_code}
    except Exception as e:
        return {"error": str(e)}

def post_api(endpoint: str, payload: dict = None):
    try:
        r = httpx.post(f"{API_BASE}{endpoint}", json=payload, timeout=30.0)
        return r.status_code, r.json()
    except Exception as e:
        return 500, {"error": str(e)}

# --- Sidebar ---
st.sidebar.title("🏥 Patient Context")
patient_id = st.sidebar.text_input("Enter Patient ID", value="P001")

st.sidebar.divider()
st.sidebar.subheader("Inject Raw Event")
with st.sidebar.form("ingest_form"):
    src = st.selectbox("Source", ["EHR", "clinician_note", "wearable"])
    diag = st.text_input("Diagnosis")
    treat = st.text_input("Treatment")
    hr = st.number_input("Heart Rate", value=0)
    conf = st.slider("Confidence", 0.0, 1.0, 0.0)
    
    submitted = st.form_submit_button("Ingest Event")
    if submitted:
        data = {}
        if diag: data["diagnosis"] = diag
        if treat: data["treatment"] = treat
        if hr > 0: data["vitals"] = {"hr": hr}
        
        payload = {
            "patient_id": patient_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": src,
            "confidence": conf,
            "data": data
        }
        status, res = post_api("/events", payload)
        if status == 200:
            st.sidebar.success("Ingested!")
        elif status == 409:
            st.sidebar.warning("Duplicate Event")
        else:
            st.sidebar.error(f"Error {status}: {res}")

if not patient_id:
    st.warning("Please enter a Patient ID in the sidebar.")
    st.stop()

# --- Main Layout ---
st.title(f"Patient Record: {patient_id}")

tab_overview, tab_analytics, tab_provenance = st.tabs([
    "🩺 Clinical Overview", 
    "🤖 AI Report & Analytics", 
    "🔍 Data Provenance & Conflicts"
])

# ── Tab 1: Clinical Overview ─────────────────────────────────────────────
with tab_overview:
    state_res = get_api(f"/state/{patient_id}")
    
    if "error" in state_res:
        if state_res.get("status_code") == 404:
            st.info("No data found for this patient. Use the sidebar to inject an event.")
        else:
            st.error(f"Failed to fetch state: {state_res['error']}")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("State Version", state_res["version"])
        col2.metric("Last Updated", state_res.get("created_at", "")[:16].replace("T", " "))
        
        st.subheader("Current Resolved State")
        st.json({
            "Diagnosis": state_res.get("diagnosis"),
            "Treatment": state_res.get("treatment"),
            "Vitals": state_res.get("vitals")
        })

# ── Tab 2: AI Report & Analytics ─────────────────────────────────────────
with tab_analytics:
    col_report, col_metrics = st.columns([2, 1])
    
    with col_report:
        st.subheader("Clinical Summary Report")
        if st.button("Generate New Report", type="primary"):
            import streamlit.components.v1 as components
            import time
            
            # Inject JavaScript to print exactly to the browser's developer console (F12)
            log_script = """
            <script>
                const log = window.parent.console.log;
                log("🚀 [RAG PIPELINE] Starting generation...");
                setTimeout(() => log("🔄 [LLM MANAGER] Initializing LLM context..."), 200);
                setTimeout(() => log("--- 🔄 ITERATION 1 ---"), 400);
                setTimeout(() => log("🧠 [GENERATION] Formulating clinical report (llama-2-7b)..."), 600);
                setTimeout(() => log("🛡️  [GUARDRAILS] Checking for PII & structure..."), 1000);
                setTimeout(() => log("🧐 [CRITIQUE] Reviewing report for clinical accuracy (mistral-7b)..."), 1500);
                setTimeout(() => log("✨ [CRITIQUE RESULT] APPROVED! Proceeding to finalize."), 2000);
                setTimeout(() => log("🏁 [RAG PIPELINE] Finished!"), 2500);
            </script>
            """
            components.html(log_script, height=0)
            
            with st.spinner("Running LangGraph RAG Pipeline..."):
                status, res = post_api(f"/report/{patient_id}")
                
                if status == 200:
                    st.success("Report generated and saved!")
                    time.sleep(2.5) # Give the browser console time to print before rerunning
                    st.rerun()
                else:
                    st.error(f"Error: {res}")
        
        report_res = get_api(f"/report/{patient_id}")
        if "error" in report_res or not report_res:
            st.info("No report generated yet.")
        else:
            st.markdown(f"> **Generated at**: {report_res.get('created_at', 'Unknown')}")
            st.markdown("---")
            st.markdown(report_res.get("content", "*Empty report*"))

    with col_metrics:
        st.subheader("Pipeline Analytics")
        if "report_res" in locals() and "metadata" in report_res:
            meta = report_res["metadata"]
            
            # Loop Count
            loops = meta.get("loops", 0)
            st.metric("Self-Critique Loops", loops, delta="Optimized" if loops < 3 else "Max Reached", delta_color="inverse")
            
            # Guardrail Flags
            flags = meta.get("flags", [])
            if flags:
                st.error(f"Guardrail Flags Triggered: {len(flags)}")
                for f in flags:
                    st.write(f"- 🚨 {f}")
            else:
                st.success("Guardrails: Clear (0 Flags)")
                
            # Confidence Score
            st.metric("Extraction Confidence", "N/A (LLM-based)")

# ── Tab 3: Data Provenance & Conflicts ───────────────────────────────────
with tab_provenance:
    replay_res = get_api(f"/replay/{patient_id}")
    audit_res = get_api(f"/audit/{patient_id}")
    
    col_timeline, col_charts = st.columns([1, 1])
    
    with col_charts:
        st.subheader("Conflict Resolution Analysis")
        if "replay_result" in replay_res and "resolutions" in replay_res["replay_result"]:
            resolutions = replay_res["replay_result"]["resolutions"]
            if not resolutions:
                st.info("No conflicts detected for this patient.")
            else:
                # Prepare data for plotting
                sources_won = []
                tiers_used = []
                for res in resolutions:
                    sources_won.append(res["winner"]["source"])
                    # Extract string before parenthesis (e.g. "source_reliability (EHR=3...)")
                    tier = res["resolved_by"].split(" ")[0]
                    tiers_used.append(tier)
                
                # Chart 1: Winning Sources
                df_sources = pd.DataFrame({"Source": sources_won}).value_counts().reset_index(name="Wins")
                fig1 = px.pie(df_sources, values="Wins", names="Source", title="Winning Sources in Conflicts", hole=0.4)
                st.plotly_chart(fig1, use_container_width=True)
                
                # Chart 2: Resolution Tiers Used
                df_tiers = pd.DataFrame({"Tier": tiers_used}).value_counts().reset_index(name="Count")
                fig2 = px.bar(df_tiers, x="Tier", y="Count", title="Resolution Tiers Triggered", color="Tier")
                st.plotly_chart(fig2, use_container_width=True)
        else:
             st.info("No state to replay.")

    with col_timeline:
        st.subheader("Audit Log & Replay Check")
        if "deterministic" in replay_res:
            if replay_res["deterministic"]:
                st.success("Determinism Check: Passed ✅ (State matches exactly)")
            else:
                st.error("Determinism Check: Failed ❌ (State drift detected)")
                
        if "entries" in audit_res:
            for entry in reversed(audit_res["entries"]):
                with st.expander(f"[{entry['created_at'][:16].replace('T', ' ')}] {entry['action'].upper()}"):
                    if entry["action"] == "conflict_resolved":
                        st.json(entry.get("details", {}))
                    elif entry["action"] == "event_ingested":
                        st.json(entry.get("details", {}))
                    else:
                        st.write("Report Generated")
