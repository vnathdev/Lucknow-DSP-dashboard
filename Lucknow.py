import streamlit as st
import pandas as pd
import io
from datetime import datetime
import calendar
import altair as alt
import streamlit.components.v1 as components

# --- MUST BE THE FIRST STREAMLIT COMMAND ---
st.set_page_config(page_title="Lucknow DSP Dashboard", layout="wide", initial_sidebar_state="collapsed")

# ==========================================
# 1. EXCEL COLUMN HEADERS & URLS
# ==========================================
COL_TICKET_ID   = "Issue Number"
COL_SUBCATEGORY = "Subcategory"
COL_STATUS      = "Status Name"
COL_CREATED     = "Created At"
COL_RESOLVED    = "Resolved At"
COL_ZONE        = "Zone Name"
COL_WARD        = "Ward Name"
COL_BEFORE_IMG  = "Before Photo Link"
COL_AFTER_IMG   = "After Photo Link"
COL_SURVEYOR    = "User Name"
COL_ASSIGNED    = "Assigned User Name"

# --- Google Sheet URLs (Converted to CSV export links) ---
SUBCAT_MAPPING_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=2005007155"
SURVEYOR_LIST_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=1801847585"
QC_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Rl_rvPbBrpr86fsg9cpIbPEbm-GyZUBy22xHmMnvK-U/edit?gid=1455880256#gid=1455880256"

# --- Status Buckets for Lucknow ---
STATUS_COLUMNS = ["Open", "Submit for Approval", "Resolved", "Closed / Complied"]
UNRESOLVED_STATUSES = ["Open", "Submit for Approval"]
RESOLVED_STATUSES = ["Resolved", "Closed / Complied"]

# ==========================================
# HELPER FUNCTIONS & DATA LOADING
# ==========================================

def get_google_sheet_url(url):
    try:
        if "docs.google.com/spreadsheets" not in url: return None
        # If it's already a CSV export link, just return it
        if "/export?format=csv" in url: return url
        parts = url.split('/')
        if 'd' in parts:
            d_index = parts.index('d')
            sheet_id = parts[d_index + 1]
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        return None
    except:
        return None

@st.cache_data(ttl=600)
def load_dynamic_mappings():
    """Fetches Google Sheets for Categories and Surveyors."""
    cat_map = {}
    surv_map = {}
    
    # 1. Subcategories
    try:
        cat_df = pd.read_csv(SUBCAT_MAPPING_URL)
        if not cat_df.empty and len(cat_df.columns) >= 2:
            cat_map = dict(zip(cat_df.iloc[:, 0].astype(str).str.strip(), cat_df.iloc[:, 1].astype(str).str.strip()))
    except Exception as e:
        st.error(f"⚠️ Could not load Subcategory Mapping Sheet. Error: {e}")

    # 2. Surveyors
    try:
        surv_df = pd.read_csv(SURVEYOR_LIST_URL)
        if not surv_df.empty and len(surv_df.columns) >= 2:
            surv_map = dict(zip(surv_df.iloc[:, 0].astype(str).str.strip(), surv_df.iloc[:, 1].astype(str).str.strip()))
    except Exception as e:
        st.error(f"⚠️ Could not load Surveyor Mapping Sheet. Error: {e}")
        
    return cat_map, surv_map

def display_with_fixed_footer(df, show_closure=True):
    if df.empty:
        st.warning("⚠️ No data available to display.")
        return
    body = df.iloc[:-1]
    total = df.iloc[[-1]]
    
    config = {}
    if show_closure and '% Closure' in df.columns:
        config['% Closure'] = st.column_config.NumberColumn(format="%.1f%%")
    if 'Avg Closure Time (Days)' in df.columns:
        config['Avg Closure Time (Days)'] = st.column_config.NumberColumn(format="%.1f")
        
    st.dataframe(body, use_container_width=True, column_config=config)
    st.markdown("⬇️ **Grand Total**") 
    st.dataframe(total, use_container_width=True, column_config=config)

@st.cache_data
def process_data(df):
    df.columns = df.columns.str.strip()
    
    missing_cols = [col for col in [COL_SUBCATEGORY, COL_STATUS, COL_CREATED] if col not in df.columns]
    if missing_cols:
        st.error(f"❌ Missing critical columns in data: {', '.join(missing_cols)}")
        st.stop()
        
    # Apply dynamic mappings
    cat_map, surv_map = load_dynamic_mappings()
    
    # Clean and map categories
    df['Subcategory_Clean'] = df[COL_SUBCATEGORY].astype(str).str.strip()
    df['MainCategory'] = df['Subcategory_Clean'].map(cat_map).fillna("Others")
    
    # Map Surveyors (Apply rationalized names, mark others as "IGNORED")
    if COL_SURVEYOR in df.columns:
        df['Raw_Surveyor'] = df[COL_SURVEYOR].astype(str).str.strip()
        df['Rationalised_Surveyor'] = df['Raw_Surveyor'].map(surv_map).fillna("IGNORED")
        
    # Status Buckets
    def get_bucket(status_name):
        s = str(status_name).strip()
        if "Closed / Complied" in s: return "Closed / Complied"
        elif "Submit for Approval" in s: return "Submit for Approval"
        elif "Resolved" in s: return "Resolved"
        elif "Open" in s: return "Open"
        return "Open"
    df['StatusBucket'] = df[COL_STATUS].apply(get_bucket)
    
    # Dates
    df[COL_CREATED] = pd.to_datetime(df[COL_CREATED], dayfirst=True, errors='coerce')
    if COL_RESOLVED in df.columns:
        df[COL_RESOLVED] = pd.to_datetime(df[COL_RESOLVED], dayfirst=True, errors='coerce')
        df['ClosureTimeDays'] = (df[COL_RESOLVED] - df[COL_CREATED]).dt.days
        df['ClosureTimeDays'] = df['ClosureTimeDays'].apply(lambda x: x if pd.notna(x) and x >= 0 else None)
    else:
        df['ClosureTimeDays'] = None
        
    now = datetime.now()
    df['AgeDays'] = (now - df[COL_CREATED]).dt.days
    
    def get_age_bucket(row):
        if row['StatusBucket'] in RESOLVED_STATUSES: return "Closed"
        days = row['AgeDays']
        if pd.isna(days): return "Unknown"
        if days < 30: return "< 1 Month"
        elif 30 <= days <= 180: return "1-6 Months"
        elif 180 < days <= 365: return "6-12 Months"
        else: return "> 1 Year"
    df['AgeBucket'] = df.apply(get_age_bucket, axis=1)
    
    return df

