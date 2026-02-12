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

# Safe rerun helper to avoid AttributeError in environments missing experimental rerun
def safe_rerun():
    try:
        if hasattr(st, "experimental_rerun") and callable(st.experimental_rerun):
            st.experimental_rerun()
        elif hasattr(st, "rerun") and callable(st.rerun):
            st.rerun()
        else:
            # Fallback: set a session flag and stop to force UI to re-evaluate on next interaction
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
            max_w = 60
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
    y = y_top - draw_h - 20

    cols = list(df.columns)
    # compute column widths to avoid collisions
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

    # Footer with generation info
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

# ---------------------------
# Main navigation
# ---------------------------
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report", "Fee Management", "Cashbook", "Audit Log"])

# ---------------------------
# Dashboard
# ---------------------------
if page == "Dashboard":
    conn = get_db_connection()
    st.header("📊 Financial Overview")
    col1, col2, col3, col4 = st.columns(4)

    try:
        total_income = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM incomes").fetchone()["s"] or 0
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
        outstanding_fees = conn.execute("SELECT COALESCE(SUM(balance_amount),0) as s FROM invoices WHERE status IN ('Pending','Partially Paid')").fetchone()["s"] or 0
    except Exception:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")

    colA, colB = st.columns(2)
    with colA:
        st.subheader("Recent Income (Last 5)")
        try:
            df_inc = pd.read_sql("SELECT date, amount, source, payer FROM incomes ORDER BY date DESC LIMIT 5", conn)
            if df_inc.empty:
                st.info("No income records yet")
            else:
                st.dataframe(df_inc, width='stretch')
        except Exception:
            st.info("No income records yet or error loading incomes")
    with colB:
        st.subheader("Recent Expenses (Last 5)")
        try:
            df_exp = pd.read_sql("""
                SELECT e.date, e.amount, ec.name as category, e.payee
                FROM expenses e
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                ORDER BY e.date DESC LIMIT 5
            """, conn)
            if df_exp.empty:
                st.info("No expense records yet")
            else:
                st.dataframe(df_exp, width='stretch')
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
            st.dataframe(df_pivot, width='stretch')
            download_options(df_pivot.reset_index(), filename_base="monthly_financial_summary", title="Monthly Financial Summary")
    except Exception:
        st.info("No monthly data available")
    conn.close()

