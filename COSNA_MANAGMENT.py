"""
COSNA School Management System
Final improved single-file application with:
- Logo on login, sidebar, and embedded in exported PDFs (landscape)
- Per-student statements and payment UI in Fee Management (atomic transactions)
- PDF + Excel download options everywhere (PDFs are landscape to avoid column collisions)
- Duplicate / near-duplicate detection for students, classes, uniform categories
- Inventory transactional integrity (atomic stock updates + checks)
- Audit log and simple audit viewer
- Role-based access (Admin, Accountant, Clerk) with simple enforcement
- Cashbook (combined incomes/expenses running balance) view, updated to two-column cash book with cash and bank
- Robust DB initialization and safe migrations
- Editing and deleting capabilities for saved information (students, classes, uniforms, finances, etc.)
- Term-based data management for finances, reports, fee management, cashbook (students/classes/uniforms cross terms)
Notes:
- Save the school badge image as "school_badge.png" in the app folder or upload it on the login page.
- This file is intended to replace the previous script. Back up your DB before running.
"""
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
from io import BytesIO
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import random
import string
import difflib
import hashlib
import os
import traceback
# ---------------------------
# Configuration
# ---------------------------
APP_TITLE = "COSNA School Management System"
DB_PATH = "cosna_school.db"
REGISTRATION_FEE = 50000.0
SIMILARITY_THRESHOLD = 0.82
LOGO_FILENAME = "school_badge.png" # place uploaded badge here
PAGE_LAYOUT = "wide"
SCHOOL_NAME = "Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana"
SCHOOL_EMAIL = "info@cosnaschool.com Or: admin@cosnaschool.com"
SCHOOL_ADDRESS = "P.O.Box 000, kiyinda mityana,"
st.set_page_config(page_title=APP_TITLE, layout=PAGE_LAYOUT, initial_sidebar_state="expanded")
st.title(APP_TITLE)
st.markdown("Students • Uniforms • Finances • Reports")
# ---------------------------
# Utilities
# ---------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
def normalize_text(s: str):
    if s is None:
        return ""
    return " ".join(s.strip().lower().split())
def similar(a: str, b: str):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()
def is_near_duplicate(candidate: str, existing_list, threshold=SIMILARITY_THRESHOLD):
    candidate_n = normalize_text(candidate)
    for ex in existing_list:
        if similar(candidate_n, ex) >= threshold:
            return True, ex
    return False, None
def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = os.urandom(16).hex()
    hashed = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}${hashed}"
def verify_password(stored: str, provided: str):
    try:
        salt, _ = stored.split('$', 1)
    except Exception:
        return False
    return hash_password(provided, salt) == stored
def generate_code(prefix="RCPT"):
    day = datetime.now().strftime("%d")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
    return f"{prefix}-{day}{random_chars}"
def generate_receipt_number(): return generate_code("RCPT")
def generate_invoice_number(): return generate_code("INV")
def generate_voucher_number(): return generate_code("VCH")
# Safe rerun helper
def safe_rerun():
    try:
        if hasattr(st, "rerun") and callable(st.rerun):
            st.rerun()
        else:
            st.session_state['_needs_refresh'] = True
            st.stop()
    except Exception:
        pass
# ---------------------------
# DB migration helpers
# ---------------------------
def table_has_column(conn, table_name, column_name):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = [r[1] for r in cur.fetchall()]
    return column_name in cols
def safe_alter_add_column(conn, table, column_def):
    col_name = column_def.split()[0]
    try:
        if not table_has_column(conn, table, col_name):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            conn.commit()
            return True
    except Exception:
        return False
    return False
