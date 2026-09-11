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
CIVIL_OFFICER_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=0"
SANITATION_OFFICER_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=1074591996"
SUBCAT_MAPPING_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=2005007155"
SURVEYOR_LIST_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=1801847585"

# --- Status Buckets for Lucknow ---
STATUS_COLUMNS = ["Open", "Submit for Approval", "Resolved", "Closed / Complied"]
UNRESOLVED_STATUSES = ["Open", "Submit for Approval"]
RESOLVED_STATUSES = ["Resolved", "Closed / Complied"]

# ==========================================
# HELPER FUNCTIONS & DATA LOADING
# ==========================================

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

@st.cache_data(ttl=600)
def load_officer_roster():
    """Fetches and combines the Civil and Sanitation Officer sheets."""
    combined_roster = pd.DataFrame()
    try:
        civil_df = pd.read_csv(CIVIL_OFFICER_URL)
        san_df = pd.read_csv(SANITATION_OFFICER_URL)
        combined_roster = pd.concat([civil_df, san_df], ignore_index=True)
        
        if 'Officer Name' in combined_roster.columns and 'Reporting Manager' in combined_roster.columns:
            combined_roster['Officer Name'] = combined_roster['Officer Name'].astype(str).str.strip()
            combined_roster['Reporting Manager'] = combined_roster['Reporting Manager'].astype(str).str.strip()
            # Create a dictionary to map Ground Officer -> Manager
            return dict(zip(combined_roster['Officer Name'], combined_roster['Reporting Manager']))
    except Exception as e:
        st.error(f"⚠️ Could not load Officer Roster Sheets. Error: {e}")
        
    return {}

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
    officer_map = load_officer_roster()
    
    # Clean and map categories
    df['Subcategory_Clean'] = df[COL_SUBCATEGORY].astype(str).str.strip()
    df['MainCategory'] = df['Subcategory_Clean'].map(cat_map).fillna("Others")
    
    # Map Surveyors (Apply rationalized names, mark others as "Ignored")
    if COL_SURVEYOR in df.columns:
        df['Raw_Surveyor'] = df[COL_SURVEYOR].astype(str).str.strip()
        df['Rationalised_Surveyor'] = df['Raw_Surveyor'].map(surv_map).fillna("IGNORED")
        
    # Map Officers (Assigned User -> Reporting Manager)
    if COL_ASSIGNED in df.columns:
        df['Ground Officer'] = df[COL_ASSIGNED].astype(str).str.strip()
        df['Manager'] = df['Ground Officer'].map(officer_map).fillna("Unmapped Manager")
    else:
        df['Ground Officer'] = "Unassigned"
        df['Manager'] = "Unmapped Manager"
        
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
        summary['Avg Closure Time (Days)'] = df.groupby(group_col)['ClosureTimeDays'].mean().round(1)

    total_row_data = {col: summary[col].sum() for col in STATUS_COLUMNS + ['Unresolved Total', 'Resolved Total', 'Grand Total']}
    total_row_data['% Closure'] = (total_row_data['Resolved Total'] / total_row_data['Grand Total'] * 100) if total_row_data['Grand Total'] > 0 else 0
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        total_row_data['Avg Closure Time (Days)'] = df['ClosureTimeDays'].mean().round(1)
    
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
        "Surveyor Performance"
    ]
    
    for view in views:
        btn_type = "primary" if st.session_state.current_view == view else "secondary"
        if st.sidebar.button(view, use_container_width=True, type=btn_type):
            st.session_state.current_view = view
            st.rerun()

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
                    f1, f2, f3 = st.columns(3)
                    
                    with f1:
                        filter_cat = st.selectbox("1. Select Main Category", ["All"] + main_categories)
                    
                    with f2:
                        if filter_cat == "All":
                            available_subs = ["All"] + sorted(df_processed['Subcategory_Clean'].dropna().unique().tolist())
                        else:
                            available_subs = ["All"] + sorted(df_processed[df_processed['MainCategory'] == filter_cat]['Subcategory_Clean'].dropna().unique().tolist())
                        filter_sub = st.selectbox("2. Select Subcategory", available_subs)
                        
                    with f3:
                        filter_status = st.selectbox("3. Select Status", ["All"] + STATUS_COLUMNS)
                        
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    d1, d2 = st.columns([1, 2])
                    with d1:
                        use_date = st.checkbox("📅 Filter by Date Range")
                    with d2:
                        if use_date:
                            min_date = df_processed[COL_CREATED].min().date()
                            max_date = df_processed[COL_CREATED].max().date()
                            filter_dates = st.date_input("4. Select Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
                        
                    deep_dive_df = df_processed.copy()
                    if filter_cat != "All":
                        deep_dive_df = deep_dive_df[deep_dive_df['MainCategory'] == filter_cat]
                    if filter_sub != "All":
                        deep_dive_df = deep_dive_df[deep_dive_df['Subcategory_Clean'] == filter_sub]
                    if filter_status != "All":
                        deep_dive_df = deep_dive_df[deep_dive_df['StatusBucket'] == filter_status]
                        
                    if use_date and len(filter_dates) == 2:
                        start_d, end_d = filter_dates
                        deep_dive_df = deep_dive_df[(deep_dive_df[COL_CREATED].dt.date >= start_d) & (deep_dive_df[COL_CREATED].dt.date <= end_d)]
                        
                    st.markdown(f"**Found {len(deep_dive_df)} matching tickets:**")
                    
                    raw_cols = [COL_TICKET_ID, COL_ZONE, COL_WARD, COL_CREATED, 'AgeDays', COL_BEFORE_IMG, COL_AFTER_IMG]
                    display_cols = [c for c in raw_cols if c in deep_dive_df.columns]
                    
                    out_df = deep_dive_df[display_cols].copy()
                    
                    rename_mapping = {
                        COL_TICKET_ID: "Ticket Number",
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
            # OFFICER LEADERBOARD
            # ==========================================
            elif st.session_state.current_view == "Officer Leaderboard":
                st.subheader("🏆 Officer Leaderboard & Pendency Tracking")
                st.caption("Live mappings pulled from Google Sheets.")
                
                unresolved_df = df_processed[df_processed['StatusBucket'].isin(UNRESOLVED_STATUSES)].copy()
                ignore_list = ['Unassigned', 'Unmapped Manager']
                
                valid_unresolved = unresolved_df[
                    (~unresolved_df['Ground Officer'].isin(ignore_list)) & 
                    (~unresolved_df['Manager'].isin(ignore_list))
                ]
                
                # Split by Category dynamically
                cat_tabs = st.tabs(main_categories)
                
                def draw_leaderboard(df_to_use, group_col, role_label):
                    if df_to_use.empty:
                        st.info(f"No unresolved tickets found for {role_label}s in this category.")
                        return
                        
                    counts = df_to_use.groupby(group_col).size().reset_index(name='Total Unresolved Tickets')
                    counts = counts.sort_values('Total Unresolved Tickets', ascending=True).reset_index(drop=True)
                    counts.columns = [f"{role_label} Name", 'Total Unresolved Tickets']
                        
                    c1, c2 = st.columns(2)
                    with c1:
                        st.success(f"🌟 Top 5 {role_label}s (Least Pendency)")
                        top_5 = counts.head(5).copy()
                        top_5.index = top_5.index + 1  
                        st.dataframe(top_5, use_container_width=True)
                            
                    with c2:
                        st.error(f"⚠️ Bottom 5 {role_label}s (Highest Pendency)")
                        bottom_5 = counts.tail(5).sort_values('Total Unresolved Tickets', ascending=False).reset_index(drop=True)
                        bottom_5.index = bottom_5.index + 1  
                        st.dataframe(bottom_5, use_container_width=True)

                for tab, cat in zip(cat_tabs, main_categories):
                    with tab:
                        cat_df = valid_unresolved[valid_unresolved['MainCategory'] == cat]
                        st.markdown("##### 👷 Ground Officers")
                        draw_leaderboard(cat_df, 'Ground Officer', 'Officer')
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("##### 👔 Managers")
                        draw_leaderboard(cat_df, 'Manager', 'Manager')
                        
                st.markdown("---")
                st.markdown("### 🔍 Filtered Officer Pendency View")
                
                f1, f2, f3 = st.columns(3)
                with f1: f_cat = st.selectbox("Category", ["All"] + main_categories)
                with f2: 
                    if COL_ZONE in df_processed.columns:
                        f_zone = st.selectbox("Zone", ["All"] + sorted(df_processed[COL_ZONE].dropna().unique().tolist()))
                    else:
                        f_zone = "All"
                with f3: role_type = st.radio("Select Role to Inspect", ["Ground Officer", "Manager"], horizontal=True)
                
                filt_df = valid_unresolved.copy()
                if f_cat != "All": filt_df = filt_df[filt_df['MainCategory'] == f_cat]
                if f_zone != "All" and COL_ZONE in filt_df.columns: filt_df = filt_df[filt_df[COL_ZONE] == f_zone]
                
                target_col = 'Ground Officer' if role_type == "Ground Officer" else 'Manager'
                
                if not filt_df.empty:
                    officer_list = ["All"] + sorted(filt_df[target_col].dropna().unique().tolist())
                    f_officer = st.selectbox(f"Select Specific {role_type}", officer_list)
                    
                    if f_officer != "All":
                        filt_df = filt_df[filt_df[target_col] == f_officer]
                        
                    final_table = filt_df.groupby(target_col).size().reset_index(name='Total Unresolved Tickets')
                    final_table = final_table.sort_values('Total Unresolved Tickets', ascending=False).reset_index(drop=True)
                    final_table.columns = ['Officer Name', 'Total Unresolved Tickets']
                    final_table.index = final_table.index + 1
                    st.dataframe(final_table, use_container_width=True)
                else:
                    st.info("No unresolved tickets found matching those filters.")

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
                    f1, f2, f3 = st.columns(3)
                    
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
                        
                    insp_age_df = df_processed[df_processed['StatusBucket'].isin(UNRESOLVED_STATUSES)].copy()
                    
                    if filter_cat_age != "All":
                        insp_age_df = insp_age_df[insp_age_df['MainCategory'] == filter_cat_age]
                    if filter_sub_age != "All":
                        insp_age_df = insp_age_df[insp_age_df['Subcategory_Clean'] == filter_sub_age]
                    if filter_age_bucket != "All":
                        insp_age_df = insp_age_df[insp_age_df['AgeBucket'] == filter_age_bucket]
                        
                    st.markdown(f"**Found {len(insp_age_df)} pending tickets:**")
                    
                    raw_cols_age = [COL_TICKET_ID, COL_CREATED, COL_ZONE, COL_WARD, 'Ground Officer', 'Manager', COL_BEFORE_IMG]
                    display_cols_age = [c for c in raw_cols_age if c in insp_age_df.columns]
                    
                    out_age_df = insp_age_df[display_cols_age].copy()
                    
                    rename_mapping_age = {
                        COL_TICKET_ID: "Ticket Number",
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
                            top_users = user_ticket_counts[user_ticket_counts >= 10].index.tolist() # Lowered threshold to 10 for visibility
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