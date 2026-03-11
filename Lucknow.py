import streamlit as st
import pandas as pd
import io
from datetime import datetime
import calendar

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
    st.set_page_config(page_title="Complaints Dashboard", layout="wide")
    st.title("📊 Complaints Status Summary Dashboard")
    st.markdown("---")
    
    st.sidebar.header("📂 Data Source")
    uploaded_file = st.sidebar.file_uploader("1️⃣ Upload Complaints Data (XLSX)", type=['xlsx'])

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
            
            # --- 1. Main Category Summary ---
            st.subheader("📈 Status-wise Summary by Main Category")
            summary_table = generate_pivot_summary(df_processed, 'MainCategory', "TOTAL")
            display_with_fixed_footer(summary_table)
            st.markdown("---")
            
            # --- 2. Subcategory Drill-Down ---
            st.subheader("🔍 Subcategory Drill-Down")
            main_categories = sorted(df_processed['MainCategory'].unique())
            tabs = st.tabs([f"{cat}" for cat in main_categories])
            for tab, main_cat in zip(tabs, main_categories):
                with tab:
                    sub_df = df_processed[df_processed['MainCategory'] == main_cat]
                    if not sub_df.empty:
                        display_with_fixed_footer(generate_pivot_summary(sub_df, 'Subcategory', f"{main_cat} Total"))
            st.markdown("---")

            # --- 3. ZONE-WISE DRILL-DOWN ---
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
            st.markdown("---")
            
            # --- 4. Department Drill-Down ---
            st.subheader("🏢 Department-wise Drill-Down")
            b4_dept = st.selectbox("Select Department", sorted(df_processed['Department'].unique()), key="b4_dept")
            dept_df = df_processed[df_processed['Department'] == b4_dept]
            if not dept_df.empty:
                display_with_fixed_footer(generate_pivot_summary(dept_df, 'MainCategory', f"{b4_dept} Total"))
            else:
                st.warning("No data found.")
            st.markdown("---")
            
            # --- 5. AGE-WISE PENDENCY ---
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
            st.markdown("---")

# --- 6. MONTHLY TREND ANALYSIS ---
            st.subheader("📅 Monthly Trend Analysis")
            st.caption("Compare the number of tickets raised vs. closed each month.")
            
            valid_created_years = df_processed[date_col].dt.year.dropna().unique().tolist()
            valid_resolved_years = []
            if resolved_date_col in df_processed.columns:
                valid_resolved_years = df_processed[resolved_date_col].dt.year.dropna().unique().tolist()
                
            all_years = sorted(list(set(valid_created_years + valid_resolved_years)), reverse=True)
            
            if all_years:
                selected_year = st.selectbox("Select Year", all_years, key="trend_year")
                
                raised_mask = df_processed[date_col].dt.year == selected_year
                raised_counts = df_processed[raised_mask][date_col].dt.month.value_counts().rename("Tickets Raised")
                
                closed_counts = pd.Series(dtype=int, name="Tickets Closed")
                if resolved_date_col in df_processed.columns:
                    closed_mask = (df_processed[resolved_date_col].dt.year == selected_year) & (df_processed['StatusBucket'].isin(['Closed / Complied', 'Resolved']))
                    closed_counts = df_processed[closed_mask][resolved_date_col].dt.month.value_counts().rename("Tickets Closed")
                
                trend_df = pd.concat([raised_counts, closed_counts], axis=1).fillna(0).astype(int)
                
                if not trend_df.empty:
                    # Sort by month integer (1 to 12)
                    trend_df = trend_df.sort_index()
                    
                    # 1. Chart Data: Use "YYYY-MM" string format. 
                    # Streamlit recognizes this as a timeline and automatically labels the x-axis with Month names!
                    chart_df = trend_df.copy()
                    chart_df.index = [f"{selected_year}-{str(int(m)).zfill(2)}" for m in chart_df.index]
                    
                    # 2. Table Data: Use clean strings like "Jan", "Feb"
                    table_df = trend_df.copy()
                    table_df.index = table_df.index.map(lambda x: calendar.month_abbr[int(x)] if pd.notna(x) else 'Unknown')
                    table_df.index.name = "Month"
                    
                    col_chart, col_table = st.columns([2, 1])
                    
                    with col_chart:
                        st.bar_chart(chart_df, use_container_width=True)
                        
                    with col_table:
                        total_raised = table_df['Tickets Raised'].sum()
                        total_closed = table_df['Tickets Closed'].sum()
                        total_row = pd.DataFrame([{'Tickets Raised': total_raised, 'Tickets Closed': total_closed}], index=['**TOTAL**'])
                        trend_display = pd.concat([table_df, total_row])
                        st.dataframe(trend_display, use_container_width=True)
                else:
                    st.info(f"No ticket activity found for the year {selected_year}.")
            else:
                st.warning("⚠️ No valid dates found in the data to generate trends. Please check your 'Created At' column format.")
            
            st.markdown("---")
            
