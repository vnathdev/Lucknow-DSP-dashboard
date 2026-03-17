import streamlit as st
import pandas as pd
import io
from datetime import datetime
import calendar
import altair as alt

# --- MUST BE THE FIRST STREAMLIT COMMAND ---
st.set_page_config(page_title="Complaints Dashboard", layout="wide", initial_sidebar_state="collapsed")

# ==========================================
# CONFIGURATION & MAPPINGS
# ==========================================

SHEET_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/edit?gid=0#gid=0"

MAIN_CATEGORY_MAPPING = {
    # Sanitation
    "Garbage dumped on public land": "Sanitation",
    "Overflowing Dustbin": "Sanitation", 
    "Mud/silt sticking on structures on the roadsides/footpaths/Dividers": "Sanitation",
    "Burning of Garbage, Plastic, Leaves, Branches etc.": "Sanitation",
    "Road Dust/Sand Piled on Roadside": "Sanitation",
    "Road Dust": "Sanitation",
    "Garbage Burning at roadside": "Sanitation",
    
    # Malba
    "Malba, Bricks, Bori, etc on Dumping Land": "Malba",
    "Construction material lying unattended/encroaching public spaces": "Malba",
    "Construction and Demolition Activity Without Safeguards": "Malba",
    "C&D Waste Pick up request": "Malba",
    
    # Engineering
    "Pothole": "Engineering",
    "Unpaved road": "Engineering",
    "Broken Footpath/ Divider": "Engineering",
    "End to end pavement required": "Engineering"
}

CATEGORY_TO_DEPT_MAPPING = {
    "Sanitation": "Sanitation",
    "Malba": "Engineering",
    "Engineering": "Engineering"
}

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_google_sheet_url(url):
    try:
        if "docs.google.com/spreadsheets" not in url: return None
        parts = url.split('/')
        if 'd' in parts:
            d_index = parts.index('d')
            sheet_id = parts[d_index + 1]
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        return None
    except:
        return None

def display_with_fixed_footer(df, show_closure=True, show_pendency=False):
    if df.empty:
        st.warning("⚠️ No data available to display.")
        return
    body = df.iloc[:-1]
    total = df.iloc[[-1]]
    
    config = {}
    if show_closure and '% Closure' in df.columns:
        config['% Closure'] = st.column_config.NumberColumn(format="%.1f%%")
    if show_pendency and '% Pendency' in df.columns:
        config['% Pendency'] = st.column_config.NumberColumn(format="%.1f%%")
    if 'Avg Closure Time (Days)' in df.columns:
        config['Avg Closure Time (Days)'] = st.column_config.NumberColumn(format="%.1f")
        
    st.dataframe(body, use_container_width=True, column_config=config)
    st.markdown("⬇️ **Grand Total**") 
    st.dataframe(total, use_container_width=True, column_config=config)

@st.cache_data
def add_main_category(df):
    df['Subcategory'] = df['Subcategory'].astype(str).str.strip()
    df['MainCategory'] = df['Subcategory'].map(MAIN_CATEGORY_MAPPING).fillna('Others')
    return df

@st.cache_data
def add_status_buckets(df):
    def get_bucket(status_name):
        s = str(status_name).strip()
        if "Closed / Complied" in s: return "Closed / Complied"
        elif "Submit for Approval" in s: return "Submit for Approval"
        elif "Resolved" in s: return "Resolved"
        else: return "Open"
    df['StatusBucket'] = df['Status Name'].apply(get_bucket)
    return df

@st.cache_data
def add_department(df):
    def get_department(assigned_user):
        if pd.isna(assigned_user): return 'LMC'
        s = str(assigned_user).strip()
        if s.startswith('PWD'): return 'PWD'
        elif s.startswith('LDA'): return 'LDA'
        else: return 'LMC'
    df['Department'] = df['Assigned User Name'].apply(get_department)
    return df

@st.cache_data
def process_dates_and_closure_time(df, created_col, resolved_col):
    if created_col in df.columns:
        df[created_col] = pd.to_datetime(df[created_col], dayfirst=True, errors='coerce')
    
    if resolved_col in df.columns:
        df[resolved_col] = pd.to_datetime(df[resolved_col], dayfirst=True, errors='coerce')
        
    if created_col in df.columns and resolved_col in df.columns:
        df['ClosureTimeDays'] = (df[resolved_col] - df[created_col]).dt.days
        df['ClosureTimeDays'] = df['ClosureTimeDays'].apply(lambda x: x if pd.notna(x) and x >= 0 else None)
    else:
        df['ClosureTimeDays'] = None
    return df

