import streamlit as st
import pandas as pd
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
SUBCAT_MAPPING_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=2005007155"
SURVEYOR_LIST_URL = "https://docs.google.com/spreadsheets/d/1R7NnhOQNibQtAI6OnUjvg8BtZ-SZGRKcIHi0f_qRM68/export?format=csv&gid=1801847585"
QC_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRuBQ0mhHm-JkKIymtE7gRHARPGRS3B6evvAq88Qv1"
    "xRJGtBAtztWJ0EjIpSs75mW5kKattUbaHwNfV/pub?gid=940031451&single=true&output=csv"
)

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
        # Already a CSV link - either an /export link or a File > Share > Publish
        # to web link (/d/e/2PACX.../pub?...output=csv). Use it as given.
        if "/export?format=csv" in url or "output=csv" in url: return url
        if "/spreadsheets/d/e/" in url: return url
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
            # Swapped iloc[:, 1] (Subcategory) as the key and iloc[:, 0] (Main Category) as the value
            cat_map = dict(zip(cat_df.iloc[:, 1].map(norm_key), cat_df.iloc[:, 0].astype(str).str.strip()))
    except Exception as e:
        st.error(f"⚠️ Could not load Subcategory Mapping Sheet. Error: {e}")

    # 2. Surveyors
    try:
        surv_df = pd.read_csv(SURVEYOR_LIST_URL)
        if not surv_df.empty and len(surv_df.columns) >= 2:
            surv_map = {}
            for raw_name, nice_name in zip(surv_df.iloc[:, 0], surv_df.iloc[:, 1]):
                nice = str(nice_name).strip()
                if not nice or nice.lower() in ('nan', 'none'):
                    continue
                # Index each row under several keys: the exact login name, the login name
                # with the 'Surveyor N' decoration stripped, and the rationalised name
                # itself - so a login that differs only in its surveyor number still maps.
                for key in (norm_key(raw_name), surveyor_name_key(raw_name),
                            norm_key(nice), surveyor_name_key(nice)):
                    if key and key not in ('nan', 'none'):
                        surv_map.setdefault(key, nice)
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

def norm_key(value):
    """Normalise a lookup key: NBSP -> space, collapse whitespace, strip, lowercase.
    Keeps sheet-vs-export differences in casing/spacing from breaking a mapping."""
    s = str(value).replace('\u00a0', ' ').replace('\u200b', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.lower()


def surveyor_name_key(value):
    """Reduce a surveyor name to the person, dropping the app's login decorations:
    'Surveyor 1 Prem Prakash SURVEYOR' and 'Surveyor1 Prem Prakash' both -> 'prem prakash'.
    Used as a fallback so a login whose Surveyor NUMBER differs from the sheet still matches."""
    s = norm_key(value)
    s = re.sub(r'^surveyor\s*\d*\s*', '', s)
    s = re.sub(r'\s*surveyor$', '', s)
    return s.strip()


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
    data['_IsSFA'] = data['StatusBucket'] == 'Submit for Approval'

    def summarise(frame, group_col, label):
        grouped = frame.groupby(group_col).agg(
            Raised=('_IsClosed', 'size'),
            Closed=('_IsClosed', 'sum'),
            SFA=('_IsSFA', 'sum')
        ).reset_index()
        grouped = grouped.rename(columns={'SFA': 'Submit for Approval'})
        # Pending still means everything not closed; 'Submit for Approval' is the
        # subset of that pending pile which is awaiting sign-off.
        grouped['Pending'] = grouped['Raised'] - grouped['Closed']
        grouped['% Closure'] = (grouped['Closed'] / grouped['Raised'] * 100).where(grouped['Raised'] > 0, 0).round(2)
        grouped = grouped.rename(columns={group_col: label})
        return grouped[[label, 'Raised', 'Closed', 'Submit for Approval', 'Pending', '% Closure']]

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
    sfa = int(table_df['Submit for Approval'].sum()) if 'Submit for Approval' in table_df.columns else 0
    total = {
        first_col: label,
        'Raised': raised,
        'Closed': closed,
        'Submit for Approval': sfa,
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

    h_cell = ParagraphStyle('HCell', parent=styles['Normal'], fontName='Helvetica-Bold',
                            fontSize=8.5, leading=10, alignment=1, textColor=colors.white)

    def make_table(df_table, headers):
        # Header labels are wrapped in Paragraphs so long ones break onto a
        # second line instead of spilling over the neighbouring column.
        rows = [[Paragraph(h, h_cell) for h in headers]]
        for _, r in df_table.iterrows():
            rows.append([
                str(r.iloc[0]),
                f"{int(r['Raised']):,}",
                f"{int(r['Closed']):,}",
                f"{int(r['Submit for Approval']):,}",
                f"{int(r['Pending']):,}",
                f"{r['% Closure']:.2f}%"
            ])
        tbl = Table(rows, colWidths=[42 * mm] + [26 * mm] * 5, repeatRows=1, hAlign='LEFT')
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
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
                   ['Category', 'Tickets raised', 'Tickets closed', 'Submit for approval',
                    'Tickets pending', '% closure']),
        Spacer(1, 6),
    ]

    from reportlab.platypus import KeepTogether
    for category, zt in zone_tables.items():
        block = [
            Paragraph(f"{category} Ticket status", h_sec),
            make_table(_add_total_row(zt, 'Zone'),
                       ['Zone', 'Raised', 'Closed', 'Submit for Approval', 'Pending', '% Closure']),
            Spacer(1, 6),
        ]
        story.append(KeepTogether(block))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


SHORT_TERM_CATEGORIES = ['sanitation', 'malba']
SHORT_TERM_LABEL = 'Short-term (Sanitation + Malba)'


def _short_term_slice(pivot):
    """Rows of a category pivot that count as short-term tickets."""
    idx = [i for i in pivot.index if str(i).strip().lower() in SHORT_TERM_CATEGORIES]
    return pivot.loc[idx] if idx else None


def _correct_status_col(columns):
    """Return the status column that means a good-quality check.
    Matched exactly so 'Incorrect' is never mistaken for 'Correct'."""
    for c in columns:
        if str(c).strip().lower() == 'correct':
            return c
    return None


