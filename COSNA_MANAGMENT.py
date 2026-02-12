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
- Cashbook (combined incomes/expenses running balance) view
- Robust DB initialization and safe migrations
- Academic term configuration and global term filtering
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
LOGO_FILENAME = "school_badge.png"  # place uploaded badge here
PAGE_LAYOUT = "wide"

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

def safe_rerun():
    try:
        if hasattr(st, "experimental_rerun") and callable(st.experimental_rerun):
            st.experimental_rerun()
        elif hasattr(st, "rerun") and callable(st.rerun):
            st.rerun()
        else:
            st.session_state['_needs_refresh'] = True
            st.stop()
    except Exception:
        try:
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

    # Core tables
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
        CREATE TABLE IF NOT EXISTS academic_terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            academic_year TEXT,
            term TEXT CHECK(term IN ('Term 1','Term 2','Term 3')),
            start_date DATE,
            end_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(academic_year, term)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fee_structure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_id INTEGER,
            class_id INTEGER,
            tuition_fee REAL DEFAULT 0,
            uniform_fee REAL DEFAULT 0,
            activity_fee REAL DEFAULT 0,
            exam_fee REAL DEFAULT 0,
            library_fee REAL DEFAULT 0,
            other_fee REAL DEFAULT 0,
            total_fee REAL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(term_id) REFERENCES academic_terms(id),
            FOREIGN KEY(class_id) REFERENCES classes(id),
            UNIQUE(term_id, class_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE,
            student_id INTEGER,
            term_id INTEGER,
            issue_date DATE,
            due_date DATE,
            total_amount REAL,
            paid_amount REAL DEFAULT 0,
            balance_amount REAL,
            status TEXT CHECK(status IN ('Pending','Partially Paid','Fully Paid','Overdue')) DEFAULT 'Pending',
            notes TEXT,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(term_id) REFERENCES academic_terms(id)
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

    conn.commit()

    # Safe migrations (add columns if missing)
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
    safe_alter_add_column(conn, "fee_structure", "term_id INTEGER")

    # Backfill normalized fields
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

    # Ensure uniforms rows exist for categories
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

    # Seed default admin user if none exists
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

    # Seed uniform categories and expense categories
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

    expense_seeds = [
        ('Medical', 'Expense'), ('Salaries', 'Expense'), ('Utilities', 'Expense'),
        ('Maintenance', 'Expense'), ('Supplies', 'Expense'), ('Transport', 'Expense'),
        ('Events', 'Expense'), ('Tuition Fees', 'Income'), ('Registration Fees', 'Income'),
        ('Uniform Sales', 'Income'), ('Donations', 'Income'), ('Other Income', 'Income')
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

    c.setFont("Helvetica-Bold", 14)
    c.drawString(title_x, y_top, title)
    c.setFont("Helvetica", 9)
    y = y_top - draw_h - 30  # Adjusted to prevent overlap

    cols = list(df.columns)
    usable_width = width - 80
    col_width = max(80, usable_width / max(1, len(cols)))
    # Header
    for i, col in enumerate(cols):
        c.drawString(40 + i * col_width, y, str(col))
    y -= 14
    # Rows
    for _, row in df.iterrows():
        if y < 40:
            c.showPage()
            y = height - 40
        for i, col in enumerate(cols):
            text = str(row[col])
            if len(text) > 120:
                text = text[:117] + "..."
            c.drawString(40 + i * col_width, y, text)
        y -= 12

    # Footer
    c.setFont("Helvetica", 8)
    c.drawString(40, 20, f"Generated: {datetime.now().isoformat()}  •  {APP_TITLE}")
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

# ---------------------------
# Global Term Selector in Sidebar
# ---------------------------
conn_global = get_db_connection()
terms_df = pd.read_sql("""
    SELECT id, academic_year, term, start_date, end_date,
           CASE WHEN date('now') > end_date THEN 'Closed' ELSE 'Active' END as status
    FROM academic_terms
    ORDER BY academic_year DESC, term DESC
""", conn_global)
conn_global.close()

if terms_df.empty:
    st.sidebar.warning("No academic terms configured yet. Go to Fee Management → Configure Academic Terms.")
    st.session_state['selected_term_id'] = None
    st.session_state['selected_term_label'] = "No term selected"
else:
    term_labels = terms_df.apply(
        lambda r: f"{r['term']} {r['academic_year']} ({r['status']})", axis=1
    ).tolist()
    default_index = 0  # most recent term
    selected_index = st.sidebar.selectbox(
        "Current Term for Display",
        range(len(term_labels)),
        index=default_index,
        format_func=lambda i: term_labels[i]
    )
    selected_term_row = terms_df.iloc[selected_index]
    st.session_state['selected_term_id'] = selected_term_row['id']
    st.session_state['selected_term_label'] = term_labels[selected_index]

# ---------------------------
# Main navigation
# ---------------------------
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report", "Fee Management", "Cashbook", "Audit Log"])

# Helper to get term filter SQL and params
def get_term_filter():
    if st.session_state.get('selected_term_id'):
        return " AND term_id = ?", [st.session_state['selected_term_id']]
    return "", []

# ---------------------------
# Dashboard
# ---------------------------
if page == "Dashboard":
    conn = get_db_connection()
    st.header("📊 Financial Overview")
    col1, col2, col3, col4 = st.columns(4)

    term_sql, term_p = get_term_filter()

    try:
        total_income = conn.execute(f"SELECT COALESCE(SUM(amount),0) as s FROM incomes WHERE 1=1{term_sql}", term_p).fetchone()["s"] or 0
    except Exception:
        total_income = 0
    col1.metric("Total Income", f"USh {total_income:,.0f}")

    try:
        total_expenses = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM expenses").fetchone()["s"] or 0
    except Exception:
        total_expenses = 0
    col2.metric("Total Expenses", f"USh {total_expenses:,.0f}")

    net_balance = total_income - total_expenses
    col3.metric("Net Balance", f"USh {net_balance:,.0f}", delta=f"USh {net_balance:,.0f}")

    try:
        outstanding_fees = conn.execute(f"SELECT COALESCE(SUM(balance_amount),0) as s FROM invoices WHERE status IN ('Pending','Partially Paid'){term_sql}", term_p).fetchone()["s"] or 0
    except Exception:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")

    colA, colB = st.columns(2)
    with colA:
        st.subheader("Recent Income (Last 5)")
        try:
            df_inc = pd.read_sql(f"SELECT date, amount, source, payer FROM incomes WHERE 1=1{term_sql} ORDER BY date DESC LIMIT 5", conn, params=term_p)
            if df_inc.empty:
                st.info("No income records yet")
            else:
                st.dataframe(df_inc, use_container_width=True)
        except Exception:
            st.info("No income records yet or error loading incomes")
    with colB:
        st.subheader("Recent Expenses (Last 5)")
        try:
            df_exp = pd.read_sql("SELECT e.date, e.amount, ec.name as category, e.payee FROM expenses e LEFT JOIN expense_categories ec ON e.category_id = ec.id ORDER BY e.date DESC LIMIT 5", conn)
            if df_exp.empty:
                st.info("No expense records yet")
            else:
                st.dataframe(df_exp, use_container_width=True)
        except Exception:
            st.info("No expense records yet or error loading expenses")

    st.subheader("Monthly Financial Summary (Last 12 months)")
    try:
        df_monthly = pd.read_sql("""
            SELECT strftime('%Y-%m', date) as month, SUM(amount) as total_amount, 'Income' as type
            FROM incomes
            GROUP BY strftime('%Y-%m', date)
            UNION ALL
            SELECT strftime('%Y-%m', date) as month, SUM(amount) as total_amount, 'Expense' as type
            FROM expenses
            GROUP BY strftime('%Y-%m', date)
            ORDER BY month DESC
            LIMIT 24
        """, conn)
        if df_monthly.empty:
            st.info("No monthly data available")
        else:
            df_pivot = df_monthly.pivot_table(index='month', columns='type', values='total_amount', aggfunc='sum').fillna(0)
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
    tab_view, tab_add, tab_fees, tab_classes = st.tabs(["View & Export", "Add Student", "Student Fees", "Manage Classes"])

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
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(students)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'student_type' in columns:
                query = "SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name, s.student_type, s.registration_fee_paid FROM students s LEFT JOIN classes c ON s.class_id = c.id"
            else:
                query = "SELECT s.id, s.name, s.age, s.enrollment_date, c.name AS class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id"
            conditions = []
            params = []
            if selected_class != "All Classes":
                conditions.append("c.name = ?")
                params.append(selected_class)
            if selected_type != "All Types" and 'student_type' in columns:
                conditions.append("s.student_type = ?")
                params.append(selected_type)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            df = pd.read_sql_query(query, conn, params=params)
            if df.empty:
                st.info("No students found")
            else:
                st.dataframe(df, use_container_width=True)
                download_options(df, filename_base="students", title="Students Report")
        except Exception:
            st.info("No student records yet or error loading data")
        conn.close()

    with tab_add:
        st.subheader("Add Student")
        conn = get_db_connection()
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
                                    INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by, created_by)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (enroll_date.isoformat(), generate_receipt_number(), REGISTRATION_FEE, "Registration Fees",
                                      cat_id, f"Registration fee for {name}", "Cash", name, st.session_state.user['username'], st.session_state.user['username']))
                            except Exception:
                                cur.execute("INSERT INTO incomes (date, amount, source, created_by) VALUES (?, ?, ?, ?)",
                                            (enroll_date.isoformat(), REGISTRATION_FEE, f"Registration fee for {name}", st.session_state.user['username']))
                            conn.commit()
                        st.success("Student added successfully")
                        log_action("add_student", f"Added student {name} (ID: {student_id})", st.session_state.user['username'])
                    except Exception as e:
                        st.error(f"Error adding student: {e}")
        conn.close()

    with tab_fees:
        conn = get_db_connection()

        st.subheader("Outstanding Fees Breakdown")

        term_sql, term_p = get_term_filter()

        total_outstanding = conn.execute(f"""
            SELECT COALESCE(SUM(i.balance_amount), 0)
            FROM invoices i
            WHERE i.status IN ('Pending', 'Partially Paid'){term_sql}
        """, term_p).fetchone()[0]
        st.metric("Total Outstanding Fees", f"USh {total_outstanding:,.0f}")

        class_df = pd.read_sql(f"""
            SELECT c.name as class_name, COALESCE(SUM(i.balance_amount), 0) as class_outstanding
            FROM invoices i
            JOIN students s ON i.student_id = s.id
            JOIN classes c ON s.class_id = c.id
            WHERE i.status IN ('Pending', 'Partially Paid'){term_sql}
            GROUP BY c.name
            ORDER BY class_outstanding DESC
        """, conn, params=term_p)

        if class_df.empty:
            st.info("No outstanding fees in the selected term.")
        else:
            st.dataframe(class_df, hide_index=True, use_container_width=True)
            download_options(class_df, "outstanding_by_class", "Outstanding Fees by Class")

            selected_class = st.selectbox(
                "Select Class to View Student Details",
                [""] + class_df['class_name'].tolist(),
                format_func=lambda x: "— Select a class —" if x == "" else x
            )

            if selected_class:
                student_df = pd.read_sql(f"""
                    SELECT s.name, COALESCE(SUM(i.balance_amount), 0) as outstanding
                    FROM invoices i
                    JOIN students s ON i.student_id = s.id
                    JOIN classes c ON s.class_id = c.id
                    WHERE c.name = ? AND i.status IN ('Pending', 'Partially Paid'){term_sql}
                    GROUP BY s.id, s.name
                    ORDER BY outstanding DESC
                """, conn, params=[selected_class] + term_p)

                if student_df.empty:
                    st.info(f"No students with outstanding balances in {selected_class}")
                else:
                    st.subheader(f"Students with Outstanding Balances in {selected_class}")
                    st.dataframe(student_df, hide_index=True, use_container_width=True)
                    download_options(student_df, f"outstanding_students_{selected_class.replace(' ', '_')}", f"Outstanding Students in {selected_class}")

        st.subheader("Student Fee Management")
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        if students.empty:
            st.info("No students available")
        else:
            selected = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))
            try:
                invoices = pd.read_sql(f"SELECT * FROM invoices WHERE student_id = ?{term_sql} ORDER BY issue_date DESC", conn, params=[student_id] + term_p)
            except Exception:
                invoices = pd.DataFrame()
            if invoices.empty:
                st.info("No invoices for this student in selected term")
            else:
                st.dataframe(invoices[['invoice_number','issue_date','due_date','total_amount','paid_amount','balance_amount','status']], use_container_width=True)

                st.subheader("Payment History")
                try:
                    payments = pd.read_sql(f"SELECT p.payment_date, p.amount, p.payment_method, p.receipt_number, p.reference_number, p.notes FROM payments p JOIN invoices i ON p.invoice_id = i.id WHERE i.student_id = ?{term_sql} ORDER BY p.payment_date DESC", conn, params=[student_id] + term_p)
                    if payments.empty:
                        st.info("No payments recorded for this student in selected term")
                    else:
                        st.dataframe(payments, use_container_width=True)
                        download_options(payments, f"payments_student_{student_id}", f"Payments for Student {student_id}")
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
                        if pay_amount <= 0:
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
                                            INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, payment_method, reference_number, received_by, notes, created_by)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (inv_id, pay_receipt, pay_date.isoformat(), pay_amount, pay_method, pay_ref, st.session_state.user['username'], pay_notes, st.session_state.user['username']))
                                        try:
                                            cat_row = conn.execute("SELECT id FROM expense_categories WHERE name = 'Tuition Fees'").fetchone()
                                            cat_id = cat_row["id"] if cat_row else None
                                            cur.execute("""
                                                INSERT INTO incomes (date, receipt_number, amount, source, category_id, payment_method, payer, received_by, created_by)
                                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                            """, (pay_date.isoformat(), pay_receipt, pay_amount, "Tuition Fees", cat_id, pay_method, selected.split(" - ")[0], st.session_state.user['username'], st.session_state.user['username']))
                                        except Exception:
                                            cur.execute("INSERT INTO incomes (date, amount, source, created_by) VALUES (?, ?, ?, ?)",
                                                        (pay_date.isoformat(), pay_amount, f"Tuition fee payment for invoice {chosen_inv}", st.session_state.user['username']))
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

    with tab_classes:
        st.subheader("Manage Classes")
        conn = get_db_connection()
        with st.form("add_class_form"):
            class_name = st.text_input("Class Name")
            submit_class = st.form_submit_button("Add Class")
        if submit_class:
            if not class_name:
                st.error("Enter class name")
            else:
                try:
                    cur = conn.cursor()
                    cur.execute("INSERT INTO classes (name) VALUES (?)", (class_name.strip(),))
                    conn.commit()
                    st.success("Class added successfully")
                    log_action("add_class", f"Added class {class_name}", st.session_state.user['username'])
                    safe_rerun()
                except sqlite3.IntegrityError:
                    st.error("Class name already exists")
                except Exception as e:
                    st.error(f"Error adding class: {e}")

        st.subheader("Existing Classes")
        classes_df = pd.read_sql("SELECT name FROM classes ORDER BY name", conn)
        if classes_df.empty:
            st.info("No classes added yet")
        else:
            st.dataframe(classes_df, use_container_width=True)
        conn.close()

