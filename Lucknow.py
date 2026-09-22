import streamlit as st
import pandas as pd
import numpy as np
import io
import re
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

def norm_key(value):
    """Normalise a lookup key: NBSP -> space, collapse whitespace, strip, lowercase.
    Makes mapping immune to casing and stray-whitespace differences between the
    Google Sheet and the ticket export."""
    s = str(value).replace('\u00a0', ' ').replace('\u200b', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.lower()

def build_map_from_sheet(url, sheet_label, key_col=None, val_col=None):
    """Read a 2-column mapping sheet into {normalised_key: value}.
    key_col/val_col are header names; when given they win over column position,
    so the sheet can be stored in either order. Falls back to col 0 -> col 1.
    Raises a clear message instead of silently returning an empty map."""
    sheet_df = pd.read_csv(url)
    if sheet_df.empty:
        st.error(f"⚠️ {sheet_label}: sheet loaded but is empty.")
        return {}
    if len(sheet_df.columns) < 2:
        # Usually means the sheet is no longer publicly viewable and Google
        # returned an HTML sign-in page instead of CSV.
        st.error(
            f"⚠️ {sheet_label}: expected at least 2 columns, got "
            f"{len(sheet_df.columns)} ({list(sheet_df.columns)[:3]}). "
            "Check that the sheet is shared as 'Anyone with the link - Viewer'."
        )
        return {}
    sheet_df.columns = [str(c).strip() for c in sheet_df.columns]
    # Resolve which column is the lookup key and which is the returned value.
    if key_col and val_col and key_col in sheet_df.columns and val_col in sheet_df.columns:
        key_series, val_series = sheet_df[key_col], sheet_df[val_col]
    else:
        if key_col or val_col:
            st.warning(
                f"⚠️ {sheet_label}: expected headers '{key_col}' and '{val_col}' but found "
                f"{list(sheet_df.columns)[:4]}. Falling back to column order (A -> B)."
            )
        key_series, val_series = sheet_df.iloc[:, 0], sheet_df.iloc[:, 1]
    keys = key_series.map(norm_key)
    vals = val_series.astype(str).str.strip()
    pairs = {k: v for k, v in zip(keys, vals) if k and k not in ('nan', 'none') and v and v != 'nan'}
    if not pairs:
        st.error(f"⚠️ {sheet_label}: no usable rows found in the first two columns.")
    return pairs

@st.cache_data(ttl=600)
def load_dynamic_mappings():
    """Fetches Google Sheets for Categories and Surveyors."""
    cat_map = {}
    surv_map = {}
    
    # 1. Subcategories
    try:
        # Sheet is stored Category (col A) -> Subcategory (col B); we need the reverse.
        cat_map = build_map_from_sheet(
            SUBCAT_MAPPING_URL, "Subcategory Mapping Sheet",
            key_col="Subcategory", val_col="Category"
        )
    except Exception as e:
        st.error(f"⚠️ Could not load Subcategory Mapping Sheet. Error: {e}")

    # 2. Surveyors
    try:
        surv_map = build_map_from_sheet(SURVEYOR_LIST_URL, "Surveyor Mapping Sheet")
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
            combined_roster['Officer Key'] = combined_roster['Officer Name'].map(norm_key)
            combined_roster['Reporting Manager'] = combined_roster['Reporting Manager'].astype(str).str.strip()
            # Create a dictionary to map Ground Officer -> Manager (normalised keys)
            return dict(zip(combined_roster['Officer Key'], combined_roster['Reporting Manager']))
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

def _natural_zone_key(label):
    """Sort 'Zone 2' before 'Zone 10' instead of alphabetically."""
    digits = re.findall(r'\d+', str(label))
    return (int(digits[0]) if digits else 10**9, str(label))


def _format_report_date(d):
    """11 Sept 2026 - matches the printed report convention."""
    abbr = d.strftime("%b")
    if abbr == "Sep":
        abbr = "Sept"
    return f"{d.day} {abbr} {d.year}"


def build_summary_tables(df, as_of_date=None):
    """Returns (category_table, {category: zone_table}) in the printed report's shape.

    'Closed' counts tickets whose status bucket is in RESOLVED_STATUSES.
    """
    data = df.copy()
    if as_of_date is not None:
        data = data[data[COL_CREATED].dt.date <= as_of_date]

    data['_IsClosed'] = data['StatusBucket'].isin(RESOLVED_STATUSES)

    def summarise(frame, group_col, label):
        grouped = frame.groupby(group_col).agg(
            Raised=('_IsClosed', 'size'),
            Closed=('_IsClosed', 'sum')
        ).reset_index()
        grouped['Pending'] = grouped['Raised'] - grouped['Closed']
        grouped['% Closure'] = (grouped['Closed'] / grouped['Raised'] * 100).where(grouped['Raised'] > 0, 0).round(2)
        grouped = grouped.rename(columns={group_col: label})
        return grouped

    cat_table = summarise(data, 'MainCategory', 'Category')
    cat_table = cat_table.sort_values('Raised', ascending=False).reset_index(drop=True)

    zone_tables = {}
    if COL_ZONE in data.columns:
        for category in cat_table['Category']:
            cat_rows = data[data['MainCategory'] == category]
            zt = summarise(cat_rows, COL_ZONE, 'Zone')
            zt = zt.sort_values('Zone', key=lambda s: s.map(_natural_zone_key)).reset_index(drop=True)
            zone_tables[category] = zt

    return cat_table, zone_tables


def _add_total_row(table_df, first_col, label="Total"):
    raised = int(table_df['Raised'].sum())
    closed = int(table_df['Closed'].sum())
    total = {
        first_col: label,
        'Raised': raised,
        'Closed': closed,
        'Pending': raised - closed,
        '% Closure': round(closed / raised * 100, 2) if raised else 0.0
    }
    return pd.concat([table_df, pd.DataFrame([total])], ignore_index=True)


def build_summary_pdf(cat_table, zone_tables, report_date, city_name="Lucknow Nagar Nigam"):
    """Renders the DSP status report to PDF bytes in the standard printed layout."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"{city_name} DSP Program Status"
    )
    styles = getSampleStyleSheet()
    h_city = ParagraphStyle('City', parent=styles['Title'], fontSize=18, spaceAfter=2)
    h_sub = ParagraphStyle('Sub', parent=styles['Title'], fontSize=13, spaceAfter=2)
    h_date = ParagraphStyle('DateLine', parent=styles['Normal'], fontSize=10, alignment=1, spaceAfter=10)
    h_sec = ParagraphStyle('Sec', parent=styles['Heading2'], fontSize=12, spaceBefore=10, spaceAfter=6)

    def make_table(df_table, headers):
        rows = [headers]
        for _, r in df_table.iterrows():
            rows.append([
                str(r.iloc[0]),
                f"{int(r['Raised']):,}",
                f"{int(r['Closed']):,}",
                f"{int(r['Pending']):,}",
                f"{r['% Closure']:.2f}%"
            ])
        tbl = Table(rows, colWidths=[55 * mm] + [26 * mm] * 4, repeatRows=1, hAlign='LEFT')
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#DCE6F1')),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#9BA7B4')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F4F6F8')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        return tbl

    story = [
        Paragraph(city_name, h_city),
        Paragraph("DSP Program Status", h_sub),
        Paragraph(f"Date: {_format_report_date(report_date)}", h_date),
        Paragraph("Dispersed sources ticket resolution status", h_sec),
        make_table(_add_total_row(cat_table, 'Category'),
                   ['Category', 'Tickets raised', 'Tickets closed', 'Tickets pending', '% closure']),
        Spacer(1, 6),
    ]

    from reportlab.platypus import KeepTogether
    for category, zt in zone_tables.items():
        block = [
            Paragraph(f"{category} Ticket status", h_sec),
            make_table(_add_total_row(zt, 'Zone'),
                       ['Zone', 'Raised', 'Closed', 'Pending', '% Closure']),
            Spacer(1, 6),
        ]
        story.append(KeepTogether(block))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

@st.cache_data(ttl=600)
def process_data(df, cat_map, surv_map, officer_map):
    """The mappings are passed IN (not fetched inside) so that they are part of
    the cache key - otherwise an edit to a Google Sheet would never invalidate
    the cached result for an already-uploaded file."""
    df = df.copy()
    df.columns = df.columns.str.strip()
    
    missing_cols = [col for col in [COL_SUBCATEGORY, COL_STATUS, COL_CREATED] if col not in df.columns]
    if missing_cols:
        st.error(f"❌ Missing critical columns in data: {', '.join(missing_cols)}")
        st.stop()
    
    # Clean and map categories (match on normalised keys)
    df['Subcategory_Clean'] = df[COL_SUBCATEGORY].astype(str).str.strip()
    df['Subcategory_Key'] = df[COL_SUBCATEGORY].map(norm_key)
    df['MainCategory'] = df['Subcategory_Key'].map(cat_map).fillna("Others")
    
    # Diagnostics: surface subcategories that found no match in the mapping sheet
    unmapped = df.loc[df['MainCategory'] == "Others", 'Subcategory_Clean']
    if not cat_map:
        st.error(
            "❌ Subcategory mapping is empty - every ticket has fallen into 'Others'. "
            "Fix the mapping sheet access/format above, then reload."
        )
    elif not unmapped.empty:
        with st.expander(f"⚠️ {unmapped.nunique()} subcategory value(s) fell into 'Others' ({len(unmapped)} tickets)"):
            st.caption("These exact values are missing from column A of the Subcategory Mapping Sheet:")
            st.dataframe(
                unmapped.value_counts().rename_axis('Subcategory').reset_index(name='Tickets'),
                use_container_width=True
            )
    
    # Map Surveyors (Apply rationalized names, mark others as "Ignored")
    if COL_SURVEYOR in df.columns:
        df['Raw_Surveyor'] = df[COL_SURVEYOR].astype(str).str.strip()
        df['Rationalised_Surveyor'] = df[COL_SURVEYOR].map(norm_key).map(surv_map).fillna("IGNORED")
        
    # Map Officers (Assigned User -> Reporting Manager)
    if COL_ASSIGNED in df.columns:
        df['Ground Officer'] = df[COL_ASSIGNED].astype(str).str.strip()
        df['Manager'] = df[COL_ASSIGNED].map(norm_key).map(officer_map).fillna("Unmapped Manager")
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
        # Mask invalid/negative durations with NaN (keeps the column float64, not object)
        df['ClosureTimeDays'] = df['ClosureTimeDays'].where(df['ClosureTimeDays'] >= 0)
    else:
        df['ClosureTimeDays'] = np.nan
        
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
    total_row_data['% Closure'] = round((total_row_data['Resolved Total'] / total_row_data['Grand Total'] * 100), 1) if total_row_data['Grand Total'] > 0 else 0
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        total_row_data['Avg Closure Time (Days)'] = round(df['ClosureTimeDays'].mean(), 1)
    
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
        "Summary Report"
    ]
    
    for view in views:
        btn_type = "primary" if st.session_state.current_view == view else "secondary"
        if st.sidebar.button(view, use_container_width=True, type=btn_type):
            st.session_state.current_view = view
            st.rerun()

    st.sidebar.divider()
    if st.sidebar.button("🔄 Refresh mapping sheets", use_container_width=True,
                         help="Re-reads the Category, Surveyor and Officer sheets immediately "
                              "instead of waiting for the 10-minute cache to expire."):
        load_dynamic_mappings.clear()
        load_officer_roster.clear()
        process_data.clear()
        st.rerun()

    if uploaded_file is not None:
        try:
            file_name = uploaded_file.name.lower()
            if file_name.endswith('.csv'):
                df_raw = pd.read_csv(uploaded_file, encoding='utf-8')
            else:
                df_raw = pd.read_excel(uploaded_file)
                
            cat_map, surv_map = load_dynamic_mappings()
            officer_map = load_officer_roster()
            df_processed = process_data(df_raw, cat_map, surv_map, officer_map)
            
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
                        avail_subs = ["All"] + sorted(df_processed['Subcategory'].dropna().unique().tolist())
                    else:
                        avail_subs = ["All"] + sorted(df_processed[df_processed['MainCategory'] == f_cat]['Subcategory'].dropna().unique().tolist())
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
                    filt_df = filt_df[filt_df['Subcategory'] == f_sub]
                if f_desig and 'Assigned User Designation' in filt_df.columns:
                    filt_df = filt_df[filt_df['Assigned User Designation'].astype(str).isin(f_desig)]
                if f_status:
                    filt_df = filt_df[filt_df['StatusBucket'].isin(f_status)]
                
                # --- 3. Generate Leaderboard ---
                if not filt_df.empty and (not avail_desig or f_desig) and f_status:
                    group_cols = ['Assigned User Name']
                    
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
                    
                    rename_dict = {'Assigned User Name': 'Officer Name'}
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
                                total_row_data['Yearly Avg'] = round(closed_year_df['ClosureTimeDays'].mean(), 1)
                                
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

            elif st.session_state.current_view == "Summary Report":
                st.subheader("📄 DSP Program Status — Summary Report")
                st.caption("Generates the standard printed status report: overall category summary "
                           "followed by a zone-wise table for each category.")

                rc1, rc2 = st.columns(2)
                with rc1:
                    report_date = st.date_input(
                        "Report Date", value=datetime.now().date(), key="summary_report_date",
                        help="Printed on the report header. Defaults to today."
                    )
                with rc2:
                    city_name = st.text_input("Report Heading", value="Lucknow Nagar Nigam", key="summary_city_name")

                cutoff = st.checkbox(
                    "Count only tickets raised on or before the report date",
                    value=False, key="summary_report_cutoff",
                    help="Off by default - the report covers every ticket in the uploaded file. "
                         "Tick this to cut the data off at the report date instead."
                )

                cat_table, zone_tables = build_summary_tables(
                    df_processed, as_of_date=report_date if cutoff else None
                )

                if cat_table.empty or cat_table['Raised'].sum() == 0:
                    st.warning("⚠️ No tickets fall within the selected reporting period.")
                else:
                    st.markdown("#### Dispersed sources ticket resolution status")
                    cat_display = _add_total_row(cat_table, 'Category').rename(columns={
                        'Raised': 'Tickets raised', 'Closed': 'Tickets closed', 'Pending': 'Tickets pending',
                        '% Closure': '% closure'
                    })
                    st.dataframe(cat_display, use_container_width=True, hide_index=True,
                                 column_config={"% closure": st.column_config.NumberColumn(format="%.2f%%")})

                    for category, zt in zone_tables.items():
                        st.markdown(f"#### {category} Ticket status")
                        st.dataframe(_add_total_row(zt, 'Zone'), use_container_width=True, hide_index=True,
                                     column_config={"% Closure": st.column_config.NumberColumn(format="%.2f%%")})

                    st.markdown("---")
                    try:
                        pdf_bytes = build_summary_pdf(cat_table, zone_tables, report_date, city_name)
                        st.download_button(
                            "📄 Download Report (PDF)",
                            data=pdf_bytes,
                            file_name=f"{city_name.replace(' ', '_')}_DSP_Report_{report_date.strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            type="primary"
                        )
                    except ImportError:
                        st.error("⚠️ PDF export needs the `reportlab` package. Add `reportlab` to requirements.txt and redeploy.")
                    except Exception as pdf_err:
                        st.error(f"⚠️ Could not build the PDF: {pdf_err}")

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
                    st.markdown("### 📆 Daily Surveyor Activity")
                    st.caption("Pick a single date to see who was active that day, how many tickets each raised, "
                               "and which zones and wards they covered.")

                    day_min = view_df[COL_CREATED].min().date()
                    day_max = view_df[COL_CREATED].max().date()
                    selected_day = st.date_input(
                        "Select Date", value=day_max, min_value=day_min, max_value=day_max, key="surv_daily_date"
                    )

                    daily_df = view_df[view_df[COL_CREATED].dt.date == selected_day].copy()

                    if daily_df.empty:
                        st.info(f"No tickets were raised by mapped surveyors on {selected_day.strftime('%d %b %Y')}.")
                    else:
                        has_zone = COL_ZONE in daily_df.columns
                        has_ward = COL_WARD in daily_df.columns

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Surveyors Active", daily_df['Rationalised_Surveyor'].nunique())
                        m2.metric("Tickets Raised", len(daily_df))
                        m3.metric("Zones Covered", daily_df[COL_ZONE].nunique() if has_zone else "-")
                        m4.metric("Wards Covered", daily_df[COL_WARD].nunique() if has_ward else "-")

                        def name_list(series):
                            names = sorted({str(v).strip() for v in series.dropna() if str(v).strip()})
                            return ", ".join(names)

                        agg_spec = {'Tickets Raised': (COL_TICKET_ID if COL_TICKET_ID in daily_df.columns else 'Rationalised_Surveyor', 'count')}
                        if has_zone:
                            agg_spec['Zones Visited'] = (COL_ZONE, 'nunique')
                            agg_spec['Zone Names'] = (COL_ZONE, name_list)
                        if has_ward:
                            agg_spec['Wards Visited'] = (COL_WARD, 'nunique')
                            agg_spec['Ward Names'] = (COL_WARD, name_list)

                        daily_summary = (
                            daily_df.groupby('Rationalised_Surveyor')
                                    .agg(**agg_spec)
                                    .reset_index()
                                    .rename(columns={'Rationalised_Surveyor': 'Surveyor Name'})
                                    .sort_values('Tickets Raised', ascending=False)
                                    .reset_index(drop=True)
                        )
                        daily_summary.index = daily_summary.index + 1

                        st.markdown(f"**Activity on {selected_day.strftime('%d %b %Y')}**")
                        st.dataframe(daily_summary, use_container_width=True)

                        st.download_button(
                            "⬇️ Download this day's summary (CSV)",
                            data=daily_summary.to_csv(index=False).encode('utf-8-sig'),
                            file_name=f"surveyor_daily_{selected_day.strftime('%Y%m%d')}.csv",
                            mime="text/csv"
                        )

                        inactive = sorted(
                            set(view_df['Rationalised_Surveyor'].dropna().unique())
                            - set(daily_df['Rationalised_Surveyor'].dropna().unique())
                        )
                        if inactive:
                            with st.expander(f"🚫 {len(inactive)} mapped surveyor(s) raised no tickets on this date"):
                                st.write(", ".join(inactive))

                        with st.expander("📋 Ticket-level detail for this date"):
                            daily_raw_cols = ['Rationalised_Surveyor', COL_TICKET_ID, COL_CREATED, COL_SUBCATEGORY,
                                              'MainCategory', COL_STATUS, COL_ZONE, COL_WARD]
                            daily_cols = [c for c in daily_raw_cols if c in daily_df.columns]
                            daily_detail = daily_df[daily_cols].sort_values(
                                ['Rationalised_Surveyor', COL_CREATED]
                            ).reset_index(drop=True)
                            daily_detail.index = daily_detail.index + 1
                            st.dataframe(
                                daily_detail.rename(columns={
                                    'Rationalised_Surveyor': 'Surveyor Name', COL_TICKET_ID: 'Ticket Number',
                                    COL_CREATED: 'Raised At', COL_SUBCATEGORY: 'Subcategory',
                                    'MainCategory': 'Category', COL_STATUS: 'Status',
                                    COL_ZONE: 'Zone', COL_WARD: 'Ward'
                                }),
                                use_container_width=True,
                                column_config={"Raised At": st.column_config.DatetimeColumn("Raised At", format="DD MMM YYYY, HH:mm")}
                            )

                    st.markdown("---")
                    st.markdown("### 🗓️ Monthly Surveyor Report")
                    st.caption("Select a month to see, for each surveyor, how many days they worked, "
                               "how many tickets they raised, and how many zones and wards they covered.")

                    month_series = view_df[COL_CREATED].dropna().dt.to_period('M')
                    available_months = sorted(month_series.unique(), reverse=True)

                    if not available_months:
                        st.info("No dated tickets available to build a monthly report.")
                    else:
                        month_labels = {f"{calendar.month_name[p.month]} {p.year}": p for p in available_months}
                        selected_label = st.selectbox("Select Month", list(month_labels.keys()), key="surv_month_report")
                        selected_period = month_labels[selected_label]

                        monthly_df = view_df[view_df[COL_CREATED].dt.to_period('M') == selected_period].copy()

                        if monthly_df.empty:
                            st.info(f"No tickets were raised by mapped surveyors in {selected_label}.")
                        else:
                            has_zone = COL_ZONE in monthly_df.columns
                            has_ward = COL_WARD in monthly_df.columns
                            days_in_month = calendar.monthrange(selected_period.year, selected_period.month)[1]

                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric("Surveyors Active", monthly_df['Rationalised_Surveyor'].nunique())
                            m2.metric("Tickets Raised", len(monthly_df))
                            m3.metric("Zones Covered", monthly_df[COL_ZONE].nunique() if has_zone else "-")
                            m4.metric("Wards Covered", monthly_df[COL_WARD].nunique() if has_ward else "-")

                            monthly_df['SurveyDate'] = monthly_df[COL_CREATED].dt.date
                            month_agg = {
                                'Days Worked': ('SurveyDate', 'nunique'),
                                'Tickets Raised': (COL_TICKET_ID if COL_TICKET_ID in monthly_df.columns else 'Rationalised_Surveyor', 'count'),
                            }
                            if has_zone:
                                month_agg['Zones Visited'] = (COL_ZONE, 'nunique')
                            if has_ward:
                                month_agg['Wards Visited'] = (COL_WARD, 'nunique')

                            monthly_summary = (
                                monthly_df.groupby('Rationalised_Surveyor')
                                          .agg(**month_agg)
                                          .reset_index()
                                          .rename(columns={'Rationalised_Surveyor': 'Surveyor Name'})
                            )
                            monthly_summary['Avg Tickets / Working Day'] = (
                                monthly_summary['Tickets Raised'] / monthly_summary['Days Worked']
                            ).round(1)
                            monthly_summary = monthly_summary.sort_values(
                                ['Tickets Raised', 'Days Worked'], ascending=False
                            ).reset_index(drop=True)
                            monthly_summary.index = monthly_summary.index + 1

                            st.markdown(f"**{selected_label} — {days_in_month} calendar days**")
                            st.dataframe(monthly_summary, use_container_width=True)

                            st.download_button(
                                "⬇️ Download monthly report (CSV)",
                                data=monthly_summary.to_csv(index=False).encode('utf-8-sig'),
                                file_name=f"surveyor_monthly_{selected_period.year}{selected_period.month:02d}.csv",
                                mime="text/csv"
                            )

                            month_inactive = sorted(
                                set(view_df['Rationalised_Surveyor'].dropna().unique())
                                - set(monthly_df['Rationalised_Surveyor'].dropna().unique())
                            )
                            if month_inactive:
                                with st.expander(f"🚫 {len(month_inactive)} mapped surveyor(s) raised no tickets in {selected_label}"):
                                    st.write(", ".join(month_inactive))

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