# --- 7. SURVEYOR PERFORMANCE ---
            st.subheader("📝 Batch 7: Surveyor Performance")
            st.caption("Monthly breakdown of tickets raised by surveyors (Showing only those with 100+ tickets in the selected year).")
            
            user_col = "User Name" # Assuming this is the exact column name in your Excel
            
            if user_col in df_processed.columns:
                if all_years:
                    surveyor_year = st.selectbox("Select Year for Surveyor Data", all_years, key="surveyor_year")
                    
                    # Filter for the selected year
                    surveyor_mask = df_processed[date_col].dt.year == surveyor_year
                    surveyor_df = df_processed[surveyor_mask]
                    
                    if not surveyor_df.empty:
                        # --- NEW: Filter for 100+ tickets ---
                        # Count how many tickets each user has in this year
                        user_ticket_counts = surveyor_df[user_col].value_counts()
                        # Keep only users with 100 or more
                        top_users = user_ticket_counts[user_ticket_counts >= 100].index.tolist()
                        
                        if not top_users:
                            st.info(f"No surveyor raised 100 or more tickets in the year {surveyor_year}.")
                        else:
                            # Filter the dataframe to only include those top users
                            top_surveyor_df = surveyor_df[surveyor_df[user_col].isin(top_users)]
                            
                            # Create the cross-tabulation table
                            surveyor_pivot = pd.crosstab(
                                index=top_surveyor_df[date_col].dt.month,
                                columns=top_surveyor_df[user_col],
                                margins=True,
                                margins_name='**TOTAL**'
                            )
                            
                            # Safely map month numbers to names
                            def safe_month_map(val):
                                if isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()):
                                    return calendar.month_abbr[int(val)]
                                return val
                                
                            surveyor_pivot.index = surveyor_pivot.index.map(safe_month_map)
                            surveyor_pivot.index.name = "Month"
                            
                            # Display the table
                            st.dataframe(surveyor_pivot, use_container_width=True)
                    else:
                        st.info(f"No tickets were raised in the year {surveyor_year}.")
                else:
                    st.warning("⚠️ No valid dates found to generate surveyor performance.")
            else:
                st.warning(f"⚠️ Column '{user_col}' not found in the uploaded data. Please check your Excel file headers.")
            
            st.markdown("---")