# ---------------------------
# Uniforms
# ---------------------------
elif page == "Uniforms":
    st.header("Uniforms – Inventory & Sales")
    conn = get_db_connection()

    def get_inventory_df():
        return pd.read_sql_query("""
            SELECT uc.id as cat_id, uc.category, uc.gender, uc.is_shared, u.stock, u.unit_price
            FROM uniforms u JOIN uniform_categories uc ON u.category_id = uc.id
            ORDER BY uc.gender, uc.category
        """, conn)

    tab_view, tab_update, tab_sale, tab_manage = st.tabs(["View Inventory", "Update Stock/Price", "Record Sale", "Manage Categories"])

    with tab_view:
        inventory_df = get_inventory_df()
        if inventory_df.empty:
            st.info("No inventory records")
        else:
            display_df = inventory_df.copy()
            display_df['unit_price'] = display_df['unit_price'].apply(lambda x: f"USh {x:,.0f}")
            st.dataframe(display_df[['category','gender','is_shared','stock','unit_price']], use_container_width=True)
            total_stock = inventory_df['stock'].sum()
            total_value = (inventory_df['stock'] * inventory_df['unit_price']).sum()
            col1, col2 = st.columns(2)
            col1.metric("Total Items in Stock", f"{int(total_stock):,}")
            col2.metric("Total Inventory Value", f"USh {total_value:,.0f}")
            download_options(inventory_df, filename_base="uniform_inventory", title="Uniform Inventory Report")

    with tab_update:
        st.subheader("Update Stock & Price")
        categories_df = pd.read_sql("SELECT uc.id, uc.category, u.stock, u.unit_price FROM uniform_categories uc JOIN uniforms u ON uc.id = u.category_id ORDER BY uc.category", conn)
        if categories_df.empty:
            st.info("No uniform categories available. Add categories in Manage Categories tab.")
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
            if st.button("Record Sale"):
                if qty <= 0:
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
                            try:
                                cat_row = conn.execute("SELECT id FROM expense_categories WHERE name = 'Uniform Sales'").fetchone()
                                cat_id_income = cat_row["id"] if cat_row else None
                                cur.execute("""
                                    INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by, created_by)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (date.today().isoformat(), receipt_no, amount, "Uniform Sales", cat_id_income, f"Sale of {qty} x {selected}", payment_method, buyer or "Walk-in", st.session_state.user['username'], st.session_state.user['username']))
                            except Exception:
                                cur.execute("INSERT INTO incomes (date, amount, source, created_by) VALUES (?, ?, ?, ?)",
                                            (date.today().isoformat(), amount, f"Uniform sale {selected}", st.session_state.user['username']))
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
        st.subheader("Manage Uniform Categories")
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
    conn.close()

# ---------------------------
# Finances
# ---------------------------
elif page == "Finances":
    user_role = st.session_state.user.get('role')
    st.header("Finances")
    tab_inc, tab_exp, tab_reports = st.tabs(["Record Income", "Record Expense", "View Transactions"])

    term_sql, term_p = get_term_filter()

    with tab_inc:
        st.subheader("Record Income")
        if user_role not in ("Admin", "Accountant"):
            st.info("You do not have permission to record incomes. View-only access.")
        conn = get_db_connection()
        try:
            categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
        except Exception:
            categories = pd.DataFrame(columns=["id","name"])
        with st.form("record_income_form"):
            date_in = st.date_input("Date", date.today())
            receipt_no = st.text_input("Receipt Number", value=generate_receipt_number())
            amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
            source = st.text_input("Source (e.g., Tuition Fees, Donations)")
            category = st.selectbox("Category", ["-- Select --"] + categories["name"].tolist())
            payment_method = st.selectbox("Payment Method", ["Cash","Bank Transfer","Mobile Money","Cheque"])
            payer = st.text_input("Payer")
            notes = st.text_area("Notes")
            submit_income = st.form_submit_button("Record Income")
        if submit_income:
            if user_role not in ("Admin", "Accountant"):
                st.error("Permission denied")
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
                        INSERT INTO incomes (date, receipt_number, amount, source, category_id, description, payment_method, payer, received_by, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (date_in.isoformat(), receipt_no, amount, source, cat_id, notes, payment_method, payer, st.session_state.user['username'], st.session_state.user['username']))
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
        conn = get_db_connection()
        try:
            categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name", conn)
        except Exception:
            categories = pd.DataFrame(columns=["id","name"])
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
            if user_role not in ("Admin", "Accountant"):
                st.error("Permission denied")
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
                        INSERT INTO expenses (date, voucher_number, amount, category_id, description, payment_method, payee, approved_by, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (date_e.isoformat(), voucher_no, amount, cat_id, description, payment_method, payee, approved_by, st.session_state.user['username']))
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
        try:
            df_inc = pd.read_sql(f"SELECT id, date, receipt_number, amount, source, payer, created_by FROM incomes WHERE 1=1{term_sql} ORDER BY date DESC LIMIT 500", conn, params=term_p)
        except Exception:
            df_inc = pd.DataFrame()
        try:
            df_exp = pd.read_sql("SELECT id, date, voucher_number, amount, description, payee, created_by FROM expenses ORDER BY date DESC LIMIT 500", conn)
        except Exception:
            df_exp = pd.DataFrame()
        st.write("Recent Incomes")
        if df_inc.empty:
            st.info("No incomes recorded")
        else:
            st.dataframe(df_inc, use_container_width=True)
            download_options(df_inc, "recent_incomes", "Recent Incomes")
        st.write("Recent Expenses")
        if df_exp.empty:
            st.info("No expenses recorded")
        else:
            st.dataframe(df_exp, use_container_width=True)
            download_options(df_exp, "recent_expenses", "Recent Expenses")
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
        if st.button("Generate Report"):
            try:
                term_sql, term_p = get_term_filter()
                if report_type == "Income vs Expense (date range)":
                    df_inc = pd.read_sql(f"SELECT date, amount, source, payer FROM incomes WHERE date BETWEEN ? AND ?{term_sql} ORDER BY date", conn, params=[start_date.isoformat(), end_date.isoformat()] + term_p)
                    df_exp = pd.read_sql("SELECT date, amount, description, payee FROM expenses WHERE date BETWEEN ? AND ? ORDER BY date", conn, params=(start_date.isoformat(), end_date.isoformat()))
                    if df_inc.empty and df_exp.empty:
                        st.info("No transactions in this range")
                    else:
                        st.subheader("Incomes")
                        st.dataframe(df_inc, use_container_width=True)
                        st.subheader("Expenses")
                        st.dataframe(df_exp, use_container_width=True)
                        total_inc = df_inc['amount'].sum() if not df_inc.empty else 0
                        total_exp = df_exp['amount'].sum() if not df_exp.empty else 0
                        st.metric("Total Income", f"USh {total_inc:,.0f}")
                        st.metric("Total Expense", f"USh {total_exp:,.0f}")
                        combined = pd.concat([df_inc.assign(type='Income'), df_exp.assign(type='Expense')], sort=False).fillna('')
                        download_options(combined, f"financial_{start_date}_{end_date}", "Income vs Expense Report")
                elif report_type == "By Category":
                    cat = st.selectbox("Category Type", ["Income", "Expense"])
                    sql_cat = f"SELECT ec.name, SUM(COALESCE(i.amount,0)) as total_income, SUM(COALESCE(e.amount,0)) as total_expense FROM expense_categories ec LEFT JOIN incomes i ON i.category_id = ec.id LEFT JOIN expenses e ON e.category_id = ec.id WHERE ec.category_type = ?{term_sql if cat == 'Income' else ''} GROUP BY ec.name"
                    params_cat = (cat,) + (term_p if cat == 'Income' else ())
                    df = pd.read_sql(sql_cat, conn, params=params_cat)
                    if df.empty:
                        st.info("No data for selected category type")
                    else:
                        st.dataframe(df, use_container_width=True)
                        download_options(df, f"by_category_{cat}", f"By Category - {cat}")
                elif report_type == "Outstanding Invoices":
                    df = pd.read_sql(f"SELECT invoice_number, student_id, issue_date, due_date, total_amount, paid_amount, balance_amount, status FROM invoices WHERE status IN ('Pending','Partially Paid'){term_sql} ORDER BY due_date", conn, params=term_p)
                    if df.empty:
                        st.info("No outstanding invoices")
                    else:
                        st.dataframe(df, use_container_width=True)
                        download_options(df, "outstanding_invoices", "Outstanding Invoices")
                else:  # Student Payment Summary
                    students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
                    if students.empty:
                        st.info("No students available")
                    else:
                        sel = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1))
                        sid = int(sel.split("(ID: ")[1].replace(")", ""))
                        df_inv = pd.read_sql(f"SELECT invoice_number, academic_year, term, total_amount, paid_amount, balance_amount, status, issue_date FROM invoices WHERE student_id = ?{term_sql} ORDER BY issue_date DESC", conn, params=(sid,) + term_p)
                        df_pay = pd.read_sql(f"SELECT payment_date, amount, payment_method, receipt_number, reference_number FROM payments p JOIN invoices i ON p.invoice_id = i.id WHERE i.student_id = ?{term_sql} ORDER BY payment_date DESC", conn, params=(sid,) + term_p)
                        st.subheader("Invoices")
                        if df_inv.empty:
                            st.info("No invoices for this student")
                        else:
                            st.dataframe(df_inv, use_container_width=True)
                            download_options(df_inv, f"student_{sid}_invoices", f"Invoices for Student {sid}")
                        st.subheader("Payments")
                        if df_pay.empty:
                            st.info("No payments for this student")
                        else:
                            st.dataframe(df_pay, use_container_width=True)
                            download_options(df_pay, f"student_{sid}_payments", f"Payments for Student {sid}")
            except Exception as e:
                st.error(f"Error generating report: {e}")
    conn.close()

# ---------------------------
# Cashbook
# ---------------------------
elif page == "Cashbook":
    require_role(["Admin", "Accountant", "Clerk"])
    st.header("Cashbook (Running Balance)")
    conn = get_db_connection()
    start_date = st.date_input("Start Date", date.today().replace(day=1))
    end_date = st.date_input("End Date", date.today())
    if start_date > end_date:
        st.error("Start date must be before end date")
    else:
        try:
            # Incomes are NOT filtered by term_id – only invoices are
            df_inc = pd.read_sql(
                "SELECT date as tx_date, amount, 'Income' as type, source as description "
                "FROM incomes WHERE date BETWEEN ? AND ?",
                conn, params=(start_date.isoformat(), end_date.isoformat())
            )
            df_exp = pd.read_sql(
                "SELECT date as tx_date, amount, 'Expense' as type, description "
                "FROM expenses WHERE date BETWEEN ? AND ?",
                conn, params=(start_date.isoformat(), end_date.isoformat())
            )
            combined = pd.concat([df_inc, df_exp], sort=False).fillna('')
            if combined.empty:
                st.info("No transactions in this range")
            else:
                combined['tx_date'] = pd.to_datetime(combined['tx_date'])
                combined = combined.sort_values('tx_date').reset_index(drop=True)
                combined['amount_signed'] = combined.apply(
                    lambda r: r['amount'] if r['type'] == 'Income' else -abs(r['amount']), axis=1
                )
                combined['running_balance'] = combined['amount_signed'].cumsum()
                display = combined[['tx_date','type','description','amount','running_balance']].copy()
                display['tx_date'] = display['tx_date'].dt.date
                st.dataframe(display, use_container_width=True)
                download_options(display, f"cashbook_{start_date}_{end_date}", "Cashbook")
        except Exception as e:
            st.error(f"Error loading cashbook: {str(e)}")
    conn.close()

# ---------------------------
# Audit Log
# ---------------------------
elif page == "Audit Log":
    require_role(["Admin", "Accountant"])
    st.header("Audit Log")
    conn = get_db_connection()
    try:
        df_audit = pd.read_sql("SELECT performed_at, performed_by, action, details FROM audit_log ORDER BY performed_at DESC LIMIT 500", conn)
        if df_audit.empty:
            st.info("No audit entries")
        else:
            st.dataframe(df_audit, use_container_width=True)
            download_options(df_audit, "audit_log", "Audit Log")
    except Exception as e:
        st.error(f"Error loading audit log: {e}")
    conn.close()

# ---------------------------# Fee Management - FULL IMPLEMENTATION
elif page == "Fee Management":
    require_role(["Admin", "Accountant"])
    st.header("Fee Management")
    conn = get_db_connection()

    st.subheader("Configure Academic Terms")
    with st.form("term_config_form"):
        col1, col2 = st.columns(2)
        with col1:
            academic_year = st.text_input("Academic Year (e.g., 2025/2026)", 
                                        value=f"{date.today().year}/{date.today().year + 1}")
            term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
        with col2:
            start_date = st.date_input("Start Date")
            end_date = st.date_input("End Date")
        submit_term = st.form_submit_button("Save Term")

    if submit_term:
        if end_date < start_date:
            st.error("End date must be after start date")
        else:
            try:
                cur = conn.cursor()
                row = cur.execute(
                    "SELECT id FROM academic_terms WHERE academic_year = ? AND term = ?",
                    (academic_year, term)
                ).fetchone()
                if row:
                    cur.execute(
                        "UPDATE academic_terms SET start_date = ?, end_date = ? WHERE id = ?",
                        (start_date.isoformat(), end_date.isoformat(), row[0])
                    )
                    st.success("Term updated")
                else:
                    cur.execute(
                        "INSERT INTO academic_terms (academic_year, term, start_date, end_date) VALUES (?, ?, ?, ?)",
                        (academic_year, term, start_date.isoformat(), end_date.isoformat())
                    )
                    st.success("Term created")
                conn.commit()
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    st.subheader("Existing Academic Terms")
    terms = pd.read_sql("SELECT * FROM academic_terms ORDER BY academic_year DESC, term", conn)
    if not terms.empty:
        st.dataframe(terms, use_container_width=True)
    else:
        st.info("No terms yet")

    st.subheader("Define Fee Structure")
    classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
    active_terms = pd.read_sql(
        "SELECT id, term, academic_year FROM academic_terms WHERE date('now') <= end_date "
        "ORDER BY academic_year DESC, term", conn
    )

    if classes.empty:
        st.info("No classes found. Add some in Students → Manage Classes.")
    elif active_terms.empty:
        st.info("No active terms. Create one above.")
    else:
        with st.form("fee_structure_form"):
            term_str = st.selectbox(
                "Select Term",
                active_terms.apply(lambda r: f"{r['term']} {r['academic_year']} (ID:{r['id']})", axis=1)
            )
            term_id = int(term_str.split("ID:")[1][:-1])

            class_name = st.selectbox("Class", classes["name"].tolist())
            class_id = classes[classes["name"] == class_name]["id"].iloc[0]

            tuition = st.number_input("Tuition Fee", 0.0, step=1000.0)
            uniform = st.number_input("Uniform Fee", 0.0, step=1000.0)
            activity = st.number_input("Activity Fee", 0.0, step=1000.0)
            exam = st.number_input("Exam Fee", 0.0, step=1000.0)
            library = st.number_input("Library Fee", 0.0, step=1000.0)
            other = st.number_input("Other Fee", 0.0, step=1000.0)

            if st.form_submit_button("Save Fee Structure"):
                total = tuition + uniform + activity + exam + library + other
                try:
                    cur = conn.cursor()
                    exists = cur.execute(
                        "SELECT id FROM fee_structure WHERE term_id = ? AND class_id = ?",
                        (term_id, class_id)
                    ).fetchone()
                    if exists:
                        cur.execute("""
                            UPDATE fee_structure SET 
                                tuition_fee=?, uniform_fee=?, activity_fee=?, exam_fee=?, 
                                library_fee=?, other_fee=?, total_fee=?, created_at=CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (tuition, uniform, activity, exam, library, other, total, exists[0]))
                        st.success("Fee structure updated")
                    else:
                        cur.execute("""
                            INSERT INTO fee_structure 
                            (term_id, class_id, tuition_fee, uniform_fee, activity_fee, exam_fee, 
                             library_fee, other_fee, total_fee)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (term_id, class_id, tuition, uniform, activity, exam, library, other, total))
                        st.success("Fee structure created")
                    conn.commit()
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

        st.subheader("Existing Fee Structures")
        structures = pd.read_sql("""
            SELECT 
                at.term || ' ' || at.academic_year AS term,
                c.name AS class,
                fs.tuition_fee, fs.uniform_fee, fs.activity_fee, fs.exam_fee,
                fs.library_fee, fs.other_fee, fs.total_fee
            FROM fee_structure fs
            JOIN academic_terms at ON fs.term_id = at.id
            JOIN classes c ON fs.class_id = c.id
            ORDER BY at.academic_year DESC, at.term, c.name
        """, conn)
        if not structures.empty:
            st.dataframe(structures, use_container_width=True)
        else:
            st.info("No fee structures saved yet")

    st.subheader("Generate Invoice")
    students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
    if students.empty:
        st.info("No students available")
    else:
        selected_student = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
        student_id = int(selected_student.split("(ID: ")[1].replace(")", ""))
        active_terms = pd.read_sql("SELECT id, term, academic_year FROM academic_terms WHERE date('now') <= end_date", conn)
        if active_terms.empty:
            st.warning("No active term available for new invoices.")
        else:
            term_choice = st.selectbox("Select Term for Invoice", active_terms.apply(lambda x: f"{x['term']} {x['academic_year']} (ID: {x['id']})", axis=1))
            selected_term_id = int(term_choice.split("(ID: ")[1].replace(")", ""))
            fee_struct = pd.read_sql("""
                SELECT fs.total_fee 
                FROM fee_structure fs 
                WHERE fs.term_id = ? AND fs.class_id = (SELECT class_id FROM students WHERE id = ?)
            """, conn, params=(selected_term_id, student_id))
            if fee_struct.empty:
                st.error("No fee structure defined for this class and term.")
            else:
                total_fee = fee_struct['total_fee'].iloc[0]
                issue_date = st.date_input("Issue Date", date.today())
                due_date = st.date_input("Due Date", date.today())
                notes = st.text_area("Notes")
                if st.button("Create Invoice"):
                    try:
                        cur = conn.cursor()
                        existing = cur.execute("SELECT id FROM invoices WHERE student_id = ? AND term_id = ?", (student_id, selected_term_id)).fetchone()
                        if existing:
                            st.error("Invoice already exists for this student and term.")
                        else:
                            inv_no = generate_invoice_number()
                            cur.execute("""
                                INSERT INTO invoices (invoice_number, student_id, term_id, issue_date, due_date, total_amount, paid_amount, balance_amount, status, notes, created_by)
                                VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'Pending', ?, ?)
                            """, (inv_no, student_id, selected_term_id, issue_date.isoformat(), due_date.isoformat(), total_fee, total_fee, notes, st.session_state.user['username']))
                            conn.commit()
                            st.success(f"Invoice {inv_no} created for USh {total_fee:,.0f}")
                            log_action("create_invoice", f"Invoice {inv_no} for student {student_id} term {selected_term_id}", st.session_state.user['username'])
                            safe_rerun()
                    except Exception as e:
                        st.error(f"Error creating invoice: {e}")
    conn.close()
           