# ---------------------------
# Initialize DB and seed
# ---------------------------
def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Core tables (unchanged)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT DEFAULT 'Clerk',
            full_name TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expense_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense','Income'))
        )
    ''')
    cursor.execute('CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            normalized_name TEXT,
            age INTEGER,
            enrollment_date DATE,
            class_id INTEGER,
            student_type TEXT DEFAULT 'Returning',
            registration_fee_paid INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uniform_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE,
            normalized_category TEXT,
            gender TEXT,
            is_shared INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uniforms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER UNIQUE,
            stock INTEGER DEFAULT 0,
            unit_price REAL DEFAULT 0.0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(category_id) REFERENCES uniform_categories(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE,
            voucher_number TEXT UNIQUE,
            amount REAL,
            category_id INTEGER,
            description TEXT,
            payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
            payee TEXT,
            attachment_path TEXT,
            approved_by TEXT,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(category_id) REFERENCES expense_categories(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE,
            receipt_number TEXT UNIQUE,
            amount REAL,
            source TEXT,
            category_id INTEGER,
            description TEXT,
            payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
            payer TEXT,
            student_id INTEGER,
            attachment_path TEXT,
            received_by TEXT,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(category_id) REFERENCES expense_categories(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fee_structure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER,
            term TEXT CHECK(term IN ('Term 1','Term 2','Term 3')),
            academic_year TEXT,
            tuition_fee REAL DEFAULT 0,
            uniform_fee REAL DEFAULT 0,
            activity_fee REAL DEFAULT 0,
            exam_fee REAL DEFAULT 0,
            library_fee REAL DEFAULT 0,
            other_fee REAL DEFAULT 0,
            total_fee REAL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE,
            student_id INTEGER,
            issue_date DATE,
            due_date DATE,
            academic_year TEXT,
            term TEXT,
            total_amount REAL,
            paid_amount REAL DEFAULT 0,
            balance_amount REAL,
            status TEXT CHECK(status IN ('Pending','Partially Paid','Fully Paid','Overdue')) DEFAULT 'Pending',
            notes TEXT,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            receipt_number TEXT UNIQUE,
            payment_date DATE,
            amount REAL,
            payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
            reference_number TEXT,
            received_by TEXT,
            notes TEXT,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            details TEXT,
            performed_by TEXT,
            performed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            academic_year TEXT,
            start_date DATE,
            end_date DATE,
            is_current INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    # Safe migrations (unchanged)
    safe_alter_add_column(conn, "incomes", "created_by TEXT")
    safe_alter_add_column(conn, "incomes", "received_by TEXT")
    safe_alter_add_column(conn, "incomes", "description TEXT")
    safe_alter_add_column(conn, "incomes", "category_id INTEGER")
    safe_alter_add_column(conn, "incomes", "receipt_number TEXT UNIQUE")
    safe_alter_add_column(conn, "expenses", "created_by TEXT")
    safe_alter_add_column(conn, "expenses", "approved_by TEXT")
    safe_alter_add_column(conn, "expenses", "voucher_number TEXT UNIQUE")
    safe_alter_add_column(conn, "students", "normalized_name TEXT")
    safe_alter_add_column(conn, "uniform_categories", "normalized_category TEXT")
    safe_alter_add_column(conn, "invoices", "created_by TEXT")
    safe_alter_add_column(conn, "payments", "created_by TEXT")
    safe_alter_add_column(conn, "incomes", "term_id INTEGER")
    safe_alter_add_column(conn, "expenses", "term_id INTEGER")
    safe_alter_add_column(conn, "invoices", "term_id INTEGER")
    safe_alter_add_column(conn, "payments", "term_id INTEGER")
    safe_alter_add_column(conn, "fee_structure", "term_id INTEGER")
    # Backfill normalized fields (unchanged)
    try:
        rows = conn.execute("SELECT id, category, normalized_category FROM uniform_categories").fetchall()
        for r in rows:
            if (r["normalized_category"] is None or r["normalized_category"] == "") and r["category"]:
                conn.execute("UPDATE uniform_categories SET normalized_category = ? WHERE id = ?", (normalize_text(r["category"]), r["id"]))
        conn.commit()
    except Exception:
        pass
    try:
        rows = conn.execute("SELECT id, name, normalized_name FROM students").fetchall()
        for r in rows:
            if (r["normalized_name"] is None or r["normalized_name"] == "") and r["name"]:
                conn.execute("UPDATE students SET normalized_name = ? WHERE id = ?", (normalize_text(r["name"]), r["id"]))
        conn.commit()
    except Exception:
        pass
    # Ensure uniforms rows (unchanged)
    try:
        rows = conn.execute("SELECT id FROM uniform_categories").fetchall()
        for r in rows:
            cat_id = r["id"]
            u = conn.execute("SELECT id FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
            if not u:
                conn.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES (?, 0, 0.0)", (cat_id,))
        conn.commit()
    except Exception:
        pass
    # Seed default admin (unchanged)
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM users")
        if cur.fetchone()["cnt"] == 0:
            default_user = "admin"
            default_pass = "costa2026"
            conn.execute("INSERT OR IGNORE INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                         (default_user, hash_password(default_pass), "Admin", "Administrator"))
            conn.commit()
    except Exception:
        pass
    # Seed uniforms (unchanged)
    uniform_seeds = [
        ('Boys Main Shorts', 'boys', 0),
        ('Button Shirts Main', 'shared', 1),
        ('Boys Stockings', 'boys', 0),
        ('Boys Sports Shorts', 'boys', 0),
        ('Shared Sports T-Shirts', 'shared', 1),
        ('Girls Main Dresses', 'girls', 0)
    ]
    try:
        for name, gender, shared in uniform_seeds:
            nname = normalize_text(name)
            row = conn.execute("SELECT id FROM uniform_categories WHERE normalized_category = ? OR category = ?", (nname, name)).fetchone()
            if not row:
                conn.execute("INSERT INTO uniform_categories (category, normalized_category, gender, is_shared) VALUES (?, ?, ?, ?)",
                             (name, nname, gender, shared))
                conn.commit()
                cat_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
                conn.execute("INSERT OR IGNORE INTO uniforms (category_id, stock, unit_price) VALUES (?, 0, 0.0)", (cat_id,))
                conn.commit()
            else:
                cat_id = row["id"]
                u = conn.execute("SELECT id FROM uniforms WHERE category_id = ?", (cat_id,)).fetchone()
                if not u:
                    conn.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES (?, 0, 0.0)", (cat_id,))
                    conn.commit()
    except Exception:
        pass
    # Seed expense categories (add Transfer In/Out)
    expense_seeds = [
        ('Medical', 'Expense'), ('Salaries', 'Expense'), ('Utilities', 'Expense'),
        ('Maintenance', 'Expense'), ('Supplies', 'Expense'), ('Transport', 'Expense'),
        ('Events', 'Expense'), ('Tuition Fees', 'Income'), ('Registration Fees', 'Income'),
        ('Uniform Sales', 'Income'), ('Donations', 'Income'), ('Other Income', 'Income'),
        ('Transfer In', 'Income'), ('Transfer Out', 'Expense')
    ]
    try:
        for cat, cat_type in expense_seeds:
            if not conn.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,)).fetchone():
                conn.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, ?)", (cat, cat_type))
                conn.commit()
    except Exception:
        pass
    conn.close()
initialize_database()
# ---------------------------
# Audit logging
# ---------------------------
def log_action(action, details="", performed_by="system"):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO audit_log (action, details, performed_by) VALUES (?, ?, ?)", (action, details, performed_by))
        conn.commit()
        conn.close()
    except Exception:
        pass
# ---------------------------
# Authentication
# ---------------------------
def get_user(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row
if 'user' not in st.session_state:
    st.session_state.user = None
# ---------------------------
# Logo handling
# ---------------------------
def logo_exists():
    return os.path.exists(LOGO_FILENAME)
def save_uploaded_logo(uploaded_file):
    try:
        with open(LOGO_FILENAME, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return True
    except Exception:
        return False
# ---------------------------
# Export helpers (Excel & PDF landscape)
# ---------------------------
def df_to_excel_bytes(df: pd.DataFrame, sheet_name="Sheet1"):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    buf.seek(0)
    return buf
def draw_wrapped_text(c, text, x, y, width, font='Helvetica', size=8):
    c.setFont(font, size)
    lines = []
    line = []
    for word in text.split():
        if c.stringWidth(' '.join(line + [word])) <= width:
            line.append(word)
        else:
            lines.append(' '.join(line))
            line = [word]
    lines.append(' '.join(line))
    for l in lines:
        c.drawString(x, y, l)
        y -= size + 1 # tighter spacing
    return y
def dataframe_to_pdf_bytes_landscape(df: pd.DataFrame, title="Report", logo_path=None):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)
    # Draw logo if available
    y_top = height - 30
    title_x = 40
    draw_h = 0
    if logo_path and os.path.exists(logo_path):
        try:
            img = ImageReader(logo_path)
            img_w, img_h = img.getSize()
            max_w = 100
            scale = min(max_w / img_w, 1.0)
            draw_w = img_w * scale
            draw_h = img_h * scale
            c.drawImage(img, 40, y_top - draw_h, width=draw_w, height=draw_h, mask='auto')
            title_x = 40 + draw_w + 10
        except Exception:
            title_x = 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(title_x, y_top, SCHOOL_NAME)
    c.setFont("Helvetica", 10)
    c.drawString(title_x, y_top - 15, SCHOOL_EMAIL)
    c.drawString(title_x, y_top - 30, SCHOOL_ADDRESS)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(title_x, y_top - 50, title)
    y = y_top - draw_h - 70
    cols = list(df.columns)
    usable_width = width - 80
    col_width = usable_width / max(1, len(cols))
    # Header
    for i, col in enumerate(cols):
        c.drawString(40 + i * col_width, y, str(col))
    y -= 12
    # Rows
    for _, row in df.iterrows():
        if y < 40:
            c.showPage()
            y = height - 40
        row_y = y
        for i, col in enumerate(cols):
            value = row[col]
            if isinstance(value, (int, float)):
                if 'amount' in col.lower() or 'fee' in col.lower() or 'balance' in col.lower():
                    text = f"{value:,.0f}"
                else:
                    text = str(value)
            else:
                text = str(value)
            temp_y = draw_wrapped_text(c, text, 40 + i * col_width, row_y, col_width - 10)
            y = min(y, temp_y - 12) # adjust for next row
        y -= 12 # extra row spacing if needed
    # Footer
    c.setFont("Helvetica", 7)
    c.drawString(40, 20, f"Generated: {datetime.now().isoformat()} • {APP_TITLE}")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf
def download_options(df: pd.DataFrame, filename_base="report", title="Report"):
    col1, col2 = st.columns([1,1])
    with col1:
        excel_buf = df_to_excel_bytes(df)
        st.download_button("Download Excel", excel_buf, f"{filename_base}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with col2:
        pdf_buf = dataframe_to_pdf_bytes_landscape(df, title=title, logo_path=LOGO_FILENAME if logo_exists() else None)
        st.download_button("Download PDF (Landscape)", pdf_buf, f"{filename_base}.pdf", "application/pdf")
# ---------------------------
# Role-based access helper
# ---------------------------
def require_role(allowed_roles):
    user = st.session_state.get('user')
    if not user:
        st.error("Not logged in")
        st.stop()
    if user.get('role') not in allowed_roles:
        st.error("You do not have permission to access this section")
        st.stop()
# ---------------------------
# Term management helpers
# ---------------------------
def get_current_term_id():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM terms WHERE is_current = 1")
    row = cur.fetchone()
    conn.close()
    return row['id'] if row else None
def get_all_terms():
    conn = get_db_connection()
    df = pd.read_sql("SELECT id, name, academic_year, start_date, end_date, is_current FROM terms ORDER BY start_date DESC", conn)
    conn.close()
    return df
def is_term_current(term_id):
    if not term_id:
        return False
    conn = get_db_connection()
    row = conn.execute("SELECT is_current FROM terms WHERE id = ?", (term_id,)).fetchone()
    conn.close()
    return row and row['is_current'] == 1
# ---------------------------
# Login page (isolated)
# ---------------------------
def show_login_page():
    st.markdown("### Login")
    col1, col2 = st.columns([1,2])
    with col1:
        if logo_exists():
            try:
                st.image(LOGO_FILENAME, width=160)
            except Exception:
                pass
        else:
            st.info("Upload school badge (optional) to display on login and reports")
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            uploaded_logo = st.file_uploader("Upload School Badge (PNG/JPG) — optional", type=["png","jpg","jpeg"])
            submit = st.form_submit_button("Login")
            if submit:
                if uploaded_logo is not None:
                    save_uploaded_logo(uploaded_logo)
                if not username or not password:
                    st.error("Enter username and password")
                else:
                    user = get_user(username)
                    if user and verify_password(user["password_hash"], password):
                        st.session_state.user = {
                            "id": user["id"],
                            "username": user["username"],
                            "role": user["role"] if user["role"] else "Clerk",
                            "full_name": user["full_name"] if user["full_name"] else user["username"]
                        }
                        log_action("login", f"user {username} logged in", username)
                        safe_rerun()
                    else:
                        st.error("Invalid credentials")
# If not logged in, show only login page
if not st.session_state.user:
    show_login_page()
    st.stop()
# ---------------------------
# Sidebar after login
# ---------------------------
with st.sidebar:
    if logo_exists():
        try:
            st.image(LOGO_FILENAME, width=140)
        except Exception:
            pass
    user_safe = st.session_state.get('user') or {}
    st.markdown(f"**User:** {user_safe.get('full_name') or user_safe.get('username')}")
    st.markdown(f"**Role:** {user_safe.get('role') or 'Clerk'}")
    if st.button("Logout"):
        uname = user_safe.get('username', 'unknown')
        log_action("logout", f"user {uname} logged out", uname)
        st.session_state.user = None
        safe_rerun()
    st.markdown("---")
    st.subheader("Term")
    if 'term_id' not in st.session_state:
        current_id = get_current_term_id()
        st.session_state['term_id'] = current_id
    terms_df = get_all_terms()
    if terms_df.empty:
        st.info("No terms. Create in Terms Management.")
    else:
        display_terms = terms_df.apply(lambda row: f"{row['name']} ({row['academic_year']})", axis=1).tolist()
        if st.session_state['term_id'] in terms_df['id'].values.to_list():
            current_row = terms_df[terms_df['id'] == st.session_state['term_id']].iloc[0]
            current_display = f"{current_row['name']} ({current_row['academic_year']})"
            selected_index = display_terms.index(current_display) if current_display in display_terms else 0
        else:
            selected_index = 0
        selected_display = st.selectbox("Select Term", display_terms, index=selected_index)
        selected_name, selected_year = selected_display.rsplit(' (', 1)
        selected_name = selected_name.strip()
        selected_year = selected_year.replace(')', '').strip()
        st.session_state['term_id'] = terms_df[(terms_df['name'] == selected_name) & (terms_df['academic_year'] == selected_year)]['id'].iloc[0]
# ---------------------------
# Main navigation
# ---------------------------
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report", "Fee Management", "Cashbook", "Audit Log", "Terms Management"])
# Get term filter
term_id = st.session_state.get('term_id')
if term_id:
    term_filter = " AND term_id = ? "
    params = (term_id,)
else:
    term_filter = ""
    params = ()
# ---------------------------
# Dashboard
# ---------------------------
if page == "Dashboard":
    conn = get_db_connection()
    st.header("📊 Financial Overview")
    col1, col2, col3, col4 = st.columns(4)
    try:
        total_income = conn.execute(f"SELECT COALESCE(SUM(amount),0) as s FROM incomes WHERE 1=1 {term_filter}", params).fetchone()["s"] or 0
    except Exception:
        total_income = 0
    col1.metric("Total Income", f"USh {total_income:,.0f}")
    try:
        total_expenses = conn.execute(f"SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE 1=1 {term_filter}", params).fetchone()["s"] or 0
    except Exception:
        total_expenses = 0
    col2.metric("Total Expenses", f"USh {total_expenses:,.0f}")
    net_balance = total_income - total_expenses
    col3.metric("Net Balance", f"USh {net_balance:,.0f}", delta=f"USh {net_balance:,.0f}")
    try:
        outstanding_fees = conn.execute(f"SELECT COALESCE(SUM(balance_amount),0) as s FROM invoices WHERE status IN ('Pending','Partially Paid') {term_filter}", params).fetchone()["s"] or 0
    except Exception:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")
    colA, colB = st.columns(2)
    with colA:
        st.subheader("Recent Income (Last 5)")
        try:
            df_inc = pd.read_sql(f"SELECT date as Date, receipt_number as 'Receipt No', amount as Amount, source as Source, payment_method as 'Payment Method', payer as Payer, description as Description FROM incomes WHERE 1=1 {term_filter} ORDER BY date DESC LIMIT 5", conn, params=params)
            if df_inc.empty:
                st.info("No income records yet")
            else:
                st.dataframe(df_inc, use_container_width=True)
        except Exception:
            st.info("No income records yet or error loading incomes")
    with colB:
        st.subheader("Recent Expenses (Last 5)")
        try:
            df_exp = pd.read_sql(f"""
                SELECT e.date as Date, e.voucher_number as 'Voucher No', e.amount as Amount, ec.name as Category, e.payment_method as 'Payment Method', e.payee as Payee, e.description as Description
                FROM expenses e
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                WHERE 1=1 {term_filter}
                ORDER BY e.date DESC LIMIT 5
            """, conn, params=params)
            if df_exp.empty:
                st.info("No expense records yet")
            else:
                st.dataframe(df_exp, use_container_width=True)
        except Exception:
            st.info("No expense records yet or error loading expenses")
    st.subheader("Monthly Financial Summary (Last 12 months)")
    try:
        df_monthly = pd.read_sql(f"""
            SELECT strftime('%Y-%m', date) as Month, SUM(amount) as 'Total Amount', 'Income' as Type
            FROM incomes
            WHERE 1=1 {term_filter}
            GROUP BY strftime('%Y-%m', date)
            UNION ALL
            SELECT strftime('%Y-%m', date) as Month, SUM(amount) as 'Total Amount', 'Expense' as Type
            FROM expenses
            WHERE 1=1 {term_filter}
            GROUP BY strftime('%Y-%m', date)
            ORDER BY Month DESC
            LIMIT 24
        """, conn, params=params*2)
        if df_monthly.empty:
            st.info("No monthly data available")
        else:
            df_pivot = df_monthly.pivot_table(index='Month', columns='Type', values='Total Amount', aggfunc='sum').fillna(0)
            df_pivot['Net Balance'] = df_pivot.get('Income', 0) - df_pivot.get('Expense', 0)
            st.dataframe(df_pivot, use_container_width=True)
            download_options(df_pivot.reset_index(), filename_base="monthly_financial_summary", title="Monthly Financial Summary")
    except Exception:
        st.info("No monthly data available")
    conn.close()
# ---------------------------
# Students
# ---------------------------
elif page == "Students":
    st.header("Students")
    tab_view, tab_add, tab_edit, tab_delete, tab_fees = st.tabs(["View & Export", "Add Student", "Edit Student", "Delete Student", "Student Fees"])
    # View & Export
    with tab_view:
        conn = get_db_connection()
        try:
            classes = ["All Classes"] + [r["name"] for r in conn.execute("SELECT name FROM classes ORDER BY name").fetchall()]
        except Exception:
            classes = ["All Classes"]
        selected_class = st.selectbox("Filter by Class", classes)
        student_types = ["All Types", "New", "Returning"]
        selected_type = st.selectbox("Filter by Student Type", student_types)
        try:
            query = "SELECT s.id as ID, s.name as Name, s.age as Age, s.enrollment_date as 'Enrollment Date', c.name AS 'Class Name', s.student_type as 'Student Type', s.registration_fee_paid as 'Registration Fee Paid' FROM students s LEFT JOIN classes c ON s.class_id = c.id"
            conditions = []
            q_params = []
            if selected_class != "All Classes":
                conditions.append("c.name = ?")
                q_params.append(selected_class)
            if selected_type != "All Types":
                conditions.append("s.student_type = ?")
                q_params.append(selected_type)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            df = pd.read_sql_query(query, conn, params=q_params)
            if df.empty:
                st.info("No students found")
            else:
                st.dataframe(df, use_container_width=True)
                download_options(df, filename_base="students", title="Students Report")
        except Exception:
            st.info("No student records yet or error loading data")
        conn.close()
    # Add Student
    with tab_add:
        st.subheader("Add Student")
        conn = get_db_connection()
        with st.expander("➕ Add a new class (if not in list)", expanded=False):
            new_class_name = st.text_input("New Class Name", key="new_class_input", placeholder="e.g. P.4, S.1 Gold, Baby")
            if st.button("Create Class", key="create_class_btn", use_container_width=True):
                if not new_class_name.strip():
                    st.error("Enter class name")
                else:
                    try:
                        exists = conn.execute("SELECT 1 FROM classes WHERE LOWER(name) = LOWER(?)", (new_class_name.strip(),)).fetchone()
                        if exists:
                            st.error(f"Class '{new_class_name}' already exists")
                        else:
                            cur = conn.cursor()
                            cur.execute("INSERT INTO classes (name) VALUES (?)", (new_class_name.strip(),))
                            conn.commit()
                            st.success(f"Class '{new_class_name}' created")
                            log_action("add_class", f"Created class: {new_class_name}", st.session_state.user['username'])
                            safe_rerun()
                    except sqlite3.IntegrityError:
                        st.error("Class name already exists (case-sensitive conflict")
                    except Exception as e:
                        st.error(f"Error creating class: {str(e)}")
        with st.form("add_student_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Full Name")
                age = st.number_input("Age", min_value=3, max_value=30, value=10)
                enroll_date = st.date_input("Enrollment Date", value=date.today())
            with col2:
                cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                cls_options = cls_df["name"].tolist() if not cls_df.empty else []
                cls_name = st.selectbox("Class", ["-- No class --"] + cls_options)
                cls_id = None
                if cls_name != "-- No class --":
                    cls_id = int(cls_df[cls_df["name"] == cls_name]["id"].iloc[0])
                student_type = st.radio("Student Type", ["New", "Returning"], horizontal=True)
                if student_type == "New":
                    st.info(f"Registration Fee: USh {REGISTRATION_FEE:,.0f} (Mandatory for new students)")
            submitted = st.form_submit_button("Add Student")
        if submitted:
            if not name or cls_id is None:
                st.error("Provide student name and class")
            else:
                term_id = st.session_state.get('term_id')
                if student_type == "New" and (not term_id or not is_term_current(term_id)):
                    st.error("Can only register new students in the current active term. Please select the current term in the sidebar.")
                else:
                    try:
                        existing = [r["normalized_name"] for r in conn.execute("SELECT normalized_name FROM students").fetchall() if r["normalized_name"]]
                    except Exception:
                        existing = []
                    nname = normalize_text(name)
                    dup, match = is_near_duplicate(nname, existing)
                    if dup:
                        st.warning(f"A similar student already exists: '{match}'. Please verify before adding.")
                    else:
                        try:
                            cur = conn.cursor()
                            cur.execute("""
                                INSERT INTO students (name, normalized_name, age, enrollment_date, class_id, student_type, registration_fee_paid)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (name.strip(), nname, int(age), enroll_date.isoformat(), cls_id, student_type, 1 if student_type == "New" else 0))
                            conn.commit()
                            student_id = cur.lastrowid
                            if student_type == "New":
                                try:
                                    cat_row = conn.execute("SELECT id FROM expense_categories WHERE name = 'Registration Fees'").fetchone()
                                    cat_id = cat_row["id"] if cat_row else None
                                    cur.execute("""
                                        INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by, created_by, term_id)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (enroll_date.isoformat(), generate_receipt_number(), REGISTRATION_FEE, "Registration Fees",
                                          cat_id, f"Registration fee for {name}", "Cash", name, st.session_state.user['username'], st.session_state.user['username'], term_id))
                                except Exception:
                                    cur.execute("INSERT INTO incomes (date, amount, source, created_by, term_id) VALUES (?, ?, ?, ?, ?)",
                                                (enroll_date.isoformat(), REGISTRATION_FEE, f"Registration fee for {name}", st.session_state.user['username'], term_id))
                                conn.commit()
                            st.success("Student added successfully")
                            log_action("add_student", f"Added student {name} (ID: {student_id})", st.session_state.user['username'])
                        except Exception as e:
                            st.error(f"Error adding student: {e}")
        conn.close()
    # Edit Student
    with tab_edit:
        st.subheader("Edit Student")
        conn = get_db_connection()
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        if students.empty:
            st.info("No students available to edit")
        else:
            selected = st.selectbox("Select Student to Edit", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))
            student_row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
            with st.form("edit_student_form"):
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("Full Name", value=student_row['name'])
                    age = st.number_input("Age", min_value=3, max_value=30, value=student_row['age'])
                    enroll_date = st.date_input("Enrollment Date", value=date.fromisoformat(student_row['enrollment_date']))
                with col2:
                    cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                    cls_options = cls_df["name"].tolist() if not cls_df.empty else []
                    current_cls_name = conn.execute("SELECT name FROM classes WHERE id = ?", (student_row['class_id'],)).fetchone()[0] if student_row['class_id'] else "-- No class --"
                    cls_name = st.selectbox("Class", cls_options, index=cls_options.index(current_cls_name) if current_cls_name in cls_options else 0)
                    cls_id = int(cls_df[cls_df["name"] == cls_name]["id"].iloc[0]) if cls_name in cls_options else None
                    student_type = st.radio("Student Type", ["New", "Returning"], index=0 if student_row['student_type'] == "New" else 1)
                submitted = st.form_submit_button("Update Student")
            if submitted:
                if not name:
                    st.error("Provide student name")
                else:
                    try:
                        existing = [r["normalized_name"] for r in conn.execute("SELECT normalized_name FROM students WHERE id != ?", (student_id,)).fetchall() if r["normalized_name"]]
                        nname = normalize_text(name)
                        dup, match = is_near_duplicate(nname, existing)
                        if dup:
                            st.warning(f"A similar student already exists: '{match}'. Please verify before updating.")
                        else:
                            cur = conn.cursor()
                            cur.execute("""
                                UPDATE students SET name = ?, normalized_name = ?, age = ?, enrollment_date = ?, class_id = ?, student_type = ?
                                WHERE id = ?
                            """, (name.strip(), nname, int(age), enroll_date.isoformat(), cls_id, student_type, student_id))
                            conn.commit()
                            st.success("Student updated successfully")
                            log_action("edit_student", f"Updated student {name} (ID: {student_id})", st.session_state.user['username'])
                            safe_rerun()
                    except Exception as e:
                        st.error(f"Error updating student: {e}")
        conn.close()
    # Delete Student
    with tab_delete:
        require_role(["Admin"])
        st.subheader("Delete Student")
        st.warning("Deleting a student may affect related records like invoices and payments. Proceed with caution.")
        conn = get_db_connection()
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        if students.empty:
            st.info("No students available to delete")
        else:
            selected = st.selectbox("Select Student to Delete", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1), key="select_student_to_delete")
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))
            if st.checkbox("Confirm deletion", key=f"confirm_delete_student_{student_id}"):
                if st.button("Delete Student", key=f"delete_student_btn_{student_id}"):
                    try:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM students WHERE id = ?", (student_id,))
                        conn.commit()
                        st.success("Student deleted successfully")
                        log_action("delete_student", f"Deleted student ID: {student_id}", st.session_state.user['username'])
                        safe_rerun()
                    except sqlite3.IntegrityError:
                        st.error("Cannot delete student due to related records (e.g., invoices, payments). Delete those first.")
                    except Exception as e:
                        st.error(f"Error deleting student: {e}")
        conn.close()
    # Student Fees
    with tab_fees:
        conn = get_db_connection()
        st.subheader("Outstanding Fees Breakdown")
        total_outstanding = conn.execute(
            f"SELECT COALESCE(SUM(balance_amount), 0) FROM invoices WHERE status IN ('Pending', 'Partially Paid') {term_filter}", params
        ).fetchone()[0]
        st.metric("Total Outstanding Fees", f"USh {total_outstanding:,.0f}")
        class_df = pd.read_sql(f"""
            SELECT c.name as 'Class Name', COALESCE(SUM(i.balance_amount), 0) as 'Class Outstanding'
            FROM invoices i
            JOIN students s ON i.student_id = s.id
            JOIN classes c ON s.class_id = c.id
            WHERE i.status IN ('Pending', 'Partially Paid') {term_filter}
            GROUP BY c.name
            ORDER BY 'Class Outstanding' DESC
        """, conn, params=params)
        if class_df.empty:
            st.info("No outstanding fees at the moment.")
        else:
            st.dataframe(class_df, hide_index=True, use_container_width=True)
            download_options(class_df, filename_base="outstanding_by_class", title="Outstanding Fees by Class")
            selected_class = st.selectbox(
                "Select Class to View Student Details",
                [""] + class_df['Class Name'].tolist(),
                format_func=lambda x: "— Select a class —" if x == "" else x
            )
            if selected_class:
                student_df = pd.read_sql(f"""
                    SELECT s.name as Name, COALESCE(SUM(i.balance_amount), 0) as Outstanding
                    FROM invoices i
                    JOIN students s ON i.student_id = s.id
                    JOIN classes c ON s.class_id = c.id
                    WHERE c.name = ? AND i.status IN ('Pending', 'Partially Paid') {term_filter}
                    GROUP BY s.name
                    ORDER BY Outstanding DESC
                """, conn, params=(selected_class,) + params)
                if student_df.empty:
                    st.info(f"No students with outstanding balances in {selected_class}")
                else:
                    st.subheader(f"Students with Outstanding Balances in {selected_class}")
                    st.dataframe(student_df, hide_index=True, use_container_width=True)
                    download_options(
                        student_df,
                        filename_base=f"outstanding_students_{selected_class.replace(' ', '_')}",
                        title=f"Outstanding Students in {selected_class}"
                    )
        st.subheader("Student Fee Management")
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        if students.empty:
            st.info("No students available")
        else:
            selected = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
            student_name = selected.split(" - ")[0]
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))
            try:
                invoices = pd.read_sql(f"SELECT * FROM invoices WHERE student_id = ? {term_filter} ORDER BY issue_date DESC", conn, params=(student_id,) + params)
            except Exception:
                invoices = pd.DataFrame()
            if invoices.empty:
                st.info("No invoices for this student")
            else:
                display_invoices = invoices[['invoice_number', 'issue_date', 'due_date', 'total_amount', 'paid_amount', 'balance_amount', 'status', 'notes']].rename(columns={
                    'invoice_number': 'Invoice No',
                    'issue_date': 'Issue Date',
                    'due_date': 'Due Date',
                    'total_amount': 'Total Amount',
                    'paid_amount': 'Paid Amount',
                    'balance_amount': 'Balance Amount',
                    'status': 'Status',
                    'notes': 'Notes'
                })
                st.dataframe(display_invoices, use_container_width=True)
                st.subheader("Payment History")
                try:
                    payments = pd.read_sql(f"SELECT p.id, p.payment_date, p.amount, p.payment_method, p.receipt_number, p.reference_number, p.notes FROM payments p JOIN invoices i ON p.invoice_id = i.id WHERE i.student_id = ? {term_filter} ORDER BY p.payment_date DESC", conn, params=(student_id,) + params)
                    if payments.empty:
                        st.info("No payments recorded for this student")
                    else:
                        display_payments = payments.rename(columns={
                            'payment_date': 'Payment Date',
                            'amount': 'Amount',
                            'payment_method': 'Payment Method',
                            'receipt_number': 'Receipt No',
                            'reference_number': 'Reference No',
                            'notes': 'Notes'
                        })
                        st.dataframe(display_payments, use_container_width=True)
                        download_options(display_payments, filename_base=f"payments_student_{student_id}", title=f"Payments for {student_name}")
                except Exception:
                    st.info("No payments or error loading payments")
                st.subheader("Pay Outstanding Invoice")
                outstanding_invoices = invoices[invoices['status'].isin(['Pending','Partially Paid'])]
                if outstanding_invoices.empty:
                    st.info("No outstanding invoices to pay")
                else:
                    chosen_inv = st.selectbox("Select Invoice to Pay", outstanding_invoices['invoice_number'].tolist())
                    inv_row = outstanding_invoices[outstanding_invoices['invoice_number'] == chosen_inv].iloc[0]
                    inv_id = int(inv_row['id'])
                    inv_balance = float(inv_row['balance_amount'] if inv_row['balance_amount'] is not None else inv_row['total_amount'])
                    st.write(f"Invoice {chosen_inv} — Balance: USh {inv_balance:,.0f}")
                    with st.form("pay_invoice_form"):
                        pay_date = st.date_input("Payment Date", date.today())
                        pay_amount = st.number_input("Amount (USh)", min_value=0.0, max_value=float(inv_balance), value=float(inv_balance), step=100.0)
                        pay_method = st.selectbox("Payment Method", ["Cash","Bank Transfer","Mobile Money","Cheque"])
                        pay_ref = st.text_input("Reference Number")
                        pay_receipt = st.text_input("Receipt Number", value=generate_receipt_number())
                        pay_notes = st.text_area("Notes")
                        submit_pay = st.form_submit_button("Record Payment")
                    if submit_pay:
                        term_id = st.session_state.get('term_id')
                        if not term_id or not is_term_current(term_id):
                            st.error("Can only record payments in the current active term. Please select the current term in the sidebar.")
                        elif pay_amount <= 0:
                            st.error("Enter a positive amount")
                        elif pay_amount > inv_balance + 0.0001:
                            st.error("Amount exceeds invoice balance")
                        else:
                            try:
                                cur = conn.cursor()
                                conn.isolation_level = None
                                cur.execute("BEGIN")
                                inv_check = cur.execute("SELECT paid_amount, balance_amount, total_amount FROM invoices WHERE id = ?", (inv_id,)).fetchone()
                                if not inv_check:
                                    cur.execute("ROLLBACK")
                                    st.error("Invoice not found")
                                else:
                                    current_balance = inv_check[1] if inv_check[1] is not None else inv_check[2]
                                    if pay_amount > current_balance + 0.0001:
                                        cur.execute("ROLLBACK")
                                        st.error("Payment exceeds current balance. Refresh and try again.")
                                    else:
                                        new_paid = (inv_check[0] or 0) + pay_amount
                                        new_balance = current_balance - pay_amount
                                        new_status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid'
                                        cur.execute("UPDATE invoices SET paid_amount = ?, balance_amount = ?, status = ? WHERE id = ?", (new_paid, new_balance, new_status, inv_id))
                                        cur.execute("""
                                            INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, payment_method, reference_number, received_by, notes, created_by, term_id)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (inv_id, pay_receipt, pay_date.isoformat(), pay_amount, pay_method, pay_ref, st.session_state.user['username'], pay_notes, st.session_state.user['username'], term_id))
                                        cat_row = conn.execute("SELECT id FROM expense_categories WHERE name = 'Tuition Fees'").fetchone()
                                        cat_id = cat_row["id"] if cat_row else None
                                        cur.execute("""
                                            INSERT INTO incomes (date, receipt_number, amount, source, category_id, payment_method, payer, received_by, created_by, description, term_id)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (pay_date.isoformat(), pay_receipt, pay_amount, "Tuition Fees", cat_id, pay_method, student_name, st.session_state.user['username'], st.session_state.user['username'], pay_notes, term_id))
                                        cur.execute("COMMIT")
                                        st.success("Payment recorded and invoice updated")
                                        log_action("pay_invoice", f"Payment {pay_amount} for invoice {chosen_inv}", st.session_state.user['username'])
                                        safe_rerun()
                            except Exception as e:
                                try:
                                    cur.execute("ROLLBACK")
                                except Exception:
                                    pass
                                st.error(f"Error recording payment: {e}")
        conn.close()
# ---------------------------
# Uniforms
# ---------------------------
elif page == "Uniforms":
    st.header("Uniforms – Inventory & Sales")
    conn = get_db_connection()
    def get_inventory_df():
        return pd.read_sql_query("""
            SELECT uc.id as cat_id, uc.category as Category, uc.gender as Gender, uc.is_shared as 'Is Shared', u.stock as Stock, u.unit_price as 'Unit Price'
            FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id
            ORDER BY uc.gender, uc.category
        """, conn)
    tab_view, tab_update, tab_sale, tab_manage, tab_edit_cat, tab_delete_cat = st.tabs(["View Inventory", "Update Stock/Price", "Record Sale", "Add Category", "Edit Category", "Delete Category"])
    with tab_view:
        inventory_df = get_inventory_df()
        if inventory_df.empty:
            st.info("No inventory records")
        else:
            display_df = inventory_df.copy()
            display_df['Unit Price'] = display_df['Unit Price'].apply(lambda x: f"USh {x:,.0f}")
            st.dataframe(display_df, use_container_width=True)
            total_stock = inventory_df['Stock'].sum()
            total_value = (inventory_df['Stock'] * inventory_df['Unit Price']).sum()
            col1, col2 = st.columns(2)
            col1.metric("Total Items in Stock", f"{int(total_stock):,}")
            col2.metric("Total Inventory Value", f"USh {total_value:,.0f}")
            download_options(inventory_df, filename_base="uniform_inventory", title="Uniform Inventory Report")
    with tab_update:
        st.subheader("Update Stock & Price")
        categories_df = pd.read_sql("SELECT uc.id, uc.category, u.stock, u.unit_price FROM uniform_categories uc JOIN uniforms u ON uc.id = u.category_id ORDER BY uc.category", conn)
        if categories_df.empty:
            st.info("No uniform categories available.")
        else:
            selected_category = st.selectbox("Select Category", categories_df["category"].tolist(), key="update_category_select")
            cat_row = categories_df[categories_df["category"] == selected_category].iloc[0]
            cat_id = int(cat_row['id'])
            current_stock = int(cat_row['stock'])
            current_price = float(cat_row['unit_price'])
            st.write(f"**Current Stock:** {current_stock} items")
            st.write(f"**Current Price:** USh {current_price:,.0f}")
            with st.form("update_stock_form"):
                add_stock = st.number_input("Add to Stock (enter 0 to leave unchanged)", min_value=0, value=0, step=1)
                set_stock = st.number_input("Set Stock Level (leave as current to skip)", min_value=0, value=current_stock, step=1)
                new_price = st.number_input("Set Unit Price (USh)", min_value=0.0, value=current_price, step=100.0)
                submit_update = st.form_submit_button("Update")
            if submit_update:
                try:
                    cur = conn.cursor()
                    conn.isolation_level = None
                    cur.execute("BEGIN")
                    final_stock = int(set_stock) if set_stock != current_stock else current_stock + int(add_stock)
                    cur.execute("UPDATE uniforms SET stock = ?, unit_price = ? WHERE category_id = ?", (final_stock, float(new_price), cat_id))
                    cur.execute("COMMIT")
                    st.success("Inventory updated")
                    log_action("update_uniform", f"Updated category {selected_category}: stock={final_stock}, price={new_price}", st.session_state.user['username'])
                    safe_rerun()
                except Exception as e:
                    try:
                        cur.execute("ROLLBACK")
                    except Exception:
                        pass
                    st.error(f"Error updating inventory: {e}")
    with tab_sale:
        st.subheader("Record Uniform Sale")
        inv_df = pd.read_sql("""
            SELECT uc.id as cat_id, uc.category, u.stock, u.unit_price
            FROM uniform_categories uc JOIN uniforms u ON uc.id = u.category_id
            ORDER BY uc.category
        """, conn)
        if inv_df.empty:
            st.info("No uniform items available")
        else:
            selected = st.selectbox("Select Item", inv_df["category"].tolist())
            row = inv_df[inv_df["category"] == selected].iloc[0]
            cat_id = int(row['cat_id'])
            available_stock = int(row['stock'])
            unit_price = float(row['unit_price'])
            st.write(f"Available: {available_stock} | Unit Price: USh {unit_price:,.0f}")
            qty = st.number_input("Quantity to sell", min_value=1, max_value=max(1, available_stock), value=1, step=1)
            buyer = st.text_input("Buyer Name (optional)")
            payment_method = st.selectbox("Payment Method", ["Cash","Bank Transfer","Mobile Money","Cheque"])
            receipt_no = st.text_input("Receipt Number", value=generate_receipt_number())
            notes = st.text_area("Notes")
            if st.button("Record Sale"):
                term_id = st.session_state.get('term_id')
                if not term_id or not is_term_current(term_id):
                    st.error("Can only record sales in the current active term. Please select the current term in the sidebar.")
                elif qty <= 0:
                    st.error("Enter a valid quantity")
                elif qty > available_stock:
                    st.error("Insufficient stock")
                else:
                    try:
                        cur = conn.cursor()
                        conn.isolation_level = None
                        cur.execute("BEGIN")
                        cur.execute("SELECT stock FROM uniforms WHERE category_id = ?", (cat_id,))
                        current = cur.fetchone()[0]
                        if current < qty:
                            cur.execute("ROLLBACK")
                            st.error("Stock changed; insufficient stock now")
                        else:
                            new_stock = current - qty
                            cur.execute("UPDATE uniforms SET stock = ? WHERE category_id = ?", (new_stock, cat_id))
                            amount = qty * unit_price
                            cat_row = conn.execute("SELECT id FROM expense_categories WHERE name = 'Uniform Sales'").fetchone()
                            cat_id_income = cat_row["id"] if cat_row else None
                            cur.execute("""
                                INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by, created_by, term_id)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (date.today().isoformat(), receipt_no, amount, "Uniform Sales", cat_id_income, f"Sale of {qty} x {selected} - {notes}", payment_method, buyer or "Walk-in", st.session_state.user['username'], st.session_state.user['username'], term_id))
                            cur.execute("COMMIT")
                            st.success(f"Sale recorded. New stock: {new_stock}")
                            log_action("uniform_sale", f"Sold {qty} of {selected} for USh {amount}", st.session_state.user['username'])
                            safe_rerun()
                    except Exception as e:
                        try:
                            cur.execute("ROLLBACK")
                        except Exception:
                            pass
                        st.error(f"Error recording sale: {e}")
    with tab_manage:
        st.subheader("Add Uniform Category")
        with st.form("add_uniform_category"):
            cat_name = st.text_input("Category Name")
            gender = st.selectbox("Gender", ["boys","girls","shared"])
            is_shared = 1 if gender == "shared" else 0
            initial_stock = st.number_input("Initial Stock", min_value=0, value=0, step=1)
            unit_price = st.number_input("Unit Price (USh)", min_value=0.0, value=0.0, step=100.0)
            add_cat = st.form_submit_button("Add Category")
        if add_cat:
            if not cat_name:
                st.error("Enter category name")
            else:
                try:
                    existing = [r["normalized_category"] for r in conn.execute("SELECT normalized_category FROM uniform_categories").fetchall() if r["normalized_category"]]
                except Exception:
                    existing = []
                ncat = normalize_text(cat_name)
                dup, match = is_near_duplicate(ncat, existing)
                if dup:
                    st.warning(f"A similar uniform category exists: '{match}'")
                else:
                    try:
                        cur = conn.cursor()
                        cur.execute("INSERT INTO uniform_categories (category, normalized_category, gender, is_shared) VALUES (?, ?, ?, ?)",
                                    (cat_name.strip(), ncat, gender, is_shared))
                        conn.commit()
                        cat_id = cur.lastrowid
                        cur.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES (?, ?, ?)", (cat_id, int(initial_stock), float(unit_price)))
                        conn.commit()
                        st.success("Uniform category added")
                        log_action("add_uniform_category", f"Added {cat_name} stock={initial_stock} price={unit_price}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error adding category: {e}")
    with tab_edit_cat:
        st.subheader("Edit Uniform Category")
        categories_df = pd.read_sql("SELECT id, category, gender, is_shared FROM uniform_categories ORDER BY category", conn)
        if categories_df.empty:
            st.info("No categories to edit")
        else:
            selected_category = st.selectbox("Select Category to Edit", categories_df["category"].tolist())
            cat_row = categories_df[categories_df["category"] == selected_category].iloc[0]
            cat_id = int(cat_row['id'])
            with st.form("edit_uniform_category"):
                new_cat_name = st.text_input("Category Name", value=cat_row['category'])
                new_gender = st.selectbox("Gender", ["boys","girls","shared"], index=["boys","girls","shared"].index(cat_row['gender']))
                new_is_shared = 1 if new_gender == "shared" else 0
                submit_edit = st.form_submit_button("Update Category")
            if submit_edit:
                if not new_cat_name:
                    st.error("Enter category name")
                else:
                    try:
                        existing = [r["normalized_category"] for r in conn.execute("SELECT normalized_category FROM uniform_categories WHERE id != ?", (cat_id,)).fetchall() if r["normalized_category"]]
                        ncat = normalize_text(new_cat_name)
                        dup, match = is_near_duplicate(ncat, existing)
                        if dup:
                            st.warning(f"A similar category exists: '{match}'")
                        else:
                            cur = conn.cursor()
                            cur.execute("""
                                UPDATE uniform_categories SET category = ?, normalized_category = ?, gender = ?, is_shared = ?
                                WHERE id = ?
                            """, (new_cat_name.strip(), ncat, new_gender, new_is_shared, cat_id))
                            conn.commit()
                            st.success("Category updated")
                            log_action("edit_uniform_category", f"Updated category ID {cat_id} to {new_cat_name}", st.session_state.user['username'])
                            safe_rerun()
                    except Exception as e:
                        st.error(f"Error updating category: {e}")
    with tab_delete_cat:
        require_role(["Admin"])
        st.subheader("Delete Uniform Category")
        st.warning("Deleting a category will also delete its inventory record. Proceed with caution.")
        categories_df = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        if categories_df.empty:
            st.info("No categories to delete")
        else:
            selected_category = st.selectbox("Select Category to Delete", categories_df["category"].tolist(), key="select_uniform_cat_to_delete")
            cat_id = int(categories_df[categories_df["category"] == selected_category]["id"].iloc[0])
            if st.checkbox("Confirm deletion", key=f"confirm_delete_uniform_cat_{cat_id}"):
                if st.button("Delete Category", key=f"delete_uniform_cat_btn_{cat_id}"):
                    try:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM uniforms WHERE category_id = ?", (cat_id,))
                        cur.execute("DELETE FROM uniform_categories WHERE id = ?", (cat_id,))
                        conn.commit()
                        st.success("Category deleted successfully")
                        log_action("delete_uniform_category", f"Deleted category ID: {cat_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error deleting category: {e}")
    conn.close()
# ---------------------------
# Finances
# ---------------------------
elif page == "Finances":
    user_role = st.session_state.user.get('role')
    st.header("Finances")
    tab_inc, tab_exp, tab_reports, tab_edit_inc, tab_delete_inc, tab_edit_exp, tab_delete_exp, tab_transfer = st.tabs(["Record Income", "Record Expense", "View Transactions", "Edit Income", "Delete Income", "Edit Expense", "Delete Expense", "Record Transfer"])
    with tab_inc:
        st.subheader("Record Income")
        if user_role not in ("Admin", "Accountant"):
            st.info("You do not have permission to record incomes. View-only access.")
        else:
            conn = get_db_connection()
            categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
            with st.form("record_income_form"):
                date_in = st.date_input("Date", date.today())
                receipt_no = st.text_input("Receipt Number", value=generate_receipt_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
                source = st.text_input("Source (e.g., Tuition Fees, Donations)")
                category = st.selectbox("Category", ["-- Select --"] + categories["name"].tolist())
                payment_method = st.selectbox("Payment Method", ["Cash","Bank Transfer","Mobile Money","Cheque"])
                payer = st.text_input("Payer")
                description = st.text_area("Description")
                submit_income = st.form_submit_button("Record Income")
            if submit_income:
                term_id = st.session_state.get('term_id')
                if not term_id or not is_term_current(term_id):
                    st.error("Can only record incomes in the current active term. Please select the current term in the sidebar.")
                elif amount <= 0:
                    st.error("Enter a positive amount")
                else:
                    try:
                        cur = conn.cursor()
                        cat_id = None
                        if category != "-- Select --":
                            cat_row = categories[categories["name"] == category]
                            if not cat_row.empty:
                                cat_id = int(cat_row["id"].iloc[0])
                        cur.execute("""
                            INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by, created_by, term_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (date_in.isoformat(), receipt_no, amount, source, cat_id, description, payment_method, payer, st.session_state.user['username'], st.session_state.user['username'], term_id))
                        conn.commit()
                        st.success("Income recorded")
                        log_action("record_income", f"Income {amount} from {source}", st.session_state.user['username'])
                        safe_rerun()
                    except sqlite3.IntegrityError:
                        st.error("Receipt number already exists")
                    except Exception as e:
                        st.error(f"Error recording income: {e}")
            conn.close()
    with tab_exp:
        st.subheader("Record Expense")
        if user_role not in ("Admin", "Accountant"):
            st.info("You do not have permission to record expenses. View-only access.")
        else:
            conn = get_db_connection()
            categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name", conn)
            with st.form("record_expense_form"):
                date_e = st.date_input("Date", date.today())
                voucher_no = st.text_input("Voucher Number", value=generate_voucher_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
                category = st.selectbox("Category", ["-- Select --"] + categories["name"].tolist())
                payment_method = st.selectbox("Payment Method", ["Cash","Bank Transfer","Mobile Money","Cheque"])
                payee = st.text_input("Payee")
                description = st.text_area("Description")
                approved_by = st.text_input("Approved By")
                submit_expense = st.form_submit_button("Record Expense")
            if submit_expense:
                term_id = st.session_state.get('term_id')
                if not term_id or not is_term_current(term_id):
                    st.error("Can only record expenses in the current active term. Please select the current term in the sidebar.")
                elif amount <= 0:
                    st.error("Enter a positive amount")
                else:
                    try:
                        cur = conn.cursor()
                        cat_id = None
                        if category != "-- Select --":
                            cat_row = categories[categories["name"] == category]
                            if not cat_row.empty:
                                cat_id = int(cat_row["id"].iloc[0])
                        cur.execute("""
                            INSERT INTO expenses (date, voucher_number, amount, category_id, description, payment_method, payee, approved_by, created_by, term_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (date_e.isoformat(), voucher_no, amount, cat_id, description, payment_method, payee, approved_by, st.session_state.user['username'], term_id))
                        conn.commit()
                        st.success("Expense recorded")
                        log_action("record_expense", f"Expense {amount} voucher {voucher_no}", st.session_state.user['username'])
                        safe_rerun()
                    except sqlite3.IntegrityError:
                        st.error("Voucher number already exists")
                    except Exception as e:
                        st.error(f"Error recording expense: {e}")
            conn.close()
    with tab_reports:
        st.subheader("Transactions")
        conn = get_db_connection()
        df_inc = pd.read_sql(f"""
            SELECT i.date as Date, i.receipt_number as 'Receipt No', i.amount as Amount, i.source as Source, ec.name as Category, i.description as Description, i.payment_method as 'Payment Method', i.payer as Payer, i.received_by as 'Received By', i.created_by as 'Created By'
            FROM incomes i LEFT JOIN expense_categories ec ON i.category_id = ec.id
            WHERE 1=1 {term_filter}
            ORDER BY i.date DESC LIMIT 500
        """, conn, params=params)
        df_exp = pd.read_sql(f"""
            SELECT e.date as Date, e.voucher_number as 'Voucher No', e.amount as Amount, ec.name as Category, e.description as Description, e.payment_method as 'Payment Method', e.payee as Payee, e.approved_by as 'Approved By', e.created_by as 'Created By'
            FROM expenses e LEFT JOIN expense_categories ec ON e.category_id = ec.id
            WHERE 1=1 {term_filter}
            ORDER BY e.date DESC LIMIT 500
        """, conn, params=params)
        st.write("Recent Incomes")
        if df_inc.empty:
            st.info("No incomes recorded")
        else:
            st.dataframe(df_inc, use_container_width=True)
            download_options(df_inc, filename_base="recent_incomes", title="Recent Incomes")
        st.write("Recent Expenses")
        if df_exp.empty:
            st.info("No expenses recorded")
        else:
            st.dataframe(df_exp, use_container_width=True)
            download_options(df_exp, filename_base="recent_expenses", title="Recent Expenses")
        conn.close()
    with tab_edit_inc:
        st.subheader("Edit Income")
        if user_role not in ("Admin", "Accountant"):
            st.info("Permission denied")
        else:
            conn = get_db_connection()
            incomes = pd.read_sql(f"SELECT id, receipt_number, date, amount, source, category_id, description, payment_method, payer FROM incomes WHERE 1=1 {term_filter} ORDER BY date DESC", conn, params=params)
            if incomes.empty:
                st.info("No incomes to edit")
            else:
                selected_inc = st.selectbox("Select Income by Receipt Number", incomes['receipt_number'].tolist(), key="select_income_to_edit")
                inc_row = incomes[incomes['receipt_number'] == selected_inc].iloc[0]
                inc_id = int(inc_row['id'])
                categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
                with st.form("edit_income_form"):
                    date_in = st.date_input("Date", value=date.fromisoformat(inc_row['date']))
                    receipt_no = st.text_input("Receipt Number", value=inc_row['receipt_number'])
                    amount = st.number_input("Amount (USh)", min_value=0.0, value=float(inc_row['amount']), step=100.0)
                    source = st.text_input("Source", value=inc_row['source'])
                    current_cat_id = inc_row['category_id']
                    current_cat_name = categories[categories['id'] == current_cat_id]['name'].iloc[0] if current_cat_id else "-- Select --"
                    category = st.selectbox("Category", ["-- Select --"] + categories["name"].tolist(), index= categories["name"].tolist().index(current_cat_name) if current_cat_name != "-- Select --" else 0)
                    payment_method = st.selectbox("Payment Method", ["Cash","Bank Transfer","Mobile Money","Cheque"], index=["Cash","Bank Transfer","Mobile Money","Cheque"].index(inc_row['payment_method']))
                    payer = st.text_input("Payer", value=inc_row['payer'])
                    description = st.text_area("Description", value=inc_row['description'])
                    submit_edit = st.form_submit_button("Update Income")
                if submit_edit:
                    if amount <= 0:
                        st.error("Enter a positive amount")
                    else:
                        try:
                            cur = conn.cursor()
                            cat_id = None
                            if category != "-- Select --":
                                cat_row = categories[categories["name"] == category]
                                if not cat_row.empty:
                                    cat_id = int(cat_row["id"].iloc[0])
                            cur.execute("""
                                UPDATE incomes SET date = ?, receipt_number = ?, amount = ?, source = ?, category_id = ?, description = ?, payment_method = ?, payer = ?
                                WHERE id = ?
                            """, (date_in.isoformat(), receipt_no, amount, source, cat_id, description, payment_method, payer, inc_id))
                            conn.commit()
                            st.success("Income updated")
                            log_action("edit_income", f"Updated income ID {inc_id} receipt {receipt_no}", st.session_state.user['username'])
                            safe_rerun()
                        except sqlite3.IntegrityError:
                            st.error("Receipt number already exists")
                        except Exception as e:
                            st.error(f"Error updating income: {e}")
            conn.close()
    with tab_delete_inc:
        require_role(["Admin"])
        st.subheader("Delete Income")
        st.warning("Deleting an income record is permanent. Proceed with caution.")
        conn = get_db_connection()
        incomes = pd.read_sql(f"SELECT id, receipt_number FROM incomes WHERE 1=1 {term_filter} ORDER BY date DESC", conn, params=params)
        if incomes.empty:
            st.info("No incomes to delete")
        else:
            selected_inc = st.selectbox("Select Income to Delete by Receipt Number", incomes['receipt_number'].tolist(), key="select_income_to_delete")
            inc_id = int(incomes[incomes['receipt_number'] == selected_inc]['id'].iloc[0])
            if st.checkbox("Confirm deletion", key=f"confirm_delete_income_{inc_id}"):
                if st.button("Delete Income", key=f"delete_income_btn_{inc_id}"):
                    try:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM incomes WHERE id = ?", (inc_id,))
                        conn.commit()
                        st.success("Income deleted successfully")
                        log_action("delete_income", f"Deleted income ID: {inc_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error deleting income: {e}")
        conn.close()
    with tab_edit_exp:
        st.subheader("Edit Expense")
        if user_role not in ("Admin", "Accountant"):
            st.info("Permission denied")
        else:
            conn = get_db_connection()
            expenses = pd.read_sql(f"SELECT id, voucher_number, date, amount, category_id, description, payment_method, payee, approved_by FROM expenses WHERE 1=1 {term_filter} ORDER BY date DESC", conn, params=params)
            if expenses.empty:
                st.info("No expenses to edit")
            else:
                selected_exp = st.selectbox("Select Expense by Voucher Number", expenses['voucher_number'].tolist(), key="select_expense_to_edit")
                exp_row = expenses[expenses['voucher_number'] == selected_exp].iloc[0]
                exp_id = int(exp_row['id'])
                categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name", conn)
                with st.form("edit_expense_form"):
                    date_e = st.date_input("Date", value=date.fromisoformat(exp_row['date']))
                    voucher_no = st.text_input("Voucher Number", value=exp_row['voucher_number'])
                    amount = st.number_input("Amount (USh)", min_value=0.0, value=float(exp_row['amount']), step=100.0)
                    current_cat_id = exp_row['category_id']
                    current_cat_name = categories[categories['id'] == current_cat_id]['name'].iloc[0] if current_cat_id else "-- Select --"
                    category = st.selectbox("Category", ["-- Select --"] + categories["name"].tolist(), index= categories["name"].tolist().index(current_cat_name) if current_cat_name != "-- Select --" else 0)
                    payment_method = st.selectbox("Payment Method", ["Cash","Bank Transfer","Mobile Money","Cheque"], index=["Cash","Bank Transfer","Mobile Money","Cheque"].index(exp_row['payment_method']))
                    payee = st.text_input("Payee", value=exp_row['payee'])
                    description = st.text_area("Description", value=exp_row['description'])
                    approved_by = st.text_input("Approved By", value=exp_row['approved_by'])
                    submit_edit = st.form_submit_button("Update Expense")
                if submit_edit:
                    if amount <= 0:
                        st.error("Enter a positive amount")
                    else:
                        try:
                            cur = conn.cursor()
                            cat_id = None
                            if category != "-- Select --":
                                cat_row = categories[categories["name"] == category]
                                if not cat_row.empty:
                                    cat_id = int(cat_row["id"].iloc[0])
                            cur.execute("""
                                UPDATE expenses SET date = ?, voucher_number = ?, amount = ?, category_id = ?, description = ?, payment_method = ?, payee = ?, approved_by = ?
                                WHERE id = ?
                            """, (date_e.isoformat(), voucher_no, amount, cat_id, description, payment_method, payee, approved_by, exp_id))
                            conn.commit()
                            st.success("Expense updated")
                            log_action("edit_expense", f"Updated expense ID {exp_id} voucher {voucher_no}", st.session_state.user['username'])
                            safe_rerun()
                        except sqlite3.IntegrityError:
                            st.error("Voucher number already exists")
                        except Exception as e:
                            st.error(f"Error updating expense: {e}")
            conn.close()
    with tab_delete_exp:
        require_role(["Admin"])
        st.subheader("Delete Expense")
        st.warning("Deleting an expense record is permanent. Proceed with caution.")
        conn = get_db_connection()
        expenses = pd.read_sql(f"SELECT id, voucher_number FROM expenses WHERE 1=1 {term_filter} ORDER BY date DESC", conn, params=params)
        if expenses.empty:
            st.info("No expenses to delete")
        else:
            selected_exp = st.selectbox("Select Expense to Delete by Voucher Number", expenses['voucher_number'].tolist(), key="select_expense_to_delete")
            exp_id = int(expenses[expenses['voucher_number'] == selected_exp]['id'].iloc[0])
            if st.checkbox("Confirm deletion", key=f"confirm_delete_expense_{exp_id}"):
                if st.button("Delete Expense", key=f"delete_expense_btn_{exp_id}"):
                    try:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM expenses WHERE id = ?", (exp_id,))
                        conn.commit()
                        st.success("Expense deleted successfully")
                        log_action("delete_expense", f"Deleted expense ID: {exp_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error deleting expense: {e}")
        conn.close()
    with tab_transfer:
        st.subheader("Record Contra Entry (Transfer between Cash and Bank)")
        if user_role not in ("Admin", "Accountant"):
            st.info("Permission denied")
        else:
            conn = get_db_connection()
            with st.form("record_transfer_form"):
                transfer_date = st.date_input("Date", date.today())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
                from_account = st.selectbox("From Account", ["Cash", "Bank"])
                to_account = st.selectbox("To Account", ["Bank", "Cash"])
                description = st.text_area("Description")
                submit_transfer = st.form_submit_button("Record Transfer")
            if submit_transfer:
                term_id = st.session_state.get('term_id')
                if not term_id or not is_term_current(term_id):
                    st.error("Can only record transfers in the current active term. Please select the current term in the sidebar.")
                elif amount <= 0:
                    st.error("Enter a positive amount")
                elif from_account == to_account:
                    st.error("From and To accounts must be different")
                else:
                    try:
                        cur = conn.cursor()
                        # Get category IDs
                        transfer_out_cat = conn.execute("SELECT id FROM expense_categories WHERE name = 'Transfer Out'").fetchone()
                        transfer_out_id = transfer_out_cat["id"] if transfer_out_cat else None
                        transfer_in_cat = conn.execute("SELECT id FROM expense_categories WHERE name = 'Transfer In'").fetchone()
                        transfer_in_id = transfer_in_cat["id"] if transfer_in_cat else None
                        # Expense from 'From'
                        voucher_no = generate_voucher_number()
                        pay_method_from = 'Cash' if from_account == "Cash" else 'Bank Transfer'
                        cur.execute("""
                            INSERT INTO expenses (date, voucher_number, amount, category_id, description, payment_method, payee, approved_by, created_by, term_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (transfer_date.isoformat(), voucher_no, amount, transfer_out_id, f"Transfer to {to_account}: {description}", pay_method_from, to_account, st.session_state.user['username'], st.session_state.user['username'], term_id))
                        # Income to 'To'
                        receipt_no = generate_receipt_number()
                        pay_method_to = 'Bank Transfer' if to_account == "Bank" else 'Cash'
                        cur.execute("""
                            INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by, created_by, term_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (transfer_date.isoformat(), receipt_no, amount, f"Transfer from {from_account}", transfer_in_id, f"Transfer from {from_account}: {description}", pay_method_to, from_account, st.session_state.user['username'], st.session_state.user['username'], term_id))
                        conn.commit()
                        st.success("Transfer recorded successfully")
                        log_action("record_transfer", f"Transfer {amount} from {from_account} to {to_account}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error recording transfer: {e}")
            conn.close()
# ---------------------------
# Financial Report
# ---------------------------
elif page == "Financial Report":
    st.header("Financial Reports & Exports")
    conn = get_db_connection()
    st.subheader("Generate Report")
    report_type = st.selectbox("Report Type", ["Income vs Expense (date range)", "By Category", "Outstanding Invoices", "Student Payment Summary"])
    start_date = st.date_input("Start Date", date.today().replace(day=1))
    end_date = st.date_input("End Date", date.today())
    if start_date > end_date:
        st.error("Start date must be before end date")
    else:
        date_filter = " AND date BETWEEN ? AND ? "
        date_params = (start_date.isoformat(), end_date.isoformat())
        full_params = date_params + params
        if st.button("Generate Report"):
            try:
                if report_type == "Income vs Expense (date range)":
                    df_inc = pd.read_sql(f"SELECT date as Date, receipt_number as 'Receipt No', amount as Amount, source as Source, payment_method as 'Payment Method', payer as Payer, description as Description FROM incomes WHERE 1=1 {date_filter} {term_filter} ORDER BY date", conn, params=full_params)
                    df_exp = pd.read_sql(f"SELECT date as Date, voucher_number as 'Voucher No', amount as Amount, description as Description, payment_method as 'Payment Method', payee as Payee FROM expenses WHERE 1=1 {date_filter} {term_filter} ORDER BY date", conn, params=full_params)
                    if df_inc.empty and df_exp.empty:
                        st.info("No transactions in this range")
                    else:
                        st.subheader("Incomes")
                        st.dataframe(df_inc, use_container_width=True)
                        st.subheader("Expenses")
                        st.dataframe(df_exp, use_container_width=True)
                        total_inc = df_inc['Amount'].sum() if not df_inc.empty else 0
                        total_exp = df_exp['Amount'].sum() if not df_exp.empty else 0
                        st.metric("Total Income", f"USh {total_inc:,.0f}")
                        st.metric("Total Expense", f"USh {total_exp:,.0f}")
                        combined = pd.concat([df_inc.assign(Type='Income'), df_exp.assign(Type='Expense')], sort=False).fillna('')
                        download_options(combined, filename_base=f"financial_{start_date}_{end_date}", title="Income vs Expense Report")
                elif report_type == "By Category":
                    cat = st.selectbox("Category Type", ["Income", "Expense"])
                    df = pd.read_sql(f"""
                        SELECT ec.name as Category, SUM(COALESCE(i.amount,0)) as 'Total Income', SUM(COALESCE(e.amount,0)) as 'Total Expense'
                        FROM expense_categories ec
                        LEFT JOIN incomes i ON i.category_id = ec.id AND i.date BETWEEN ? AND ? {term_filter.replace('?', '')}
                        LEFT JOIN expenses e ON e.category_id = ec.id AND e.date BETWEEN ? AND ? {term_filter.replace('?', '')}
                        WHERE ec.category_type = ?
                        GROUP BY ec.name
                    """, conn, params=(start_date.isoformat(), end_date.isoformat()) + params + (start_date.isoformat(), end_date.isoformat()) + params + (cat,))
                    if df.empty:
                        st.info("No data for selected category type")
                    else:
                        st.dataframe(df, use_container_width=True)
                        download_options(df, filename_base=f"by_category_{cat}", title=f"By Category - {cat}")
                elif report_type == "Outstanding Invoices":
                    df = pd.read_sql(f"SELECT invoice_number as 'Invoice No', student_id as 'Student ID', issue_date as 'Issue Date', due_date as 'Due Date', total_amount as 'Total Amount', paid_amount as 'Paid Amount', balance_amount as 'Balance Amount', status as Status, notes as Notes FROM invoices WHERE status IN ('Pending','Partially Paid') {term_filter} ORDER BY due_date", conn, params=params)
                    if df.empty:
                        st.info("No outstanding invoices")
                    else:
                        st.dataframe(df, use_container_width=True)
                        download_options(df, filename_base="outstanding_invoices", title="Outstanding Invoices")
                else: # Student Payment Summary
                    students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
                    if students.empty:
                        st.info("No students available")
                    else:
                        sel = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1))
                        sid = int(sel.split("(ID: ")[1].replace(")", ""))
                        df_inv = pd.read_sql(f"SELECT invoice_number as 'Invoice No', academic_year as 'Academic Year', term as Term, total_amount as 'Total Amount', paid_amount as 'Paid Amount', balance_amount as 'Balance Amount', status as Status, issue_date as 'Issue Date', notes as Notes FROM invoices WHERE student_id = ? {term_filter} ORDER BY issue_date DESC", conn, params=(sid,) + params)
                        df_pay = pd.read_sql(f"SELECT payment_date as 'Payment Date', amount as Amount, payment_method as 'Payment Method', receipt_number as 'Receipt No', reference_number as 'Reference No', notes as Notes FROM payments p JOIN invoices i ON p.invoice_id = i.id WHERE i.student_id = ? {term_filter} ORDER BY payment_date DESC", conn, params=(sid,) + params)
                        st.subheader("Invoices")
                        if df_inv.empty:
                            st.info("No invoices for this student")
                        else:
                            st.dataframe(df_inv, use_container_width=True)
                            download_options(df_inv, filename_base=f"student_{sid}_invoices", title=f"Invoices for Student {sid}")
                        st.subheader("Payments")
                        if df_pay.empty:
                            st.info("No payments for this student")
                        else:
                            st.dataframe(df_pay, use_container_width=True)
                            download_options(df_pay, filename_base=f"student_{sid}_payments", title=f"Payments for Student {sid}")
            except Exception as e:
                st.error(f"Error generating report: {e}")
    conn.close()
# ---------------------------
# Cashbook - Updated to two-column
# ---------------------------
elif page == "Cashbook":
    require_role(["Admin", "Accountant", "Clerk"])
    st.header("Two-Column Cashbook (Cash and Bank)")
    conn = get_db_connection()
    start_date = st.date_input("Start Date", date.today().replace(day=1))
    end_date = st.date_input("End Date", date.today())
    if start_date > end_date:
        st.error("Start date must be before end date")
    else:
        try:
            # Fetch incomes and expenses with payment_method
            df_inc = pd.read_sql(f"""
                SELECT date as tx_date, source || ' from ' || payer as description, amount, payment_method, 'Income' as type
                FROM incomes WHERE date BETWEEN ? AND ? {term_filter}
            """, conn, params=(start_date.isoformat(), end_date.isoformat()) + params)
            df_exp = pd.read_sql(f"""
                SELECT date as tx_date, description || ' to ' || payee as description, amount, payment_method, 'Expense' as type
                FROM expenses WHERE date BETWEEN ? AND ? {term_filter}
            """, conn, params=(start_date.isoformat(), end_date.isoformat()) + params)
            combined = pd.concat([df_inc, df_exp], ignore_index=True)
            if combined.empty:
                st.info("No transactions in this range")
            else:
                combined['tx_date'] = pd.to_datetime(combined['tx_date'])
                combined = combined.sort_values('tx_date').reset_index(drop=True)
                # Classify to cash or bank
                combined['cash_dr'] = 0.0
                combined['cash_cr'] = 0.0
                combined['bank_dr'] = 0.0
                combined['bank_cr'] = 0.0
                for idx, row in combined.iterrows():
                    is_cash = row['payment_method'] in ['Cash', 'Mobile Money']
                    if row['type'] == 'Income':
                        if is_cash:
                            combined.at[idx, 'cash_dr'] = row['amount']
                        else:
                            combined.at[idx, 'bank_dr'] = row['amount']
                    else: # Expense
                        if is_cash:
                            combined.at[idx, 'cash_cr'] = row['amount']
                        else:
                            combined.at[idx, 'bank_cr'] = row['amount']
                # Running balances
                combined['cash_balance'] = (combined['cash_dr'] - combined['cash_cr']).cumsum()
                combined['bank_balance'] = (combined['bank_dr'] - combined['bank_cr']).cumsum()
                display = combined[['tx_date', 'description', 'cash_dr', 'bank_dr', 'cash_cr', 'bank_cr', 'cash_balance', 'bank_balance']].copy()
                display = display.rename(columns={
                    'tx_date': 'Date',
                    'description': 'Description',
                    'cash_dr': 'Cash In',
                    'cash_cr': 'Cash Out',
                    'bank_dr': 'Bank In',
                    'bank_cr': 'Bank Out',
                    'cash_balance': 'Cash Balance',
                    'bank_balance': 'Bank Balance'
                })
                display['Date'] = display['Date'].dt.date
                st.dataframe(display, use_container_width=True)
                download_options(display, filename_base=f"cashbook_{start_date}_{end_date}", title="Two-Column Cashbook")
        except Exception as e:
            st.error(f"Error loading cashbook: {e}")
    conn.close()
# ---------------------------
# Audit Log viewer
# ---------------------------
elif page == "Audit Log":
    require_role(["Admin", "Accountant"])
    st.header("Audit Log")
    conn = get_db_connection()
    try:
        df_audit = pd.read_sql("SELECT performed_at as 'Performed At', performed_by as 'Performed By', action as Action, details as Details FROM audit_log ORDER BY performed_at DESC LIMIT 500", conn)
        if df_audit.empty:
            st.info("No audit entries")
        else:
            st.dataframe(df_audit, use_container_width=True)
            download_options(df_audit, filename_base="audit_log", title="Audit Log")
    except Exception as e:
        st.error(f"Error loading audit log: {e}")
    conn.close()
# ---------------------------
# Fee Management
# ---------------------------
elif page == "Fee Management":
    require_role(["Admin", "Accountant"])
    st.header("Fee Management")
    tab_define, tab_generate, tab_edit_inv, tab_delete_inv = st.tabs(["Define Fee Structure", "Generate Invoice", "Edit Invoice", "Delete Invoice"])
    with tab_define:
        st.subheader("Define Fee Structure")
        conn = get_db_connection()
        classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
        term_id = st.session_state.get('term_id')
        if not term_id:
            st.info("Select a term in the sidebar to define fee structure.")
        else:
            term_row = conn.execute("SELECT name, academic_year FROM terms WHERE id = ?", (term_id,)).fetchone()
            if not term_row:
                st.error("Invalid term selected.")
            else:
                term = term_row['name']
                academic_year = term_row['academic_year']
                st.info(f"Defining fee structure for: **{term} - {academic_year}**")

                with st.form("fee_structure_form"):
                    cls_name = st.selectbox("Class", classes["name"].tolist())
                    cls_id = int(classes[classes["name"] == cls_name]["id"].iloc[0]) if not classes.empty else None

                    tuition_fee = st.number_input("Tuition Fee (USh)", min_value=0.0, value=0.0, step=1000.0)
                    uniform_fee = st.number_input("Uniform Fee (USh)", min_value=0.0, value=0.0, step=500.0)
                    activity_fee = st.number_input("Activity Fee (USh)", min_value=0.0, value=0.0, step=500.0)
                    exam_fee    = st.number_input("Exam Fee (USh)", min_value=0.0, value=0.0, step=500.0)
                    library_fee = st.number_input("Library Fee (USh)", min_value=0.0, value=0.0, step=500.0)
                    other_fee   = st.number_input("Other Fee (USh)", min_value=0.0, value=0.0, step=500.0)

                    create_fee = st.form_submit_button("Save / Update Fee Structure")

                if create_fee:
                    if cls_id is None:
                        st.error("Please select a valid class.")
                    else:
                        try:
                            total_fee = (
                                tuition_fee + uniform_fee + activity_fee +
                                exam_fee + library_fee + other_fee
                            )

                            cur = conn.cursor()

                            # Check if already exists for this class + term + year
                            existing = cur.execute("""
                                SELECT id FROM fee_structure 
                                WHERE class_id = ? AND term = ? AND academic_year = ?
                            """, (cls_id, term, academic_year)).fetchone()

                            if existing:
                                cur.execute("""
                                    UPDATE fee_structure
                                    SET 
                                        tuition_fee = ?, uniform_fee = ?, activity_fee = ?,
                                        exam_fee = ?, library_fee = ?, other_fee = ?,
                                        total_fee = ?, term_id = ?, created_at = CURRENT_TIMESTAMP
                                    WHERE id = ?
                                """, (
                                    tuition_fee, uniform_fee, activity_fee,
                                    exam_fee, library_fee, other_fee,
                                    total_fee, term_id, existing[0]
                                ))
                                action = "updated"
                            else:
                                cur.execute("""
                                    INSERT INTO fee_structure (
                                        class_id, term, academic_year,
                                        tuition_fee, uniform_fee, activity_fee,
                                        exam_fee, library_fee, other_fee, total_fee,
                                        term_id
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    cls_id, term, academic_year,
                                    tuition_fee, uniform_fee, activity_fee,
                                    exam_fee, library_fee, other_fee, total_fee,
                                    term_id
                                ))
                                action = "created"

                            conn.commit()

                            st.success(f"Fee structure for {cls_name} ({term} {academic_year}) {action} successfully. Total: USh {total_fee:,.0f}")
                            log_action(
                                f"{action}_fee_structure",
                                f"{cls_name} - {term} {academic_year} - USh {total_fee:,.0f}",
                                st.session_state.user['username']
                            )
                            safe_rerun()

                        except Exception as e:
                            st.error(f"Error saving fee structure: {str(e)}")
    with tab_generate:
        st.subheader("Generate Invoice")
        conn = get_db_connection()
        term_id = st.session_state.get('term_id')
        if not term_id or not is_term_current(term_id):
            st.error("Can only generate invoices in the current active term. Please select the current term in the sidebar.")
        else:
            students = pd.read_sql("""
                SELECT s.id, s.name, c.name as class_name 
                FROM students s 
                JOIN classes c ON s.class_id = c.id 
                ORDER BY s.name
            """, conn)

            if students.empty:
                st.info("No students available yet.")
            else:
                selected_student_str = st.selectbox(
                    "Select Student",
                    students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1)
                )
                student_id = int(selected_student_str.split("(ID: ")[1].replace(")", ""))

                # Get available fee structures for this student's class
                fee_structures = pd.read_sql("""
                    SELECT fs.id, fs.term, fs.academic_year, fs.total_fee,
                           fs.tuition_fee, fs.uniform_fee, fs.activity_fee,
                           fs.exam_fee, fs.library_fee, fs.other_fee
                    FROM fee_structure fs
                    WHERE fs.class_id = (SELECT class_id FROM students WHERE id = ?)
                    ORDER BY fs.academic_year DESC, fs.term
                """, conn, params=(student_id,))

                if fee_structures.empty:
                    st.warning("No fee structure defined for this student's class yet.")
                else:
                    options = fee_structures.apply(
                        lambda x: f"{x['academic_year']} - {x['term']} → USh {x['total_fee']:,.0f}", axis=1
                    ).tolist()

                    chosen = st.selectbox("Select Fee Structure to Invoice", options)

                    if chosen:
                        idx = options.index(chosen)
                        fs = fee_structures.iloc[idx]

                        st.markdown(f"**Structure details:**")
                        st.write(f"Academic Year: {fs['academic_year']}")
                        st.write(f"Term: {fs['term']}")
                        st.write(f"Total Fee: **USh {fs['total_fee']:,.0f}**")

                        with st.form("generate_invoice_form"):
                            issue_date = st.date_input("Issue Date", value=date.today())
                            due_date   = st.date_input("Due Date",   value=date.today())
                            notes      = st.text_area("Notes / Remarks", height=80)

                            submitted = st.form_submit_button("Generate Invoice")

                        if submitted:
                            try:
                                cur = conn.cursor()

                                # Prevent duplicate invoice for same student + term + year
                                duplicate = cur.execute("""
                                    SELECT id FROM invoices 
                                    WHERE student_id = ? 
                                      AND term = ? 
                                      AND academic_year = ?
                                """, (student_id, fs['term'], fs['academic_year'])).fetchone()

                                if duplicate:
                                    st.error("An invoice already exists for this student, term, and academic year.")
                                else:
                                    inv_number = generate_invoice_number()

                                    cur.execute("""
                                        INSERT INTO invoices (
                                            invoice_number, student_id, issue_date, due_date,
                                            academic_year, term, total_amount, balance_amount,
                                            status, notes, created_by, term_id
                                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?, ?)
                                    """, (
                                        inv_number, student_id, issue_date.isoformat(), due_date.isoformat(),
                                        fs['academic_year'], fs['term'], fs['total_fee'], fs['total_fee'],
                                        notes, st.session_state.user['username'], term_id
                                    ))

                                    conn.commit()

                                    st.success(f"Invoice **{inv_number}** generated successfully!")
                                    st.balloons()

                                    log_action(
                                        "generate_invoice",
                                        f"Invoice {inv_number} - {fs['total_fee']:,.0f} - {selected_student_str}",
                                        st.session_state.user['username']
                                    )
                                    safe_rerun()

                            except Exception as e:
                                st.error(f"Error creating invoice: {str(e)}")

        conn.close()

    with tab_edit_inv:
        st.subheader("Edit Existing Invoice")
        conn = get_db_connection()

        invoices = pd.read_sql("""
            SELECT i.id, i.invoice_number, s.name as student_name, 
                   i.academic_year, i.term, i.total_amount, i.balance_amount, i.status, i.notes
            FROM invoices i
            JOIN students s ON i.student_id = s.id
            ORDER BY i.issue_date DESC
        """, conn)

        if invoices.empty:
            st.info("No invoices exist yet.")
        else:
            inv_options = invoices.apply(
                lambda x: f"{x['invoice_number']} - {x['student_name']} ({x['academic_year']} {x['term']})", axis=1
            ).tolist()

            selected_inv_str = st.selectbox("Select Invoice to Edit", inv_options)
            inv_idx = inv_options.index(selected_inv_str)
            inv = invoices.iloc[inv_idx]
            inv_id = int(inv['id'])

            with st.form("edit_invoice_form"):
                new_total = st.number_input("Total Amount (USh)", value=float(inv['total_amount']), step=1000.0)
                new_notes = st.text_area("Notes", value=inv['notes'] or "")

                edit_submitted = st.form_submit_button("Save Changes")

            if edit_submitted:
                try:
                    new_balance = new_total - (inv['total_amount'] - inv['balance_amount'])  # preserve payments
                    new_status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid' if new_balance < new_total else 'Pending'

                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE invoices 
                        SET total_amount = ?, balance_amount = ?, status = ?, notes = ?
                        WHERE id = ?
                    """, (new_total, new_balance, new_status, new_notes, inv_id))

                    conn.commit()
                    st.success("Invoice updated successfully")
                    log_action("edit_invoice", f"Invoice {inv['invoice_number']} updated", st.session_state.user['username'])
                    safe_rerun()

                except Exception as e:
                    st.error(f"Error updating invoice: {str(e)}")

        conn.close()

    with tab_delete_inv:
        require_role(["Admin"])
        st.subheader("Delete Invoice")
        st.warning("This action is permanent and cannot be undone.")

        conn = get_db_connection()
        invoices = pd.read_sql("SELECT id, invoice_number, student_id FROM invoices ORDER BY issue_date DESC", conn)

        if invoices.empty:
            st.info("No invoices to delete.")
        else:
            inv_options = invoices.apply(lambda x: f"{x['invoice_number']} (Student ID: {x['student_id']})", axis=1).tolist()
            selected = st.selectbox("Select Invoice to Delete", inv_options)

            inv_idx = inv_options.index(selected)
            inv_id = int(invoices.iloc[inv_idx]['id'])

            confirm = st.checkbox("I understand this action is **permanent**", key="delete_confirm")

            if confirm and st.button("🗑️ Delete Invoice", type="primary"):
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM invoices WHERE id = ?", (inv_id,))
                    conn.commit()
                    st.success("Invoice deleted successfully.")
                    log_action("delete_invoice", f"Invoice ID {inv_id} deleted", st.session_state.user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error deleting invoice: {str(e)}")

        conn.close()

# ────────────────────────────────────────────────
# Terms Management – FIXED VERSION
# ────────────────────────────────────────────────
elif page == "Terms Management":
    require_role(["Admin"])
    st.header("Terms Management")
    conn = get_db_connection()
    tab_view, tab_add, tab_close, tab_edit = st.tabs(["View Terms", "Add New Term", "Close/Set Current Term", "Edit Term"])
    with tab_view:
        st.subheader("All Terms")
        terms_df = pd.read_sql("""
            SELECT id, name, academic_year, start_date, end_date, 
                   CASE WHEN is_current = 1 THEN 'Yes' ELSE 'No' END as Current,
                   created_at
            FROM terms 
            ORDER BY start_date DESC
        """, conn)
        if terms_df.empty:
            st.info("No terms created yet")
        else:
            st.dataframe(terms_df, use_container_width=True)
            download_options(terms_df, filename_base="all_terms", title="All Academic Terms")
    with tab_add:
        st.subheader("Create New Term")
        with st.form("add_term_form"):
            term_name = st.selectbox("Term Name", ["Term 1", "Term 2", "Term 3"])
            academic_year = st.text_input("Academic Year", value="2026")
            start_date = st.date_input("Start Date")
            end_date = st.date_input("End Date")
            make_current = st.checkbox("Make this the current active term", value=True)
            submit_term = st.form_submit_button("Create Term")
        if submit_term:
            if start_date >= end_date:
                st.error("End date must be after start date")
            else:
                try:
                    cur = conn.cursor()
                    overlap = cur.execute("""
                        SELECT COUNT(*) FROM terms 
                        WHERE (start_date <= ? AND end_date >= ?) 
                           OR (start_date <= ? AND end_date >= ?)
                    """, (end_date.isoformat(), start_date.isoformat(), 
                          end_date.isoformat(), start_date.isoformat())).fetchone()[0]
                    if overlap > 0:
                        st.error("This date range overlaps with an existing term")
                    else:
                        cur.execute("""
                            INSERT INTO terms (name, academic_year, start_date, end_date, is_current)
                            VALUES (?, ?, ?, ?, ?)
                        """, (term_name.strip(), academic_year.strip(), 
                              start_date.isoformat(), end_date.isoformat(), 1 if make_current else 0))
                        if make_current:
                            cur.execute("UPDATE terms SET is_current = 0 WHERE id != last_insert_rowid()")
                        conn.commit()
                        st.success(f"Term '{term_name} {academic_year}' created successfully")
                        log_action("create_term", f"Created term {term_name} {academic_year} ({start_date} to {end_date})", 
                                   st.session_state.user['username'])
                        safe_rerun()
                except Exception as e:
                    st.error(f"Error creating term: {str(e)}")
    with tab_close:
        st.subheader("Set/Close Current Term")
        current_term = conn.execute("SELECT * FROM terms WHERE is_current = 1").fetchone()
        if current_term:
            st.info(f"Current active term: **{current_term['name']} {current_term['academic_year']}** "
                    f"({current_term['start_date']} → {current_term['end_date']})")
        else:
            st.warning("No current term is set.")

        all_terms = pd.read_sql("SELECT id, name, academic_year FROM terms ORDER BY start_date DESC", conn)
        if not all_terms.empty:
            selected = st.selectbox(
                "Select term to make current",
                all_terms.apply(lambda x: f"{x['name']} {x['academic_year']} (ID: {x['id']})", axis=1)
            )
            term_id_to_set = int(selected.split("(ID: ")[1].replace(")", ""))
            
            if st.button("Set as Current Term"):
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE terms SET is_current = 0")
                    cur.execute("UPDATE terms SET is_current = 1 WHERE id = ?", (term_id_to_set,))
                    conn.commit()
                    st.success("Current term updated successfully")
                    st.session_state['term_id'] = term_id_to_set
                    log_action("set_current_term", f"Set term ID {term_id_to_set} as current", 
                               st.session_state.user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error setting current term: {e}")
    with tab_edit:
        st.subheader("Edit Existing Term")
        terms_list = pd.read_sql("SELECT id, name || ' ' || academic_year as display FROM terms ORDER BY start_date DESC", conn)
        if terms_list.empty:
            st.info("No terms to edit")
        else:
            selected_edit = st.selectbox("Select Term to Edit", terms_list['display'].tolist())
            term_id_edit = terms_list[terms_list['display'] == selected_edit]['id'].iloc[0]
            term_data = conn.execute("SELECT * FROM terms WHERE id = ?", (term_id_edit,)).fetch
        if term_data is None:
                        st.error("Selected term not found in database.")
        else:
            with st.form("edit_term_form"):
                term_options = ["Term 1", "Term 2", "Term 3"]
                current_name = (term_data['name'] or "").strip()
            try:
                default_index = term_options.index(current_name)
            except ValueError:
                default_index = 0
                st.warning(
                    f"Stored term name '{current_name}' is not one of the standard options "
                    f"({', '.join(term_options)}). Defaulting to 'Term 1' for editing."
                        )
                    
                    edit_name = st.selectbox("Term Name", term_options, index=default_index)
                    edit_year = st.text_input("Academic Year", value=term_data['academic_year'] or "")
                    edit_start = st.date_input(
                        
                        "Start Date", 
                        value=date.fromisoformat(term_data['start_date']) if term_data['start_date'] else date.today()
                        )
                    edit_end = st.date_input(
                        "End Date", 
                        value=date.fromisoformat(term_data['end_date']) if term_data['end_date'] else date.today()
                        )
                        edit_current = st.checkbox("Mark as Current Term", value=bool(term_data['is_current']))
                        submit_edit_term = st.form_submit_button("Save Changes")
                    

                    if submit_edit_term:
                        if edit_start >= edit_end:
                            st.error("End date must be after start date")
                            else:
                                try:
                                    cur = conn.cursor()
                                    cur.execute("""
                                        UPDATE terms 
                                        SET name = ?, academic_year = ?, start_date = ?, end_date = ?, is_current = ?
                                        WHERE id = ?
                                    """, (
                                        edit_name.strip(), 
                                        edit_year.strip(), 
                                        edit_start.isoformat(), 
                                        edit_end.isoformat(), 
                                        1 if edit_current else 0, 
                                        term_id_edit
                                    ))
                                    
                                    if edit_current:
                                        cur.execute("UPDATE terms SET is_current = 0 WHERE id != ?", (term_id_edit,))
                                    
                                    conn.commit()
                                    st.success("Term updated successfully")
                                    if edit_current:
                                        st.session_state['term_id'] = term_id_edit
                                    log_action("edit_term", f"Edited term ID {term_id_edit} to {edit_name} {edit_year}", 
                                               st.session_state.user['username'])
                                    safe_rerun()
                                except Exception as e:
                                    st.error(f"Error updating term: {str(e)}")

    conn.close()

# ────────────────────────────────────────────────
#   Footer / Final Closing
# ────────────────────────────────────────────────
st.markdown("---")
st.caption(f"© COSNA School Management System • {datetime.now().year} • Final Fixed Version")
st.caption("Developed for Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana")