def generate_pivot_summary(df, group_col, label_suffix="Total", show_avg_time=False):
    if df.empty: return pd.DataFrame()
    summary = df.groupby([group_col, 'StatusBucket']).size().unstack(fill_value=0)
    
    for col in STATUS_COLUMNS:
        if col not in summary.columns: summary[col] = 0
            
    summary = summary[STATUS_COLUMNS] 
    summary['Unresolved Total'] = summary[UNRESOLVED_STATUSES].sum(axis=1)
    summary['Resolved Total'] = summary[RESOLVED_STATUSES].sum(axis=1)
    summary['Grand Total'] = summary['Unresolved Total'] + summary['Resolved Total']
    summary['% Closure'] = summary.apply(lambda r: (r['Resolved Total'] / r['Grand Total'] * 100) if r['Grand Total'] > 0 else 0, axis=1).round(1)
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        avg_val = df['ClosureTimeDays'].mean()
        summary['Avg Closure Time (Days)'] = df.groupby(group_col)['ClosureTimeDays'].mean().round(1)

    total_row_data = {col: summary[col].sum() for col in STATUS_COLUMNS + ['Unresolved Total', 'Resolved Total', 'Grand Total']}
    total_row_data['% Closure'] = (total_row_data['Resolved Total'] / total_row_data['Grand Total'] * 100) if total_row_data['Grand Total'] > 0 else 0
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        avg_overall = df['ClosureTimeDays'].mean()
        total_row_data['Avg Closure Time (Days)'] = round(avg_overall, 1) if pd.notna(avg_overall) else None
    
    total_row = pd.DataFrame([total_row_data], index=[f'**{label_suffix}**'])
    
    cols_order = STATUS_COLUMNS + ['Unresolved Total', 'Grand Total', '% Closure']
    if show_avg_time and 'ClosureTimeDays' in df.columns: cols_order.append('Avg Closure Time (Days)')
        
    return pd.concat([summary, total_row])[cols_order]

def generate_aging_summary(df, group_col):
    if 'AgeBucket' not in df.columns or df.empty: return pd.DataFrame()
    summary = df.groupby([group_col, 'AgeBucket']).size().unstack(fill_value=0)
    cols = ['< 1 Month', '1-6 Months', '6-12 Months', '> 1 Year']
    for c in cols:
        if c not in summary.columns: summary[c] = 0
    summary = summary[cols]
    summary['Total Unresolved'] = summary.sum(axis=1)
    return summary.sort_values('Total Unresolved', ascending=False)

# ==========================================
# MAIN APP
# ==========================================

