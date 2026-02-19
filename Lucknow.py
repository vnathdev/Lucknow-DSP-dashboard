import streamlit as st
import pandas as pd
import io
from datetime import datetime

# ==========================================
# CONFIGURATION & MAPPINGS
# ==========================================

# 1. HARDCODED GOOGLE SHEET URL
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

# Map Main Categories to Department (from Google Sheet)
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

def sort_with_total(df, sort_col, ascending=False):
    if df.empty or len(df) == 1: return df
    body = df.iloc[:-1]
    total = df.iloc[[-1]]
    body_sorted = body.sort_values(by=sort_col, ascending=ascending)
    return pd.concat([body_sorted, total])

def display_with_fixed_footer(df, show_closure=True):
    if df.empty:
        st.warning("⚠️ No data available to display.")
        return
    body = df.iloc[:-1]
    total = df.iloc[[-1]]
    
    config = {}
    if show_closure:
        config = {'% Closure': st.column_config.NumberColumn(format="%.1f%%")}
        
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
    """
    UNIFIED STATUS LOGIC (Applied to ALL Batches):
    1. Closed / Complied -> 'Closed / Complied'
    2. Submit For Approval -> 'Submit for Approval'
    3. Resolved -> 'Resolved'
    4. Everything Else (Assigned, WIP, Long Term, Re-Open, etc.) -> 'Open'
    """
    def get_bucket(status_name):
        s = str(status_name).strip()
        # Exact/Partial matches based on your request
        if "Closed / Complied" in s: 
            return "Closed / Complied"
        elif "Submit for Approval" in s: 
            return "Submit for Approval"
        elif "Resolved" in s: 
            return "Resolved"
        else:
            # Catches: Assigned, Long Term, Re-Open, Work In Progress, etc.
            return "Open"

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
def add_age_buckets(df, date_col):
    if date_col not in df.columns: return df
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')
    now = datetime.now()
    df['AgeDays'] = (now - df[date_col]).dt.days
    
    def get_age_bucket(row):
        # We only age-check active items. Resolved/Closed are ignored here.
        if row['StatusBucket'] in ['Closed / Complied', 'Resolved']: return "Closed"
        days = row['AgeDays']
        if pd.isna(days): return "Unknown"
        if days < 30: return "< 1 Month"
        elif 30 <= days <= 180: return "1-6 Months"
        elif 180 < days <= 365: return "6-12 Months"
        else: return "> 1 Year"
    df['AgeBucket'] = df.apply(get_age_bucket, axis=1)
    return df

def generate_pivot_summary(df, group_col, label_suffix="Total"):
    """
    Standard Pivot for Batches 1-4 (Includes Resolved for Performance tracking)
    """
    if df.empty: return pd.DataFrame()
    summary = df.groupby([group_col, 'StatusBucket']).size().unstack(fill_value=0)
    
    # Ensure all buckets exist
    required_cols = ['Open', 'Submit for Approval', 'Resolved', 'Closed / Complied']
    for col in required_cols:
        if col not in summary.columns: summary[col] = 0
    summary = summary[required_cols]
    
    summary['Grand Total'] = summary.sum(axis=1)
    # Closure = (Resolved + Closed Complied) / Total
    summary['% Closure'] = summary.apply(lambda row: ((row['Resolved'] + row['Closed / Complied']) / row['Grand Total'] * 100) if row['Grand Total'] > 0 else 0, axis=1).round(1)
    
    total_row_data = {col: summary[col].sum() for col in required_cols}
    total_grand = sum(total_row_data.values())
    numerator = total_row_data['Resolved'] + total_row_data['Closed / Complied']
    total_pct = (numerator / total_grand * 100) if total_grand > 0 else 0
    total_row_data['Grand Total'] = total_grand
    total_row_data['% Closure'] = total_pct
    
    total_row = pd.DataFrame(total_row_data, index=[f'**{label_suffix}**'])
    return pd.concat([summary, total_row])