def _qc_chart_png(kind, data, title=""):
    """Render a QC chart to PNG bytes for embedding in the PDF.
    kind 'donut' expects a DataFrame with Status/Count; kind 'bar' expects
    Category/Status/Count and draws a stacked bar per category."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    palette = plt.get_cmap('tab20').colors

    if kind == 'donut':
        fig, ax = plt.subplots(figsize=(4.2, 3.4), dpi=150)
        counts = data['Count'].tolist()
        labels = [str(s) for s in data['Status'].tolist()]
        total = sum(counts)
        wedges, _ = ax.pie(counts, startangle=90, counterclock=False,
                           colors=palette[:len(counts)], wedgeprops=dict(width=0.42))
        ax.set_aspect('equal')
        legend_labels = [f"{l} - {c} ({c / total * 100:.1f}%)" if total else l
                         for l, c in zip(labels, counts)]
        ax.legend(wedges, legend_labels, loc='upper center', bbox_to_anchor=(0.5, 0.02),
                  fontsize=7, frameon=False, ncol=1)
        if title:
            ax.set_title(title, fontsize=10, fontweight='bold')
    else:
        pivot = data.pivot_table(index='Category', columns='Status',
                                 values='Count', aggfunc='sum', fill_value=0)
        # Plot each category as 100%, so categories of very different sizes
        # stay comparable; the table underneath carries the absolute counts.
        totals = pivot.sum(axis=1).replace(0, 1)
        pct = pivot.div(totals, axis=0) * 100
        fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=150)
        bottom = [0] * len(pct.index)
        for i, status in enumerate(pct.columns):
            vals = pct[status].tolist()
            ax.bar(pct.index.astype(str), vals, bottom=bottom,
                   label=str(status), color=palette[i % len(palette)])
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_ylabel('% of category', fontsize=9)
        ax.set_ylim(0, 100)
        ax.tick_params(axis='both', labelsize=8)
        ax.spines[['top', 'right']].set_visible(False)
        ax.legend(fontsize=7, frameon=False, ncol=3,
                  loc='upper center', bbox_to_anchor=(0.5, -0.12))
        if title:
            ax.set_title(title, fontsize=10, fontweight='bold')

    fig.tight_layout()
    fig.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def build_qc_pdf(qc_scopes_data, report_date, city_name="Lucknow Nagar Nigam", period_label=None,
                 resolved_status_label=None):
    """Renders the Quality Check module to PDF bytes.

    qc_scopes_data: list of dicts, each with
        title, completed, pending, counts (Status/Count df), tidy (Category/Status/Count df or None)
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, Image, KeepTogether)
    from reportlab.lib.utils import ImageReader

    def sized_image(buf, max_w, max_h):
        """Place a PNG at its natural aspect ratio inside the given box.
        Passing fixed width AND height to Image() stretches the picture, which
        turns the donuts into ovals."""
        buf.seek(0)
        img_w, img_h = ImageReader(buf).getSize()
        scale = min(max_w / img_w, max_h / img_h)
        buf.seek(0)
        return Image(buf, width=img_w * scale, height=img_h * scale)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"{city_name} DSP Quality Check Status"
             + (f" - {period_label}" if period_label else "")
    )
    styles = getSampleStyleSheet()
    h_city = ParagraphStyle('City', parent=styles['Title'], fontSize=18, spaceAfter=2)
    h_sub = ParagraphStyle('Sub', parent=styles['Title'], fontSize=13, spaceAfter=2)
    h_date = ParagraphStyle('DateLine', parent=styles['Normal'], fontSize=10, alignment=1, spaceAfter=10)
    h_sec = ParagraphStyle('Sec', parent=styles['Heading2'], fontSize=12, spaceBefore=8, spaceAfter=5)
    h_sub2 = ParagraphStyle('Sub2', parent=styles['Heading3'], fontSize=10, spaceBefore=6, spaceAfter=4)
    h_cell = ParagraphStyle('HCell', parent=styles['Normal'], fontName='Helvetica-Bold',
                            fontSize=8.5, leading=10, alignment=1, textColor=colors.white)

    def styled_table(rows, col_widths, total_row=False, bold_last_n=1):
        tbl = Table(rows, colWidths=col_widths, repeatRows=1, hAlign='LEFT')
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#9BA7B4')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F4F6F8')]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]
        if total_row:
            first_bold = len(rows) - bold_last_n
            style += [('FONTNAME', (0, first_bold), (-1, -1), 'Helvetica-Bold'),
                      ('BACKGROUND', (0, first_bold), (-1, -1), colors.HexColor('#DCE6F1'))]
        tbl.setStyle(TableStyle(style))
        return tbl

    h_period = ParagraphStyle('PeriodLine', parent=styles['Normal'], fontSize=10,
                              alignment=1, spaceAfter=2, fontName='Helvetica-Bold')
    h_note = ParagraphStyle('NoteLine', parent=styles['Normal'], fontSize=8,
                            alignment=1, spaceAfter=10, textColor=colors.HexColor('#555555'))

    story = [
        Paragraph(city_name, h_city),
        Paragraph("DSP Quality Check Status", h_sub),
        Paragraph(f"Date: {_format_report_date(report_date)}",
                  h_date if not period_label else h_period),
    ]
    if period_label:
        # A month/year filter was active in the dashboard - say so on the report.
        story.append(Paragraph(f"Period: {period_label}", h_period))
    if resolved_status_label:
        story.append(Paragraph(f"Resolved tickets counted: {resolved_status_label}", h_period))
    if period_label or resolved_status_label:
        story.append(Paragraph(
            "Category-wise figures reflect the filters above; "
            "the completion status and distribution charts cover all months and statuses.", h_note))

    # --- Completion summary across all four scopes ---
    story.append(Paragraph("Quality check completion status", h_sec))
    rows = [[Paragraph(h, h_cell) for h in
             ['Scope', 'Completed', 'Pending', 'Total', '% Completed']]]
    for sc in qc_scopes_data:
        done, pend = int(sc['completed']), int(sc['pending'])
        tot = done + pend
        rows.append([sc['title'], f"{done:,}", f"{pend:,}", f"{tot:,}",
                     f"{(done / tot * 100) if tot else 0:.2f}%"])
    story.append(styled_table(rows, [58 * mm] + [30 * mm] * 4))
    story.append(Spacer(1, 8))

    # --- One block per scope: donut + status table, then category chart + table ---
    for sc_idx, sc in enumerate(qc_scopes_data):
        block = [Paragraph(sc['title'], h_sec)]

        counts = sc['counts']
        if counts is not None and not counts.empty and counts['Count'].sum() > 0:
            total = int(counts['Count'].sum())
            img = sized_image(_qc_chart_png('donut', counts), 78 * mm, 68 * mm)
            st_rows = [[Paragraph(h, h_cell) for h in ['Status', 'Count', '% of completed']]]
            for _, r in counts.iterrows():
                st_rows.append([str(r['Status']), f"{int(r['Count']):,}",
                                f"{r['Count'] / total * 100:.2f}%"])
            st_rows.append(['Completed', f"{total:,}", '100.00%'])
            st_rows.append(['Pending QC', f"{int(sc['pending']):,}", '-'])
            side = styled_table(st_rows, [40 * mm, 22 * mm, 26 * mm], total_row=False)
            pair = Table([[img, side]], colWidths=[82 * mm, 92 * mm], hAlign='LEFT')
            pair.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                      ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
            block.append(pair)
        else:
            block.append(Paragraph("No quality check data recorded for this scope.", styles['Normal']))

        story.append(KeepTogether(block))
        story.append(Spacer(1, 4))

        tidy = sc.get('tidy')
        if tidy is not None and not tidy.empty:
            cat_block = [Paragraph("By category", h_sub2),
                         sized_image(_qc_chart_png('bar', tidy), 168 * mm, 82 * mm)]
            pivot = tidy.pivot_table(index='Category', columns='Status',
                                     values='Count', aggfunc='sum', fill_value=0)
            pivot['Total'] = pivot.sum(axis=1)
            correct_col = _correct_status_col(pivot.columns)
            headers = ['Category'] + [str(c) for c in pivot.columns]
            if correct_col is not None:
                headers.append('% Correct')
            cat_rows = [[Paragraph(h, h_cell) for h in headers]]
            for cat, r in pivot.iterrows():
                row = [str(cat)] + [f"{int(v):,}" for v in r.tolist()]
                if correct_col is not None:
                    tot = int(r['Total'])
                    row.append(f"{int(r[correct_col]) / tot * 100:.1f}%" if tot else "-")
                cat_rows.append(row)
            totals = ['Total'] + [f"{int(pivot[c].sum()):,}" for c in pivot.columns]
            if correct_col is not None:
                grand = int(pivot['Total'].sum())
                totals.append(f"{int(pivot[correct_col].sum()) / grand * 100:.1f}%" if grand else "-")
            cat_rows.append(totals)

            bold_rows = 1
            if str(sc['title']).lower().startswith('resolved'):
                st_slice = _short_term_slice(pivot)
                if st_slice is not None:
                    st_label = ParagraphStyle('STCell', parent=styles['Normal'], fontSize=8,
                                              leading=9.5, fontName='Helvetica-Bold')
                    st_row = [Paragraph(SHORT_TERM_LABEL, st_label)] + \
                             [f"{int(st_slice[c].sum()):,}" for c in pivot.columns]
                    if correct_col is not None:
                        st_tot = int(st_slice['Total'].sum())
                        st_row.append(
                            f"{int(st_slice[correct_col].sum()) / st_tot * 100:.1f}%" if st_tot else "-")
                    cat_rows.append(st_row)
                    bold_rows = 2

            n_val_cols = len(headers) - 1
            cat_block.append(styled_table(
                cat_rows, [40 * mm] + [min(26, 128 / max(n_val_cols, 1)) * mm] * n_val_cols,
                total_row=True, bold_last_n=bold_rows))
            story.append(KeepTogether(cat_block))

        story.append(Spacer(1, 8))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