def main():
    st.title("📊 Lucknow DSP Dashboard")
    
    # --- PDF EXPORT ---
    c_title, c_btn = st.columns([5, 1])
    with c_title:
        st.markdown("Select a view from the sidebar (👈) to explore the data.")
    with c_btn:
        if st.button("🖨️ Export PDF", use_container_width=True, type="primary"):
            components.html("<script>window.parent.print();</script>", height=0)
            
    st.markdown("---")
    
    st.sidebar.header("📂 Data Source")
    uploaded_file = st.sidebar.file_uploader("Upload Data (XLSX)", type=['xlsx', 'xls', 'csv'])

    st.sidebar.markdown("---")
    st.sidebar.header("🧭 Navigation")
    
    if 'current_view' not in st.session_state:
        st.session_state.current_view = "Main Category Summary"
    
    views = [
        "Main Category Summary",
        "Subcategory Drill-Down",
        "Zone-wise Drill-Down",
        "Officer Leaderboard", 
        "Age-wise Pendency",
        "Monthly Trend Analysis",
        "Custom Date Range Analysis",
        "Quarterly Performance (FY)",
        "Surveyor Performance",
        "Quality Check Status"
    ]
    
    for view in views:
        btn_type = "primary" if st.session_state.current_view == view else "secondary"
        if st.sidebar.button(view, use_container_width=True, type=btn_type):
            st.session_state.current_view = view
            st.rerun()

    # ==========================================
    # VIEWS THAT DO NOT REQUIRE DATA DUMP
    # ==========================================
    if st.session_state.current_view == "Quality Check Status":
        st.subheader("✅ Quality Check Status")
        st.caption("Overview of L1 and L2 quality checks for Raised and Resolved tickets directly from the QC Sheet.")
        
        qc_url = get_google_sheet_url(QC_SHEET_URL)
        
        if not qc_url or "PASTE_YOUR" in qc_url:
            st.warning("⚠️ Please paste a valid Quality Check Google Sheet URL into the `QC_SHEET_URL` variable at the top of the code.")
        else:
            try:
                # Load the QC data
                qc_df = pd.read_csv(qc_url)
                
                # Ensure the sheet has up to Column W (Index 22)
                if len(qc_df.columns) >= 23:
                    # Map columns directly by Excel index (A=0 ... R=17, S=18, T=19, U=20, V=21, W=22)
                    r_l1_col = qc_df.columns[17]  # Column R
                    r_l2_col = qc_df.columns[18]  # Column S
                    res_l1_col = qc_df.columns[19] # Column T
                    res_l2_col = qc_df.columns[20] # Column U
                    res_l1_rsn = qc_df.columns[21] # Column V
                    res_l2_rsn = qc_df.columns[22] # Column W
                    
                    # --- PRE-COMPUTE ALL COUNTS ---
                    r_l1_counts = qc_df[r_l1_col].value_counts().reset_index()
                    r_l1_counts.columns = ['Status', 'Count']
                    r_l1_counts['Level'] = 'L1 (Col R)'
                    
                    r_l2_counts = qc_df[r_l2_col].value_counts().reset_index()
                    r_l2_counts.columns = ['Status', 'Count']
                    r_l2_counts['Level'] = 'L2 (Col S)'
                    
                    # Filter out "Not Evaluated" (case-insensitive) for Resolved tickets
                    res_l1_clean = qc_df[~qc_df[res_l1_col].astype(str).str.lower().str.contains('not evaluated', na=False)]
                    res_l1_counts = res_l1_clean[res_l1_col].value_counts().reset_index()
                    res_l1_counts.columns = ['Status', 'Count']
                    res_l1_counts['Level'] = 'L1 (Col T)'
                    
                    res_l2_clean = qc_df[~qc_df[res_l2_col].astype(str).str.lower().str.contains('not evaluated', na=False)]
                    res_l2_counts = res_l2_clean[res_l2_col].value_counts().reset_index()
                    res_l2_counts.columns = ['Status', 'Count']
                    res_l2_counts['Level'] = 'L2 (Col U)'

                    # --- 1. INDIVIDUAL DISTRIBUTION PIE CHARTS ---
                    st.markdown("### 📊 Overall L1 vs L2 Distribution")
                    
                    chart_configs = [
                        ("Raised Tickets (L1)", r_l1_counts),
                        ("Raised Tickets (L2)", r_l2_counts),
                        ("Resolved Tickets (L1)", res_l1_counts),
                        ("Resolved Tickets (L2)", res_l2_counts)
                    ]
                    
                    pie_cols = st.columns(4)
                    
                    for idx, (title, df_c) in enumerate(chart_configs):
                        with pie_cols[idx]:
                            st.markdown(f"<p style='text-align: center; font-weight: bold;'>{title}</p>", unsafe_allow_html=True)
                            if not df_c.empty and df_c['Count'].sum() > 0:
                                total_val = df_c['Count'].sum()
                                plot_df = df_c.copy()
                                plot_df['%'] = (plot_df['Count'] / total_val * 100).round(1)
                                
                                pie = alt.Chart(plot_df).mark_arc(innerRadius=40).encode(
                                    theta=alt.Theta(field="Count", type="quantitative"),
                                    color=alt.Color(
                                        field="Status", 
                                        type="nominal", 
                                        legend=alt.Legend(
                                            orient="bottom", 
                                            title=None,
                                            labelFontSize=10, 
                                            symbolSize=60,
                                            labelLimit=0
                                        )
                                    ),
                                    tooltip=['Status', 'Count', '%']
                                ).properties(height=320)
                                
                                st.altair_chart(pie, use_container_width=True)
                                st.markdown(f"<p style='text-align: center; font-weight: bold; margin-top: -15px;'>Total: {total_val}</p>", unsafe_allow_html=True)
                            else:
                                st.info("No data available.")
                        
                    st.markdown("---")
                    
                    # --- 2. RAISED TICKETS QC ---
                    st.markdown("### 🚨 Raised Tickets Quality Check")
                    raised_chart_df = pd.concat([r_l1_counts, r_l2_counts]).dropna()
                    
                    # Full-width bar chart
                    if not raised_chart_df.empty:
                        raised_chart = alt.Chart(raised_chart_df).mark_bar().encode(
                            x=alt.X('Status:N', title='Quality Status', axis=alt.Axis(labelAngle=0)),
                            y=alt.Y('Count:Q', title='Tickets'),
                            color=alt.Color('Level:N', legend=alt.Legend(title="Check Level", labelFontSize=11)),
                            xOffset='Level:N'
                        ).properties(height=400)
                        st.altair_chart(raised_chart, use_container_width=True)
                    else:
                        st.info("No data found for Raised Quality Checks.")
                        
                    # Tables beneath chart
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**L1 Raised Checks**")
                        st.dataframe(r_l1_counts[['Status', 'Count']], use_container_width=True, hide_index=True)
                    with c2:
                        st.markdown("**L2 Raised Checks**")
                        st.dataframe(r_l2_counts[['Status', 'Count']], use_container_width=True, hide_index=True)
                        
                    st.markdown("---")
                    
                    # --- 3. RESOLVED TICKETS QC ---
                    st.markdown("### 🏁 Resolved Tickets Quality Check")
                    res_chart_df = pd.concat([res_l1_counts, res_l2_counts]).dropna()
                    
                    # Full-width bar chart
                    if not res_chart_df.empty:
                        res_chart = alt.Chart(res_chart_df).mark_bar().encode(
                            x=alt.X('Status:N', title='Quality Status', axis=alt.Axis(labelAngle=0)),
                            y=alt.Y('Count:Q', title='Tickets'),
                            color=alt.Color('Level:N', legend=alt.Legend(title="Check Level", labelFontSize=11)),
                            xOffset='Level:N'
                        ).properties(height=400)
                        st.altair_chart(res_chart, use_container_width=True)
                    else:
                        st.info("No data found for Resolved Quality Checks.")
                        
                    # Tables beneath chart
                    c3, c4 = st.columns(2)
                    with c3:
                        st.markdown("**L1 Resolved Checks**")
                        st.dataframe(res_l1_counts[['Status', 'Count']], use_container_width=True, hide_index=True)
                    with c4:
                        st.markdown("**L2 Resolved Checks**")
                        st.dataframe(res_l2_counts[['Status', 'Count']], use_container_width=True, hide_index=True)
                        
                    st.markdown("##### 📝 Reasons for Resolved Quality Checks")
                    c5, c6 = st.columns(2)
                    with c5:
                        l1_reasons = qc_df[res_l1_rsn].value_counts().reset_index()
                        l1_reasons.columns = ['L1 Reason (Col V)', 'Count']
                        st.dataframe(l1_reasons, use_container_width=True, hide_index=True)
                    with c6:
                        l2_reasons = qc_df[res_l2_rsn].value_counts().reset_index()
                        l2_reasons.columns = ['L2 Reason (Col W)', 'Count']
                        st.dataframe(l2_reasons, use_container_width=True, hide_index=True)

                else:
                    st.error("⚠️ The linked Google Sheet does not have enough columns. The tool requires data extending at least up to Column W (23 columns).")
                    
            except Exception as e:
                st.error(f"❌ Could not load or parse the Quality Check sheet: {e}")

    # ==========================================
    # VIEWS THAT REQUIRE THE EXCEL DATA DUMP
    # ==========================================
    else:
        if uploaded_file is not None:
            try:
                file_name = uploaded_file.name.lower()
                if file_name.endswith('.csv'):
                    df_raw = pd.read_csv(uploaded_file, encoding='utf-8')
                else:
                    df_raw = pd.read_excel(uploaded_file)
                    
                df_processed = process_data(df_raw)
                
                main_categories = sorted(df_processed[df_processed['MainCategory'] != 'Others']['MainCategory'].unique().tolist())
                if 'Others' in df_processed['MainCategory'].unique():
                    main_categories.append('Others')
                
                valid_created_years = df_processed[COL_CREATED].dt.year.dropna().unique().tolist()
                valid_resolved_years = []
                if COL_RESOLVED in df_processed.columns:
                    valid_resolved_years = df_processed[COL_RESOLVED].dt.year.dropna().unique().tolist()
                all_years = sorted(list(set(valid_created_years + valid_resolved_years)), reverse=True)

                # ==========================================
                # VIEWS
                # ==========================================
                
                if st.session_state.current_view == "Main Category Summary":
                    st.subheader("📈 Main Category Summary")
                    summary_table = generate_pivot_summary(df_processed, 'MainCategory', "TOTAL")
                    
                    if not summary_table.empty:
                        body_df = summary_table.iloc[:-1]
                        total_series = summary_table.iloc[-1]
                        
                        st.markdown("##### 🎯 Individual Status Breakdown")
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("🔴 Open", int(total_series['Open']))
                        c2.metric("🟠 Submit for Approval", int(total_series['Submit for Approval']))
                        c3.metric("🟡 Resolved", int(total_series['Resolved']))
                        c4.metric("🟢 Closed / Complied", int(total_series['Closed / Complied']))
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("##### 🚜 Citywide Aggregates")
                        m1, m2, m3 = st.columns(3)
                        m1.metric("🚧 Total Unresolved", int(total_series['Unresolved Total']))
                        m2.metric("📋 Grand Total", int(total_series['Grand Total']))
                        m3.metric("✅ % Closure", f"{int(round(total_series['% Closure']))}%")
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("##### 📂 Category-wise Breakdown")
                        st.dataframe(body_df, use_container_width=True, column_config={"% Closure": st.column_config.NumberColumn(format="%.1f%%")})
                    
                    st.markdown("---")
                    st.subheader("📊 Citywide & Zone-wise Snapshot")
                    c1, c2 = st.columns([2, 1])
                    
                    with c1:
                        st.markdown("**Tickets Raised vs. Closed by Zone**")
                        if COL_ZONE in df_processed.columns:
                            zone_raised = df_processed.groupby(COL_ZONE).size().rename("Total Raised")
                            zone_closed = df_processed[df_processed['StatusBucket'].isin(RESOLVED_STATUSES)].groupby(COL_ZONE).size().rename("Total Closed")
                            zone_bar_df = pd.concat([zone_raised, zone_closed], axis=1).fillna(0).astype(int)
                            st.bar_chart(zone_bar_df, use_container_width=True)
                        else:
                            st.info(f"⚠️ '{COL_ZONE}' column not found in data.")
                            
                    with c2:
                        st.markdown("**Citywide Status Breakdown**")
                        status_counts = df_processed['StatusBucket'].value_counts().reset_index()
                        status_counts.columns = ['Status', 'Count']
                        pie_chart = alt.Chart(status_counts).mark_arc(innerRadius=40).encode(
                            theta=alt.Theta(field="Count", type="quantitative"),
                            color=alt.Color(field="Status", type="nominal", 
                                            scale=alt.Scale(
                                                domain=STATUS_COLUMNS,
                                                range=['#EF4444', '#F59E0B', '#10B981', '#3B82F6'] 
                                            )),
                            tooltip=['Status', 'Count']
                        ).properties(height=350)
                        st.altair_chart(pie_chart, use_container_width=True)

                elif st.session_state.current_view == "Subcategory Drill-Down":
                    st.subheader("🔍 Subcategory Drill-Down")
                    tabs = st.tabs(main_categories)
                    for tab, main_cat in zip(tabs, main_categories):
                        with tab:
                            sub_df = df_processed[df_processed['MainCategory'] == main_cat]
                            if not sub_df.empty:
                                display_with_fixed_footer(generate_pivot_summary(sub_df, 'Subcategory_Clean', f"{main_cat} Total"))

                    # ==========================================
                    # TICKET INSPECTOR (DEEP DIVE)
                    # ==========================================
                    st.markdown("---")
                    st.subheader("🔎 Ticket Inspector (Deep Dive)")
                    st.caption("Use the filters below to pull up specific raw tickets based on the summary numbers above.")
                    
                    with st.expander("Click to Open Ticket Inspector", expanded=False):
                        f1, f2, f3, f4 = st.columns(4)
                        
                        with f1:
                            filter_cat = st.selectbox("1. Select Main Category", ["All"] + main_categories)
                        
                        with f2:
                            if filter_cat == "All":
                                avail_subs = ["All"] + sorted(df_processed['Subcategory_Clean'].dropna().unique().tolist())
                            else:
                                avail_subs = ["All"] + sorted(df_processed[df_processed['MainCategory'] == filter_cat]['Subcategory_Clean'].dropna().unique().tolist())
                            filter_sub = st.selectbox("2. Select Subcategory", avail_subs)
                            
                        with f3:
                            filter_status = st.selectbox("3. Select Status", ["All"] + STATUS_COLUMNS)

                        with f4:
                            if 'Assigned User Designation' in df_processed.columns:
                                avail_desig = ["All"] + sorted(df_processed['Assigned User Designation'].dropna().astype(str).unique().tolist())
                            else:
                                avail_desig = ["All"]
                            filter_desig = st.selectbox("4. Select Designation", avail_desig)
                            
                        st.markdown("<br>", unsafe_allow_html=True)
                        
                        d1, d2 = st.columns([1, 2])
                        with d1:
                            use_date = st.checkbox("📅 Filter by Date Range")
                        with d2:
                            if use_date:
                                min_date = df_processed[COL_CREATED].min().date()
                                max_date = df_processed[COL_CREATED].max().date()
                                filter_dates = st.date_input("5. Select Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
                            
                        deep_dive_df = df_processed.copy()
                        if filter_cat != "All":
                            deep_dive_df = deep_dive_df[deep_dive_df['MainCategory'] == filter_cat]
                        if filter_sub != "All":
                            deep_dive_df = deep_dive_df[deep_dive_df['Subcategory_Clean'] == filter_sub]
                        if filter_status != "All":
                            deep_dive_df = deep_dive_df[deep_dive_df['StatusBucket'] == filter_status]
                        if filter_desig != "All" and 'Assigned User Designation' in deep_dive_df.columns:
                            deep_dive_df = deep_dive_df[deep_dive_df['Assigned User Designation'] == filter_desig]
                            
                        if use_date and len(filter_dates) == 2:
                            start_d, end_d = filter_dates
                            deep_dive_df = deep_dive_df[(deep_dive_df[COL_CREATED].dt.date >= start_d) & (deep_dive_df[COL_CREATED].dt.date <= end_d)]
                            
                        st.markdown(f"**Found {len(deep_dive_df)} matching tickets:**")
                        
                        # Output columns structurally ordered
                        raw_cols = [COL_TICKET_ID, 'Subcategory_Clean', COL_ASSIGNED, 'Assigned User Designation', COL_ZONE, COL_WARD, COL_CREATED, 'AgeDays', COL_BEFORE_IMG, COL_AFTER_IMG]
                        display_cols = [c for c in raw_cols if c in deep_dive_df.columns]
                        
                        out_df = deep_dive_df[display_cols].copy()
                        
                        rename_mapping = {
                            COL_TICKET_ID: "Ticket Number",
                            'Subcategory_Clean': "Subcategory",
                            COL_ASSIGNED: "Officer Name",
                            'Assigned User Designation': "Designation",
                            COL_ZONE: "Zone",
                            COL_WARD: "Ward",
                            COL_CREATED: "Raised Date",
                            'AgeDays': "Age (Days)",
                            COL_BEFORE_IMG: "Before Image Link",
                            COL_AFTER_IMG: "After Image Link"
                        }
                        out_df = out_df.rename(columns=rename_mapping)
                        
                        st.dataframe(
                            out_df, 
                            use_container_width=True,
                            column_config={
                                "Before Image Link": st.column_config.ImageColumn("Before Image Preview"),
                                "After Image Link": st.column_config.ImageColumn("After Image Preview")
                            }
                        )

                # ==========================================
                # OFFICER LEADERBOARD (DATA DUMP BASED)
                # ==========================================
                elif st.session_state.current_view == "Officer Leaderboard":
                    st.subheader("🏆 Officer Leaderboard")
                    st.caption("Tracking performance directly mapped to the Assigned Officers in the data dump.")
                    
                    # --- 1. Dynamic Filters ---
                    f1, f2, f3 = st.columns(3)
                    
                    with f1: 
                        f_cat = st.selectbox("Category", ["All"] + main_categories)
                        
                    with f2: 
                        avail_zones = ["All"] + sorted(df_processed['Zone Name'].dropna().unique().tolist()) if 'Zone Name' in df_processed.columns else ["All"]
                        f_zone = st.selectbox("Zone", avail_zones)
                        
                    with f3: 
                        if f_cat == "All":
                            avail_subs = ["All"] + sorted(df_processed['Subcategory_Clean'].dropna().unique().tolist())
                        else:
                            avail_subs = ["All"] + sorted(df_processed[df_processed['MainCategory'] == f_cat]['Subcategory_Clean'].dropna().unique().tolist())
                        f_sub = st.selectbox("Subcategory", avail_subs)
                        
                    f4, f5 = st.columns(2)
                    
                    with f4:
                        if 'Assigned User Designation' in df_processed.columns:
                            avail_desig = sorted(df_processed['Assigned User Designation'].dropna().astype(str).unique().tolist())
                        else:
                            avail_desig = []
                        f_desig = st.multiselect("Designation", avail_desig, default=avail_desig)
                        
                    with f5:
                        avail_status = sorted(df_processed['StatusBucket'].dropna().unique().tolist())
                        f_status = st.multiselect("Status", avail_status, default=avail_status)
                    
                    # --- 2. Apply Filters ---
                    filt_df = df_processed.copy()
                    if f_cat != "All": 
                        filt_df = filt_df[filt_df['MainCategory'] == f_cat]
                    if f_zone != "All" and 'Zone Name' in filt_df.columns: 
                        filt_df = filt_df[filt_df['Zone Name'] == f_zone]
                    if f_sub != "All": 
                        filt_df = filt_df[filt_df['Subcategory_Clean'] == f_sub]
                    if f_desig and 'Assigned User Designation' in filt_df.columns:
                        filt_df = filt_df[filt_df['Assigned User Designation'].astype(str).isin(f_desig)]
                    if f_status:
                        filt_df = filt_df[filt_df['StatusBucket'].isin(f_status)]
                    
                    # --- 3. Generate Leaderboard ---
                    if not filt_df.empty and (not avail_desig or f_desig) and f_status:
                        group_cols = [COL_ASSIGNED]
                        
                        if 'Assigned User Designation' in filt_df.columns:
                            filt_df['Assigned User Designation'] = filt_df['Assigned User Designation'].fillna('Unknown')
                            group_cols.append('Assigned User Designation')
                            
                        # Group by Name (and Designation if it exists)
                        officer_summary = filt_df.groupby(group_cols + ['StatusBucket']).size().unstack(fill_value=0)
                        
                        # Guarantee all baseline columns exist even if no tickets match the current selection
                        for col in ['Open', 'Submit for Approval', 'Resolved', 'Closed / Complied']:
                            if col not in officer_summary.columns:
                                officer_summary[col] = 0
                                
                        # Calculate customized Pending and Closed buckets based on selected data
                        officer_summary['Pending'] = officer_summary['Open'] + officer_summary['Submit for Approval']
                        officer_summary['Closed'] = officer_summary['Resolved'] + officer_summary['Closed / Complied']
                        officer_summary['Total'] = officer_summary['Pending'] + officer_summary['Closed']
                        
                        # Clean up the final display table
                        officer_summary = officer_summary.reset_index()
                        
                        rename_dict = {COL_ASSIGNED: 'Officer Name'}
                        display_cols = ['Officer Name']
                        
                        if 'Assigned User Designation' in officer_summary.columns:
                            rename_dict['Assigned User Designation'] = 'Designation'
                            display_cols.append('Designation')
                            
                        display_cols.extend(['Pending', 'Closed', 'Total'])
                        
                        officer_summary = officer_summary.rename(columns=rename_dict)
                        officer_summary = officer_summary[display_cols].sort_values(by='Total', ascending=False).reset_index(drop=True)
                        
                        # 1-based indexing for ranking
                        officer_summary.index = officer_summary.index + 1
                        
                        st.dataframe(officer_summary, use_container_width=True)
                    else:
                        st.info("No tickets found matching the selected filters.")

                elif st.session_state.current_view == "Zone-wise Drill-Down":
                    st.subheader("🗺️ Zone-wise Drill-Down")
                    if COL_ZONE not in df_processed.columns:
                        st.error(f"Column '{COL_ZONE}' required for this view is missing.")
                    else:
                        st.markdown("##### 📍 Zone Comparison by Status & Closure Time")
                        b3_cat_all = st.selectbox("Select Main Category (For Zone Comparison)", main_categories, key="b3_cat_all")
                        zone_matrix_df = df_processed[df_processed['MainCategory'] == b3_cat_all]
                        if not zone_matrix_df.empty:
                            display_with_fixed_footer(generate_pivot_summary(zone_matrix_df, COL_ZONE, "ALL ZONES TOTAL", show_avg_time=True))
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("##### 📋 Subcategory Detail by Zone")
                        c1, c2 = st.columns(2)
                        with c1: b3_cat_spec = st.selectbox("Select Main Category", main_categories, key="b3_cat_spec")
                        with c2: b3_zone_spec = st.selectbox("Select Zone", sorted(df_processed[COL_ZONE].dropna().unique()), key="b3_zone_spec")
                        
                        zone_spec_df = df_processed[(df_processed['MainCategory'] == b3_cat_spec) & (df_processed[COL_ZONE] == b3_zone_spec)]
                        if not zone_spec_df.empty:
                            display_with_fixed_footer(generate_pivot_summary(zone_spec_df, 'Subcategory_Clean', f"{b3_cat_spec} - {b3_zone_spec} Total", show_avg_time=True))
                        else:
                            st.warning("No data found.")

                elif st.session_state.current_view == "Age-wise Pendency":
                    st.subheader("⏳ Age-wise Pendency Analysis")
                    
                    # --- 1. Summary Table ---
                    b5_cat = st.selectbox("Select Category", ["All Categories"] + main_categories)
                    
                    if b5_cat != "All Categories":
                        age_df = df_processed[(df_processed['MainCategory'] == b5_cat) & (df_processed['StatusBucket'].isin(UNRESOLVED_STATUSES))]
                        grouping_col = 'Subcategory_Clean'
                    else:
                        age_df = df_processed[df_processed['StatusBucket'].isin(UNRESOLVED_STATUSES)]
                        grouping_col = 'MainCategory'
                        
                    if not age_df.empty:
                        st.markdown("##### 📊 Age-wise Summary")
                        st.dataframe(generate_aging_summary(age_df, grouping_col), use_container_width=True)
                    else:
                        st.success("No unresolved tickets found for this category.")
                        
                    st.markdown("---")
                    st.subheader("🔎 Pendency Ticket Inspector")
                    
                    # --- 2. Ticket Inspector ---
                    with st.expander("Click to Open Pendency Inspector", expanded=False):
                        f1, f2, f3, f4 = st.columns(4)
                        
                        with f1:
                            filter_cat_age = st.selectbox("1. Category", ["All"] + main_categories, key="insp_cat_age")
                            
                        with f2:
                            if filter_cat_age == "All":
                                available_subs_age = ["All"] + sorted(df_processed['Subcategory_Clean'].dropna().unique().tolist())
                            else:
                                available_subs_age = ["All"] + sorted(df_processed[df_processed['MainCategory'] == filter_cat_age]['Subcategory_Clean'].dropna().unique().tolist())
                            filter_sub_age = st.selectbox("2. Subcategory", available_subs_age, key="insp_sub_age")
                            
                        with f3:
                            age_buckets = ['< 1 Month', '1-6 Months', '6-12 Months', '> 1 Year']
                            filter_age_bucket = st.selectbox("3. Age Bucket", ["All"] + age_buckets)

                        with f4:
                            if 'Assigned User Designation' in df_processed.columns:
                                avail_desig_age = ["All"] + sorted(df_processed['Assigned User Designation'].dropna().astype(str).unique().tolist())
                            else:
                                avail_desig_age = ["All"]
                            filter_desig_age = st.selectbox("4. Designation", avail_desig_age, key="insp_desig_age")
                            
                        insp_age_df = df_processed[df_processed['StatusBucket'].isin(UNRESOLVED_STATUSES)].copy()
                        
                        if filter_cat_age != "All":
                            insp_age_df = insp_age_df[insp_age_df['MainCategory'] == filter_cat_age]
                        if filter_sub_age != "All":
                            insp_age_df = insp_age_df[insp_age_df['Subcategory_Clean'] == filter_sub_age]
                        if filter_age_bucket != "All":
                            insp_age_df = insp_age_df[insp_age_df['AgeBucket'] == filter_age_bucket]
                        if filter_desig_age != "All" and 'Assigned User Designation' in insp_age_df.columns:
                            insp_age_df = insp_age_df[insp_age_df['Assigned User Designation'] == filter_desig_age]
                            
                        st.markdown(f"**Found {len(insp_age_df)} pending tickets:**")
                        
                        raw_cols_age = [COL_TICKET_ID, 'Subcategory_Clean', COL_ASSIGNED, 'Assigned User Designation', COL_CREATED, COL_ZONE, COL_WARD, COL_BEFORE_IMG]
                        display_cols_age = [c for c in raw_cols_age if c in insp_age_df.columns]
                        
                        out_age_df = insp_age_df[display_cols_age].copy()
                        
                        rename_mapping_age = {
                            COL_TICKET_ID: "Ticket Number",
                            'Subcategory_Clean': "Subcategory",
                            COL_ASSIGNED: "Officer Name",
                            'Assigned User Designation': "Designation",
                            COL_CREATED: "Raised Date",
                            COL_ZONE: "Zone",
                            COL_WARD: "Ward",
                            COL_BEFORE_IMG: "Before Image"
                        }
                        out_age_df = out_age_df.rename(columns=rename_mapping_age)
                        
                        st.dataframe(
                            out_age_df, 
                            use_container_width=True,
                            column_config={
                                "Before Image": st.column_config.ImageColumn("Before Image"),
                                "Raised Date": st.column_config.DatetimeColumn("Raised Date", format="DD MMM YYYY, HH:mm")
                            }
                        )

                elif st.session_state.current_view == "Monthly Trend Analysis":
                    st.subheader("📅 Monthly Trend Analysis")
                    st.caption("Compare ticket volumes and track average closure times across the year.")
                    
                    if all_years:
                        selected_year = st.selectbox("Select Year", all_years, key="trend_year")
                        st.markdown(f"**1. Monthly Ticket Volume ({selected_year})**")
                        
                        raised_mask = df_processed[COL_CREATED].dt.year == selected_year
                        raised_counts = df_processed[raised_mask][COL_CREATED].dt.month.value_counts().rename("Tickets Raised")
                        
                        closed_counts = pd.Series(dtype=int, name="Tickets Closed")
                        if COL_RESOLVED in df_processed.columns:
                            closed_mask = (df_processed[COL_RESOLVED].dt.year == selected_year) & (df_processed['StatusBucket'].isin(RESOLVED_STATUSES))
                            closed_counts = df_processed[closed_mask][COL_RESOLVED].dt.month.value_counts().rename("Tickets Closed")
                        
                        trend_df = pd.concat([raised_counts, closed_counts], axis=1).fillna(0).astype(int)
                        if not trend_df.empty:
                            trend_df = trend_df.sort_index()
                            table_df = trend_df.copy()
                            table_df.index = table_df.index.map(lambda x: calendar.month_abbr[int(x)] if pd.notna(x) else 'Unknown')
                            table_df.index.name = "Month"
                            
                            total_row = pd.DataFrame([{'Tickets Raised': table_df['Tickets Raised'].sum(), 'Tickets Closed': table_df['Tickets Closed'].sum()}], index=['**TOTAL**'])
                            st.dataframe(pd.concat([table_df, total_row]), use_container_width=True)
                            
                            chart_df = trend_df.copy()
                            chart_df.index = [f"{selected_year}-{str(int(m)).zfill(2)}" for m in chart_df.index]
                            st.bar_chart(chart_df, use_container_width=True)
                            
                            st.markdown("---")
                            st.markdown(f"**2. Average Closure Days by Subcategory ({selected_year})**")
                            
                            if COL_RESOLVED in df_processed.columns:
                                closed_year_df = df_processed[(df_processed[COL_RESOLVED].dt.year == selected_year) & (df_processed['StatusBucket'].isin(RESOLVED_STATUSES))].copy()
                                
                                if not closed_year_df.empty and 'ClosureTimeDays' in closed_year_df.columns:
                                    closed_year_df['ResolvedMonth'] = closed_year_df[COL_RESOLVED].dt.month
                                    
                                    st.markdown("##### 🏢 Main Category Averages")
                                    main_avg_pivot = closed_year_df.groupby(['MainCategory', 'ResolvedMonth'])['ClosureTimeDays'].mean().unstack(fill_value=None).round(1)
                                    for m in range(1, 13):
                                        if m not in main_avg_pivot.columns: main_avg_pivot[m] = None
                                            
                                    main_avg_pivot = main_avg_pivot[range(1, 13)]
                                    main_avg_pivot.columns = [calendar.month_abbr[m] for m in range(1, 13)]
                                    main_avg_pivot['Yearly Avg'] = closed_year_df.groupby('MainCategory')['ClosureTimeDays'].mean().round(1)
                                    
                                    monthly_avgs = closed_year_df.groupby('ResolvedMonth')['ClosureTimeDays'].mean().round(1)
                                    total_row_data = {calendar.month_abbr[m]: monthly_avgs.get(m, None) for m in range(1, 13)}
                                    total_row_data['Yearly Avg'] = closed_year_df['ClosureTimeDays'].mean().round(1)
                                    
                                    st.dataframe(pd.concat([main_avg_pivot, pd.DataFrame([total_row_data], index=['**OVERALL AVG**'])]), use_container_width=True)
                                    
                                    st.markdown("##### 🔍 Subcategory Drill-Down")
                                    for main_cat in sorted(closed_year_df['MainCategory'].unique()):
                                        with st.expander(f"📂 {main_cat} Subcategories"):
                                            sub_df = closed_year_df[closed_year_df['MainCategory'] == main_cat]
                                            sub_pivot = sub_df.groupby(['Subcategory_Clean', 'ResolvedMonth'])['ClosureTimeDays'].mean().unstack(fill_value=None).round(1)
                                            for m in range(1, 13):
                                                if m not in sub_pivot.columns: sub_pivot[m] = None
                                            sub_pivot = sub_pivot[range(1, 13)]
                                            sub_pivot.columns = [calendar.month_abbr[m] for m in range(1, 13)]
                                            sub_pivot['Yearly Avg'] = sub_df.groupby('Subcategory_Clean')['ClosureTimeDays'].mean().round(1)
                                            st.dataframe(sub_pivot, use_container_width=True)
                                    
                                    st.markdown("---")
                                    st.markdown("**3. Category-wise Average Closure Trend**")
                                    line_df = closed_year_df.groupby(['ResolvedMonth', 'MainCategory'])['ClosureTimeDays'].mean().unstack()
                                    line_df.index = [f"{selected_year}-{str(int(m)).zfill(2)}" for m in line_df.index]
                                    st.line_chart(line_df, use_container_width=True)
                                else:
                                    st.info("No closure time data available.")
                    else:
                        st.warning("⚠️ No valid dates found in the data.")

                elif st.session_state.current_view == "Custom Date Range Analysis":
                    st.subheader("📆 Custom Date Range Analysis")
                    c1, c2 = st.columns(2)
                    with c1:
                        min_date = df_processed[COL_CREATED].min().date()
                        max_date = df_processed[COL_CREATED].max().date()
                        custom_dates = st.date_input("1️⃣ Select Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
                    with c2:
                        custom_cat = st.selectbox("2️⃣ Select Category", ["All Categories"] + main_categories)
                        
                    if len(custom_dates) == 2:
                        start_date, end_date = custom_dates
                        raised_mask = (df_processed[COL_CREATED].dt.date >= start_date) & (df_processed[COL_CREATED].dt.date <= end_date)
                        raised_df = df_processed[raised_mask]
                        
                        if COL_RESOLVED in df_processed.columns:
                            closed_mask = (df_processed[COL_RESOLVED].dt.date >= start_date) & (df_processed[COL_RESOLVED].dt.date <= end_date) & (df_processed['StatusBucket'].isin(RESOLVED_STATUSES))
                            closed_df = df_processed[closed_mask]
                            closed_out_of_raised_df = raised_df[(raised_df['StatusBucket'].isin(RESOLVED_STATUSES)) & (raised_df[COL_RESOLVED].dt.date >= start_date) & (raised_df[COL_RESOLVED].dt.date <= end_date)]
                        else:
                            closed_df = closed_out_of_raised_df = pd.DataFrame(columns=df_processed.columns)
                            
                        if custom_cat != "All Categories":
                            raised_df = raised_df[raised_df['MainCategory'] == custom_cat]
                            closed_df = closed_df[closed_df['MainCategory'] == custom_cat]
                            closed_out_of_raised_df = closed_out_of_raised_df[closed_out_of_raised_df['MainCategory'] == custom_cat]
                            group_col = 'Subcategory_Clean'
                        else:
                            group_col = 'MainCategory'
                            
                        raised_grouped = raised_df.groupby(group_col).size().rename("Total Raised")
                        closed_grouped = closed_df.groupby(group_col).size().rename("Total Closed")
                        closed_out_grouped = closed_out_of_raised_df.groupby(group_col).size().rename("Closed (Out of Raised)")
                        
                        custom_summary = pd.concat([raised_grouped, closed_grouped, closed_out_grouped], axis=1).fillna(0).astype(int)
                        if not custom_summary.empty:
                            custom_summary["% of New Tickets Resolved"] = ((custom_summary["Closed (Out of Raised)"] / custom_summary["Total Raised"]) * 100).fillna(0).round(1)
                            total_raised = custom_summary["Total Raised"].sum()
                            total_row = pd.DataFrame([{
                                "Total Raised": total_raised, "Total Closed": custom_summary["Total Closed"].sum(),
                                "Closed (Out of Raised)": custom_summary["Closed (Out of Raised)"].sum(), 
                                "% of New Tickets Resolved": (custom_summary["Closed (Out of Raised)"].sum() / total_raised * 100) if total_raised > 0 else 0
                            }], index=["**TOTAL**"])
                            
                            st.dataframe(pd.concat([custom_summary, total_row]), use_container_width=True, column_config={"% of New Tickets Resolved": st.column_config.NumberColumn(format="%.1f%%")})
                            st.bar_chart(custom_summary[["Total Raised", "Total Closed", "Closed (Out of Raised)"]], use_container_width=True)
                        else:
                            st.info("No data found for this specific combination.")

                elif st.session_state.current_view == "Quarterly Performance (FY)":
                    st.subheader("📊 Quarterly Performance (FY)")
                    def get_fy(date_val):
                        if pd.isna(date_val): return None
                        if date_val.month <= 3: return f"{date_val.year - 1}-{str(date_val.year)[-2:]}"
                        else: return f"{date_val.year}-{str(date_val.year + 1)[-2:]}"
                    
                    def get_fy_q(date_val):
                        if pd.isna(date_val): return None
                        if date_val.month in [4, 5, 6]: return "Q1 (Apr-Jun)"
                        elif date_val.month in [7, 8, 9]: return "Q2 (Jul-Sep)"
                        elif date_val.month in [10, 11, 12]: return "Q3 (Oct-Dec)"
                        else: return "Q4 (Jan-Mar)"

                    fy_df = df_processed.copy()
                    fy_df['FY'] = fy_df[COL_CREATED].apply(get_fy)
                    fy_df['FY_Quarter'] = fy_df[COL_CREATED].apply(get_fy_q)

                    if COL_RESOLVED in fy_df.columns:
                        fy_df['Resolved_FY'] = fy_df[COL_RESOLVED].apply(get_fy)
                        fy_df['Resolved_FY_Quarter'] = fy_df[COL_RESOLVED].apply(get_fy_q)

                    available_fys = sorted(fy_df['FY'].dropna().unique().tolist(), reverse=True)
                    
                    if available_fys:
                        c1, c2 = st.columns(2)
                        with c1: selected_fy = st.selectbox("1️⃣ Select Financial Year", available_fys)
                        with c2: quarterly_cat = st.selectbox("2️⃣ Select Category", ["All Categories"] + main_categories)
                        
                        q_base_df = fy_df[fy_df['FY'] == selected_fy].copy()
                        if COL_RESOLVED in fy_df.columns:
                            q_closed_base_df = fy_df[fy_df['Resolved_FY'] == selected_fy].copy()
                        else:
                            q_closed_base_df = pd.DataFrame(columns=fy_df.columns)

                        if quarterly_cat != "All Categories":
                            q_base_df = q_base_df[q_base_df['MainCategory'] == quarterly_cat]
                            q_closed_base_df = q_closed_base_df[q_closed_base_df['MainCategory'] == quarterly_cat]
                        
                        if not q_base_df.empty or not q_closed_base_df.empty:
                            q_raised = q_base_df.groupby('FY_Quarter').size().rename("Tickets Raised")
                            q_total_closed = q_closed_base_df[q_closed_base_df['StatusBucket'].isin(RESOLVED_STATUSES)].groupby('Resolved_FY_Quarter').size().rename("Total Closed")
                            
                            if COL_RESOLVED in q_base_df.columns:
                                same_q_mask = (q_base_df['StatusBucket'].isin(RESOLVED_STATUSES)) & (q_base_df['Resolved_FY_Quarter'] == q_base_df['FY_Quarter']) & (q_base_df['Resolved_FY'] == q_base_df['FY'])
                                q_resolved = q_base_df[same_q_mask].groupby('FY_Quarter').size().rename("Resolved Same Quarter")
                            else:
                                q_resolved = pd.Series(dtype=int, name="Resolved Same Quarter")
                            
                            quarter_summary = pd.concat([q_raised, q_total_closed, q_resolved], axis=1).fillna(0).astype(int)
                            
                            for q in ['Q1 (Apr-Jun)', 'Q2 (Jul-Sep)', 'Q3 (Oct-Dec)', 'Q4 (Jan-Mar)']:
                                if q not in quarter_summary.index: quarter_summary.loc[q] = [0, 0, 0]
                            
                            quarter_summary = quarter_summary.sort_index()
                            quarter_summary['% Resolved Same Quarter'] = ((quarter_summary['Resolved Same Quarter'] / quarter_summary['Tickets Raised']) * 100).fillna(0).round(1)
                            
                            total_raised = quarter_summary["Tickets Raised"].sum()
                            total_row = pd.DataFrame([{
                                "Tickets Raised": total_raised, "Total Closed": quarter_summary["Total Closed"].sum(),
                                "Resolved Same Quarter": quarter_summary["Resolved Same Quarter"].sum(), 
                                "% Resolved Same Quarter": (quarter_summary["Resolved Same Quarter"].sum() / total_raised * 100) if total_raised > 0 else 0
                            }], index=["**TOTAL**"])
                            
                            st.dataframe(pd.concat([quarter_summary, total_row]), use_container_width=True, column_config={"% Resolved Same Quarter": st.column_config.NumberColumn(format="%.1f%%")})
                            st.bar_chart(quarter_summary[['Tickets Raised', 'Total Closed', 'Resolved Same Quarter']], use_container_width=True)
                            
                        st.markdown("---")
                        st.markdown("##### 🚜 Category Gap Analysis Trend")
                        c3, c4 = st.columns(2)
                        with c3: gap_fy = st.selectbox("3️⃣ Select Financial Year (Gap Trend)", available_fys, key="gap_fy")
                        with c4: gap_cats = st.multiselect("4️⃣ Select Categories", options=main_categories, default=main_categories[:2] if len(main_categories)>=2 else main_categories)
                        
                        if gap_cats:
                            sm_df = fy_df[(fy_df['FY'] == gap_fy) & (fy_df['MainCategory'].isin(gap_cats))].copy()
                            if not sm_df.empty:
                                sm_raised = sm_df.groupby('FY_Quarter').size().rename("Tickets Raised")
                                if COL_RESOLVED in sm_df.columns:
                                    sm_closed = sm_df[(sm_df['StatusBucket'].isin(RESOLVED_STATUSES)) & (sm_df['Resolved_FY_Quarter'] == sm_df['FY_Quarter']) & (sm_df['Resolved_FY'] == sm_df['FY'])].groupby('FY_Quarter').size().rename("Closed Same Quarter")
                                else:
                                    sm_closed = pd.Series(dtype=int, name="Closed Same Quarter")
                                    
                                sm_trend = pd.concat([sm_raised, sm_closed], axis=1).fillna(0).astype(int)
                                for q in ['Q1 (Apr-Jun)', 'Q2 (Jul-Sep)', 'Q3 (Oct-Dec)', 'Q4 (Jan-Mar)']:
                                    if q not in sm_trend.index: sm_trend.loc[q] = [0, 0]
                                        
                                sm_trend = sm_trend.sort_index()
                                sm_trend['Gap (Unresolved)'] = sm_trend['Tickets Raised'] - sm_trend['Closed Same Quarter']
                                sm_trend['% Resolved Same Quarter'] = ((sm_trend['Closed Same Quarter'] / sm_trend['Tickets Raised']) * 100).fillna(0).round(1)
                                
                                st.dataframe(sm_trend, use_container_width=True, column_config={"% Resolved Same Quarter": st.column_config.NumberColumn(format="%.1f%%")})
                                st.line_chart(sm_trend[['Tickets Raised', 'Closed Same Quarter']], use_container_width=True)

                elif st.session_state.current_view == "Surveyor Performance":
                    st.subheader("📝 Surveyor Performance & Operations")
                    
                    if COL_SURVEYOR in df_processed.columns:
                        view_df = df_processed[df_processed['Rationalised_Surveyor'] != 'IGNORED'].copy()
                        
                        st.markdown("### 🏆 Top Surveyors Overview")
                        if all_years:
                            surveyor_year = st.selectbox("Select Year for Overview", all_years, key="surv_year")
                            surveyor_df = view_df[view_df[COL_CREATED].dt.year == surveyor_year]
                            if not surveyor_df.empty:
                                user_ticket_counts = surveyor_df['Rationalised_Surveyor'].value_counts()
                                top_users = user_ticket_counts[user_ticket_counts >= 10].index.tolist()
                                if top_users:
                                    top_surveyor_df = surveyor_df[surveyor_df['Rationalised_Surveyor'].isin(top_users)]
                                    surveyor_pivot = pd.crosstab(index=top_surveyor_df[COL_CREATED].dt.month, columns=top_surveyor_df['Rationalised_Surveyor'], margins=True, margins_name='**TOTAL**')
                                    surveyor_pivot.index = surveyor_pivot.index.map(lambda val: calendar.month_abbr[int(val)] if str(val).isdigit() or isinstance(val, (int, float)) else val)
                                    surveyor_pivot.index.name = "Month"
                                    st.dataframe(surveyor_pivot, use_container_width=True)
                                else:
                                    st.info(f"No mapped surveyor raised enough tickets in {surveyor_year}.")
                        
                        st.markdown("---")
                        st.markdown("### 🔍 Surveyor Deep Dive")
                        c1, c2 = st.columns(2)
                        with c1:
                            min_date = view_df[COL_CREATED].min().date()
                            max_date = view_df[COL_CREATED].max().date()
                            surv_dates = st.date_input("1. Select Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date, key="surv_dates")
                        with c2:
                            all_surveyors = sorted(view_df['Rationalised_Surveyor'].dropna().unique().tolist())
                            selected_surv = st.selectbox("2. Select Surveyor", ["Select a Surveyor..."] + all_surveyors)
                            
                        if len(surv_dates) == 2 and selected_surv != "Select a Surveyor...":
                            start_d, end_d = surv_dates
                            mask = ((view_df[COL_CREATED].dt.date >= start_d) & (view_df[COL_CREATED].dt.date <= end_d) & (view_df['Rationalised_Surveyor'] == selected_surv))
                            surv_filtered_df = view_df[mask].copy()
                            
                            if not surv_filtered_df.empty:
                                st.markdown(f"**Category-wise Tickets for {selected_surv}**")
                                cat_counts = surv_filtered_df['MainCategory'].value_counts().reset_index()
                                cat_counts.columns = ['Category', 'Tickets Raised']
                                cat_counts.index = cat_counts.index + 1
                                st.dataframe(cat_counts, use_container_width=True)
                                
                                st.markdown(f"**Detailed Tickets ({len(surv_filtered_df)} found)**")
                                raw_cols = [COL_TICKET_ID, COL_CREATED, COL_STATUS, COL_WARD, COL_ZONE, COL_BEFORE_IMG, COL_AFTER_IMG]
                                display_cols = [c for c in raw_cols if c in surv_filtered_df.columns]
                                
                                out_df = surv_filtered_df[display_cols].copy()
                                rename_mapping = {
                                    COL_TICKET_ID: "Ticket Number", COL_CREATED: "Raised Date", COL_STATUS: "Status",
                                    COL_WARD: "Ward", COL_ZONE: "Zone", COL_BEFORE_IMG: "Before Image", COL_AFTER_IMG: "After Image"
                                }
                                st.dataframe(out_df.rename(columns=rename_mapping), use_container_width=True, column_config={"Before Image": st.column_config.ImageColumn("Before Image"), "After Image": st.column_config.ImageColumn("After Image"), "Raised Date": st.column_config.DatetimeColumn("Raised Date", format="DD MMM YYYY, HH:mm")})
                            else:
                                st.info("No tickets found for this surveyor in the selected date range.")
                                
                        st.markdown("---")
                        st.markdown("### 📅 Ward Survey Schedule")
                        st.caption("Tracks the last ticket raised by an authorized surveyor in each ward and projects the next 30-day survey deadline.")
                        
                        if COL_ZONE in view_df.columns and COL_WARD in view_df.columns:
                            schedule_zone = st.selectbox("Select Zone for Schedule", ["All"] + sorted(view_df[COL_ZONE].dropna().unique().tolist()))
                            sched_df = view_df.copy()
                            if schedule_zone != "All": sched_df = sched_df[sched_df[COL_ZONE] == schedule_zone]
                                
                            if not sched_df.empty:
                                schedule_summary = sched_df.groupby(COL_WARD)[COL_CREATED].max().reset_index()
                                schedule_summary.columns = ['Ward', 'Last Survey Date']
                                schedule_summary['Next Survey Due Date'] = schedule_summary['Last Survey Date'] + pd.Timedelta(days=30)
                                schedule_summary = schedule_summary.sort_values('Next Survey Due Date', ascending=True).reset_index(drop=True)
                                schedule_summary.index = schedule_summary.index + 1
                                
                                st.dataframe(schedule_summary, use_container_width=True, column_config={"Last Survey Date": st.column_config.DateColumn("Last Survey Date", format="DD MMM YYYY"), "Next Survey Due Date": st.column_config.DateColumn("Next Survey Due Date", format="DD MMM YYYY")})
                            else:
                                st.warning("No ward data available for this zone.")

            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                st.exception(e)
        else:
            st.info("👆 Please upload the Data file in the sidebar to begin.")

if __name__ == "__main__":
    main()