@st.cache_data
def add_age_buckets(df, date_col):
    if date_col not in df.columns: return df
    now = datetime.now()
    df['AgeDays'] = (now - df[date_col]).dt.days
    
    def get_age_bucket(row):
        if row['StatusBucket'] in ['Closed / Complied', 'Resolved']: return "Closed"
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
    
    required_cols = ['Open', 'Submit for Approval', 'Resolved', 'Closed / Complied']
    for col in required_cols:
        if col not in summary.columns: summary[col] = 0
    summary = summary[required_cols]
    
    summary['Grand Total'] = summary.sum(axis=1)
    summary['% Closure'] = summary.apply(lambda row: ((row['Resolved'] + row['Closed / Complied']) / row['Grand Total'] * 100) if row['Grand Total'] > 0 else 0, axis=1).round(1)
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        summary['Avg Closure Time (Days)'] = df.groupby(group_col)['ClosureTimeDays'].mean().round(1)

    total_row_data = {col: summary[col].sum() for col in required_cols}
    total_grand = sum(total_row_data.values())
    numerator = total_row_data['Resolved'] + total_row_data['Closed / Complied']
    total_row_data['Grand Total'] = total_grand
    total_row_data['% Closure'] = (numerator / total_grand * 100) if total_grand > 0 else 0
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        total_row_data['Avg Closure Time (Days)'] = df['ClosureTimeDays'].mean().round(1)
    
    total_row = pd.DataFrame([total_row_data], index=[f'**{label_suffix}**'])
    return pd.concat([summary, total_row])

def generate_leaderboard_summary(df, group_cols, label_suffix="Total"):
    if df.empty: return pd.DataFrame()
    
    summary = df.groupby(group_cols + ['StatusBucket']).size().unstack(fill_value=0)
    
    if isinstance(summary.columns, pd.MultiIndex):
        summary.columns = summary.columns.droplevel(0)
    
    required_cols = ['Open', 'Submit for Approval', 'Closed / Complied', 'Resolved']
    for col in required_cols:
        if col not in summary.columns: summary[col] = 0
        
    summary = summary[required_cols]
    
    summary['Total Pending'] = summary['Open'] + summary['Submit for Approval'] + summary['Closed / Complied']
    summary['Grand Total'] = summary['Total Pending'] + summary['Resolved']
    
    summary['% Pendency'] = summary.apply(
        lambda row: (row['Total Pending'] / row['Grand Total'] * 100) if row['Grand Total'] > 0 else 0, 
        axis=1
    ).round(1)
    
    summary = summary.sort_values('Total Pending', ascending=False)
    
    total_row_data = {col: summary[col].sum() for col in required_cols + ['Total Pending', 'Grand Total']}
    total_pend = total_row_data['Total Pending']
    total_grand = total_row_data['Grand Total']
    total_row_data['% Pendency'] = (total_pend / total_grand * 100) if total_grand > 0 else 0

    if isinstance(group_cols, list) and len(group_cols) > 1:
        idx_tuple = tuple([''] * (len(group_cols) - 1) + [f'**{label_suffix}**'])
        total_row = pd.DataFrame([total_row_data], index=pd.MultiIndex.from_tuples([idx_tuple], names=group_cols))
    else:
        index_name = group_cols[0] if isinstance(group_cols, list) else group_cols
        total_row = pd.DataFrame([total_row_data], index=pd.Index([f'**{label_suffix}**'], name=index_name))
        
    return pd.concat([summary, total_row])

def generate_aging_summary(df, group_col):
    if 'AgeBucket' not in df.columns or df.empty: return pd.DataFrame()
    open_df = df[df['AgeBucket'] != 'Closed']
    if open_df.empty: return pd.DataFrame()
    summary = open_df.groupby([group_col, 'AgeBucket']).size().unstack(fill_value=0)
    cols = ['< 1 Month', '1-6 Months', '6-12 Months', '> 1 Year']
    for c in cols:
        if c not in summary.columns: summary[c] = 0
    summary = summary[cols]
    summary['Total Open'] = summary.sum(axis=1)
    summary = summary.sort_values('Total Open', ascending=False)
    return summary

# ==========================================
# MAIN APP
# ==========================================