@st.cache_data(ttl=600)
def load_qc_resolved_split(cat_map, status_choice="Closed"):
    """Resolved L1/L2 quality check counts, split by main category.

    Reads the QC sheet directly so the detailed report can include QC figures
    without the user visiting the Quality Check view first. Returns
    {"Resolved L1 (Col T)": tidy_df, ...} with Category/Status/Count columns.
    """
    qc_url = get_google_sheet_url(QC_SHEET_URL)
    if not qc_url or not cat_map:
        return {}
    qc = pd.read_csv(qc_url)
    if len(qc.columns) < 21:
        return {}

    # Subcategory column = the one whose values best match the mapping sheet
    mapping_keys = set(cat_map.keys())
    scores = [float(qc.iloc[:, i].astype(str).map(norm_key).isin(mapping_keys).mean())
              for i in range(len(qc.columns))]
    best_idx = int(max(range(len(scores)), key=lambda i: scores[i]))
    if scores[best_idx] == 0:
        return {}
    categories = qc.iloc[:, best_idx].astype(str).map(norm_key).map(cat_map).fillna("Others")

    # Ticket status filter (Closed / Submit for Approval / both)
    status_col = next((c for c in qc.columns if 'status' in str(c).strip().lower()), None)
    if status_col is not None:
        s = qc[status_col].astype(str).str.strip().str.lower()
        closed = s.str.contains('closed') | s.str.contains('complied') | s.eq('resolved')
        sfa = s.str.contains('submit') & s.str.contains('approval')
        if status_choice == 'Closed':
            status_mask = closed
        elif status_choice == 'Submit for Approval':
            status_mask = sfa
        else:
            status_mask = closed | sfa
    else:
        status_mask = pd.Series(True, index=qc.index)

    out = {}
    for label, col in [("Resolved L1", qc.columns[19]),
                       ("Resolved L2", qc.columns[20])]:
        evaluated = ~qc[col].astype(str).str.lower().str.contains('not evaluated', na=False)
        keep = status_mask & evaluated & qc[col].notna()
        if not keep.any():
            continue
        tidy = (pd.DataFrame({'Category': categories[keep], 'Status': qc.loc[keep, col]})
                .groupby(['Category', 'Status']).size().reset_index(name='Count'))
        tidy = tidy[tidy['Count'] > 0]
        if not tidy.empty:
            out[label] = tidy
    return out