# --- 8. QUARTERLY PERFORMANCE ---
            st.subheader("📊 Batch 8: Quarterly Performance")
            st.caption("Tickets raised in each quarter and how many of those were resolved within the same quarter.")
            
            if all_years:
                c1, c2 = st.columns(2)
                with c1:
                    quarterly_year = st.selectbox("1️⃣ Select Year", all_years, key="quarterly_year")
                with c2:
                    quarterly_cat_options = ["All Categories"] + main_categories
                    quarterly_cat = st.selectbox("2️⃣ Select Category", quarterly_cat_options, key="quarterly_cat")
                
                # Base filter for Year
                q_base_df = df_processed[df_processed[date_col].dt.year == quarterly_year].copy()
                
                # Filter for Category
                if quarterly_cat != "All Categories":
                    q_base_df = q_base_df[q_base_df['MainCategory'] == quarterly_cat]
                
                if not q_base_df.empty:
                    # Identify the creation quarter
                    q_base_df['Created_Q'] = "Q" + q_base_df[date_col].dt.quarter.astype(str)
                    
                    # Total Raised per quarter
                    q_raised = q_base_df.groupby('Created_Q').size().rename("Tickets Raised")
                    
                    # Resolved in the SAME quarter
                    # Checks if status is resolved/closed AND the resolved quarter & year match the created quarter & year
                    same_q_mask = (
                        q_base_df['StatusBucket'].isin(['Resolved', 'Closed / Complied']) & 
                        (q_base_df[resolved_date_col].dt.quarter == q_base_df[date_col].dt.quarter) &
                        (q_base_df[resolved_date_col].dt.year == q_base_df[date_col].dt.year)
                    )
                    q_resolved = q_base_df[same_q_mask].groupby('Created_Q').size().rename("Resolved Same Quarter")
                    
                    # Combine into a single table
                    quarter_summary = pd.concat([q_raised, q_resolved], axis=1).fillna(0).astype(int)
                    
                    # Ensure Q1-Q4 are always displayed
                    for q in ['Q1', 'Q2', 'Q3', 'Q4']:
                        if q not in quarter_summary.index:
                            quarter_summary.loc[q] = [0, 0]
                            
                    quarter_summary = quarter_summary.sort_index()
                    quarter_summary['% Resolved Same Quarter'] = ((quarter_summary['Resolved Same Quarter'] / quarter_summary['Tickets Raised']) * 100).fillna(0).round(1)
                    
                    # Format display
                    st.dataframe(
                        quarter_summary, 
                        use_container_width=True,
                        column_config={
                            "% Resolved Same Quarter": st.column_config.NumberColumn(format="%.1f%%")
                        }
                    )
                    
                    # Add visual bar chart
                    st.bar_chart(quarter_summary[['Tickets Raised', 'Resolved Same Quarter']], use_container_width=True)
                    
                else:
                    st.info(f"No tickets found for {quarterly_cat} in the year {quarterly_year}.")
            else:
                st.warning("⚠️ No valid dates found to generate quarterly performance.")
            
            st.markdown("---")

            # --- 9. OFFICER LEADERBOARD ---
            st.subheader("👨‍💼 Batch 9: Officer Leaderboard")
            st.caption("Displays Active Pendency alongside Resolved Tickets for a comprehensive performance view.")
            
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1: 
                b6_cat_options = ["All Categories"] + main_categories
                b6_cat = st.selectbox("1️⃣ Main Category", b6_cat_options, key="b6_cat_dropdown")
            with c2:
                all_zones = ["All Zones"] + sorted(df_processed['Zone Name'].dropna().unique().tolist())
                b6_zone = st.selectbox("2️⃣ Zone", all_zones, key="b6_zone_dropdown")
            with c3:
                b6_view = st.radio("3️⃣ View Level", ["L2 Officers (Ground)", "L1 Managers (Total Team)"], horizontal=True)

            b6_df = df_processed.copy()
            if b6_zone != "All Zones":
                b6_df = b6_df[b6_df['Zone Name'] == b6_zone]
                
            if b6_cat != "All Categories":
                b6_df = b6_df[b6_df['MainCategory'] == b6_cat]
                required_dept = CATEGORY_TO_DEPT_MAPPING.get(b6_cat, "Others")
                b6_df = b6_df[b6_df['Sheet_Department'] == required_dept]
            
            if b6_df.empty:
                st.warning("No records found for this selection.")
            else:
                group_cols = []
                if b6_cat == "All Categories":
                    group_cols.append('Sheet_Department')
                    
                if "L1" in b6_view:
                    group_cols.append('Reporting Manager')
                else:
                    group_cols.append('Assigned User Name')

                leaderboard = generate_leaderboard_summary(b6_df, group_cols, "Group Total")
                display_with_fixed_footer(leaderboard, show_closure=False, show_pendency=True)

            st.markdown("---")
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.exception(e)
    else:
        st.info("👆 Please upload the Complaints Data file in the sidebar to begin.")

if __name__ == "__main__":
    main()