# ---------------------------
# Students
# ---------------------------
elif page == "Students":
    st.header("Students")
    tab_view, tab_add, tab_fees = st.tabs(["View & Export", "Add Student", "Student Fees"])

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
                st.dataframe(df, width='stretch')
                download_options(df, filename_base="students", title="Students Report")
        except Exception:
            st.info("No student records yet or error loading data")
        conn.close()

    # Add Student with duplicate detection
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

    # Student Fees (view + pay)
    with tab_fees:
        st.subheader("Student Fee Management")
        conn = get_db_connection()
        students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
        if students.empty:
            st.info("No students available")
        else:
            selected = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))
            try:
                invoices = pd.read_sql("SELECT * FROM invoices WHERE student_id = ? ORDER BY issue_date DESC", conn, params=(student_id,))
            except Exception:
                invoices = pd.DataFrame()
            if invoices.empty:
                st.info("No invoices for this student")
            else:
                st.dataframe(invoices[['invoice_number','issue_date','due_date','total_amount','paid_amount','balance_amount','status']], width='stretch')

                st.subheader("Payment History")
                try:
                    payments = pd.read_sql("SELECT p.payment_date, p.amount, p.payment_method, p.receipt_number, p.reference_number, p.notes FROM payments p JOIN invoices i ON p.invoice_id = i.id WHERE i.student_id = ? ORDER BY p.payment_date DESC", conn, params=(student_id,))
                    if payments.empty:
                        st.info("No payments recorded for this student")
                    else:
                        st.dataframe(payments, width='stretch')
                        download_options(payments, filename_base=f"payments_student_{student_id}", title=f"Payments for Student {student_id}")
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
                                # Atomic transaction: update invoice, insert payment, insert income
                                cur = conn.cursor()
                                conn.isolation_level = None
                                cur.execute("BEGIN")
                                # Re-fetch invoice to avoid race
                                inv_check = cur.execute("SELECT paid_amount, balance_amount, total_amount FROM invoices WHERE id = ?", (inv_id,)).fetchone()
                                if not inv_check:
                                    cur.execute("ROLLBACK")
                                    st.error("Invoice not found")
                                else:
                                    current_balance = inv_check[1] if inv_check[1] is not None else inv_check[2]
                                    if pay_amount > current_balance + 0.0001:
                                        cur.execute("ROLLBACK")
                                        st.error("Payment exceeds current balance (it may have changed). Refresh and try again.")
                                    else:
                                        new_paid = (inv_check[0] or 0) + pay_amount
                                        new_balance = current_balance - pay_amount
                                        new_status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid'
                                        cur.execute("UPDATE invoices SET paid_amount = ?, balance_amount = ?, status = ? WHERE id = ?", (new_paid, new_balance, new_status, inv_id))
                                        cur.execute("""
                                            INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, payment_method, reference_number, received_by, notes, created_by)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (inv_id, pay_receipt, pay_date.isoformat(), pay_amount, pay_method, pay_ref, st.session_state.user['username'], pay_notes, st.session_state.user['username']))
                                        # Insert income record
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
            st.dataframe(display_df[['category','gender','is_shared','stock','unit_price']], width='stretch')
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
    # Restrict access: Accountant and Admin can record finances; Clerks can view
    user_role = st.session_state.user.get('role')
    st.header("Finances")
    tab_inc, tab_exp, tab_reports = st.tabs(["Record Income", "Record Expense", "View Transactions"])

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
            df_inc = pd.read_sql("SELECT id, date, receipt_number, amount, source, payer, created_by FROM incomes ORDER BY date DESC LIMIT 500", conn)
        except Exception:
            try:
                df_inc = pd.read_sql("SELECT id, date, receipt_number, amount, source, payer FROM incomes ORDER BY date DESC LIMIT 500", conn)
            except Exception:
                df_inc = pd.DataFrame()
        try:
            df_exp = pd.read_sql("SELECT id, date, voucher_number, amount, description, payee, created_by FROM expenses ORDER BY date DESC LIMIT 500", conn)
        except Exception:
            try:
                df_exp = pd.read_sql("SELECT id, date, voucher_number, amount, description, payee FROM expenses ORDER BY date DESC LIMIT 500", conn)
            except Exception:
                df_exp = pd.DataFrame()
        st.write("Recent Incomes")
        if df_inc.empty:
            st.info("No incomes recorded")
        else:
            st.dataframe(df_inc, width='stretch')
            download_options(df_inc, filename_base="recent_incomes", title="Recent Incomes")
        st.write("Recent Expenses")
        if df_exp.empty:
            st.info("No expenses recorded")
        else:
            st.dataframe(df_exp, width='stretch')
            download_options(df_exp, filename_base="recent_expenses", title="Recent Expenses")
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
                if report_type == "Income vs Expense (date range)":
                    df_inc = pd.read_sql("SELECT date, amount, source, payer FROM incomes WHERE date BETWEEN ? AND ? ORDER BY date", conn, params=(start_date.isoformat(), end_date.isoformat()))
                    df_exp = pd.read_sql("SELECT date, amount, description, payee FROM expenses WHERE date BETWEEN ? AND ? ORDER BY date", conn, params=(start_date.isoformat(), end_date.isoformat()))
                    if df_inc.empty and df_exp.empty:
                        st.info("No transactions in this range")
                    else:
                        st.subheader("Incomes")
                        st.dataframe(df_inc, width='stretch')
                        st.subheader("Expenses")
                        st.dataframe(df_exp, width='stretch')
                        total_inc = df_inc['amount'].sum() if not df_inc.empty else 0
                        total_exp = df_exp['amount'].sum() if not df_exp.empty else 0
                        st.metric("Total Income", f"USh {total_inc:,.0f}")
                        st.metric("Total Expense", f"USh {total_exp:,.0f}")
                        combined = pd.concat([df_inc.assign(type='Income'), df_exp.assign(type='Expense')], sort=False).fillna('')
                        download_options(combined, filename_base=f"financial_{start_date}_{end_date}", title="Income vs Expense Report")
                elif report_type == "By Category":
                    cat = st.selectbox("Category Type", ["Income", "Expense"])
                    df = pd.read_sql("SELECT ec.name, SUM(COALESCE(i.amount,0)) as total_income, SUM(COALESCE(e.amount,0)) as total_expense FROM expense_categories ec LEFT JOIN incomes i ON i.category_id = ec.id LEFT JOIN expenses e ON e.category_id = ec.id WHERE ec.category_type = ? GROUP BY ec.name", conn, params=(cat,))
                    if df.empty:
                        st.info("No data for selected category type")
                    else:
                        st.dataframe(df, width='stretch')
                        download_options(df, filename_base=f"by_category_{cat}", title=f"By Category - {cat}")
                elif report_type == "Outstanding Invoices":
                    df = pd.read_sql("SELECT invoice_number, student_id, issue_date, due_date, total_amount, paid_amount, balance_amount, status FROM invoices WHERE status IN ('Pending','Partially Paid') ORDER BY due_date", conn)
                    if df.empty:
                        st.info("No outstanding invoices")
                    else:
                        st.dataframe(df, width='stretch')
                        download_options(df, filename_base="outstanding_invoices", title="Outstanding Invoices")
                else:  # Student Payment Summary
                    students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
                    if students.empty:
                        st.info("No students available")
                    else:
                        sel = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1))
                        sid = int(sel.split("(ID: ")[1].replace(")", ""))
                        df_inv = pd.read_sql("SELECT invoice_number, academic_year, term, total_amount, paid_amount, balance_amount, status, issue_date FROM invoices WHERE student_id = ? ORDER BY issue_date DESC", conn, params=(sid,))
                        df_pay = pd.read_sql("SELECT payment_date, amount, payment_method, receipt_number, reference_number FROM payments p JOIN invoices i ON p.invoice_id = i.id WHERE i.student_id = ? ORDER BY payment_date DESC", conn, params=(sid,))
                        st.subheader("Invoices")
                        if df_inv.empty:
                            st.info("No invoices for this student")
                        else:
                            st.dataframe(df_inv, width='stretch')
                            download_options(df_inv, filename_base=f"student_{sid}_invoices", title=f"Invoices for Student {sid}")
                        st.subheader("Payments")
                        if df_pay.empty:
                            st.info("No payments for this student")
                        else:
                            st.dataframe(df_pay, width='stretch')
                            download_options(df_pay, filename_base=f"student_{sid}_payments", title=f"Payments for Student {sid}")
            except Exception as e:
                st.error(f"Error generating report: {e}")
    conn.close()

# ---------------------------
# Cashbook (combined incomes & expenses with running balance)
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
            df_inc = pd.read_sql("SELECT date as tx_date, amount, 'Income' as type, source as description FROM incomes WHERE date BETWEEN ? AND ?", conn, params=(start_date.isoformat(), end_date.isoformat()))
            df_exp = pd.read_sql("SELECT date as tx_date, amount, 'Expense' as type, description FROM expenses WHERE date BETWEEN ? AND ?", conn, params=(start_date.isoformat(), end_date.isoformat()))
            combined = pd.concat([df_inc, df_exp], sort=False).fillna('')
            if combined.empty:
                st.info("No transactions in this range")
            else:
                combined['tx_date'] = pd.to_datetime(combined['tx_date'])
                combined = combined.sort_values('tx_date').reset_index(drop=True)
                combined['amount_signed'] = combined.apply(lambda r: r['amount'] if r['type'] == 'Income' else -abs(r['amount']), axis=1)
                combined['running_balance'] = combined['amount_signed'].cumsum()
                display = combined[['tx_date','type','description','amount','running_balance']].copy()
                display['tx_date'] = display['tx_date'].dt.date
                st.dataframe(display, width='stretch')
                download_options(display, filename_base=f"cashbook_{start_date}_{end_date}", title="Cashbook")
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
        df_audit = pd.read_sql("SELECT performed_at, performed_by, action, details FROM audit_log ORDER BY performed_at DESC LIMIT 500", conn)
        if df_audit.empty:
            st.info("No audit entries")
        else:
            st.dataframe(df_audit, width='stretch')
            download_options(df_audit, filename_base="audit_log", title="Audit Log")
    except Exception as e:
        st.error(f"Error loading audit log: {e}")
    conn.close()

# ---------------------------
# Fee Management (detailed)
# ---------------------------
elif page == "Fee Management":
    require_role(["Admin", "Accountant"])
    st.header("Fee Management")
    conn = get_db_connection()
    st.subheader("Define Fee Structure")
    classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
    if classes.empty:
        st.info("No classes defined. Add classes in Students tab.")
    else:
        with st.form("fee_structure_form"):
            cls_name = st.selectbox("Class", classes["name"].tolist())
            cls_id = int(classes[classes["name"] == cls_name]["id"].iloc[0])
            term = st.selectbox("Term", ["Term 1","Term 2","Term 3"])
            academic_year = st.text_input("Academic Year (e.g., 2025/2026)", value=str(date.today().year) + "/" + str(date.today().year+1))
            tuition_fee = st.number_input("Tuition Fee", min_value=0.0, value=0.0, step=100.0)
            uniform_fee = st.number_input("Uniform Fee", min_value=0.0, value=0.0, step=100.0)
            activity_fee = st.number_input("Activity Fee", min_value=0.0, value=0.0, step=100.0)
            exam_fee = st.number_input("Exam Fee", min_value=0.0, value=0.0, step=100.0)
            library_fee = st.number_input("Library Fee", min_value=0.0, value=0.0, step=100.0)
            other_fee = st.number_input("Other Fee", min_value=0.0, value=0.0, step=100.0)
            create_fee = st.form_submit_button("Create/Update Fee Structure")
        if create_fee:
            try:
                total_fee = sum([tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee])
                cur = conn.cursor()
                existing = cur.execute("SELECT id FROM fee_structure WHERE class_id = ? AND term = ? AND academic_year = ?", (cls_id, term, academic_year)).fetchone()
                if existing:
                    cur.execute("""
                        UPDATE fee_structure SET tuition_fee=?, uniform_fee=?, activity_fee=?, exam_fee=?, library_fee=?, other_fee=?, total_fee=?, created_at=CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee, total_fee, existing[0]))
                    conn.commit()
                    st.success("Fee structure updated")
                    log_action("update_fee_structure", f"class {cls_name} term {term} year {academic_year} total {total_fee}", st.session_state.user['username'])
                    safe_rerun()
                else:
                    cur.execute("""
                        INSERT INTO fee_structure (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee, total_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (cls_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee, total_fee))
                    conn.commit()
                    st.success("Fee structure created")
                    log_action("create_fee_structure", f"class {cls_name} term {term} year {academic_year} total {total_fee}", st.session_state.user['username'])
                    safe_rerun()
            except Exception as e:
                st.error(f"Error saving fee structure: {e}")

    # Generate invoice for a student
    st.subheader("Generate Invoice")
    students = pd.read_sql("SELECT s.id, s.name, c.name as class_name FROM students s LEFT JOIN classes c ON s.class_id = c.id ORDER BY s.name", conn)
    if students.empty:
        st.info("No students to invoice")
    else:
        selected = st.selectbox("Select Student", students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
        student_id = int(selected.split("(ID: ")[1].replace(")", ""))
        fee_options = pd.read_sql("SELECT fs.id, c.name as class_name, fs.term, fs.academic_year, fs.total_fee FROM fee_structure fs JOIN classes c ON fs.class_id = c.id WHERE fs.class_id = (SELECT class_id FROM students WHERE id = ?) ORDER BY fs.academic_year DESC", conn, params=(student_id,))
        if fee_options.empty:
            st.info("No fee structure for this student's class. Define fee structure first.")
        else:
            chosen = st.selectbox("Choose Fee Structure", fee_options.apply(lambda x: f"{x['academic_year']} - {x['term']} (USh {x['total_fee']:,.0f})", axis=1))
            idx = fee_options.index[fee_options.apply(lambda x: f"{x['academic_year']} - {x['term']} (USh {x['total_fee']:,.0f})", axis=1) == chosen][0]
            fee_row = fee_options.loc[idx]
            issue_date = st.date_input("Issue Date", date.today())
            due_date = st.date_input("Due Date", date.today())
            notes = st.text_area("Notes")
            if st.button("Create Invoice"):
                try:
                    inv_no = generate_invoice_number()
                    total_amount = float(fee_row['total_fee'])
                    cur = conn.cursor()
                    # Create invoice with balance = total_amount
                    cur.execute("""
                        INSERT INTO invoices (invoice_number, student_id, issue_date, due_date, academic_year, term, total_amount, paid_amount, balance_amount, status, notes, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'Pending', ?, ?)
                    """, (inv_no, student_id, issue_date.isoformat(), due_date.isoformat(), fee_row['academic_year'], fee_row['term'], total_amount, total_amount, notes, st.session_state.user['username']))
                    conn.commit()
                    st.success(f"Invoice {inv_no} created for USh {total_amount:,.0f}")
                    log_action("create_invoice", f"Invoice {inv_no} for student {student_id} amount {total_amount}", st.session_state.user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error creating invoice: {e}")
    conn.close()