def build_detailed_pdf(cat_table, zone_tables, report_date, city_name="Lucknow Nagar Nigam",
                       qc_splits=None, qc_status_label="Closed"):
    """Detailed report: category share pies, the standard status tables, and the
    L1/L2 resolved quality check split by category."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, Image, KeepTogether, CondPageBreak)
    from reportlab.lib.utils import ImageReader

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"{city_name} DSP Detailed Status Report"
    )
    styles = getSampleStyleSheet()
    h_city = ParagraphStyle('City', parent=styles['Title'], fontSize=18, spaceAfter=2)
    h_sub = ParagraphStyle('Sub', parent=styles['Title'], fontSize=13, spaceAfter=2)
    h_date = ParagraphStyle('DateLine', parent=styles['Normal'], fontSize=10, alignment=1, spaceAfter=10)
    h_sec = ParagraphStyle('Sec', parent=styles['Heading2'], fontSize=12, spaceBefore=8, spaceAfter=5)
    h_sub2 = ParagraphStyle('Sub2', parent=styles['Heading3'], fontSize=10, spaceBefore=6, spaceAfter=4)
    h_cell = ParagraphStyle('HCell', parent=styles['Normal'], fontName='Helvetica-Bold',
                            fontSize=8.5, leading=10, alignment=1, textColor=colors.white)
    h_note = ParagraphStyle('NoteLine', parent=styles['Normal'], fontSize=8, alignment=1,
                            spaceAfter=8, textColor=colors.HexColor('#555555'))

    def sized_image(buf, max_w, max_h):
        buf.seek(0)
        iw, ih = ImageReader(buf).getSize()
        scale = min(max_w / iw, max_h / ih)
        buf.seek(0)
        return Image(buf, width=iw * scale, height=ih * scale)

    def styled_table(rows, col_widths, total_row=False, bold_last_n=1):
        tbl = Table(rows, colWidths=col_widths, repeatRows=1, hAlign='LEFT')
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#9BA7B4')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F4F6F8')]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]
        if total_row:
            first_bold = len(rows) - bold_last_n
            style += [('FONTNAME', (0, first_bold), (-1, -1), 'Helvetica-Bold'),
                      ('BACKGROUND', (0, first_bold), (-1, -1), colors.HexColor('#DCE6F1'))]
        tbl.setStyle(TableStyle(style))
        return tbl

    def status_table(df_table, headers):
        rows = [[Paragraph(h, h_cell) for h in headers]]
        for _, r in df_table.iterrows():
            rows.append([
                str(r.iloc[0]),
                f"{int(r['Raised']):,}",
                f"{int(r['Closed']):,}",
                f"{int(r['Submit for Approval']):,}",
                f"{int(r['Pending']):,}",
                f"{r['% Closure']:.2f}%"
            ])
        return styled_table(rows, [42 * mm] + [26 * mm] * 5, total_row=True)

    story = [
        Paragraph(city_name, h_city),
        Paragraph("DSP Program Status - Detailed Report", h_sub),
        Paragraph(f"Date: {_format_report_date(report_date)}", h_date),
    ]

    # --- 1. Category share of raised vs closed ---
    story.append(Paragraph("Category share of tickets", h_sec))
    pie_cells = []
    for value_col, caption in [('Raised', 'Share of tickets raised'),
                               ('Closed', 'Share of tickets closed')]:
        slice_df = cat_table[cat_table[value_col] > 0]
        if slice_df.empty:
            continue
        donut_src = pd.DataFrame({'Status': slice_df['Category'].tolist(),
                                  'Count': slice_df[value_col].tolist()})
        pie_cells.append(sized_image(_qc_chart_png('donut', donut_src, caption), 84 * mm, 70 * mm))
    if pie_cells:
        if len(pie_cells) == 1:
            pie_cells[0].hAlign = 'CENTER'
            story.append(pie_cells[0])
        else:
            # Centre the pair on the page, and each donut within its own half
            pair = Table([pie_cells], colWidths=[86 * mm, 86 * mm], hAlign='CENTER')
            pair.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(pair)
    story.append(Spacer(1, 6))

    # --- 2. Standard status tables ---
    story.append(Paragraph("Dispersed sources ticket resolution status", h_sec))
    story.append(status_table(
        _add_total_row(cat_table, 'Category'),
        ['Category', 'Tickets raised', 'Tickets closed', 'Submit for approval',
         'Tickets pending', '% closure']))
    story.append(Spacer(1, 6))

    for category, zt in zone_tables.items():
        block = [Paragraph(f"{category} Ticket status", h_sec),
                 status_table(_add_total_row(zt, 'Zone'),
                              ['Zone', 'Raised', 'Closed', 'Submit for Approval',
                               'Pending', '% Closure']),
                 Spacer(1, 6)]
        story.append(KeepTogether(block))

    # --- 3. Quality check split for resolved tickets ---
    if qc_splits:
        # Break first unless there is room for the heading AND a full block, so the
        # heading is never stranded at the foot of a page.
        story.append(CondPageBreak(125 * mm))
        story.append(Paragraph("Resolved ticket quality check by category", h_sec))
        story.append(Paragraph(f"Tickets counted: {qc_status_label}", h_note))
        for label, tidy in qc_splits.items():
            pivot = tidy.pivot_table(index='Category', columns='Status',
                                     values='Count', aggfunc='sum', fill_value=0)
            pivot['Total'] = pivot.sum(axis=1)
            correct_col = _correct_status_col(pivot.columns)
            headers = ['Category'] + [str(c) for c in pivot.columns]
            if correct_col is not None:
                headers.append('% Correct')
            rows = [[Paragraph(h, h_cell) for h in headers]]
            for cat, r in pivot.iterrows():
                row = [str(cat)] + [f"{int(v):,}" for v in r.tolist()]
                if correct_col is not None:
                    tot = int(r['Total'])
                    row.append(f"{int(r[correct_col]) / tot * 100:.1f}%" if tot else "-")
                rows.append(row)
            totals = ['Total'] + [f"{int(pivot[c].sum()):,}" for c in pivot.columns]
            if correct_col is not None:
                grand = int(pivot['Total'].sum())
                totals.append(f"{int(pivot[correct_col].sum()) / grand * 100:.1f}%" if grand else "-")
            rows.append(totals)

            bold_rows = 1
            st_slice = _short_term_slice(pivot)
            if st_slice is not None:
                st_label = ParagraphStyle('STCell2', parent=styles['Normal'], fontSize=8,
                                          leading=9.5, fontName='Helvetica-Bold')
                st_row = [Paragraph(SHORT_TERM_LABEL, st_label)] + \
                         [f"{int(st_slice[c].sum()):,}" for c in pivot.columns]
                if correct_col is not None:
                    st_tot = int(st_slice['Total'].sum())
                    st_row.append(f"{int(st_slice[correct_col].sum()) / st_tot * 100:.1f}%"
                                  if st_tot else "-")
                rows.append(st_row)
                bold_rows = 2

            n_val = len(headers) - 1
            block = [
                Paragraph(label, h_sub2),
                sized_image(_qc_chart_png('bar', tidy), 151 * mm, 64 * mm),
                styled_table(rows, [40 * mm] + [min(26, 128 / max(n_val, 1)) * mm] * n_val,
                             total_row=True, bold_last_n=bold_rows),
                Spacer(1, 6)]
            # Keep the label with its chart, then let the table follow naturally -
            # wrapping the whole block reserves more height than it needs and
            # bumps the second level onto its own page.
            story.append(KeepTogether(block[:2]))
            story.append(KeepTogether(block[2:]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

@st.cache_data(ttl=600)
def process_data(df, cat_map, surv_map):
    """The mappings are passed IN (not fetched inside) so that they form part of the
    cache key - otherwise editing a Google Sheet never invalidates the cached result
    for an already-uploaded file."""
    df = df.copy()
    df.columns = df.columns.str.strip()
    
    missing_cols = [col for col in [COL_SUBCATEGORY, COL_STATUS, COL_CREATED] if col not in df.columns]
    if missing_cols:
        st.error(f"❌ Missing critical columns in data: {', '.join(missing_cols)}")
        st.stop()
        
    # Clean and map categories (matched on normalised keys)
    df['Subcategory_Clean'] = df[COL_SUBCATEGORY].astype(str).str.strip()
    df['MainCategory'] = df[COL_SUBCATEGORY].map(norm_key).map(cat_map).fillna("Others")
    
    # Map Surveyors (Apply rationalized names, mark others as "IGNORED")
    if COL_SURVEYOR in df.columns:
        df['Raw_Surveyor'] = df[COL_SURVEYOR].astype(str).str.strip()
        exact_hit = df[COL_SURVEYOR].map(norm_key).map(surv_map)
        name_hit = df[COL_SURVEYOR].map(surveyor_name_key).map(surv_map)
        df['Rationalised_Surveyor'] = exact_hit.fillna(name_hit).fillna("IGNORED")
        
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
        "Summary Report",
        "Quality Check Status"
    ]
    
    for view in views:
        btn_type = "primary" if st.session_state.current_view == view else "secondary"
        if st.sidebar.button(view, use_container_width=True, type=btn_type):
            st.session_state.current_view = view
            st.rerun()

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Refresh mapping sheets", use_container_width=True,
                         help="Re-reads the Category and Surveyor sheets immediately instead of "
                              "waiting for the 10-minute cache to expire."):
        load_dynamic_mappings.clear()
        process_data.clear()
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

                    # --- COMPLETED vs PENDING QC ---
                    # A ticket is eligible for RESOLVED quality check only once an
                    # after-image has been uploaded, so that column defines the universe.
                    after_img_idx = None
                    for i, c in enumerate(qc_df.columns):
                        h = str(c).strip().lower()
                        if 'after' in h and ('image' in h or 'photo' in h or 'img' in h or 'pic' in h):
                            after_img_idx = i
                            break
                    if after_img_idx is None:
                        for i, c in enumerate(qc_df.columns):
                            if 'after' in str(c).strip().lower():
                                after_img_idx = i
                                break

                    total_rows = len(qc_df)
                    if after_img_idx is not None:
                        after_vals = qc_df.iloc[:, after_img_idx].astype(str).str.strip()
                        resolved_mask = after_vals.str.contains('http', case=False, na=False)
                        resolved_universe = int(resolved_mask.sum())
                    else:
                        resolved_universe = total_rows
                        st.warning("⚠️ No 'after image' column found in the QC sheet, so pending counts "
                                   "for resolved tickets are measured against every row.")

                    # --- 1. INDIVIDUAL DISTRIBUTION PIE CHARTS ---
                    st.markdown("### 📊 Overall L1 vs L2 Distribution")
                    
                    chart_configs = [
                        ("Raised Tickets (L1)", r_l1_counts, total_rows),
                        ("Raised Tickets (L2)", r_l2_counts, total_rows),
                        ("Resolved Tickets (L1)", res_l1_counts, resolved_universe),
                        ("Resolved Tickets (L2)", res_l2_counts, resolved_universe)
                    ]
                    qc_scopes_data = []
                    
                    pie_cols = st.columns(4)
                    
                    for idx, (title, df_c, universe) in enumerate(chart_configs):
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
                                pending_val = max(int(universe) - int(total_val), 0)
                                st.markdown(
                                    f"<p style='text-align: center; font-weight: bold; margin-top: -15px;'>"
                                    f"Completed: {total_val:,}</p>"
                                    f"<p style='text-align: center; color: #d08700; margin-top: -12px;'>"
                                    f"Pending QC: {pending_val:,}</p>",
                                    unsafe_allow_html=True
                                )
                                qc_scopes_data.append({'title': title, 'counts': df_c[['Status', 'Count']].copy(),
                                                       'completed': int(total_val), 'pending': pending_val,
                                                       'tidy': None})
                            else:
                                st.info("No data available.")
                                qc_scopes_data.append({'title': title, 'counts': None,
                                                       'completed': 0, 'pending': int(universe),
                                                       'tidy': None})
                        
                    st.markdown("---")
                    
                    # --- 4. CATEGORY-WISE QC DISTRIBUTION ---
                    try:
                        st.markdown("### 📂 Category-wise Quality Check Distribution")

                        # The Subcategory -> Category mapping sheet is the source of truth.
                        # Instead of trusting the QC sheet's own headers, score EVERY column
                        # against the mapping sheet's subcategory list and take the best match.
                        qc_cat_map, _ = load_dynamic_mappings()
                        if not qc_cat_map:
                            st.warning("⚠️ The Subcategory mapping sheet is empty or could not be read, "
                                       "so categories cannot be derived.")
                            raise ValueError("Subcategory mapping sheet unavailable")

                        mapping_keys = set(qc_cat_map.keys())
                        col_scores = []
                        for i in range(len(qc_df.columns)):
                            vals = qc_df.iloc[:, i].astype(str).map(norm_key)
                            col_scores.append(float(vals.isin(mapping_keys).mean()) if len(vals) else 0.0)

                        qc_cat_idx = int(max(range(len(col_scores)), key=lambda i: col_scores[i]))
                        qc_cat_col = qc_df.columns[qc_cat_idx]
                        if col_scores[qc_cat_idx] == 0:
                            st.warning("⚠️ No column in the QC sheet matches the subcategory list in the "
                                       "mapping sheet. Check that the QC sheet spells subcategories the same "
                                       "way the mapping sheet does.")

                        qc_cat = qc_df.copy()
                        raw_cat = qc_cat.iloc[:, qc_cat_idx].astype(str).str.strip()
                        rolled_up = raw_cat.map(norm_key).map(qc_cat_map)
                        match_rate = float(rolled_up.notna().mean()) if len(rolled_up) else 0.0

                        # Always roll up through the mapping sheet; anything it doesn't cover is 'Others'.
                        qc_cat['QC Category'] = rolled_up.fillna("Others")
                        st.caption(f"Categories derived from '{qc_cat_col}' via the Subcategory mapping sheet "
                                   f"({match_rate:.0%} of rows matched; the rest are counted as Others).")

                        def _not_evaluated_mask(frame, col):
                            return ~frame[col].astype(str).str.lower().str.contains('not evaluated', na=False)

                        # --- Display mode + month/year filter ---
                        qc_ticket_date = None
                        for c in qc_df.columns:
                            if 'created' in str(c).strip().lower():
                                qc_ticket_date = c
                                break
                        if qc_ticket_date is None:
                            for c in qc_df.columns:
                                if 'date' in str(c).strip().lower():
                                    qc_ticket_date = c
                                    break

                        if qc_ticket_date is not None:
                            qc_cat['_QCDate'] = pd.to_datetime(qc_cat[qc_ticket_date],
                                                               dayfirst=True, errors='coerce')
                        else:
                            qc_cat['_QCDate'] = pd.NaT

                        qc_status_col = None
                        for c in qc_df.columns:
                            if 'status' in str(c).strip().lower():
                                qc_status_col = c
                                break

                        fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 1.6])
                        with fc1:
                            qc_display_mode = st.radio(
                                "Show as", ["% within category", "Ticket counts"],
                                horizontal=True, key="qc_cat_mode"
                            )
                        qc_years = sorted(qc_cat['_QCDate'].dropna().dt.year.unique().tolist(), reverse=True)
                        with fc2:
                            qc_year_pick = st.selectbox("Year", ["All"] + [int(y) for y in qc_years],
                                                        key="qc_filter_year")
                        with fc3:
                            if qc_year_pick == "All":
                                month_pool = sorted(qc_cat['_QCDate'].dropna().dt.month.unique().tolist())
                            else:
                                month_pool = sorted(qc_cat.loc[qc_cat['_QCDate'].dt.year == qc_year_pick,
                                                               '_QCDate'].dropna().dt.month.unique().tolist())
                            qc_month_pick = st.selectbox(
                                "Month", ["All"] + [int(m) for m in month_pool],
                                format_func=lambda m: "All" if m == "All" else calendar.month_name[int(m)],
                                key="qc_filter_month"
                            )

                        with fc4:
                            res_status_pick = st.selectbox(
                                "Resolved ticket status",
                                ["Closed", "Submit for Approval", "Closed + Submit for Approval"],
                                key="qc_res_status",
                                help="Which ticket statuses count towards the RESOLVED quality check "
                                     "tables below. Raised tables are unaffected."
                            )
                        if qc_status_col is None:
                            st.warning("⚠️ No status column found in the QC sheet, so the resolved "
                                       "status filter cannot be applied.")

                        def _ticket_status_mask(frame, choice):
                            """Rows whose ticket status matches the chosen resolved scope."""
                            if qc_status_col is None or frame.empty:
                                return pd.Series(True, index=frame.index)
                            s = frame[qc_status_col].astype(str).str.strip().str.lower()
                            closed = s.str.contains('closed') | s.str.contains('complied') | s.eq('resolved')
                            sfa = s.str.contains('submit') & s.str.contains('approval')
                            if choice == 'Closed':
                                return closed
                            if choice == 'Submit for Approval':
                                return sfa
                            return closed | sfa

                        normalise = qc_display_mode.startswith("%")

                        if qc_year_pick != "All":
                            qc_cat = qc_cat[qc_cat['_QCDate'].dt.year == qc_year_pick]
                        if qc_month_pick != "All":
                            qc_cat = qc_cat[qc_cat['_QCDate'].dt.month == qc_month_pick]

                        if qc_year_pick == "All" and qc_month_pick == "All":
                            st.caption(f"Showing all {len(qc_cat):,} tickets.")
                        else:
                            period_label = " ".join(
                                ([calendar.month_name[int(qc_month_pick)]] if qc_month_pick != "All" else [])
                                + ([str(qc_year_pick)] if qc_year_pick != "All" else [])
                            )
                            st.caption(f"Filtered to {period_label} - {len(qc_cat):,} ticket(s). "
                                       "The distribution charts above cover all months.")

                        if qc_cat.empty:
                            st.info("No tickets in the selected period.")

                        qc_scopes = {
                            "Raised": [("L1 (Col R)", qc_cat, r_l1_col), ("L2 (Col S)", qc_cat, r_l2_col)],
                            "Resolved": [
                                ("L1 (Col T)",
                                 qc_cat[_not_evaluated_mask(qc_cat, res_l1_col)
                                        & _ticket_status_mask(qc_cat, res_status_pick)], res_l1_col),
                                ("L2 (Col U)",
                                 qc_cat[_not_evaluated_mask(qc_cat, res_l2_col)
                                        & _ticket_status_mask(qc_cat, res_status_pick)], res_l2_col),
                            ],
                        }

                        for scope_name, levels in qc_scopes.items():
                            heading = f"#### {'🚨' if scope_name == 'Raised' else '🏁'} {scope_name} Tickets by Category"
                            if scope_name == 'Resolved':
                                heading += f" - {res_status_pick}"
                            st.markdown(heading)
                            lvl_cols = st.columns(2)
                            for lvl_idx, (lvl_label, frame, status_col) in enumerate(levels):
                                with lvl_cols[lvl_idx]:
                                    st.markdown(f"**{lvl_label}**")
                                    tidy = (
                                        frame.dropna(subset=[status_col])
                                             .groupby(['QC Category', status_col])
                                             .size().reset_index(name='Count')
                                             .rename(columns={status_col: 'Status', 'QC Category': 'Category'})
                                    )
                                    tidy = tidy[tidy['Count'] > 0]
                                    # Hand the same frame to the PDF builder; the loop runs in the
                                    # same order as qc_scopes_data (Raised L1, L2, Resolved L1, L2).
                                    pdf_slot = (0 if scope_name == 'Raised' else 2) + lvl_idx
                                    if pdf_slot < len(qc_scopes_data):
                                        qc_scopes_data[pdf_slot]['tidy'] = tidy.copy()
                                    if tidy.empty:
                                        st.info("No data available.")
                                        continue

                                    tidy['Share %'] = (
                                        tidy['Count'] / tidy.groupby('Category')['Count'].transform('sum') * 100
                                    ).round(1)

                                    y_field = alt.Y('Share %:Q', title='% of category', stack='zero') if normalise \
                                        else alt.Y('Count:Q', title='Tickets', stack='zero')

                                    bar = alt.Chart(tidy).mark_bar().encode(
                                        x=alt.X('Category:N', title=None, axis=alt.Axis(labelAngle=0, labelLimit=0)),
                                        y=y_field,
                                        color=alt.Color('Status:N', legend=alt.Legend(
                                            orient='bottom', title=None, labelFontSize=10, labelLimit=0)),
                                        tooltip=['Category', 'Status', 'Count', 'Share %']
                                    ).properties(
                                        height=340,
                                        # leave room for y-axis numbers on the left and the
                                        # wrapped legend underneath, so neither gets clipped
                                        padding={'left': 28, 'right': 16, 'top': 10, 'bottom': 16},
                                        autosize=alt.AutoSizeParams(type='fit', contains='padding')
                                    ).configure_legend(
                                        labelLimit=0, columns=3, symbolSize=70, labelFontSize=11,
                                        orient='bottom', direction='horizontal'
                                    ).configure_axis(labelLimit=0)
                                    st.altair_chart(bar, use_container_width=True)

                                    pivot = tidy.pivot_table(index='Category', columns='Status',
                                                             values='Count', aggfunc='sum', fill_value=0)
                                    pivot['Total'] = pivot.sum(axis=1)
                                    correct_col = _correct_status_col(pivot.columns)
                                    if correct_col is not None:
                                        pivot['% Correct'] = (
                                            pivot[correct_col] / pivot['Total'].replace(0, pd.NA) * 100
                                        ).astype(float).round(1)

                                    # Sanitation + Malba are the short-term tickets; show their
                                    # combined quality under the resolved tables.
                                    if scope_name == 'Resolved':
                                        st_slice = _short_term_slice(pivot)
                                        if st_slice is not None:
                                            st_total = int(st_slice['Total'].sum())
                                            combined = {c: int(st_slice[c].sum())
                                                        for c in pivot.columns if c != '% Correct'}
                                            if correct_col is not None:
                                                combined['% Correct'] = round(
                                                    int(st_slice[correct_col].sum()) / st_total * 100, 1
                                                ) if st_total else None
                                            pivot = pd.concat(
                                                [pivot, pd.DataFrame([combined], index=[SHORT_TERM_LABEL])]
                                            )
                                    st.dataframe(
                                        pivot, use_container_width=True,
                                        column_config={"% Correct": st.column_config.NumberColumn(format="%.1f%%")}
                                    )


                        # --- Reasons, broken down by subcategory ---
                        st.markdown("---")
                        st.markdown("##### 📝 Reasons for Resolved Quality Checks by Subcategory")

                        qc_cat['QC Subcategory'] = raw_cat.replace(
                            {'': 'Blank', 'nan': 'Blank', 'None': 'Blank'}
                        )

                        def _reason_counts(frame, col, label):
                            s = frame[col].astype(str).str.strip()
                            s = s[~s.str.lower().isin(['', 'nan', 'none', 'not evaluated', '-', 'na'])]
                            out = s.value_counts().reset_index()
                            out.columns = [label, 'Count']
                            return out

                        reason_cats = sorted(qc_cat['QC Category'].unique())
                        chosen_cat = st.selectbox("Category", reason_cats, key="qc_reason_cat")
                        cat_scope = qc_cat[qc_cat['QC Category'] == chosen_cat]

                        subs_with_reasons = 0
                        for sub in sorted(cat_scope['QC Subcategory'].unique()):
                            sub_df = cat_scope[cat_scope['QC Subcategory'] == sub]
                            l1_sub = _reason_counts(sub_df, res_l1_rsn, 'L1 Reason (Col V)')
                            l2_sub = _reason_counts(sub_df, res_l2_rsn, 'L2 Reason (Col W)')
                            if l1_sub.empty and l2_sub.empty:
                                continue
                            subs_with_reasons += 1
                            st.markdown(f"**{sub}** — {len(sub_df):,} ticket(s)")
                            rc1, rc2 = st.columns(2)
                            with rc1:
                                if l1_sub.empty:
                                    st.caption("No L1 reasons recorded.")
                                else:
                                    st.dataframe(l1_sub, use_container_width=True, hide_index=True)
                            with rc2:
                                if l2_sub.empty:
                                    st.caption("No L2 reasons recorded.")
                                else:
                                    st.dataframe(l2_sub, use_container_width=True, hide_index=True)

                        if subs_with_reasons == 0:
                            st.info(f"No quality-check reasons recorded for any subcategory under {chosen_cat}.")

                        # --- PDF export of the whole QC module ---
                        st.markdown("---")
                        st.markdown("##### 📄 Download Quality Check Report")
                        qr1, qr2 = st.columns(2)
                        with qr1:
                            qc_report_date = st.date_input(
                                "Report Date", value=datetime.now().date(), key="qc_report_date"
                            )
                        with qr2:
                            qc_city_name = st.text_input(
                                "Report Heading", value="Lucknow Nagar Nigam", key="qc_city_name"
                            )
                        if qc_year_pick == "All" and qc_month_pick == "All":
                            qc_pdf_period = None
                            qc_period_slug = ""
                        else:
                            qc_pdf_period = " ".join(
                                ([calendar.month_name[int(qc_month_pick)]] if qc_month_pick != "All" else [])
                                + ([str(qc_year_pick)] if qc_year_pick != "All" else [])
                            )
                            qc_period_slug = "_" + qc_pdf_period.replace(" ", "_")
                            st.caption(f"The report will be labelled: {qc_pdf_period}")

                        try:
                            qc_pdf_bytes = build_qc_pdf(qc_scopes_data, qc_report_date, qc_city_name,
                                                        period_label=qc_pdf_period,
                                                        resolved_status_label=res_status_pick)
                            st.download_button(
                                "📄 Download QC Report (PDF)",
                                data=qc_pdf_bytes,
                                file_name=f"{qc_city_name.replace(' ', '_')}_QC_Report"
                                          f"{qc_period_slug}_{qc_report_date.strftime('%Y%m%d')}.pdf",
                                mime="application/pdf", type="primary"
                            )
                        except ImportError as imp_err:
                            st.error("⚠️ PDF export needs `reportlab` and `matplotlib`. "
                                     f"Add them to requirements.txt and redeploy. ({imp_err})")
                        except Exception as qc_pdf_err:
                            st.error(f"⚠️ Could not build the QC PDF: {qc_pdf_err}")

                    except Exception as cat_err:
                        st.error(f"⚠️ Could not build the category-wise QC breakdown: {cat_err}")

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
                    
                cat_map, surv_map = load_dynamic_mappings()
                df_processed = process_data(df_raw, cat_map, surv_map)
                
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

                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("##### 🥧 Share of Tickets Raised by Category")
                        cat_dist = df_processed['MainCategory'].value_counts().reset_index()
                        cat_dist.columns = ['Category', 'Tickets Raised']
                        total_raised = int(cat_dist['Tickets Raised'].sum())
                        if total_raised > 0:
                            cat_dist['Share %'] = (cat_dist['Tickets Raised'] / total_raised * 100).round(1)
                            cat_dist['Label'] = cat_dist['Share %'].map(lambda v: f"{v:.1f}%")

                            pie_base = alt.Chart(cat_dist).encode(
                                theta=alt.Theta("Tickets Raised:Q", stack=True),
                                color=alt.Color("Category:N",
                                                scale=alt.Scale(scheme='tableau10'),
                                                legend=alt.Legend(title="Category")),
                                tooltip=['Category', 'Tickets Raised', 'Share %']
                            )
                            cat_pie = (
                                pie_base.mark_arc(innerRadius=55, outerRadius=115)
                                + pie_base.mark_text(radius=138, size=12).encode(text="Label:N")
                            ).properties(height=320)

                            pc1, pc2 = st.columns([3, 2])
                            with pc1:
                                st.altair_chart(cat_pie, use_container_width=True)
                            with pc2:
                                st.dataframe(
                                    cat_dist[['Category', 'Tickets Raised', 'Share %']],
                                    use_container_width=True, hide_index=True,
                                    column_config={"Share %": st.column_config.NumberColumn(format="%.1f%%")}
                                )
                                st.caption(f"Based on all {total_raised:,} tickets raised, regardless of status.")

                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("##### 🥧 Share of Tickets Resolved by Category")
                        resolved_only = df_processed[df_processed['StatusBucket'].isin(RESOLVED_STATUSES)]
                        res_dist = resolved_only['MainCategory'].value_counts().reset_index()
                        res_dist.columns = ['Category', 'Tickets Resolved']
                        total_resolved = int(res_dist['Tickets Resolved'].sum())
                        if total_resolved == 0:
                            st.info("No tickets have been resolved yet, so there is nothing to split by category.")
                        else:
                            res_dist['Share %'] = (res_dist['Tickets Resolved'] / total_resolved * 100).round(1)
                            res_dist['Label'] = res_dist['Share %'].map(lambda v: f"{v:.1f}%")

                            res_pie_base = alt.Chart(res_dist).encode(
                                theta=alt.Theta("Tickets Resolved:Q", stack=True),
                                color=alt.Color("Category:N",
                                                scale=alt.Scale(scheme='tableau10'),
                                                legend=alt.Legend(title="Category")),
                                tooltip=['Category', 'Tickets Resolved', 'Share %']
                            )
                            res_pie = (
                                res_pie_base.mark_arc(innerRadius=55, outerRadius=115)
                                + res_pie_base.mark_text(radius=138, size=12).encode(text="Label:N")
                            ).properties(height=320)

                            rc1, rc2 = st.columns([3, 2])
                            with rc1:
                                st.altair_chart(res_pie, use_container_width=True)
                            with rc2:
                                # Closure rate per category, so a big slice isn't mistaken for good performance
                                res_table = res_dist[['Category', 'Tickets Resolved', 'Share %']].merge(
                                    cat_dist[['Category', 'Tickets Raised']], on='Category', how='left'
                                )
                                res_table['% Closure'] = (
                                    res_table['Tickets Resolved'] / res_table['Tickets Raised'] * 100
                                ).round(1)
                                st.dataframe(
                                    res_table[['Category', 'Tickets Resolved', 'Share %', '% Closure']],
                                    use_container_width=True, hide_index=True,
                                    column_config={
                                        "Share %": st.column_config.NumberColumn(format="%.1f%%"),
                                        "% Closure": st.column_config.NumberColumn(format="%.1f%%")
                                    }
                                )
                                st.caption(f"Based on {total_resolved:,} resolved tickets "
                                           f"({', '.join(RESOLVED_STATUSES)}).")
                    
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
                            'Raised': 'Tickets raised', 'Closed': 'Tickets closed',
                            'Submit for Approval': 'Submit for approval', 'Pending': 'Tickets pending',
                            '% Closure': '% closure'
                        })
                        st.dataframe(cat_display, use_container_width=True, hide_index=True,
                                     column_config={"% closure": st.column_config.NumberColumn(format="%.2f%%")})

                        for category, zt in zone_tables.items():
                            st.markdown(f"#### {category} Ticket status")
                            st.dataframe(_add_total_row(zt, 'Zone'), use_container_width=True, hide_index=True,
                                         column_config={"% Closure": st.column_config.NumberColumn(format="%.2f%%")})

                        st.markdown("---")
                        dl1, dl2 = st.columns(2)
                        try:
                            pdf_bytes = build_summary_pdf(cat_table, zone_tables, report_date, city_name)
                            with dl1:
                                st.download_button(
                                    "📄 Download Report (PDF)",
                                    data=pdf_bytes,
                                    file_name=f"{city_name.replace(' ', '_')}_DSP_Report_{report_date.strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    type="primary"
                                )
                            with dl2:
                                detail_status = st.selectbox(
                                    "Quality check: tickets counted",
                                    ["Closed", "Submit for Approval", "Closed + Submit for Approval"],
                                    key="detail_qc_status"
                                )
                                qc_splits = load_qc_resolved_split(cat_map, detail_status)
                                if not qc_splits:
                                    st.caption("ℹ️ Quality check data unavailable - the detailed report "
                                               "will be produced without the QC section.")
                                detailed_bytes = build_detailed_pdf(
                                    cat_table, zone_tables, report_date, city_name,
                                    qc_splits=qc_splits, qc_status_label=detail_status
                                )
                                st.download_button(
                                    "📘 Download Detailed Report (PDF)",
                                    data=detailed_bytes,
                                    file_name=f"{city_name.replace(' ', '_')}_DSP_Detailed_Report_"
                                              f"{report_date.strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf"
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

                        # Which mapped surveyors actually appear in this upload, and which don't
                        mapped_names = sorted(set(surv_map.values()))
                        present_names = sorted(set(view_df['Rationalised_Surveyor'].dropna().unique()))
                        missing_names = [n for n in mapped_names if n not in present_names]
                        unmatched_raw = sorted(
                            df_processed.loc[df_processed['Rationalised_Surveyor'] == 'IGNORED', 'Raw_Surveyor']
                            .dropna().unique()
                        ) if 'Raw_Surveyor' in df_processed.columns else []

                        st.caption(f"{len(mapped_names)} surveyor(s) in the mapping sheet • "
                                   f"{len(present_names)} with tickets in this upload")
                        if missing_names or unmatched_raw:
                            with st.expander("ℹ️ Surveyor mapping check"):
                                if missing_names:
                                    st.write("**In the sheet but no tickets in this file:** " + ", ".join(missing_names))
                                if unmatched_raw:
                                    st.write(f"**{len(unmatched_raw)} app login name(s) not found in the sheet "
                                             "(counted as IGNORED):**")
                                    st.write(", ".join(unmatched_raw[:50]))
                                    st.caption("Add any of these to column A of the Surveyor sheet to include them.")

                        if all_years:
                            sy1, sy2 = st.columns([1, 1])
                            with sy1:
                                surveyor_year = st.selectbox("Select Year for Overview", all_years, key="surv_year")
                            with sy2:
                                min_tickets = st.number_input(
                                    "Minimum tickets to appear", min_value=1, value=1, step=1, key="surv_min_tickets",
                                    help="Surveyors below this count are hidden from the overview table. "
                                         "Set to 1 to show everyone who raised at least one ticket."
                                )
                            surveyor_df = view_df[view_df[COL_CREATED].dt.year == surveyor_year]
                            if not surveyor_df.empty:
                                user_ticket_counts = surveyor_df['Rationalised_Surveyor'].value_counts()
                                top_users = user_ticket_counts[user_ticket_counts >= min_tickets].index.tolist()
                                if top_users:
                                    top_surveyor_df = surveyor_df[surveyor_df['Rationalised_Surveyor'].isin(top_users)]
                                    surveyor_pivot = pd.crosstab(index=top_surveyor_df[COL_CREATED].dt.month, columns=top_surveyor_df['Rationalised_Surveyor'], margins=True, margins_name='**TOTAL**')
                                    surveyor_pivot.index = surveyor_pivot.index.map(lambda val: calendar.month_abbr[int(val)] if str(val).isdigit() or isinstance(val, (int, float)) else val)
                                    surveyor_pivot.index.name = "Month"
                                    st.dataframe(surveyor_pivot, use_container_width=True)
                                else:
                                    st.info(f"No mapped surveyor reached {min_tickets} ticket(s) in {surveyor_year}.")
                        
                        st.markdown("---")
                        st.markdown("### 🗓️ Days Worked in a Month")
                        try:
                            st.caption("Counts the distinct dates on which each surveyor raised at least one ticket.")

                            month_periods = sorted(view_df[COL_CREATED].dropna().dt.to_period('M').unique(), reverse=True)
                            if not month_periods:
                                st.info("No dated tickets available.")
                            else:
                                dm1, dm2 = st.columns(2)
                                with dm1:
                                    dw_year = st.selectbox(
                                        "Year", sorted({p.year for p in month_periods}, reverse=True),
                                        key="surv_days_year"
                                    )
                                with dm2:
                                    year_months = [p.month for p in month_periods if p.year == dw_year]
                                    dw_month = st.selectbox(
                                        "Month", year_months,
                                        format_func=lambda m: calendar.month_name[int(m)],
                                        key="surv_days_month"
                                    )

                                dw_df = view_df[
                                    (view_df[COL_CREATED].dt.year == dw_year)
                                    & (view_df[COL_CREATED].dt.month == dw_month)
                                ].copy()

                                if dw_df.empty:
                                    st.info(f"No tickets raised in {calendar.month_name[int(dw_month)]} {dw_year}.")
                                else:
                                    days_in_month = calendar.monthrange(int(dw_year), int(dw_month))[1]
                                    dw_df['SurveyDate'] = dw_df[COL_CREATED].dt.date

                                    days_table = (
                                        dw_df.groupby('Rationalised_Surveyor')
                                             .agg(**{'Days Worked': ('SurveyDate', 'nunique'),
                                                     'Tickets Raised': ('SurveyDate', 'size')})
                                             .reset_index()
                                             .rename(columns={'Rationalised_Surveyor': 'Surveyor Name'})
                                    )
                                    days_table['Avg Tickets / Day'] = (
                                        days_table['Tickets Raised'] / days_table['Days Worked']
                                    ).round(1)
                                    days_table = days_table.sort_values(
                                        ['Days Worked', 'Tickets Raised'], ascending=False
                                    ).reset_index(drop=True)
                                    days_table.index = days_table.index + 1

                                    dk1, dk2, dk3 = st.columns(3)
                                    dk1.metric("Surveyors Active", len(days_table))
                                    dk2.metric("Tickets Raised", f"{len(dw_df):,}")
                                    dk3.metric("Days in Month", days_in_month)

                                    st.dataframe(days_table, use_container_width=True)

                                    st.download_button(
                                        "⬇️ Download (CSV)",
                                        data=days_table.to_csv(index=False).encode('utf-8-sig'),
                                        file_name=f"days_worked_{dw_year}{int(dw_month):02d}.csv",
                                        mime="text/csv",
                                        key="surv_days_dl"
                                    )

                                    dw_inactive = sorted(
                                        set(view_df['Rationalised_Surveyor'].dropna().unique())
                                        - set(dw_df['Rationalised_Surveyor'].dropna().unique())
                                    )
                                    if dw_inactive:
                                        with st.expander(f"🚫 {len(dw_inactive)} surveyor(s) raised no tickets this month"):
                                            st.write(", ".join(dw_inactive))

                        except Exception as dw_err:
                            st.error(f"⚠️ Could not build the days-worked table: {dw_err}")

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