def generate_leaderboard_summary(df, group_col, label_suffix="Total"):
    """
    Leaderboard Logic (Batch 6):
    - Excludes 'Resolved'
    - Shows: Open (Aggregated), Closed / Complied, Submit for Approval
    - Total Pending = Sum of those 3
    """
    if df.empty: return pd.DataFrame()
    
    # Pivot
    summary = df.groupby([group_col, 'StatusBucket']).size().unstack(fill_value=0)
    
    # Columns to show
    active_cols = ['Open', 'Closed / Complied', 'Submit for Approval']
    for col in active_cols:
        if col not in summary.columns: summary[col] = 0
        
    # Select only active columns
    summary = summary[active_cols]
    
    # Calculate Total Pending
    summary['Total Pending'] = summary.sum(axis=1)
    
    # Sort by Total Pending Descending
    summary = summary.sort_values('Total Pending', ascending=False)
    
    # Total Row
    total_row_data = {col: summary[col].sum() for col in active_cols}
    total_row_data['Total Pending'] = sum(total_row_data.values())
    
    total_row = pd.DataFrame(total_row_data, index=[f'**{label_suffix}**'])
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

@st.cache_data
def get_all_subcategory_summaries(df, main_categories):
    all_sub_data = []
    for main_cat in main_categories:
        sub_df = df[df['MainCategory'] == main_cat]
        if not sub_df.empty:
            sub_summary = generate_pivot_summary(sub_df, 'Subcategory', f"{main_cat} Total")
            sub_summary['MainCategory'] = main_cat
            all_sub_data.append(sub_summary.reset_index())
    return pd.concat(all_sub_data, ignore_index=True)

# ==========================================
# MAIN APP
# ==========================================