def main():
    st.title("📊 Complaints Status Summary Dashboard")
    st.markdown("---")
    
    # --- SIDEBAR: Data Source ---
    st.sidebar.header("📂 Data Source")
    uploaded_file = st.sidebar.file_uploader("Upload Complaints Data (XLSX)", type=['xlsx'])

    # --- SIDEBAR: CTA Navigation Menu ---
    st.sidebar.markdown("---")
    st.sidebar.header("🧭 Navigation")
    
    # Initialize the session state for navigation tracking
    if 'current_view' not in st.session_state:
        st.session_state.current_view = "Main Category Summary"
    
    views = [
        "Main Category Summary",
        "Subcategory Drill-Down",
        "Zone-wise Drill-Down",
        "Department-wise Drill-Down",
        "Age-wise Pendency",
        "Monthly Trend Analysis",
        "Custom Date Range Analysis",
        "Quarterly Performance (FY)",
        "Surveyor Performance"
        # "Officer Leaderboard" <-- Commented out
    ]
    
    # Generate the CTA buttons dynamically
    for view in views:
        # Highlight the active button in blue, make the rest gray
        button_type = "primary" if st.session_state.current_view == view else "secondary"
        if st.sidebar.button(view, use_container_width=True, type=button_type):
            st.session_state.current_view = view
            st.rerun()

    if uploaded_file is not None:
        try:
            @st.cache_data
            def load_excel(file): return pd.read_excel(file)
            
            df = load_excel(uploaded_file)
            df.columns = df.columns.str.strip() 
            
            date_col = "Created At"
            resolved_date_col = "Resolved At" 

            if date_col not in df.columns:
                st.error(f"❌ Critical Error: Column **'{date_col}'** not found.")
                st.stop()
                
            df['Reporting Manager'] = df['Assigned User Name']
            df['Sheet_Department'] = "Unmapped" 
            df['User_Clean'] = df['Assigned User Name'].astype(str).str.strip()
            
            csv_url = get_google_sheet_url(SHEET_URL)
            if csv_url:
                try:
                    mapping_df = pd.read_csv(csv_url, on_bad_lines='skip')
                    mapping_df.columns = mapping_df.columns.str.strip()
                    required_sheet_cols = ['Officer Name', 'Reporting Manager', 'Department']
                    if all(col in mapping_df.columns for col in required_sheet_cols):
                        manager_map = pd.Series(mapping_df['Reporting Manager'].values, index=mapping_df['Officer Name'].astype(str).str.strip()).to_dict()
                        dept_map = pd.Series(mapping_df['Department'].values, index=mapping_df['Officer Name'].astype(str).str.strip()).to_dict()
                        df['Reporting Manager'] = df['User_Clean'].map(manager_map).fillna(df['Assigned User Name'])
                        df['Sheet_Department'] = df['User_Clean'].map(dept_map).fillna("Unmapped")
                    else:
                        st.sidebar.error(f"❌ Google Sheet Missing Columns! Needs: {required_sheet_cols}")
                except Exception as e:
                    st.sidebar.error(f"❌ Mapping Error: {e}")

            df_processed = add_main_category(df.copy())
            df_processed = add_status_buckets(df_processed) 
            df_processed = add_department(df_processed)
            df_processed = process_dates_and_closure_time(df_processed, date_col, resolved_date_col)
            df_processed = add_age_buckets(df_processed, date_col)
            
            # --- PRE-COMPUTE SHARED VARIABLES ---
            main_categories = sorted(df_processed['MainCategory'].unique())
            
            valid_created_years = df_processed[date_col].dt.year.dropna().unique().tolist()
            valid_resolved_years = []
            if resolved_date_col in df_processed.columns:
                valid_resolved_years = df_processed[resolved_date_col].dt.year.dropna().unique().tolist()
            all_years = sorted(list(set(valid_created_years + valid_resolved_years)), reverse=True)

            # ==========================================
            # RENDER SELECTED VIEW
            # ==========================================
            
            if st.session_state.current_view == "Main Category Summary":
                st.subheader("📈 Main Category Summary")
                
                # 1. Generate the table data
                summary_table = generate_pivot_summary(df_processed, 'MainCategory', "TOTAL")
                
                if not summary_table.empty:
                    # 2. Slice the table: Separate the Grand Total row from the rest of the data
                    body_df = summary_table.iloc[:-1]
                    total_series = summary_table.iloc[-1]
                    
                    # 3. --- NEW KPI METRIC CARDS ---
                    st.markdown("##### 🎯 Citywide Grand Totals")
                    
                    # Create 6 columns for the 6 metrics
                    m1, m2, m3, m4, m5, m6 = st.columns(6)
                    
                    m1.metric("🔴 Open", int(total_series['Open']))
                    m2.metric("🟠 Submit for Approval", int(total_series['Submit for Approval']))
                    m3.metric("🟡 Resolved", int(total_series['Resolved']))
                    m4.metric("🟢 Closed / Complied", int(total_series['Closed / Complied']))
                    m5.metric("📋 Grand Total", int(total_series['Grand Total']))
                    
                    # --- PERCENTAGE ROUNDED TO NEAREST INTEGER ---
                    rounded_pct = int(round(total_series['% Closure']))
                    m6.metric("✅ % Closure", f"{rounded_pct}%")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    # 4. --- CATEGORY TABLE (Without Total Row) ---
                    st.markdown("##### 📂 Category-wise Breakdown")
                    st.dataframe(
                        body_df, 
                        use_container_width=True,
                        column_config={
                            "% Closure": st.column_config.NumberColumn(format="%.1f%%")
                        }
                    )
                else:
                    st.warning("No data available.")
                
                # 5. --- VISUAL SNAPSHOT SECTION ---
                st.markdown("---")
                st.subheader("📊 Citywide & Zone-wise Snapshot")
                
                c1, c2 = st.columns([2, 1])
                
                with c1:
                    st.markdown("**Tickets Raised vs. Closed by Zone**")
                    if 'Zone Name' in df_processed.columns:
                        zone_raised = df_processed.groupby('Zone Name').size().rename("Total Raised")
                        zone_closed = df_processed[df_processed['StatusBucket'].isin(['Resolved', 'Closed / Complied'])].groupby('Zone Name').size().rename("Total Closed")
                        zone_bar_df = pd.concat([zone_raised, zone_closed], axis=1).fillna(0).astype(int)
                        st.bar_chart(zone_bar_df, use_container_width=True)
                    else:
                        st.info("⚠️ 'Zone Name' column not found in data.")
                        
                with c2:
                    st.markdown("**Citywide Status Breakdown**")
                    status_counts = df_processed['StatusBucket'].value_counts().reset_index()
                    status_counts.columns = ['Status', 'Count']
                    pie_chart = alt.Chart(status_counts).mark_arc(innerRadius=40).encode(
                        theta=alt.Theta(field="Count", type="quantitative"),
                        color=alt.Color(field="Status", type="nominal", 
                                        scale=alt.Scale(
                                            domain=['Open', 'Submit for Approval', 'Resolved', 'Closed / Complied'],
                                            range=['#EF4444', '#F59E0B', '#10B981', '#3B82F6'] 
                                        )),
                        tooltip=['Status', 'Count']
                    ).properties(height=350)
                    st.altair_chart(pie_chart, use_container_width=True)

            elif st.session_state.current_view == "Subcategory Drill-Down":
                st.subheader("🔍 Subcategory Drill-Down")
                tabs = st.tabs([f"{cat}" for cat in main_categories])
                for tab, main_cat in zip(tabs, main_categories):
                    with tab:
                        sub_df = df_processed[df_processed['MainCategory'] == main_cat]
                        if not sub_df.empty:
                            display_with_fixed_footer(generate_pivot_summary(sub_df, 'Subcategory', f"{main_cat} Total"))

            elif st.session_state.current_view == "Zone-wise Drill-Down":
                st.subheader("🗺️ Zone-wise Drill-Down")
                
                st.markdown("##### 📍 Zone Comparison by Status & Closure Time")
                b3_cat_all = st.selectbox("Select Main Category (For Zone Comparison)", main_categories, key="b3_cat_all")
                zone_matrix_df = df_processed[df_processed['MainCategory'] == b3_cat_all]
                
                if not zone_matrix_df.empty:
                    zone_comparison_summary = generate_pivot_summary(zone_matrix_df, 'Zone Name', "ALL ZONES TOTAL", show_avg_time=True)
                    display_with_fixed_footer(zone_comparison_summary)
                else:
                    st.warning("No data found for this category.")
                    
                st.markdown("<br>", unsafe_allow_html=True)
                
                st.markdown("##### 📋 Subcategory Detail by Zone")
                c1, c2 = st.columns(2)
                with c1: 
                    b3_cat_spec = st.selectbox("Select Main Category", main_categories, key="b3_cat_spec")
                with c2: 
                    b3_zone_spec = st.selectbox("Select Zone", sorted(df_processed['Zone Name'].dropna().unique()), key="b3_zone_spec")
                
                zone_spec_df = df_processed[(df_processed['MainCategory'] == b3_cat_spec) & (df_processed['Zone Name'] == b3_zone_spec)]
                if not zone_spec_df.empty:
                    zone_subcat_summary = generate_pivot_summary(zone_spec_df, 'Subcategory', f"{b3_cat_spec} - {b3_zone_spec} Total", show_avg_time=True)
                    display_with_fixed_footer(zone_subcat_summary)
                else:
                    st.warning("No data found.")

            elif st.session_state.current_view == "Department-wise Drill-Down":
                st.subheader("🏢 Department-wise Drill-Down")
                b4_dept = st.selectbox("Select Department", sorted(df_processed['Department'].unique()), key="b4_dept")
                dept_df = df_processed[df_processed['Department'] == b4_dept]
                if not dept_df.empty:
                    display_with_fixed_footer(generate_pivot_summary(dept_df, 'MainCategory', f"{b4_dept} Total"))
                else:
                    st.warning("No data found.")

            elif st.session_state.current_view == "Age-wise Pendency":
                st.subheader("⏳ Age-wise Pendency Analysis")
                c1, c2 = st.columns(2)
                with c1: b5_dept = st.selectbox("Select Department", sorted(df_processed['Department'].unique()), key="b5_dept")
                with c2: 
                    avail_cats = sorted(df_processed[df_processed['Department'] == b5_dept]['MainCategory'].unique())
                    b5_cat = st.selectbox("Select Category", avail_cats, key="b5_cat") if avail_cats else st.selectbox("Select Category", [], key="b5_cat_empty")
                    
                age_df = df_processed[(df_processed['Department'] == b5_dept) & (df_processed['MainCategory'] == b5_cat)]
                if not age_df.empty:
                    st.dataframe(generate_aging_summary(age_df, 'Subcategory'), use_container_width=True)
                else:
                    st.warning("No data found.")

            elif st.session_state.current_view == "Monthly Trend Analysis":
                st.subheader("📅 Monthly Trend Analysis")
                st.caption("Compare ticket volumes and track average closure times across the year.")
                
                if all_years:
                    selected_year = st.selectbox("Select Year", all_years, key="trend_year")
                    
                    st.markdown(f"**1. Monthly Ticket Volume ({selected_year})**")
                    raised_mask = df_processed[date_col].dt.year == selected_year
                    raised_counts = df_processed[raised_mask][date_col].dt.month.value_counts().rename("Tickets Raised")
                    
                    closed_counts = pd.Series(dtype=int, name="Tickets Closed")
                    if resolved_date_col in df_processed.columns:
                        closed_mask = (df_processed[resolved_date_col].dt.year == selected_year) & (df_processed['StatusBucket'].isin(['Closed / Complied', 'Resolved']))
                        closed_counts = df_processed[closed_mask][resolved_date_col].dt.month.value_counts().rename("Tickets Closed")
                    
                    trend_df = pd.concat([raised_counts, closed_counts], axis=1).fillna(0).astype(int)
                    
                    if not trend_df.empty:
                        trend_df = trend_df.sort_index()
                        table_df = trend_df.copy()
                        table_df.index = table_df.index.map(lambda x: calendar.month_abbr[int(x)] if pd.notna(x) else 'Unknown')
                        table_df.index.name = "Month"
                        
                        total_raised = table_df['Tickets Raised'].sum()
                        total_closed = table_df['Tickets Closed'].sum()
                        total_row = pd.DataFrame([{'Tickets Raised': total_raised, 'Tickets Closed': total_closed}], index=['**TOTAL**'])
                        trend_display = pd.concat([table_df, total_row])
                        
                        st.dataframe(trend_display, use_container_width=True)
                        
                        chart_df = trend_df.copy()
                        chart_df.index = [f"{selected_year}-{str(int(m)).zfill(2)}" for m in chart_df.index]
                        st.bar_chart(chart_df, use_container_width=True)
                        
                        st.markdown("---")
                        st.markdown(f"**2. Average Closure Days by Subcategory ({selected_year})**")
                        
                        if resolved_date_col in df_processed.columns:
                            closed_year_df = df_processed[(df_processed[resolved_date_col].dt.year == selected_year) & (df_processed['StatusBucket'].isin(['Closed / Complied', 'Resolved']))].copy()
                            
                            if not closed_year_df.empty and 'ClosureTimeDays' in closed_year_df.columns:
                                closed_year_df['ResolvedMonth'] = closed_year_df[resolved_date_col].dt.month
                                
                                st.markdown("##### 🏢 Main Category Averages")
                                main_avg_pivot = closed_year_df.groupby(['MainCategory', 'ResolvedMonth'])['ClosureTimeDays'].mean().unstack(fill_value=None).round(1)
                                
                                for m in range(1, 13):
                                    if m not in main_avg_pivot.columns:
                                        main_avg_pivot[m] = None
                                        
                                main_avg_pivot = main_avg_pivot[range(1, 13)]
                                main_avg_pivot.columns = [calendar.month_abbr[m] for m in range(1, 13)]
                                main_avg_pivot['Yearly Avg'] = closed_year_df.groupby('MainCategory')['ClosureTimeDays'].mean().round(1)
                                
                                monthly_avgs = closed_year_df.groupby('ResolvedMonth')['ClosureTimeDays'].mean().round(1)
                                total_row_data = {calendar.month_abbr[m]: monthly_avgs.get(m, None) for m in range(1, 13)}
                                total_row_data['Yearly Avg'] = closed_year_df['ClosureTimeDays'].mean().round(1)
                                
                                total_row_df = pd.DataFrame([total_row_data], index=['**OVERALL AVG**'])
                                final_main_table = pd.concat([main_avg_pivot, total_row_df])
                                st.dataframe(final_main_table, use_container_width=True)
                                
                                st.markdown("##### 🔍 Subcategory Drill-Down")
                                st.caption("Click a category below to view its specific subcategory breakdown.")
                                
                                for main_cat in sorted(closed_year_df['MainCategory'].unique()):
                                    with st.expander(f"📂 {main_cat} Subcategories"):
                                        sub_df = closed_year_df[closed_year_df['MainCategory'] == main_cat]
                                        sub_pivot = sub_df.groupby(['Subcategory', 'ResolvedMonth'])['ClosureTimeDays'].mean().unstack(fill_value=None).round(1)
                                        
                                        for m in range(1, 13):
                                            if m not in sub_pivot.columns:
                                                sub_pivot[m] = None
                                                
                                        sub_pivot = sub_pivot[range(1, 13)]
                                        sub_pivot.columns = [calendar.month_abbr[m] for m in range(1, 13)]
                                        sub_pivot['Yearly Avg'] = sub_df.groupby('Subcategory')['ClosureTimeDays'].mean().round(1)
                                        
                                        st.dataframe(sub_pivot, use_container_width=True)
                                
                                st.markdown("---")
                                st.markdown("**3. Category-wise Average Closure Trend**")
                                line_df = closed_year_df.groupby(['ResolvedMonth', 'MainCategory'])['ClosureTimeDays'].mean().unstack()
                                line_df.index = [f"{selected_year}-{str(int(m)).zfill(2)}" for m in line_df.index]
                                st.line_chart(line_df, use_container_width=True)
                                
                            else:
                                st.info("No closure time data available to calculate averages for this year.")
                        else:
                            st.warning("Resolved date column missing, cannot calculate closure times.")
                    else:
                        st.info(f"No ticket activity found for the year {selected_year}.")
                else:
                    st.warning("⚠️ No valid dates found in the data to generate trends.")

            elif st.session_state.current_view == "Custom Date Range Analysis":
                st.subheader("📆 Custom Date Range Analysis")
                st.caption("Analyze tickets raised, total tickets closed, and the resolution rate of new tickets within the exact same timeframe.")
                
                c1, c2 = st.columns(2)
                with c1:
                    min_date = df_processed[date_col].min().date()
                    max_date = df_processed[date_col].max().date()
                    custom_dates = st.date_input(
                        "1️⃣ Select Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date, key="custom_date_range"
                    )
                with c2:
                    custom_cat_options = ["All Categories"] + sorted(df_processed['MainCategory'].unique().tolist())
                    custom_cat = st.selectbox("2️⃣ Select Category", custom_cat_options, key="custom_date_cat")
                    
                if len(custom_dates) == 2:
                    start_date, end_date = custom_dates
                    raised_mask = (df_processed[date_col].dt.date >= start_date) & (df_processed[date_col].dt.date <= end_date)
                    raised_df = df_processed[raised_mask]
                    
                    if resolved_date_col in df_processed.columns:
                        closed_mask = (
                            (df_processed[resolved_date_col].dt.date >= start_date) & 
                            (df_processed[resolved_date_col].dt.date <= end_date) & 
                            (df_processed['StatusBucket'].isin(['Closed / Complied', 'Resolved']))
                        )
                        closed_df = df_processed[closed_mask]
                        closed_out_of_raised_df = raised_df[
                            raised_df['StatusBucket'].isin(['Closed / Complied', 'Resolved']) &
                            (raised_df[resolved_date_col].dt.date >= start_date) &
                            (raised_df[resolved_date_col].dt.date <= end_date)
                        ]
                    else:
                        closed_df = pd.DataFrame(columns=df_processed.columns)
                        closed_out_of_raised_df = pd.DataFrame(columns=df_processed.columns)
                        
                    if custom_cat != "All Categories":
                        raised_df = raised_df[raised_df['MainCategory'] == custom_cat]
                        closed_df = closed_df[closed_df['MainCategory'] == custom_cat]
                        closed_out_of_raised_df = closed_out_of_raised_df[closed_out_of_raised_df['MainCategory'] == custom_cat]
                        group_col = 'Subcategory'
                    else:
                        group_col = 'MainCategory'
                        
                    raised_grouped = raised_df.groupby(group_col).size().rename("Total Raised")
                    closed_grouped = closed_df.groupby(group_col).size().rename("Total Closed")
                    closed_out_grouped = closed_out_of_raised_df.groupby(group_col).size().rename("Closed (Out of Raised)")
                    
                    custom_summary = pd.concat([raised_grouped, closed_grouped, closed_out_grouped], axis=1).fillna(0).astype(int)
                    
                    if not custom_summary.empty:
                        custom_summary["% of New Tickets Resolved"] = ((custom_summary["Closed (Out of Raised)"] / custom_summary["Total Raised"]) * 100).fillna(0).round(1)

                        total_raised = custom_summary["Total Raised"].sum()
                        total_closed = custom_summary["Total Closed"].sum()
                        total_out = custom_summary["Closed (Out of Raised)"].sum()
                        total_pct = (total_out / total_raised * 100) if total_raised > 0 else 0
                        
                        total_row = pd.DataFrame([{
                            "Total Raised": total_raised, "Total Closed": total_closed,
                            "Closed (Out of Raised)": total_out, "% of New Tickets Resolved": total_pct
                        }], index=["**TOTAL**"])
                        
                        final_custom_display = pd.concat([custom_summary, total_row])
                        st.dataframe(final_custom_display, use_container_width=True, column_config={"% of New Tickets Resolved": st.column_config.NumberColumn(format="%.1f%%")})
                        st.bar_chart(custom_summary[["Total Raised", "Total Closed", "Closed (Out of Raised)"]], use_container_width=True)
                    else:
                        st.info("No data found for this specific combination of dates and categories.")
                else:
                    st.warning("Please select both a start and end date to view the analysis.")

            elif st.session_state.current_view == "Quarterly Performance (FY)":
                st.subheader("📊 Quarterly Performance (FY)")
                st.caption("Tickets raised, total tickets closed, and same-quarter resolutions per Financial Year quarter (Apr-Mar).")
                
                def get_fy(date_val):
                    if pd.isna(date_val): return None
                    if date_val.month <= 3: return f"{date_val.year - 1}-{str(date_val.year)[-2:]}"
                    else: return f"{date_val.year}-{str(date_val.year + 1)[-2:]}"

                def get_fy_q(date_val):
                    if pd.isna(date_val): return None
                    if date_val.month in [4, 5, 6]: return "Q1"
                    elif date_val.month in [7, 8, 9]: return "Q2"
                    elif date_val.month in [10, 11, 12]: return "Q3"
                    else: return "Q4"

                fy_df = df_processed.copy()
                fy_df['FY'] = fy_df[date_col].apply(get_fy)
                fy_df['FY_Quarter'] = fy_df[date_col].apply(get_fy_q)

                if resolved_date_col in fy_df.columns:
                    fy_df['Resolved_FY'] = fy_df[resolved_date_col].apply(get_fy)
                    fy_df['Resolved_FY_Quarter'] = fy_df[resolved_date_col].apply(get_fy_q)

                available_fys = sorted(fy_df['FY'].dropna().unique().tolist(), reverse=True)
                
                if available_fys:
                    c1, c2 = st.columns(2)
                    with c1: selected_fy = st.selectbox("1️⃣ Select Financial Year", available_fys, key="quarterly_fy")
                    with c2: 
                        quarterly_cat_options = ["All Categories"] + main_categories
                        quarterly_cat = st.selectbox("2️⃣ Select Category", quarterly_cat_options, key="quarterly_cat")
                    
                    q_base_df = fy_df[fy_df['FY'] == selected_fy].copy()
                    
                    if resolved_date_col in fy_df.columns:
                        q_closed_base_df = fy_df[fy_df['Resolved_FY'] == selected_fy].copy()
                    else:
                        q_closed_base_df = pd.DataFrame(columns=fy_df.columns)

                    if quarterly_cat != "All Categories":
                        q_base_df = q_base_df[q_base_df['MainCategory'] == quarterly_cat]
                        q_closed_base_df = q_closed_base_df[q_closed_base_df['MainCategory'] == quarterly_cat]
                    
                    if not q_base_df.empty or not q_closed_base_df.empty:
                        q_raised = q_base_df.groupby('FY_Quarter').size().rename("Tickets Raised")
                        q_closed_mask = q_closed_base_df['StatusBucket'].isin(['Resolved', 'Closed / Complied'])
                        q_total_closed = q_closed_base_df[q_closed_mask].groupby('Resolved_FY_Quarter').size().rename("Total Closed")
                        
                        if resolved_date_col in q_base_df.columns:
                            same_q_mask = (
                                q_base_df['StatusBucket'].isin(['Resolved', 'Closed / Complied']) & 
                                (q_base_df['Resolved_FY_Quarter'] == q_base_df['FY_Quarter']) &
                                (q_base_df['Resolved_FY'] == q_base_df['FY'])
                            )
                            q_resolved = q_base_df[same_q_mask].groupby('FY_Quarter').size().rename("Resolved Same Quarter")
                        else:
                            q_resolved = pd.Series(dtype=int, name="Resolved Same Quarter")
                        
                        quarter_summary = pd.concat([q_raised, q_total_closed, q_resolved], axis=1).fillna(0).astype(int)
                        
                        for q in ['Q1', 'Q2', 'Q3', 'Q4']:
                            if q not in quarter_summary.index: quarter_summary.loc[q] = [0, 0, 0]
                                
                        quarter_summary = quarter_summary.sort_index()
                        quarter_summary['% Resolved Same Quarter'] = ((quarter_summary['Resolved Same Quarter'] / quarter_summary['Tickets Raised']) * 100).fillna(0).round(1)
                        
                        total_raised = quarter_summary["Tickets Raised"].sum()
                        total_closed = quarter_summary["Total Closed"].sum()
                        total_same_q = quarter_summary["Resolved Same Quarter"].sum()
                        total_pct = (total_same_q / total_raised * 100) if total_raised > 0 else 0
                        
                        total_row = pd.DataFrame([{
                            "Tickets Raised": total_raised, "Total Closed": total_closed,
                            "Resolved Same Quarter": total_same_q, "% Resolved Same Quarter": total_pct
                        }], index=["**TOTAL**"])
                        
                        final_q_display = pd.concat([quarter_summary, total_row])
                        st.dataframe(final_q_display, use_container_width=True, column_config={"% Resolved Same Quarter": st.column_config.NumberColumn(format="%.1f%%")})
                        st.bar_chart(quarter_summary[['Tickets Raised', 'Total Closed', 'Resolved Same Quarter']], use_container_width=True)
                    else:
                        st.info(f"No tickets found for {quarterly_cat} in the Financial Year {selected_fy}.")
                        
                    # --- NEW: INDEPENDENT GAP ANALYSIS ---
                    st.markdown("---")
                    st.markdown("##### 🚜 Category Gap Analysis Trend")
                    st.caption("Track the specific gap between tickets raised and resolved within the same quarter.")
                    
                    c3, c4 = st.columns(2)
                    with c3:
                        gap_fy = st.selectbox("3️⃣ Select Financial Year (Gap Trend)", available_fys, key="gap_fy")
                    with c4:
                        # Safely default to Sanitation and Malba if they exist in the uploaded data
                        default_cats = [cat for cat in ["Sanitation", "Malba"] if cat in main_categories]
                        gap_cats = st.multiselect(
                            "4️⃣ Select Categories", 
                            options=main_categories, 
                            default=default_cats if default_cats else main_categories[:1],
                            key="gap_cats"
                        )
                    
                    if gap_cats:
                        sm_df = fy_df[(fy_df['FY'] == gap_fy) & (fy_df['MainCategory'].isin(gap_cats))].copy()
                        
                        if not sm_df.empty:
                            sm_raised = sm_df.groupby('FY_Quarter').size().rename("Tickets Raised")
                            
                            if resolved_date_col in sm_df.columns:
                                sm_same_q_mask = (
                                    sm_df['StatusBucket'].isin(['Resolved', 'Closed / Complied']) & 
                                    (sm_df['Resolved_FY_Quarter'] == sm_df['FY_Quarter']) &
                                    (sm_df['Resolved_FY'] == sm_df['FY'])
                                )
                                sm_closed = sm_df[sm_same_q_mask].groupby('FY_Quarter').size().rename("Closed Same Quarter")
                            else:
                                sm_closed = pd.Series(dtype=int, name="Closed Same Quarter")
                                
                            sm_trend = pd.concat([sm_raised, sm_closed], axis=1).fillna(0).astype(int)
                            
                            for q in ['Q1', 'Q2', 'Q3', 'Q4']:
                                if q not in sm_trend.index: sm_trend.loc[q] = [0, 0]
                                    
                            sm_trend = sm_trend.sort_index()
                            sm_trend['Gap (Unresolved)'] = sm_trend['Tickets Raised'] - sm_trend['Closed Same Quarter']
                            sm_trend['% Resolved Same Quarter'] = ((sm_trend['Closed Same Quarter'] / sm_trend['Tickets Raised']) * 100).fillna(0).round(1)
                            
                            st.dataframe(
                                sm_trend, 
                                use_container_width=True,
                                column_config={"% Resolved Same Quarter": st.column_config.NumberColumn(format="%.1f%%")}
                            )
                            
                            st.line_chart(sm_trend[['Tickets Raised', 'Closed Same Quarter']], use_container_width=True)
                        else:
                            st.info(f"No tickets found for the selected categories in FY {gap_fy}.")
                    else:
                        st.warning("Please select at least one category to view the gap analysis.")

                else:
                    st.warning("⚠️ No valid dates found to generate quarterly performance.")

            elif st.session_state.current_view == "Surveyor Performance":
                st.subheader("📝 Surveyor Performance")
                st.caption("Monthly breakdown of tickets raised by surveyors (Showing only those with 100+ tickets in the selected year).")
                user_col = "User Name" 
                
                if user_col in df_processed.columns:
                    if all_years:
                        surveyor_year = st.selectbox("Select Year for Surveyor Data", all_years, key="surveyor_year")
                        surveyor_mask = df_processed[date_col].dt.year == surveyor_year
                        surveyor_df = df_processed[surveyor_mask]
                        
                        if not surveyor_df.empty:
                            user_ticket_counts = surveyor_df[user_col].value_counts()
                            top_users = user_ticket_counts[user_ticket_counts >= 100].index.tolist()
                            
                            if not top_users:
                                st.info(f"No surveyor raised 100 or more tickets in the year {surveyor_year}.")
                            else:
                                top_surveyor_df = surveyor_df[surveyor_df[user_col].isin(top_users)]
                                surveyor_pivot = pd.crosstab(
                                    index=top_surveyor_df[date_col].dt.month, columns=top_surveyor_df[user_col],
                                    margins=True, margins_name='**TOTAL**'
                                )
                                def safe_month_map(val):
                                    if isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()):
                                        return calendar.month_abbr[int(val)]
                                    return val
                                surveyor_pivot.index = surveyor_pivot.index.map(safe_month_map)
                                surveyor_pivot.index.name = "Month"
                                st.dataframe(surveyor_pivot, use_container_width=True)
                        else:
                            st.info(f"No tickets were raised in the year {surveyor_year}.")
                    else:
                        st.warning("⚠️ No valid dates found to generate surveyor performance.")
                else:
                    st.warning(f"⚠️ Column '{user_col}' not found in the uploaded data.")

        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.exception(e)
    else:
        st.info("👆 Please upload the Complaints Data file in the sidebar to begin.")

if __name__ == "__main__":
    main()