def main():
    st.set_page_config(page_title="Complaints Dashboard", layout="wide")
    st.title("📊 Complaints Status Summary Dashboard")
    st.markdown("---")
    
    # SIDEBAR
    st.sidebar.header("📂 Data Source")
    uploaded_file = st.sidebar.file_uploader("1️⃣ Upload Complaints Data (XLSX)", type=['xlsx'])
    
    st.sidebar.markdown("---")
    st.sidebar.info(f"🔗 **Google Sheet Linked:**\nValid URL found in code.")

    if uploaded_file is not None:
        try:
            @st.cache_data
            def load_excel(file): return pd.read_excel(file)
            
            df = load_excel(uploaded_file)
            df.columns = df.columns.str.strip() 
            
            # --- DATE COLUMN ---
            date_col = "Created At"
            if date_col not in df.columns:
                st.error(f"❌ Critical Error: Column **'{date_col}'** not found.")
                st.stop()
                
            # --- HIERARCHY & DEPT MAPPING ---
            df['Reporting Manager'] = df['Assigned User Name']
            df['Sheet_Department'] = "Unmapped" 
            df['User_Clean'] = df['Assigned User Name'].astype(str).str.strip()
            
            # Load Google Sheet
            csv_url = get_google_sheet_url(SHEET_URL)
            if csv_url:
                try:
                    mapping_df = pd.read_csv(csv_url, on_bad_lines='skip')
                    mapping_df.columns = mapping_df.columns.str.strip()
                    required_sheet_cols = ['Officer Name', 'Reporting Manager', 'Department']
                    if all(col in mapping_df.columns for col in required_sheet_cols):
                        manager_map = pd.Series(
                            mapping_df['Reporting Manager'].values,
                            index=mapping_df['Officer Name'].astype(str).str.strip()
                        ).to_dict()
                        dept_map = pd.Series(
                            mapping_df['Department'].values,
                            index=mapping_df['Officer Name'].astype(str).str.strip()
                        ).to_dict()
                        df['Reporting Manager'] = df['User_Clean'].map(manager_map).fillna(df['Assigned User Name'])
                        df['Sheet_Department'] = df['User_Clean'].map(dept_map).fillna("Unmapped")
                        matches = df['User_Clean'].isin(manager_map.keys()).sum()
                        st.sidebar.success(f"✅ Mapping Active: {matches} officers mapped.")
                    else:
                        st.sidebar.error(f"❌ Google Sheet Missing Columns! Needs: {required_sheet_cols}")
                except Exception as e:
                    st.sidebar.error(f"❌ Mapping Error: {e}")

            # PROCESSING
            df_processed = add_main_category(df.copy())
            df_processed = add_status_buckets(df_processed) 
            df_processed = add_department(df_processed)
            df_processed = add_age_buckets(df_processed, date_col)
            
            # ==========================================
            # DASHBOARD BLOCKS
            # ==========================================
            
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

            # --- 3. Zone Drill-Down ---
            st.subheader("🗺️ Zone-wise Drill-Down")
            c1, c2 = st.columns(2)
            with c1: b3_cat = st.selectbox("Select Category", main_categories, key="b3_cat")
            with c2: b3_zone = st.selectbox("Select Zone", sorted(df_processed['Zone Name'].dropna().unique()), key="b3_zone")
            
            zone_df = df_processed[(df_processed['MainCategory'] == b3_cat) & (df_processed['Zone Name'] == b3_zone)]
            if not zone_df.empty:
                display_with_fixed_footer(generate_pivot_summary(zone_df, 'Subcategory', f"{b3_cat} - {b3_zone} Total"))
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
            
            # =========================================================
            # BATCH 6: OFFICER LEADERBOARD (ACTIVE PENDENCY)
            # =========================================================
            st.subheader("👨‍💼 Batch 6: Officer Leaderboard (Active Pendency)")
            st.caption("Includes: Open (Assigned, WIP, etc.), Closed / Complied, Submit for Approval. Excludes: Resolved.")
            
            # Filters
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1: 
                b6_cat = st.selectbox("1️⃣ Main Category", main_categories, key="b6_cat")
            with c2:
                all_zones = sorted(df_processed['Zone Name'].dropna().unique())
                b6_zone = st.selectbox("2️⃣ Zone", all_zones, key="b6_zone")
            with c3:
                b6_view = st.radio("3️⃣ View Level", ["L2 Officers (Ground)", "L1 Managers (Total Team)"], horizontal=True)

            # 1. BASE FILTER (Category + Zone)
            base_df = df_processed[
                (df_processed['MainCategory'] == b6_cat) &
                (df_processed['Zone Name'] == b6_zone)
            ]
            
            # 2. DEPT FILTER (Engineering or Sanitation)
            required_dept = CATEGORY_TO_DEPT_MAPPING.get(b6_cat, "Others")
            filtered_df = base_df[base_df['Sheet_Department'] == required_dept]
            
            # 3. EXCLUDE RESOLVED (Strict Logic)
            filtered_df = filtered_df[filtered_df['StatusBucket'] != 'Resolved']
            
            if filtered_df.empty:
                st.warning(f"No active pending tickets for {b6_cat} (Dept: {required_dept}) in {b6_zone}.")
            else:
                # 4. GROUPING LOGIC
                group_col = 'Reporting Manager' if "L1" in b6_view else 'Assigned User Name'

                # Use SPECIAL Leaderboard Generator
                leaderboard = generate_leaderboard_summary(filtered_df, group_col, "Group Total")
                
                # Sort logic
                sort_b6 = st.radio("Sort By", ["Total Pending (Desc)", "Open (Desc)"], horizontal=True, key="sort_b6")
                
                body = leaderboard.iloc[:-1]
                total = leaderboard.iloc[[-1]]
                
                if "Open" in sort_b6:
                    body = body.sort_values('Open', ascending=False)
                else:
                    body = body.sort_values('Total Pending', ascending=False)
                
                display_with_fixed_footer(pd.concat([body, total]), show_closure=False)

            st.markdown("---")
            
            # DOWNLOADS
            st.subheader("📥 Download Reports")
            c1, c2 = st.columns(2)
            with c1:
                csv_buffer1 = io.StringIO()
                summary_table.to_csv(csv_buffer1)
                st.download_button("📥 Summary CSV", csv_buffer1.getvalue(), "summary.csv", "text/csv")
            with c2:
                combined_sub = get_all_subcategory_summaries(df_processed, main_categories)
                csv_buffer2 = io.StringIO()
                combined_sub.to_csv(csv_buffer2, index=False)
                st.download_button("📥 Details CSV", csv_buffer2.getvalue(), "details.csv", "text/csv")

        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.exception(e)
    else:
        st.info("👆 Please upload the Complaints Data file in the sidebar to begin.")

if __name__ == "__main__":
    main()