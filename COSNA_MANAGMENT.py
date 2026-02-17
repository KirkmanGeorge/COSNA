"""
COSNA School Management System - PostgreSQL / Supabase version
Final improved single-file application with persistent database
"""

import streamlit as st
import psycopg2
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
import contextlib

# ────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────
APP_TITLE = "COSNA School Management System"
SCHOOL_NAME = "Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana"
SCHOOL_ADDRESS = "P.O.BOX 000, Kiyinda-Mityana"
SCHOOL_EMAIL = "info@cosnaschool.com Or: admin@cosnaschool.com"
REGISTRATION_FEE = 50000.0
SIMILARITY_THRESHOLD = 0.82
LOGO_FILENAME = "school_badge.png"
PAGE_LAYOUT = "wide"

st.set_page_config(page_title=APP_TITLE, layout=PAGE_LAYOUT, initial_sidebar_state="expanded")
st.title(APP_TITLE)
st.markdown("Students • Uniforms • Finances • Reports")

# ────────────────────────────────────────────────
# Connection context manager (short-lived, safe for Streamlit reruns)
# ────────────────────────────────────────────────
@contextlib.contextmanager
def db_connection():
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "aws-1-eu-central-1.pooler.supabase.com"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "postgres"),
            user=os.environ.get("DB_USER", "postgres.cqdryfzqgsivqfoxdpkb"),
            password=os.environ.get("DB_PASSWORD", "4249@Kakman")
        )
        yield conn
    finally:
        if conn:
            conn.close()

# ────────────────────────────────────────────────
# Safe date parser for PostgreSQL date strings
# ────────────────────────────────────────────────
def safe_parse_date(value):
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        cleaned = value.split(' ')[0].split('+')[0].split('T')[0]
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            try:
                y, m, d = map(int, cleaned.split('-'))
                return date(y, m, d)
            except:
                pass
    return date.today()

# ────────────────────────────────────────────────
# Utilities
# ────────────────────────────────────────────────
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
    if '$' in stored:
        # Modern salted format
        try:
            salt, hashed = stored.split('$', 1)
            return hash_password(provided, salt) == stored
        except:
            return False
    else:
        # Plain SHA-256 (for your current admin user)
        return hashlib.sha256(provided.encode('utf-8')).hexdigest() == stored

def generate_code(prefix="RCPT"):
    day = datetime.now().strftime("%d")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
    return f"{prefix}-{day}{random_chars}"

def generate_receipt_number(): return generate_code("RCPT")
def generate_invoice_number(): return generate_code("INV")
def generate_voucher_number(): return generate_code("VCH")

def safe_rerun():
    try:
        if hasattr(st, "rerun") and callable(st.rerun):
            st.rerun()
        else:
            st.session_state['_needs_refresh'] = True
            st.stop()
    except Exception:
        pass

# ────────────────────────────────────────────────
# DB helpers
# ────────────────────────────────────────────────
def table_has_column(conn, table_name, column_name):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        return cur.fetchone() is not None

def safe_alter_add_column(conn, table, column_def):
    col_name = column_def.split()[0]
    try:
        if not table_has_column(conn, table, col_name):
            with conn.cursor() as cur:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            conn.commit()
            return True
    except Exception:
        return False
    return False

# ────────────────────────────────────────────────
# Initialize DB and seed (full version - no omissions)
# ────────────────────────────────────────────────
def initialize_database():
    with db_connection() as conn:
        with conn.cursor() as cursor:
            # Core tables - PostgreSQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE,
                    password_hash TEXT,
                    role TEXT DEFAULT 'Clerk',
                    full_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expense_categories (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE,
                    category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense','Income'))
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS classes (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    normalized_name TEXT,
                    age INTEGER,
                    enrollment_date DATE,
                    class_id INTEGER,
                    student_type TEXT DEFAULT 'Returning',
                    registration_fee_paid INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(class_id) REFERENCES classes(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS uniform_categories (
                    id SERIAL PRIMARY KEY,
                    category TEXT UNIQUE,
                    normalized_category TEXT,
                    gender TEXT,
                    is_shared INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS uniforms (
                    id SERIAL PRIMARY KEY,
                    category_id INTEGER UNIQUE,
                    stock INTEGER DEFAULT 0,
                    unit_price REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(category_id) REFERENCES uniform_categories(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expenses (
                    id SERIAL PRIMARY KEY,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(category_id) REFERENCES expense_categories(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS incomes (
                    id SERIAL PRIMARY KEY,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(student_id) REFERENCES students(id),
                    FOREIGN KEY(category_id) REFERENCES expense_categories(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fee_structure (
                    id SERIAL PRIMARY KEY,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(class_id) REFERENCES classes(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS invoices (
                    id SERIAL PRIMARY KEY,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(student_id) REFERENCES students(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    invoice_id INTEGER,
                    receipt_number TEXT UNIQUE,
                    payment_date DATE,
                    amount REAL,
                    payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
                    reference_number TEXT,
                    received_by TEXT,
                    notes TEXT,
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(invoice_id) REFERENCES invoices(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    action TEXT,
                    details TEXT,
                    performed_by TEXT,
                    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS terms (
                    id SERIAL PRIMARY KEY,
                    academic_year TEXT,
                    term TEXT CHECK(term IN ('Term 1','Term 2','Term 3')),
                    start_date DATE,
                    end_date DATE,
                    UNIQUE(academic_year, term)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS staff (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    normalized_name TEXT,
                    staff_type TEXT CHECK(staff_type IN ('Teaching', 'Non-Teaching')),
                    position TEXT,
                    hire_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS staff_transactions (
                    id SERIAL PRIMARY KEY,
                    staff_id INTEGER,
                    date DATE,
                    transaction_type TEXT CHECK(transaction_type IN ('Salary', 'Allowance', 'Advance', 'Other')),
                    amount REAL,
                    description TEXT,
                    payment_method TEXT CHECK(payment_method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
                    voucher_number TEXT UNIQUE,
                    approved_by TEXT,
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(staff_id) REFERENCES staff(id)
                )
            ''')
            conn.commit()

        # Safe migrations (add missing columns if needed)
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
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT id, category, normalized_category FROM uniform_categories")
                rows = cur.fetchall()
                for r in rows:
                    if (r[2] is None or r[2] == "") and r[1]:
                        cur.execute("UPDATE uniform_categories SET normalized_category = %s WHERE id = %s",
                                    (normalize_text(r[1]), r[0]))
                conn.commit()
            except:
                pass

            try:
                cur.execute("SELECT id, name, normalized_name FROM students")
                rows = cur.fetchall()
                for r in rows:
                    if (r[2] is None or r[2] == "") and r[1]:
                        cur.execute("UPDATE students SET normalized_name = %s WHERE id = %s",
                                    (normalize_text(r[1]), r[0]))
                conn.commit()
            except:
                pass

            try:
                cur.execute("SELECT id, name, normalized_name FROM staff")
                rows = cur.fetchall()
                for r in rows:
                    if (r[2] is None or r[2] == "") and r[1]:
                        cur.execute("UPDATE staff SET normalized_name = %s WHERE id = %s",
                                    (normalize_text(r[1]), r[0]))
                conn.commit()
            except:
                pass

        # Ensure uniforms rows exist
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT id FROM uniform_categories")
                rows = cur.fetchall()
                for r in rows:
                    cat_id = r[0]
                    cur.execute("SELECT id FROM uniforms WHERE category_id = %s", (cat_id,))
                    if not cur.fetchone():
                        cur.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES (%s, 0, 0.0)", (cat_id,))
                conn.commit()
            except:
                pass
        # Seed default admin - FIXED: use plain SHA256 without random salt for default
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT COUNT(*) FROM users")
                if cur.fetchone()[0] == 0:
                    default_user = "admin"
                    default_pass = "costa2026"
                    # Plain SHA256 - no salt - so verify_password can handle it
                    hashed = hashlib.sha256(default_pass.encode('utf-8')).hexdigest()
                    print(f"DEBUG: Seeding admin with plain hash: {hashed}")  # optional - remove later
                    
                    cur.execute(
                        "INSERT INTO users (username, password_hash, role, full_name) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (default_user, hashed, "Admin", "Administrator")
                    )
                    conn.commit()
                    print("DEBUG: Admin seeded successfully (no-salt hash)")
            except Exception as e:
                print(f"DEBUG: Admin seeding failed: {str(e)}")
        

        # Seed uniform categories
        uniform_seeds = [
            ('Boys Main Shorts', 'boys', 0),
            ('Button Shirts Main', 'shared', 1),
            ('Boys Stockings', 'boys', 0),
            ('Boys Sports Shorts', 'boys', 0),
            ('Shared Sports T-Shirts', 'shared', 1),
            ('Girls Main Dresses', 'girls', 0)
        ]
        with conn.cursor() as cur:
            try:
                for name, gender, shared in uniform_seeds:
                    nname = normalize_text(name)
                    cur.execute(
                        "SELECT id FROM uniform_categories WHERE normalized_category = %s OR category = %s",
                        (nname, name)
                    )
                    row = cur.fetchone()
                    if not row:
                        cur.execute(
                            "INSERT INTO uniform_categories (category, normalized_category, gender, is_shared) "
                            "VALUES (%s, %s, %s, %s) RETURNING id",
                            (name, nname, gender, shared)
                        )
                        cat_id = cur.fetchone()[0]
                        conn.commit()
                        cur.execute(
                            "INSERT INTO uniforms (category_id, stock, unit_price) VALUES (%s, 0, 0.0) ON CONFLICT DO NOTHING",
                            (cat_id,)
                        )
                        conn.commit()
                    else:
                        cat_id = row[0]
                        cur.execute("SELECT id FROM uniforms WHERE category_id = %s", (cat_id,))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES (%s, 0, 0.0)", (cat_id,))
                            conn.commit()
            except:
                pass

        # Seed expense categories
        expense_seeds = [
            ('Medical', 'Expense'), ('Salaries', 'Expense'), ('Utilities', 'Expense'),
            ('Maintenance', 'Expense'), ('Supplies', 'Expense'), ('Transport', 'Expense'),
            ('Events', 'Expense'), ('Tuition Fees', 'Income'), ('Registration Fees', 'Income'),
            ('Uniform Sales', 'Income'), ('Donations', 'Income'), ('Other Income', 'Income'),
            ('Transfer In', 'Income'), ('Transfer Out', 'Expense')
        ]
        with conn.cursor() as cur:
            try:
                for cat, cat_type in expense_seeds:
                    cur.execute("SELECT id FROM expense_categories WHERE name = %s", (cat,))
                    if not cur.fetchone():
                        cur.execute("INSERT INTO expense_categories (name, category_type) VALUES (%s, %s)", (cat, cat_type))
                        conn.commit()
            except:
                pass

# Run initialization once when the script loads
initialize_database()
# ────────────────────────────────────────────────
# Audit logging
# ────────────────────────────────────────────────
def log_action(action, details="", performed_by="system"):
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (action, details, performed_by) VALUES (%s, %s, %s)",
                    (action, details, performed_by)
                )
            conn.commit()
    except Exception:
        pass  # silent fail, same as original


# ────────────────────────────────────────────────
# Authentication
# ────────────────────────────────────────────────
def get_user(username):
    try:
        with db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception:
        return None


if 'user' not in st.session_state:
    st.session_state.user = None


# ────────────────────────────────────────────────
# Logo handling
# ────────────────────────────────────────────────
def logo_exists():
    return os.path.exists(LOGO_FILENAME)


def save_uploaded_logo(uploaded_file):
    try:
        with open(LOGO_FILENAME, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return True
    except Exception:
        return False


# ────────────────────────────────────────────────
# Export helpers (Excel & PDF landscape) - unchanged logic
# ────────────────────────────────────────────────
def df_to_excel_bytes(df: pd.DataFrame, sheet_name="Sheet1"):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    buf.seek(0)
    return buf


def draw_wrapped_text(c, text, x, y, width, font='Times-Roman', size=10):
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
        y -= size + 1
    return y


def dataframe_to_pdf_bytes_landscape(df: pd.DataFrame, title="Report", logo_path=None):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

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

    c.setFont("Times-Bold", 14)
    c.drawString(title_x, y_top, title)

    y_top -= 20 + draw_h
    c.setFont("Times-Roman", 10)
    c.drawString(40, y_top, SCHOOL_NAME)
    y_top -= 12
    c.drawString(40, y_top, SCHOOL_ADDRESS)
    y_top -= 12
    c.drawString(40, y_top, SCHOOL_EMAIL)
    y_top -= 20

    y = y_top
    cols = list(df.columns)
    usable_width = width - 80
    col_width = usable_width / max(1, len(cols))

    c.setFont("Times-Bold", 10)
    for i, col in enumerate(cols):
        c.drawString(40 + i * col_width, y, str(col))
    y -= 12

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
            y = min(y, temp_y - 12)
        y -= 12

    c.setFont("Times-Italic", 7)
    c.drawString(40, 20, f"Generated: {datetime.now().isoformat()} • {APP_TITLE}")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def download_options(df: pd.DataFrame, filename_base="report", title="Report"):
    col1, col2 = st.columns([1, 1])
    with col1:
        excel_buf = df_to_excel_bytes(df)
        st.download_button(
            "Download Excel",
            excel_buf,
            f"{filename_base}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with col2:
        pdf_buf = dataframe_to_pdf_bytes_landscape(
            df, title=title,
            logo_path=LOGO_FILENAME if logo_exists() else None
        )
        st.download_button(
            "Download PDF (Landscape)",
            pdf_buf,
            f"{filename_base}.pdf",
            "application/pdf"
        )


# ────────────────────────────────────────────────
# Role-based access helper
# ────────────────────────────────────────────────
def require_role(allowed_roles):
    user = st.session_state.get('user')
    if not user:
        st.error("Not logged in")
        st.stop()
    if user.get('role') not in allowed_roles:
        st.error("You do not have permission to access this section")
        st.stop()


# ────────────────────────────────────────────────
# Login page (isolated)
# ────────────────────────────────────────────────
def show_login_page():
    st.markdown("### Login")
    col1, col2 = st.columns([1, 2])
    with col1:
        if logo_exists():
            try:
                st.image(LOGO_FILENAME, width=160)
            except Exception:
                pass
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")

            if submit:
                if not username or not password:
                    st.error("Enter username and password")
                else:
                    user = get_user(username)
                    if user and verify_password(user["password_hash"], password):
                        st.session_state.user = {
                            "id": user["id"],
                            "username": username,
                            "role": user.get("role", "Clerk"),
                            "full_name": user.get("full_name", username)
                        }
                        log_action("login", f"user {username} logged in", username)
                        safe_rerun()
                    else:
                        st.error("Invalid credentials")


# If not logged in → show only login
if not st.session_state.user:
    show_login_page()
    st.stop()


# ────────────────────────────────────────────────
# Get defined terms
# ────────────────────────────────────────────────
def get_terms():
    try:
        with db_connection() as conn:
            df = pd.read_sql(
                """
                SELECT id, academic_year, term, start_date, end_date
                FROM terms
                ORDER BY academic_year DESC, term DESC
                """,
                conn
            )
            return df
    except Exception:
        return pd.DataFrame()


# ────────────────────────────────────────────────
# Sidebar after login
# ────────────────────────────────────────────────
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
    st.subheader("Dashboard Filter")
    view_mode = st.radio("View Financials for", ["Current Term", "All Time"], index=0)

    terms_df = get_terms()
    if terms_df.empty:
        st.warning("No terms defined. Define terms in Fee Management.")
        selected_term_id = None
        selected_term = None
    else:
        term_options = terms_df.apply(lambda x: f"{x['academic_year']} - {x['term']}", axis=1).tolist()
        selected_term_str = st.selectbox("Select Current Term", term_options)
        selected_idx = term_options.index(selected_term_str)
        selected_term = terms_df.iloc[selected_idx]
        selected_term_id = int(selected_term['id'])

    if terms_df.empty:
        st.session_state.selected_term = None
    else:
        st.session_state.selected_term = selected_term.to_dict()
# ────────────────────────────────────────────────
# Main navigation
# ────────────────────────────────────────────────
page = st.sidebar.radio(
    "Menu",
    ["Dashboard", "Students", "Staff", "Uniforms", "Finances", "Financial Report",
     "Fee Management", "Cashbook", "Audit Log", "User Settings"]
)


# ────────────────────────────────────────────────
# Dashboard
# ────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Financial Overview")

    if view_mode == "Current Term":
        if st.session_state.selected_term is None:
            st.error("Select a term in the sidebar.")
            st.stop()
        ay = st.session_state.selected_term['academic_year']
        tm = st.session_state.selected_term['term']
        start_d = safe_parse_date(st.session_state.selected_term['start_date'])
        end_d = safe_parse_date(st.session_state.selected_term['end_date'])
        st.info(f"Showing data for {tm} {ay} ({start_d} to {end_d}). Change in sidebar.")
        inc_where = "WHERE date BETWEEN %s AND %s"
        exp_where = "WHERE date BETWEEN %s AND %s"
        out_where = "WHERE academic_year = %s AND term = %s AND status IN ('Pending','Partially Paid')"
        params_date = (start_d.isoformat(), end_d.isoformat())
        params_term = (ay, tm)
    else:
        st.info("Showing all-time financial overview")
        inc_where = ""
        exp_where = ""
        out_where = "WHERE status IN ('Pending','Partially Paid')"
        params_date = ()
        params_term = ()

    col1, col2, col3, col4 = st.columns(4)

    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COALESCE(SUM(amount),0) FROM incomes {inc_where}", params_date)
                total_income = cur.fetchone()[0] or 0
    except Exception:
        total_income = 0
    col1.metric("Total Income", f"USh {total_income:,.0f}")

    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COALESCE(SUM(amount),0) FROM expenses {exp_where}", params_date)
                total_expenses = cur.fetchone()[0] or 0
    except Exception:
        total_expenses = 0
    col2.metric("Total Expenses", f"USh {total_expenses:,.0f}")

    net_balance = total_income - total_expenses
    col3.metric("Net Balance", f"USh {net_balance:,.0f}", delta=f"USh {net_balance:,.0f}")

    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COALESCE(SUM(balance_amount),0) FROM invoices {out_where}", params_term)
                outstanding_fees = cur.fetchone()[0] or 0
    except Exception:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")

    colA, colB = st.columns(2)
    with colA:
        st.subheader("Recent Income (Last 5)")
        try:
            with db_connection() as conn:
                df_inc = pd.read_sql(
                    f"""
                    SELECT date as Date, receipt_number as "Receipt No", amount as Amount,
                           source as Source, payment_method as "Payment Method",
                           payer as Payer, description as Description
                    FROM incomes {inc_where}
                    ORDER BY date DESC LIMIT 5
                    """,
                    conn, params=params_date
                )
            if df_inc.empty:
                st.info("No income records yet")
            else:
                st.dataframe(df_inc, use_container_width=True)
        except Exception:
            st.info("No income records yet or error loading incomes")

    with colB:
        st.subheader("Recent Expenses (Last 5)")
        try:
            with db_connection() as conn:
                df_exp = pd.read_sql(
                    f"""
                    SELECT e.date as Date, e.voucher_number as "Voucher No", e.amount as Amount,
                           ec.name as Category, e.payment_method as "Payment Method",
                           e.payee as Payee, e.description as Description
                    FROM expenses e
                    LEFT JOIN expense_categories ec ON e.category_id = ec.id
                    {exp_where} ORDER BY e.date DESC LIMIT 5
                    """,
                    conn, params=params_date
                )
            if df_exp.empty:
                st.info("No expense records yet")
            else:
                st.dataframe(df_exp, use_container_width=True)
        except Exception:
            st.info("No expense records yet or error loading expenses")

    st.subheader("Monthly Financial Summary (Last 12 months)")
    try:
        with db_connection() as conn:
            df_monthly = pd.read_sql("""
                SELECT to_char(date, 'YYYY-MM') as Month,
                       SUM(amount) as "Total Amount",
                       'Income' as Type
                FROM incomes
                GROUP BY to_char(date, 'YYYY-MM')
                UNION ALL
                SELECT to_char(date, 'YYYY-MM') as Month,
                       SUM(amount) as "Total Amount",
                       'Expense' as Type
                FROM expenses
                GROUP BY to_char(date, 'YYYY-MM')
                ORDER BY Month DESC
                LIMIT 24
            """, conn)

        if df_monthly.empty:
            st.info("No monthly data available")
        else:
            df_pivot = df_monthly.pivot_table(
                index='Month', columns='Type', values='Total Amount', aggfunc='sum'
            ).fillna(0)
            df_pivot['Net Balance'] = df_pivot.get('Income', 0) - df_pivot.get('Expense', 0)
            st.dataframe(df_pivot, use_container_width=True)
            download_options(
                df_pivot.reset_index(),
                filename_base="monthly_financial_summary",
                title="Monthly Financial Summary"
            )
    except Exception:
        st.info("No monthly data available")


# ────────────────────────────────────────────────
# Students (full page with all 5 tabs)
# ────────────────────────────────────────────────
elif page == "Students":
    st.header("Students")
    tab_view, tab_add, tab_edit, tab_delete, tab_fees = st.tabs(
        ["View & Export", "Add Student", "Edit Student", "Delete Student", "Student Fees"]
    )

    # ── View & Export ──
    with tab_view:
        try:
            with db_connection() as conn:
                classes = ["All Classes"] + [
                    r[0] for r in conn.cursor().execute("SELECT name FROM classes ORDER BY name").fetchall()
                ]
        except Exception:
            classes = ["All Classes"]

        selected_class = st.selectbox("Filter by Class", classes)
        student_types = ["All Types", "New", "Returning"]
        selected_type = st.selectbox("Filter by Student Type", student_types)

        try:
            with db_connection() as conn:
                query = """
                    SELECT s.id as ID, s.name as Name, s.age as Age,
                           s.enrollment_date as "Enrollment Date",
                           c.name AS "Class Name", s.student_type as "Student Type",
                           s.registration_fee_paid as "Registration Fee Paid"
                    FROM students s
                    LEFT JOIN classes c ON s.class_id = c.id
                """
                conditions = []
                params = []
                if selected_class != "All Classes":
                    conditions.append("c.name = %s")
                    params.append(selected_class)
                if selected_type != "All Types":
                    conditions.append("s.student_type = %s")
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

    # ── Add Student ──
    with tab_add:
        st.subheader("Add Student")
        with st.expander("Add a new class (if not in list)", expanded=False):
            new_class_name = st.text_input("New Class Name", key="new_class_input", placeholder="e.g. P.4, S.1 Gold, Baby")
            if st.button("Create Class", key="create_class_btn", use_container_width=True):
                if not new_class_name.strip():
                    st.error("Enter class name")
                else:
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("SELECT 1 FROM classes WHERE LOWER(name) = LOWER(%s)", (new_class_name.strip(),))
                                if cur.fetchone():
                                    st.error(f"Class '{new_class_name}' already exists")
                                else:
                                    cur.execute("INSERT INTO classes (name) VALUES (%s)", (new_class_name.strip(),))
                                    conn.commit()
                                    st.success(f"Class '{new_class_name}' created")
                                    log_action("add_class", f"Created class: {new_class_name}", st.session_state.user['username'])
                                    safe_rerun()
                    except Exception as e:
                        st.error(f"Error creating class: {str(e)}")

        with st.form("add_student_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Full Name")
                age = st.number_input("Age", min_value=3, max_value=30, value=10)
                enroll_date = st.date_input("Enrollment Date", value=date.today())
            with col2:
                try:
                    with db_connection() as conn:
                        cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                        cls_options = cls_df["name"].tolist() if not cls_df.empty else []
                except:
                    cls_options = []
                cls_name = st.selectbox("Class", ["-- No class --"] + cls_options)
                cls_id = None
                if cls_name != "-- No class --":
                    try:
                        with db_connection() as conn:
                            cls_id_df = pd.read_sql("SELECT id FROM classes WHERE name = %s", conn, params=(cls_name,))
                            cls_id = int(cls_id_df.iloc[0]['id']) if not cls_id_df.empty else None
                    except:
                        pass
                student_type = st.radio("Student Type", ["New", "Returning"], horizontal=True)

            if student_type == "New":
                st.info(f"Registration Fee: USh {REGISTRATION_FEE:,.0f} (Mandatory for new students)")

            submitted = st.form_submit_button("Add Student")
            if submitted:
                if not name or cls_id is None:
                    st.error("Provide student name and class")
                else:
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("SELECT normalized_name FROM students")
                                existing = [r[0] for r in cur.fetchall() if r[0]]
                                nname = normalize_text(name)
                                dup, match = is_near_duplicate(nname, existing)
                                if dup:
                                    st.warning(f"A similar student already exists: '{match}'. Please verify before adding.")
                                else:
                                    cur.execute("""
                                        INSERT INTO students (name, normalized_name, age, enrollment_date, class_id, student_type, registration_fee_paid)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                                        RETURNING id
                                    """, (name.strip(), nname, int(age), enroll_date.isoformat(), cls_id, student_type,
                                          1 if student_type == "New" else 0))
                                    student_id = cur.fetchone()[0]
                                    conn.commit()

                                    if student_type == "New":
                                        try:
                                            cur.execute("SELECT id FROM expense_categories WHERE name = 'Registration Fees'")
                                            cat_row = cur.fetchone()
                                            cat_id = cat_row[0] if cat_row else None
                                            cur.execute("""
                                                INSERT INTO incomes (date, receipt_number, amount, source, category_id, description,
                                                                     payment_method, payer, received_by, created_by)
                                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                            """, (enroll_date.isoformat(), generate_receipt_number(), REGISTRATION_FEE,
                                                  "Registration Fees", cat_id, f"Registration fee for {name}", "Cash", name,
                                                  st.session_state.user['username'], st.session_state.user['username']))
                                        except Exception:
                                            cur.execute("""
                                                INSERT INTO incomes (date, amount, source, created_by)
                                                VALUES (%s, %s, %s, %s)
                                            """, (enroll_date.isoformat(), REGISTRATION_FEE,
                                                  f"Registration fee for {name}", st.session_state.user['username']))
                                        conn.commit()

                                    st.success("Student added successfully")
                                    log_action("add_student", f"Added student {name} (ID: {student_id})", st.session_state.user['username'])
                    except Exception as e:
                        st.error(f"Error adding student: {e}")

    # ── Edit Student ──
    with tab_edit:
        st.subheader("Edit Student")
        try:
            with db_connection() as conn:
                students = pd.read_sql(
                    """
                    SELECT s.id, s.name, c.name as class_name
                    FROM students s
                    LEFT JOIN classes c ON s.class_id = c.id
                    ORDER BY s.name
                    """,
                    conn
                )
        except Exception:
            students = pd.DataFrame()

        if students.empty:
            st.info("No students available to edit")
        else:
            selected = st.selectbox(
                "Select Student to Edit",
                students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1)
            )
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))

            try:
                with db_connection() as conn:
                    student_row = pd.read_sql("SELECT * FROM students WHERE id = %s", conn, params=(student_id,)).iloc[0]
            except Exception:
                st.error("Could not load student details")
                student_row = None

            if student_row is not None:
                with st.form("edit_student_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        name = st.text_input("Full Name", value=student_row['name'])
                        age = st.number_input("Age", min_value=3, max_value=30, value=student_row['age'])
                        enroll_date = st.date_input(
                            "Enrollment Date",
                            value=safe_parse_date(student_row['enrollment_date'])
                        )
                    with col2:
                        try:
                            with db_connection() as conn:
                                cls_df = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                                cls_options = cls_df["name"].tolist() if not cls_df.empty else []
                        except:
                            cls_options = []

                        if student_row['class_id']:
                            try:
                                with db_connection() as conn:
                                    cls_name_df = pd.read_sql(
                                        "SELECT name FROM classes WHERE id = %s",
                                        conn,
                                        params=(student_row['class_id'],)
                                    )
                                    current_cls_name = cls_name_df.iloc[0]['name'] if not cls_name_df.empty else "-- No class --"
                            except:
                                current_cls_name = "-- No class --"
                        else:
                            current_cls_name = "-- No class --"

                        cls_name = st.selectbox(
                            "Class",
                            cls_options,
                            index=cls_options.index(current_cls_name) if current_cls_name in cls_options else 0
                        )
                        cls_id = None
                        if cls_name in cls_options:
                            try:
                                with db_connection() as conn:
                                    cls_id_df = pd.read_sql("SELECT id FROM classes WHERE name = %s", conn, params=(cls_name,))
                                    cls_id = int(cls_id_df.iloc[0]['id']) if not cls_id_df.empty else None
                            except:
                                pass

                        student_type = st.radio(
                            "Student Type",
                            ["New", "Returning"],
                            index=0 if student_row['student_type'] == "New" else 1
                        )

                    submitted = st.form_submit_button("Update Student")
                    if submitted:
                        if not name:
                            st.error("Provide student name")
                        else:
                            try:
                                with db_connection() as conn:
                                    with conn.cursor() as cur:
                                        cur.execute("SELECT normalized_name FROM students WHERE id != %s", (student_id,))
                                        existing = [r[0] for r in cur.fetchall() if r[0]]
                                        nname = normalize_text(name)
                                        dup, match = is_near_duplicate(nname, existing)
                                        if dup:
                                            st.warning(f"A similar student already exists: '{match}'. Please verify before updating.")
                                        else:
                                            cur.execute("""
                                                UPDATE students
                                                SET name = %s, normalized_name = %s, age = %s,
                                                    enrollment_date = %s, class_id = %s, student_type = %s
                                                WHERE id = %s
                                            """, (name.strip(), nname, int(age), enroll_date.isoformat(),
                                                  cls_id, student_type, student_id))
                                            conn.commit()
                                            st.success("Student updated successfully")
                                            log_action("edit_student", f"Updated student {name} (ID: {student_id})", st.session_state.user['username'])
                                            safe_rerun()
                            except Exception as e:
                                st.error(f"Error updating student: {e}")

    # ── Delete Student ──
    with tab_delete:
        require_role(["Admin"])
        st.subheader("Delete Student")
        st.warning("Deleting a student may affect related records like invoices and payments. Proceed with caution.")

        try:
            with db_connection() as conn:
                students = pd.read_sql(
                    """
                    SELECT s.id, s.name, c.name as class_name
                    FROM students s
                    LEFT JOIN classes c ON s.class_id = c.id
                    ORDER BY s.name
                    """,
                    conn
                )
        except Exception:
            students = pd.DataFrame()

        if students.empty:
            st.info("No students available to delete")
        else:
            selected = st.selectbox(
                "Select Student to Delete",
                students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1),
                key="select_student_to_delete"
            )
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))

            if st.checkbox("Confirm deletion", key=f"confirm_delete_student_{student_id}"):
                if st.button("Delete Student", key=f"delete_student_btn_{student_id}"):
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("DELETE FROM students WHERE id = %s", (student_id,))
                            conn.commit()
                        st.success("Student deleted successfully")
                        log_action("delete_student", f"Deleted student ID: {student_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        if "foreign key" in str(e).lower():
                            st.error("Cannot delete student due to related records (e.g., invoices, payments). Delete those first.")
                        else:
                            st.error(f"Error deleting student: {e}")

    # ── Student Fees ──
    with tab_fees:
        st.subheader("Outstanding Fees Breakdown")

        if view_mode == "Current Term" and st.session_state.selected_term:
            ay = st.session_state.selected_term['academic_year']
            tm = st.session_state.selected_term['term']
            out_where = "WHERE academic_year = %s AND term = %s AND status IN ('Pending', 'Partially Paid')"
            params = (ay, tm)
        else:
            out_where = "WHERE status IN ('Pending', 'Partially Paid')"
            params = ()

        try:
            with db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COALESCE(SUM(balance_amount), 0) FROM invoices {out_where}", params)
                    total_outstanding = cur.fetchone()[0]
            st.metric("Total Outstanding Fees", f"USh {total_outstanding:,.0f}")
        except:
            st.metric("Total Outstanding Fees", "USh 0")

        try:
            with db_connection() as conn:
                class_df = pd.read_sql(f"""
                    SELECT c.name as "Class Name", COALESCE(SUM(i.balance_amount), 0) as "Class Outstanding"
                    FROM invoices i
                    JOIN students s ON i.student_id = s.id
                    JOIN classes c ON s.class_id = c.id
                    {out_where}
                    GROUP BY c.name
                    ORDER BY "Class Outstanding" DESC
                """, conn, params=params)
            if class_df.empty:
                st.info("No outstanding fees at the moment.")
            else:
                st.dataframe(class_df, hide_index=True, use_container_width=True)
                download_options(class_df, filename_base="outstanding_by_class", title="Outstanding Fees by Class")
        except:
            st.info("Error loading class outstanding summary")

        selected_class = st.selectbox(
            "Select Class to View Student Details",
            [""] + (class_df['Class Name'].tolist() if 'class_df' in locals() and not class_df.empty else []),
            format_func=lambda x: "— Select a class —" if x == "" else x
        )

        if selected_class:
            student_params = params + (selected_class,)
            try:
                with db_connection() as conn:
                    student_df = pd.read_sql(f"""
                        SELECT s.name as Name, COALESCE(SUM(i.balance_amount), 0) as Outstanding
                        FROM invoices i
                        JOIN students s ON i.student_id = s.id
                        JOIN classes c ON s.class_id = c.id
                        {out_where} AND c.name = %s
                        GROUP BY s.id, s.name
                        ORDER BY Outstanding DESC
                    """, conn, params=student_params)
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
            except:
                st.info("Error loading student outstanding details")

        st.subheader("Student Fee Management")
        try:
            with db_connection() as conn:
                students = pd.read_sql(
                    """
                    SELECT s.id, s.name, c.name as class_name
                    FROM students s
                    LEFT JOIN classes c ON s.class_id = c.id
                    ORDER BY s.name
                    """,
                    conn
                )
        except:
            students = pd.DataFrame()

        if students.empty:
            st.info("No students available")
        else:
            selected = st.selectbox(
                "Select Student",
                students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1)
            )
            student_name = selected.split(" - ")[0]
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))

            try:
                if view_mode == "Current Term" and st.session_state.selected_term:
                    inv_where = "WHERE student_id = %s AND academic_year = %s AND term = %s"
                    inv_params = (student_id, ay, tm)
                else:
                    inv_where = "WHERE student_id = %s"
                    inv_params = (student_id,)

                with db_connection() as conn:
                    invoices = pd.read_sql(f"SELECT * FROM invoices {inv_where} ORDER BY issue_date DESC", conn, params=inv_params)
            except Exception:
                invoices = pd.DataFrame()

            if invoices.empty:
                st.info("No invoices for this student")
            else:
                display_invoices = invoices[[
                    'invoice_number', 'issue_date', 'due_date', 'total_amount',
                    'paid_amount', 'balance_amount', 'status', 'notes'
                ]].rename(columns={
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
                with db_connection() as conn:
                    payments = pd.read_sql(
                        f"""
                        SELECT p.payment_date, p.amount, p.payment_method, p.receipt_number,
                               p.reference_number, p.notes
                        FROM payments p
                        JOIN invoices i ON p.invoice_id = i.id
                        {inv_where}
                        ORDER BY p.payment_date DESC
                        """,
                        conn, params=inv_params
                    )
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
                    download_options(
                        display_payments,
                        filename_base=f"payments_student_{student_id}",
                        title=f"Payments for {student_name}"
                    )
            except Exception:
                st.info("No payments or error loading payments")

            st.subheader("Pay Outstanding Invoice")
            outstanding_invoices = invoices[invoices['status'].isin(['Pending', 'Partially Paid'])]
            if outstanding_invoices.empty:
                st.info("No outstanding invoices to pay")
            else:
                chosen_inv = st.selectbox("Select Invoice to Pay", outstanding_invoices['invoice_number'].tolist())
                inv_row = outstanding_invoices[outstanding_invoices['invoice_number'] == chosen_inv].iloc[0]
                inv_id = int(inv_row['id'])
                inv_balance = float(inv_row['balance_amount'] if pd.notna(inv_row['balance_amount']) else inv_row['total_amount'])
                st.write(f"Invoice {chosen_inv} — Balance: USh {inv_balance:,.0f}")

                with st.form("pay_invoice_form"):
                    pay_date = st.date_input("Payment Date", date.today())
                    pay_amount = st.number_input("Amount (USh)", min_value=0.0, max_value=float(inv_balance), value=float(inv_balance), step=100.0)
                    pay_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
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
                                with db_connection() as conn:
                                    conn.autocommit = False
                                    with conn.cursor() as cur:
                                        cur.execute("SELECT paid_amount, balance_amount, total_amount FROM invoices WHERE id = %s FOR UPDATE", (inv_id,))
                                        inv_check = cur.fetchone()
                                        if not inv_check:
                                            conn.rollback()
                                            st.error("Invoice not found")
                                        else:
                                            current_balance = inv_check[1] if inv_check[1] is not None else inv_check[2]
                                            if pay_amount > current_balance + 0.0001:
                                                conn.rollback()
                                                st.error("Payment exceeds current balance. Refresh and try again.")
                                            else:
                                                new_paid = (inv_check[0] or 0) + pay_amount
                                                new_balance = current_balance - pay_amount
                                                new_status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid'
                                                cur.execute(
                                                    "UPDATE invoices SET paid_amount = %s, balance_amount = %s, status = %s WHERE id = %s",
                                                    (new_paid, new_balance, new_status, inv_id)
                                                )
                                                cur.execute("""
                                                    INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, payment_method,
                                                                          reference_number, received_by, notes, created_by)
                                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                                """, (inv_id, pay_receipt, pay_date.isoformat(), pay_amount, pay_method, pay_ref,
                                                      st.session_state.user['username'], pay_notes, st.session_state.user['username']))

                                                cur.execute("SELECT id FROM expense_categories WHERE name = 'Tuition Fees'")
                                                cat_row = cur.fetchone()
                                                cat_id = cat_row[0] if cat_row else None
                                                cur.execute("""
                                                    INSERT INTO incomes (date, receipt_number, amount, source, category_id, payment_method,
                                                                         payer, received_by, created_by, description)
                                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                                """, (pay_date.isoformat(), pay_receipt, pay_amount, "Tuition Fees", cat_id,
                                                      pay_method, student_name, st.session_state.user['username'],
                                                      st.session_state.user['username'], pay_notes))

                                                conn.commit()
                                                st.success("Payment recorded and invoice updated")
                                                log_action("pay_invoice", f"Payment {pay_amount} for invoice {chosen_inv}", st.session_state.user['username'])
                                                safe_rerun()
                            except Exception as e:
                                if 'conn' in locals():
                                    conn.rollback()
                                st.error(f"Error recording payment: {e}")
                            finally:
                                if 'conn' in locals():
                                    conn.autocommit = True

            st.subheader("Student Ledger")
            try:
                with db_connection() as conn:
                    ledger_df = pd.read_sql(f"""
                        SELECT 
                            'Invoice' AS Type, 
                            issue_date AS Date, 
                            invoice_number AS Reference, 
                            total_amount AS Debit, 
                            0 AS Credit
                        FROM invoices 
                        WHERE student_id = %s
                        
                        UNION ALL
                        
                        SELECT 
                            'Payment' AS Type, 
                            payment_date AS Date, 
                            receipt_number AS Reference, 
                            0 AS Debit, 
                            amount AS Credit
                        FROM payments p 
                        JOIN invoices i ON p.invoice_id = i.id 
                        WHERE i.student_id = %s
                        
                        ORDER BY Date ASC
                    """, conn, params=(student_id, student_id))

                if ledger_df.empty:
                    st.info("No ledger entries for this student yet.")
                else:
                    ledger_df['Date'] = pd.to_datetime(ledger_df['Date']).dt.strftime('%Y-%m-%d')
                    ledger_df['Balance'] = (ledger_df['Debit'] - ledger_df['Credit']).cumsum()
                    ledger_df['Balance'] = ledger_df['Balance'].round(0).astype(int)
                    st.dataframe(ledger_df, use_container_width=True, hide_index=True)
                    download_options(
                        ledger_df,
                        filename_base=f"student_ledger_{student_id}",
                        title=f"Ledger for {student_name}"
                    )
            except Exception as e:
                st.error(f"Ledger could not be loaded: {str(e)}")
# ────────────────────────────────────────────────
# Staff (full page with all 5 tabs)
# ────────────────────────────────────────────────
elif page == "Staff":
    st.header("Staff")
    tab_view, tab_add, tab_edit, tab_delete, tab_trans = st.tabs(
        ["View & Export", "Add Staff", "Edit Staff", "Delete Staff", "Staff Transactions"]
    )

    # ── View & Export ──
    with tab_view:
        staff_types = ["All Types", "Teaching", "Non-Teaching"]
        selected_type = st.selectbox("Filter by Staff Type", staff_types)

        try:
            with db_connection() as conn:
                query = """
                    SELECT id as ID, name as Name, staff_type as "Staff Type",
                           position as Position, hire_date as "Hire Date"
                    FROM staff
                """
                conditions = []
                params = []
                if selected_type != "All Types":
                    conditions.append("staff_type = %s")
                    params.append(selected_type)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                df = pd.read_sql_query(query, conn, params=params)

            if df.empty:
                st.info("No staff found")
            else:
                st.dataframe(df, use_container_width=True)
                download_options(df, filename_base="staff", title="Staff Report")
        except Exception:
            st.info("No staff records yet or error loading data")

    # ── Add Staff ──
    with tab_add:
        st.subheader("Add Staff")
        with st.form("add_staff_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Full Name")
                staff_type = st.radio("Staff Type", ["Teaching", "Non-Teaching"], horizontal=True)
            with col2:
                position = st.text_input("Position")
                hire_date = st.date_input("Hire Date", value=date.today())

            submitted = st.form_submit_button("Add Staff")
            if submitted:
                if not name:
                    st.error("Provide staff name")
                else:
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("SELECT normalized_name FROM staff")
                                existing = [r[0] for r in cur.fetchall() if r[0]]
                                nname = normalize_text(name)
                                dup, match = is_near_duplicate(nname, existing)
                                if dup:
                                    st.warning(f"A similar staff already exists: '{match}'. Please verify before adding.")
                                else:
                                    cur.execute("""
                                        INSERT INTO staff (name, normalized_name, staff_type, position, hire_date)
                                        VALUES (%s, %s, %s, %s, %s)
                                        RETURNING id
                                    """, (name.strip(), nname, staff_type, position, hire_date.isoformat()))
                                    staff_id = cur.fetchone()[0]
                                    conn.commit()
                                    st.success("Staff added successfully")
                                    log_action("add_staff", f"Added staff {name} (ID: {staff_id})", st.session_state.user['username'])
                    except Exception as e:
                        st.error(f"Error adding staff: {e}")

    # ── Edit Staff ──
    with tab_edit:
        st.subheader("Edit Staff")
        try:
            with db_connection() as conn:
                staff = pd.read_sql("SELECT id, name, staff_type, position, hire_date FROM staff ORDER BY name", conn)
        except Exception:
            staff = pd.DataFrame()

        if staff.empty:
            st.info("No staff available to edit")
        else:
            selected = st.selectbox(
                "Select Staff to Edit",
                staff.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1)
            )
            staff_id = int(selected.split("(ID: ")[1].replace(")", ""))

            try:
                with db_connection() as conn:
                    staff_row = pd.read_sql("SELECT * FROM staff WHERE id = %s", conn, params=(staff_id,)).iloc[0]
            except Exception:
                st.error("Could not load staff details")
                staff_row = None

            if staff_row is not None:
                with st.form("edit_staff_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        name = st.text_input("Full Name", value=staff_row['name'])
                        staff_type = st.radio("Staff Type", ["Teaching", "Non-Teaching"],
                                              index=0 if staff_row['staff_type'] == "Teaching" else 1)
                    with col2:
                        position = st.text_input("Position", value=staff_row['position'])
                        hire_date = st.date_input(
                            "Hire Date",
                            value=safe_parse_date(staff_row['hire_date'])
                        )

                    submitted = st.form_submit_button("Update Staff")
                    if submitted:
                        if not name:
                            st.error("Provide staff name")
                        else:
                            try:
                                with db_connection() as conn:
                                    with conn.cursor() as cur:
                                        cur.execute("SELECT normalized_name FROM staff WHERE id != %s", (staff_id,))
                                        existing = [r[0] for r in cur.fetchall() if r[0]]
                                        nname = normalize_text(name)
                                        dup, match = is_near_duplicate(nname, existing)
                                        if dup:
                                            st.warning(f"A similar staff already exists: '{match}'. Please verify before updating.")
                                        else:
                                            cur.execute("""
                                                UPDATE staff
                                                SET name = %s, normalized_name = %s, staff_type = %s, position = %s, hire_date = %s
                                                WHERE id = %s
                                            """, (name.strip(), nname, staff_type, position, hire_date.isoformat(), staff_id))
                                            conn.commit()
                                            st.success("Staff updated successfully")
                                            log_action("edit_staff", f"Updated staff {name} (ID: {staff_id})", st.session_state.user['username'])
                                            safe_rerun()
                            except Exception as e:
                                st.error(f"Error updating staff: {e}")

    # ── Delete Staff ──
    with tab_delete:
        require_role(["Admin"])
        st.subheader("Delete Staff")
        st.warning("Deleting a staff may affect related records like transactions. Proceed with caution.")

        try:
            with db_connection() as conn:
                staff = pd.read_sql("SELECT id, name FROM staff ORDER BY name", conn)
        except Exception:
            staff = pd.DataFrame()

        if staff.empty:
            st.info("No staff available to delete")
        else:
            selected = st.selectbox(
                "Select Staff to Delete",
                staff.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1),
                key="select_staff_to_delete"
            )
            staff_id = int(selected.split("(ID: ")[1].replace(")", ""))

            if st.checkbox("Confirm deletion", key=f"confirm_delete_staff_{staff_id}"):
                if st.button("Delete Staff", key=f"delete_staff_btn_{staff_id}"):
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("DELETE FROM staff WHERE id = %s", (staff_id,))
                            conn.commit()
                        st.success("Staff deleted successfully")
                        log_action("delete_staff", f"Deleted staff ID: {staff_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        if "foreign key" in str(e).lower():
                            st.error("Cannot delete staff due to related records (e.g., transactions). Delete those first.")
                        else:
                            st.error(f"Error deleting staff: {e}")

    # ── Staff Transactions ──
    with tab_trans:
        st.subheader("Staff Transactions")

        try:
            with db_connection() as conn:
                staff = pd.read_sql("SELECT id, name FROM staff ORDER BY name", conn)
        except Exception:
            staff = pd.DataFrame()

        if staff.empty:
            st.info("No staff available")
        else:
            selected = st.selectbox(
                "Select Staff",
                staff.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1)
            )
            staff_name = selected.split(" (ID: ")[0]
            staff_id = int(selected.split("(ID: ")[1].replace(")", ""))

            try:
                with db_connection() as conn:
                    trans_df = pd.read_sql(
                        """
                        SELECT date as Date, transaction_type as Type, amount as Amount,
                               description as Description, payment_method as "Payment Method",
                               voucher_number as "Voucher No"
                        FROM staff_transactions
                        WHERE staff_id = %s
                        ORDER BY date DESC
                        """,
                        conn, params=(staff_id,)
                    )
                if trans_df.empty:
                    st.info("No transactions for this staff")
                else:
                    st.dataframe(trans_df, use_container_width=True)
                    download_options(
                        trans_df,
                        filename_base=f"staff_transactions_{staff_id}",
                        title=f"Transactions for {staff_name}"
                    )
            except Exception:
                st.info("Error loading transactions")

            st.subheader("Record Transaction")
            with st.form("staff_transaction_form"):
                trans_date = st.date_input("Date", date.today())
                trans_type = st.selectbox("Type", ["Salary", "Allowance", "Advance", "Other"])
                amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
                description = st.text_area("Description")
                pay_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                voucher_no = st.text_input("Voucher Number", value=generate_voucher_number())
                approved_by = st.text_input("Approved By")
                submit_trans = st.form_submit_button("Record Transaction")

                if submit_trans:
                    if amount <= 0:
                        st.error("Enter a positive amount")
                    else:
                        try:
                            with db_connection() as conn:
                                conn.autocommit = False
                                with conn.cursor() as cur:
                                    cur.execute("SELECT id FROM expense_categories WHERE name = 'Salaries'")
                                    cat_row = cur.fetchone()
                                    cat_id = cat_row[0] if cat_row else None

                                    cur.execute("""
                                        INSERT INTO staff_transactions (staff_id, date, transaction_type, amount, description,
                                                                        payment_method, voucher_number, approved_by, created_by)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (staff_id, trans_date.isoformat(), trans_type, amount, description,
                                          pay_method, voucher_no, approved_by, st.session_state.user['username']))

                                    cur.execute("""
                                        INSERT INTO expenses (date, voucher_number, amount, category_id, description,
                                                              payment_method, payee, approved_by, created_by)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (trans_date.isoformat(), voucher_no, amount, cat_id,
                                          f"{trans_type} for {staff_name}: {description}", pay_method,
                                          staff_name, approved_by, st.session_state.user['username']))

                                conn.commit()
                                st.success("Transaction recorded")
                                log_action("staff_transaction", f"{trans_type} {amount} for staff {staff_id}", st.session_state.user['username'])
                                safe_rerun()
                        except Exception as e:
                            if 'conn' in locals():
                                conn.rollback()
                            if "unique" in str(e).lower() and "voucher_number" in str(e).lower():
                                st.error("Voucher number already exists")
                            else:
                                st.error(f"Error recording transaction: {e}")
                        finally:
                            if 'conn' in locals():
                                conn.autocommit = True

            st.subheader("Staff Ledger")
            try:
                with db_connection() as conn:
                    ledger_df = pd.read_sql(
                        """
                        SELECT date as Date, transaction_type as Type, amount as Debit,
                               description as Description, voucher_number as "Voucher No"
                        FROM staff_transactions
                        WHERE staff_id = %s
                        ORDER BY date
                        """,
                        conn, params=(staff_id,)
                    )
                if not ledger_df.empty:
                    ledger_df['Balance'] = ledger_df['Debit'].cumsum()
                    st.dataframe(ledger_df, use_container_width=True)
                    download_options(
                        ledger_df,
                        filename_base=f"staff_ledger_{staff_id}",
                        title=f"Ledger for {staff_name}"
                    )
                else:
                    st.info("No ledger entries for this staff")
            except Exception:
                st.info("Error loading staff ledger")
# ────────────────────────────────────────────────
# Uniforms (full page with all 6 tabs)
# ────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms – Inventory & Sales")

    def get_inventory_df():
        try:
            with db_connection() as conn:
                return pd.read_sql_query("""
                    SELECT uc.id as cat_id, uc.category as Category, uc.gender as Gender,
                           uc.is_shared as "Is Shared", u.stock as Stock, u.unit_price as "Unit Price"
                    FROM uniforms u
                    JOIN uniform_categories uc ON u.category_id = uc.id
                    ORDER BY uc.gender, uc.category
                """, conn)
        except Exception:
            return pd.DataFrame()

    tab_view, tab_update, tab_sale, tab_manage, tab_edit_cat, tab_delete_cat = st.tabs(
        ["View Inventory", "Update Stock/Price", "Record Sale", "Add Category", "Edit Category", "Delete Category"]
    )

    with tab_view:
        inventory_df = get_inventory_df()
        if inventory_df.empty:
            st.info("No inventory records")
        else:
            display_df = inventory_df.copy()
            display_df['Unit Price'] = display_df['Unit Price'].apply(lambda x: f"USh {x:,.0f}" if pd.notna(x) else "N/A")
            st.dataframe(display_df, use_container_width=True)

            total_stock = inventory_df['Stock'].sum()
            total_value = (inventory_df['Stock'] * inventory_df['Unit Price']).sum()
            col1, col2 = st.columns(2)
            col1.metric("Total Items in Stock", f"{int(total_stock):,}")
            col2.metric("Total Inventory Value", f"USh {total_value:,.0f}")

            download_options(inventory_df, filename_base="uniform_inventory", title="Uniform Inventory Report")

    with tab_update:
        st.subheader("Update Stock & Price")
        try:
            with db_connection() as conn:
                categories_df = pd.read_sql(
                    """
                    SELECT uc.id, uc.category, u.stock, u.unit_price
                    FROM uniform_categories uc
                    JOIN uniforms u ON uc.id = u.category_id
                    ORDER BY uc.category
                    """,
                    conn
                )
        except Exception:
            categories_df = pd.DataFrame()

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
                        with db_connection() as conn:
                            conn.autocommit = False
                            final_stock = int(set_stock) if set_stock != current_stock else current_stock + int(add_stock)
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE uniforms SET stock = %s, unit_price = %s WHERE category_id = %s",
                                    (final_stock, float(new_price), cat_id)
                                )
                            conn.commit()
                            st.success("Inventory updated")
                            log_action(
                                "update_uniform",
                                f"Updated category {selected_category}: stock={final_stock}, price={new_price}",
                                st.session_state.user['username']
                            )
                            safe_rerun()
                    except Exception as e:
                        st.error(f"Error updating inventory: {e}")

    with tab_sale:
        st.subheader("Record Uniform Sale")
        try:
            with db_connection() as conn:
                inv_df = pd.read_sql("""
                    SELECT uc.id as cat_id, uc.category, u.stock, u.unit_price
                    FROM uniform_categories uc
                    JOIN uniforms u ON uc.id = u.category_id
                    ORDER BY uc.category
                """, conn)
        except Exception:
            inv_df = pd.DataFrame()

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
            payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
            receipt_no = st.text_input("Receipt Number", value=generate_receipt_number())
            notes = st.text_area("Notes")

            if st.button("Record Sale"):
                if qty <= 0:
                    st.error("Enter a valid quantity")
                elif qty > available_stock:
                    st.error("Insufficient stock")
                else:
                    try:
                        with db_connection() as conn:
                            conn.autocommit = False
                            with conn.cursor() as cur:
                                cur.execute("SELECT stock FROM uniforms WHERE category_id = %s FOR UPDATE", (cat_id,))
                                current = cur.fetchone()[0]
                                if current < qty:
                                    conn.rollback()
                                    st.error("Stock changed; insufficient stock now")
                                else:
                                    new_stock = current - qty
                                    cur.execute("UPDATE uniforms SET stock = %s WHERE category_id = %s", (new_stock, cat_id))

                                    amount = qty * unit_price
                                    cur.execute("SELECT id FROM expense_categories WHERE name = 'Uniform Sales'")
                                    cat_row = cur.fetchone()
                                    cat_id_income = cat_row[0] if cat_row else None

                                    cur.execute("""
                                        INSERT INTO incomes (date, receipt_number, amount, source, category_id, description,
                                                             payment_method, payer, received_by, created_by)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (date.today().isoformat(), receipt_no, amount, "Uniform Sales", cat_id_income,
                                          f"Sale of {qty} x {selected} - {notes}", payment_method, buyer or "Walk-in",
                                          st.session_state.user['username'], st.session_state.user['username']))

                                    conn.commit()
                                    st.success(f"Sale recorded. New stock: {new_stock}")
                                    log_action("uniform_sale", f"Sold {qty} of {selected} for USh {amount}", st.session_state.user['username'])
                                    safe_rerun()
                    except Exception as e:
                        st.error(f"Error recording sale: {e}")

    with tab_manage:
        st.subheader("Add Uniform Category")
        with st.form("add_uniform_category"):
            cat_name = st.text_input("Category Name")
            gender = st.selectbox("Gender", ["boys", "girls", "shared"])
            is_shared = 1 if gender == "shared" else 0
            initial_stock = st.number_input("Initial Stock", min_value=0, value=0, step=1)
            unit_price = st.number_input("Unit Price (USh)", min_value=0.0, value=0.0, step=100.0)
            add_cat = st.form_submit_button("Add Category")

            if add_cat:
                if not cat_name:
                    st.error("Enter category name")
                else:
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("SELECT normalized_category FROM uniform_categories")
                                existing = [r[0] for r in cur.fetchall() if r[0]]
                                ncat = normalize_text(cat_name)
                                dup, match = is_near_duplicate(ncat, existing)
                                if dup:
                                    st.warning(f"A similar uniform category exists: '{match}'")
                                else:
                                    cur.execute("""
                                        INSERT INTO uniform_categories (category, normalized_category, gender, is_shared)
                                        VALUES (%s, %s, %s, %s)
                                        RETURNING id
                                    """, (cat_name.strip(), ncat, gender, is_shared))
                                    cat_id = cur.fetchone()[0]
                                    conn.commit()

                                    cur.execute(
                                        "INSERT INTO uniforms (category_id, stock, unit_price) VALUES (%s, %s, %s)",
                                        (cat_id, int(initial_stock), float(unit_price))
                                    )
                                    conn.commit()

                                    st.success("Uniform category added")
                                    log_action(
                                        "add_uniform_category",
                                        f"Added {cat_name} stock={initial_stock} price={unit_price}",
                                        st.session_state.user['username']
                                    )
                                    safe_rerun()
                    except Exception as e:
                        st.error(f"Error adding category: {e}")

    with tab_edit_cat:
        st.subheader("Edit Uniform Category")
        try:
            with db_connection() as conn:
                categories_df = pd.read_sql("SELECT id, category, gender, is_shared FROM uniform_categories ORDER BY category", conn)
        except Exception:
            categories_df = pd.DataFrame()

        if categories_df.empty:
            st.info("No categories to edit")
        else:
            selected_category = st.selectbox("Select Category to Edit", categories_df["category"].tolist())
            cat_row = categories_df[categories_df["category"] == selected_category].iloc[0]
            cat_id = int(cat_row['id'])

            with st.form("edit_uniform_category"):
                new_cat_name = st.text_input("Category Name", value=cat_row['category'])
                new_gender = st.selectbox("Gender", ["boys", "girls", "shared"], index=["boys", "girls", "shared"].index(cat_row['gender']))
                new_is_shared = 1 if new_gender == "shared" else 0
                submit_edit = st.form_submit_button("Update Category")

                if submit_edit:
                    if not new_cat_name:
                        st.error("Enter category name")
                    else:
                        try:
                            with db_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute("SELECT normalized_category FROM uniform_categories WHERE id != %s", (cat_id,))
                                    existing = [r[0] for r in cur.fetchall() if r[0]]
                                    ncat = normalize_text(new_cat_name)
                                    dup, match = is_near_duplicate(ncat, existing)
                                    if dup:
                                        st.warning(f"A similar category exists: '{match}'")
                                    else:
                                        cur.execute("""
                                            UPDATE uniform_categories
                                            SET category = %s, normalized_category = %s, gender = %s, is_shared = %s
                                            WHERE id = %s
                                        """, (new_cat_name.strip(), ncat, new_gender, new_is_shared, cat_id))
                                        conn.commit()
                                        st.success("Category updated")
                                        log_action(
                                            "edit_uniform_category",
                                            f"Updated category ID {cat_id} to {new_cat_name}",
                                            st.session_state.user['username']
                                        )
                                        safe_rerun()
                        except Exception as e:
                            st.error(f"Error updating category: {e}")

    with tab_delete_cat:
        require_role(["Admin"])
        st.subheader("Delete Uniform Category")
        st.warning("Deleting a category will also delete its inventory record. Proceed with caution.")

        try:
            with db_connection() as conn:
                categories_df = pd.read_sql("SELECT id, category FROM uniform_categories ORDER BY category", conn)
        except Exception:
            categories_df = pd.DataFrame()

        if categories_df.empty:
            st.info("No categories to delete")
        else:
            selected_category = st.selectbox(
                "Select Category to Delete",
                categories_df["category"].tolist(),
                key="select_uniform_cat_to_delete"
            )
            cat_id = int(categories_df[categories_df["category"] == selected_category]["id"].iloc[0])

            if st.checkbox("Confirm deletion", key=f"confirm_delete_uniform_cat_{cat_id}"):
                if st.button("Delete Category", key=f"delete_uniform_cat_btn_{cat_id}"):
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("DELETE FROM uniforms WHERE category_id = %s", (cat_id,))
                                cur.execute("DELETE FROM uniform_categories WHERE id = %s", (cat_id,))
                            conn.commit()
                        st.success("Category deleted successfully")
                        log_action("delete_uniform_category", f"Deleted category ID: {cat_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error deleting category: {e}")
# ────────────────────────────────────────────────
# Finances (full page with all 8 tabs)
# ────────────────────────────────────────────────
elif page == "Finances":
    user_role = st.session_state.user.get('role')
    st.header("Finances")

    tab_inc, tab_exp, tab_reports, tab_edit_inc, tab_delete_inc, tab_edit_exp, tab_delete_exp, tab_transfer = st.tabs(
        ["Record Income", "Record Expense", "View Transactions", "Edit Income", "Delete Income",
         "Edit Expense", "Delete Expense", "Record Transfer"]
    )

    with tab_inc:
        st.subheader("Record Income")
        if user_role not in ("Admin", "Accountant"):
            st.info("You do not have permission to record incomes. View-only access.")
        else:
            try:
                with db_connection() as conn:
                    categories = pd.read_sql(
                        "SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name",
                        conn
                    )
            except Exception:
                categories = pd.DataFrame()

            with st.form("record_income_form"):
                date_in = st.date_input("Date", date.today())
                receipt_no = st.text_input("Receipt Number", value=generate_receipt_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
                source = st.text_input("Source (e.g., Tuition Fees, Donations)")
                category = st.selectbox("Category", ["-- Select --"] + categories["name"].tolist())
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                payer = st.text_input("Payer")
                description = st.text_area("Description")
                submit_income = st.form_submit_button("Record Income")

                if submit_income:
                    if amount <= 0:
                        st.error("Enter a positive amount")
                    else:
                        try:
                            with db_connection() as conn:
                                with conn.cursor() as cur:
                                    cat_id = None
                                    if category != "-- Select --":
                                        cat_row = categories[categories["name"] == category]
                                        if not cat_row.empty:
                                            cat_id = int(cat_row["id"].iloc[0])

                                    cur.execute("""
                                        INSERT INTO incomes (date, receipt_number, amount, source, category_id, description,
                                                             payment_method, payer, received_by, created_by)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (date_in.isoformat(), receipt_no, amount, source, cat_id, description,
                                          payment_method, payer, st.session_state.user['username'], st.session_state.user['username']))
                                conn.commit()
                            st.success("Income recorded")
                            log_action("record_income", f"Income {amount} from {source}", st.session_state.user['username'])
                            safe_rerun()
                        except Exception as e:
                            if "unique" in str(e).lower() and "receipt_number" in str(e).lower():
                                st.error("Receipt number already exists")
                            else:
                                st.error(f"Error recording income: {e}")

    with tab_exp:
        st.subheader("Record Expense")
        if user_role not in ("Admin", "Accountant"):
            st.info("You do not have permission to record expenses. View-only access.")
        else:
            try:
                with db_connection() as conn:
                    categories = pd.read_sql(
                        "SELECT id, name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name",
                        conn
                    )
            except Exception:
                categories = pd.DataFrame()

            with st.form("record_expense_form"):
                date_e = st.date_input("Date", date.today())
                voucher_no = st.text_input("Voucher Number", value=generate_voucher_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
                category = st.selectbox("Category", ["-- Select --"] + categories["name"].tolist())
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                payee = st.text_input("Payee")
                description = st.text_area("Description")
                approved_by = st.text_input("Approved By")
                submit_expense = st.form_submit_button("Record Expense")

                if submit_expense:
                    if amount <= 0:
                        st.error("Enter a positive amount")
                    else:
                        try:
                            with db_connection() as conn:
                                with conn.cursor() as cur:
                                    cat_id = None
                                    if category != "-- Select --":
                                        cat_row = categories[categories["name"] == category]
                                        if not cat_row.empty:
                                            cat_id = int(cat_row["id"].iloc[0])

                                    cur.execute("""
                                        INSERT INTO expenses (date, voucher_number, amount, category_id, description,
                                                              payment_method, payee, approved_by, created_by)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (date_e.isoformat(), voucher_no, amount, cat_id, description,
                                          payment_method, payee, approved_by, st.session_state.user['username']))
                                conn.commit()
                            st.success("Expense recorded")
                            log_action("record_expense", f"Expense {amount} voucher {voucher_no}", st.session_state.user['username'])
                            safe_rerun()
                        except Exception as e:
                            if "unique" in str(e).lower() and "voucher_number" in str(e).lower():
                                st.error("Voucher number already exists")
                            else:
                                st.error(f"Error recording expense: {e}")

    with tab_reports:
        st.subheader("Transactions")

        if view_mode == "Current Term" and st.session_state.selected_term:
            start_d = safe_parse_date(st.session_state.selected_term['start_date'])
            end_d = safe_parse_date(st.session_state.selected_term['end_date'])
            tx_where = "WHERE date BETWEEN %s AND %s"
            params = (start_d.isoformat(), end_d.isoformat())
        else:
            tx_where = ""
            params = ()

        try:
            with db_connection() as conn:
                df_inc = pd.read_sql(f"""
                    SELECT i.date as Date, i.receipt_number as "Receipt No", i.amount as Amount,
                           i.source as Source, ec.name as Category, i.description as Description,
                           i.payment_method as "Payment Method", i.payer as Payer,
                           i.received_by as "Received By", i.created_by as "Created By"
                    FROM incomes i
                    LEFT JOIN expense_categories ec ON i.category_id = ec.id
                    {tx_where}
                    ORDER BY i.date DESC LIMIT 500
                """, conn, params=params)

                df_exp = pd.read_sql(f"""
                    SELECT e.date as Date, e.voucher_number as "Voucher No", e.amount as Amount,
                           ec.name as Category, e.description as Description,
                           e.payment_method as "Payment Method", e.payee as Payee,
                           e.approved_by as "Approved By", e.created_by as "Created By"
                    FROM expenses e
                    LEFT JOIN expense_categories ec ON e.category_id = ec.id
                    {tx_where}
                    ORDER BY e.date DESC LIMIT 500
                """, conn, params=params)
        except Exception:
            df_inc = pd.DataFrame()
            df_exp = pd.DataFrame()

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

    with tab_edit_inc:
        st.subheader("Edit Income")
        if user_role not in ("Admin", "Accountant"):
            st.info("Permission denied")
        else:
            try:
                with db_connection() as conn:
                    incomes = pd.read_sql(
                        "SELECT id, receipt_number, date, amount, source, category_id, description, payment_method, payer "
                        "FROM incomes ORDER BY date DESC",
                        conn
                    )
            except Exception:
                incomes = pd.DataFrame()

            if incomes.empty:
                st.info("No incomes to edit")
            else:
                selected_inc = st.selectbox("Select Income by Receipt Number", incomes['receipt_number'].tolist(), key="select_income_to_edit")
                inc_row = incomes[incomes['receipt_number'] == selected_inc].iloc[0]
                inc_id = int(inc_row['id'])

                try:
                    with db_connection() as conn:
                        categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
                except Exception:
                    categories = pd.DataFrame()

                with st.form("edit_income_form"):
                    date_in = st.date_input("Date", value=safe_parse_date(inc_row['date']))
                    receipt_no = st.text_input("Receipt Number", value=inc_row['receipt_number'])
                    amount = st.number_input("Amount (USh)", min_value=0.0, value=float(inc_row['amount']), step=100.0)
                    source = st.text_input("Source", value=inc_row['source'])
                    current_cat_id = inc_row['category_id']
                    current_cat_name = categories[categories['id'] == current_cat_id]['name'].iloc[0] if current_cat_id and not categories.empty else "-- Select --"
                    category = st.selectbox(
                        "Category",
                        ["-- Select --"] + categories["name"].tolist(),
                        index=categories["name"].tolist().index(current_cat_name) + 1 if current_cat_name != "-- Select --" and current_cat_name in categories["name"].tolist() else 0
                    )
                    payment_method = st.selectbox(
                        "Payment Method",
                        ["Cash", "Bank Transfer", "Mobile Money", "Cheque"],
                        index=["Cash", "Bank Transfer", "Mobile Money", "Cheque"].index(inc_row['payment_method'])
                    )
                    payer = st.text_input("Payer", value=inc_row['payer'])
                    description = st.text_area("Description", value=inc_row['description'])
                    submit_edit = st.form_submit_button("Update Income")

                    if submit_edit:
                        if amount <= 0:
                            st.error("Enter a positive amount")
                        else:
                            try:
                                with db_connection() as conn:
                                    with conn.cursor() as cur:
                                        cat_id = None
                                        if category != "-- Select --":
                                            cat_row = categories[categories["name"] == category]
                                            if not cat_row.empty:
                                                cat_id = int(cat_row["id"].iloc[0])

                                        cur.execute("""
                                            UPDATE incomes
                                            SET date = %s, receipt_number = %s, amount = %s, source = %s,
                                                category_id = %s, description = %s, payment_method = %s, payer = %s
                                            WHERE id = %s
                                        """, (date_in.isoformat(), receipt_no, amount, source, cat_id,
                                              description, payment_method, payer, inc_id))
                                    conn.commit()
                                st.success("Income updated")
                                log_action("edit_income", f"Updated income ID {inc_id} receipt {receipt_no}", st.session_state.user['username'])
                                safe_rerun()
                            except Exception as e:
                                if "unique" in str(e).lower() and "receipt_number" in str(e).lower():
                                    st.error("Receipt number already exists")
                                else:
                                    st.error(f"Error updating income: {e}")

    with tab_delete_inc:
        require_role(["Admin"])
        st.subheader("Delete Income")
        st.warning("Deleting an income record is permanent. Proceed with caution.")

        try:
            with db_connection() as conn:
                incomes = pd.read_sql("SELECT id, receipt_number FROM incomes ORDER BY date DESC", conn)
        except Exception:
            incomes = pd.DataFrame()

        if incomes.empty:
            st.info("No incomes to delete")
        else:
            selected_inc = st.selectbox("Select Income to Delete by Receipt Number", incomes['receipt_number'].tolist(), key="select_income_to_delete")
            inc_id = int(incomes[incomes['receipt_number'] == selected_inc]['id'].iloc[0])

            if st.checkbox("Confirm deletion", key=f"confirm_delete_income_{inc_id}"):
                if st.button("Delete Income", key=f"delete_income_btn_{inc_id}"):
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("DELETE FROM incomes WHERE id = %s", (inc_id,))
                            conn.commit()
                        st.success("Income deleted successfully")
                        log_action("delete_income", f"Deleted income ID: {inc_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error deleting income: {e}")

    with tab_edit_exp:
        st.subheader("Edit Expense")
        if user_role not in ("Admin", "Accountant"):
            st.info("Permission denied")
        else:
            try:
                with db_connection() as conn:
                    expenses = pd.read_sql(
                        "SELECT id, voucher_number, date, amount, category_id, description, payment_method, payee, approved_by "
                        "FROM expenses ORDER BY date DESC",
                        conn
                    )
            except Exception:
                expenses = pd.DataFrame()

            if expenses.empty:
                st.info("No expenses to edit")
            else:
                selected_exp = st.selectbox("Select Expense by Voucher Number", expenses['voucher_number'].tolist(), key="select_expense_to_edit")
                exp_row = expenses[expenses['voucher_number'] == selected_exp].iloc[0]
                exp_id = int(exp_row['id'])

                try:
                    with db_connection() as conn:
                        categories = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name", conn)
                except Exception:
                    categories = pd.DataFrame()

                with st.form("edit_expense_form"):
                    date_e = st.date_input("Date", value=safe_parse_date(exp_row['date']))
                    voucher_no = st.text_input("Voucher Number", value=exp_row['voucher_number'])
                    amount = st.number_input("Amount (USh)", min_value=0.0, value=float(exp_row['amount']), step=100.0)
                    current_cat_id = exp_row['category_id']
                    current_cat_name = categories[categories['id'] == current_cat_id]['name'].iloc[0] if current_cat_id and not categories.empty else "-- Select --"
                    category = st.selectbox(
                        "Category",
                        ["-- Select --"] + categories["name"].tolist(),
                        index=categories["name"].tolist().index(current_cat_name) + 1 if current_cat_name != "-- Select --" and current_cat_name in categories["name"].tolist() else 0
                    )
                    payment_method = st.selectbox(
                        "Payment Method",
                        ["Cash", "Bank Transfer", "Mobile Money", "Cheque"],
                        index=["Cash", "Bank Transfer", "Mobile Money", "Cheque"].index(exp_row['payment_method'])
                    )
                    payee = st.text_input("Payee", value=exp_row['payee'])
                    description = st.text_area("Description", value=exp_row['description'])
                    approved_by = st.text_input("Approved By", value=exp_row['approved_by'])
                    submit_edit = st.form_submit_button("Update Expense")

                    if submit_edit:
                        if amount <= 0:
                            st.error("Enter a positive amount")
                        else:
                            try:
                                with db_connection() as conn:
                                    with conn.cursor() as cur:
                                        cat_id = None
                                        if category != "-- Select --":
                                            cat_row = categories[categories["name"] == category]
                                            if not cat_row.empty:
                                                cat_id = int(cat_row["id"].iloc[0])

                                        cur.execute("""
                                            UPDATE expenses
                                            SET date = %s, voucher_number = %s, amount = %s, category_id = %s,
                                                description = %s, payment_method = %s, payee = %s, approved_by = %s
                                            WHERE id = %s
                                        """, (date_e.isoformat(), voucher_no, amount, cat_id,
                                              description, payment_method, payee, approved_by, exp_id))
                                    conn.commit()
                                st.success("Expense updated")
                                log_action("edit_expense", f"Updated expense ID {exp_id} voucher {voucher_no}", st.session_state.user['username'])
                                safe_rerun()
                            except Exception as e:
                                if "unique" in str(e).lower() and "voucher_number" in str(e).lower():
                                    st.error("Voucher number already exists")
                                else:
                                    st.error(f"Error updating expense: {e}")

    with tab_delete_exp:
        require_role(["Admin"])
        st.subheader("Delete Expense")
        st.warning("Deleting an expense record is permanent. Proceed with caution.")

        try:
            with db_connection() as conn:
                expenses = pd.read_sql("SELECT id, voucher_number FROM expenses ORDER BY date DESC", conn)
        except Exception:
            expenses = pd.DataFrame()

        if expenses.empty:
            st.info("No expenses to delete")
        else:
            selected_exp = st.selectbox("Select Expense to Delete by Voucher Number", expenses['voucher_number'].tolist(), key="select_expense_to_delete")
            exp_id = int(expenses[expenses['voucher_number'] == selected_exp]['id'].iloc[0])

            if st.checkbox("Confirm deletion", key=f"confirm_delete_expense_{exp_id}"):
                if st.button("Delete Expense", key=f"delete_expense_btn_{exp_id}"):
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("DELETE FROM expenses WHERE id = %s", (exp_id,))
                            conn.commit()
                        st.success("Expense deleted successfully")
                        log_action("delete_expense", f"Deleted expense ID: {exp_id}", st.session_state.user['username'])
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error deleting expense: {e}")

    with tab_transfer:
        st.subheader("Record Contra Entry (Transfer between Cash and Bank)")
        if user_role not in ("Admin", "Accountant"):
            st.info("Permission denied")
        else:
            with st.form("record_transfer_form"):
                transfer_date = st.date_input("Date", date.today())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=100.0)
                from_account = st.selectbox("From Account", ["Cash", "Bank"])
                to_account = st.selectbox("To Account", ["Bank", "Cash"])
                description = st.text_area("Description")
                submit_transfer = st.form_submit_button("Record Transfer")

                if submit_transfer:
                    if amount <= 0:
                        st.error("Enter a positive amount")
                    elif from_account == to_account:
                        st.error("From and To accounts must be different")
                    else:
                        try:
                            with db_connection() as conn:
                                conn.autocommit = False
                                with conn.cursor() as cur:
                                    cur.execute("SELECT id FROM expense_categories WHERE name = 'Transfer Out'")
                                    transfer_out_cat = cur.fetchone()
                                    transfer_out_id = transfer_out_cat[0] if transfer_out_cat else None

                                    cur.execute("SELECT id FROM expense_categories WHERE name = 'Transfer In'")
                                    transfer_in_cat = cur.fetchone()
                                    transfer_in_id = transfer_in_cat[0] if transfer_in_cat else None

                                    voucher_no = generate_voucher_number()
                                    pay_method_from = 'Cash' if from_account == "Cash" else 'Bank Transfer'
                                    cur.execute("""
                                        INSERT INTO expenses (date, voucher_number, amount, category_id, description,
                                                              payment_method, payee, approved_by, created_by)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (transfer_date.isoformat(), voucher_no, amount, transfer_out_id,
                                          f"Transfer to {to_account}: {description}", pay_method_from,
                                          to_account, st.session_state.user['username'], st.session_state.user['username']))

                                    receipt_no = generate_receipt_number()
                                    pay_method_to = 'Bank Transfer' if to_account == "Bank" else 'Cash'
                                    cur.execute("""
                                        INSERT INTO incomes (date, receipt_number, amount, source, category_id, description,
                                                             payment_method, payer, received_by, created_by)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (transfer_date.isoformat(), receipt_no, amount, f"Transfer from {from_account}",
                                          transfer_in_id, f"Transfer from {from_account}: {description}", pay_method_to,
                                          from_account, st.session_state.user['username'], st.session_state.user['username']))

                                conn.commit()
                                st.success("Transfer recorded successfully")
                                log_action(
                                    "record_transfer",
                                    f"Transfer {amount} from {from_account} to {to_account}",
                                    st.session_state.user['username']
                                )
                                safe_rerun()
                        except Exception as e:
                            if 'conn' in locals():
                                conn.rollback()
                            st.error(f"Error recording transfer: {e}")
                        finally:
                            if 'conn' in locals():
                                conn.autocommit = True
# ────────────────────────────────────────────────
# Financial Report
# ────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Reports & Exports")

    st.subheader("Generate Report")
    report_type = st.selectbox(
        "Report Type",
        ["Income vs Expense (date range)", "By Category", "Outstanding Invoices", "Student Payment Summary"]
    )

    if view_mode == "Current Term" and st.session_state.selected_term:
        default_start = safe_parse_date(st.session_state.selected_term['start_date'])
        default_end = safe_parse_date(st.session_state.selected_term['end_date'])
    else:
        default_start = date.today().replace(day=1)
        default_end = date.today()

    start_date = st.date_input("Start Date", default_start)
    end_date = st.date_input("End Date", default_end)

    if start_date > end_date:
        st.error("Start date must be before end date")
    else:
        if st.button("Generate Report"):
            try:
                with db_connection() as conn:
                    if report_type == "Income vs Expense (date range)":
                        df_inc = pd.read_sql(
                            """
                            SELECT date as Date, receipt_number as "Receipt No", amount as Amount,
                                   source as Source, payment_method as "Payment Method", payer as Payer,
                                   description as Description
                            FROM incomes
                            WHERE date BETWEEN %s AND %s
                            ORDER BY date
                            """,
                            conn, params=(start_date.isoformat(), end_date.isoformat())
                        )
                        df_exp = pd.read_sql(
                            """
                            SELECT date as Date, voucher_number as "Voucher No", amount as Amount,
                                   description as Description, payment_method as "Payment Method", payee as Payee
                            FROM expenses
                            WHERE date BETWEEN %s AND %s
                            ORDER BY date
                            """,
                            conn, params=(start_date.isoformat(), end_date.isoformat())
                        )

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
                            download_options(
                                combined,
                                filename_base=f"financial_{start_date}_{end_date}",
                                title="Income vs Expense Report"
                            )

                    elif report_type == "By Category":
                        cat = st.selectbox("Category Type", ["Income", "Expense"])
                        df = pd.read_sql("""
                            SELECT ec.name as Category,
                                   SUM(COALESCE(i.amount,0)) as "Total Income",
                                   SUM(COALESCE(e.amount,0)) as "Total Expense"
                            FROM expense_categories ec
                            LEFT JOIN incomes i ON i.category_id = ec.id AND i.date BETWEEN %s AND %s
                            LEFT JOIN expenses e ON e.category_id = ec.id AND e.date BETWEEN %s AND %s
                            WHERE ec.category_type = %s
                            GROUP BY ec.name
                        """, conn, params=(start_date.isoformat(), end_date.isoformat(),
                                           start_date.isoformat(), end_date.isoformat(), cat))

                        if df.empty:
                            st.info("No data for selected category type")
                        else:
                            st.dataframe(df, use_container_width=True)
                            download_options(
                                df,
                                filename_base=f"by_category_{cat}",
                                title=f"By Category - {cat}"
                            )

                    elif report_type == "Outstanding Invoices":
                        df = pd.read_sql(
                            """
                            SELECT invoice_number as "Invoice No", student_id as "Student ID",
                                   issue_date as "Issue Date", due_date as "Due Date",
                                   total_amount as "Total Amount", paid_amount as "Paid Amount",
                                   balance_amount as "Balance Amount", status as Status, notes as Notes
                            FROM invoices
                            WHERE status IN ('Pending','Partially Paid')
                            ORDER BY due_date
                            """,
                            conn
                        )
                        if df.empty:
                            st.info("No outstanding invoices")
                        else:
                            st.dataframe(df, use_container_width=True)
                            download_options(df, filename_base="outstanding_invoices", title="Outstanding Invoices")

                    else:  # Student Payment Summary
                        students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
                        if students.empty:
                            st.info("No students available")
                        else:
                            sel = st.selectbox(
                                "Select Student",
                                students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1)
                            )
                            sid = int(sel.split("(ID: ")[1].replace(")", ""))

                            df_inv = pd.read_sql(
                                """
                                SELECT invoice_number as "Invoice No", academic_year as "Academic Year",
                                       term as Term, total_amount as "Total Amount",
                                       paid_amount as "Paid Amount", balance_amount as "Balance Amount",
                                       status as Status, issue_date as "Issue Date", notes as Notes
                                FROM invoices
                                WHERE student_id = %s
                                ORDER BY issue_date DESC
                                """,
                                conn, params=(sid,)
                            )
                            df_pay = pd.read_sql(
                                """
                                SELECT p.payment_date as "Payment Date", p.amount as Amount,
                                       p.payment_method as "Payment Method", p.receipt_number as "Receipt No",
                                       p.reference_number as "Reference No", p.notes as Notes
                                FROM payments p
                                JOIN invoices i ON p.invoice_id = i.id
                                WHERE i.student_id = %s
                                ORDER BY p.payment_date DESC
                                """,
                                conn, params=(sid,)
                            )

                            st.subheader("Invoices")
                            if df_inv.empty:
                                st.info("No invoices for this student")
                            else:
                                st.dataframe(df_inv, use_container_width=True)
                                download_options(
                                    df_inv,
                                    filename_base=f"student_{sid}_invoices",
                                    title=f"Invoices for Student {sid}"
                                )

                            st.subheader("Payments")
                            if df_pay.empty:
                                st.info("No payments for this student")
                            else:
                                st.dataframe(df_pay, use_container_width=True)
                                download_options(
                                    df_pay,
                                    filename_base=f"student_{sid}_payments",
                                    title=f"Payments for Student {sid}"
                                )

            except Exception as e:
                st.error(f"Error generating report: {str(e)}")


# ────────────────────────────────────────────────
# Cashbook
# ────────────────────────────────────────────────
elif page == "Cashbook":
    require_role(["Admin", "Accountant", "Clerk"])
    st.header("Two-Column Cashbook (Cash and Bank)")

    if view_mode == "Current Term" and st.session_state.selected_term:
        start_date = safe_parse_date(st.session_state.selected_term['start_date'])
        end_date = safe_parse_date(st.session_state.selected_term['end_date'])
        st.info(f"Showing for selected term: {st.session_state.selected_term['term']} {st.session_state.selected_term['academic_year']}")
    else:
        start_date = st.date_input("Start Date", date.today().replace(day=1))
        end_date = st.date_input("End Date", date.today())

    if start_date > end_date:
        st.error("Start date must be before end date")
    else:
        try:
            with db_connection() as conn:
                df_inc = pd.read_sql("""
                    SELECT date as tx_date, source || ' from ' || payer as description,
                           amount, payment_method, 'Income' as type
                    FROM incomes
                    WHERE date BETWEEN %s AND %s
                """, conn, params=(start_date.isoformat(), end_date.isoformat()))

                df_exp = pd.read_sql("""
                    SELECT date as tx_date, description || ' to ' || payee as description,
                           amount, payment_method, 'Expense' as type
                    FROM expenses
                    WHERE date BETWEEN %s AND %s
                """, conn, params=(start_date.isoformat(), end_date.isoformat()))

            combined = pd.concat([df_inc, df_exp], ignore_index=True)
            if combined.empty:
                st.info("No transactions in this range")
            else:
                combined['tx_date'] = pd.to_datetime(combined['tx_date'])
                combined = combined.sort_values('tx_date').reset_index(drop=True)

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
                    else:
                        if is_cash:
                            combined.at[idx, 'cash_cr'] = row['amount']
                        else:
                            combined.at[idx, 'bank_cr'] = row['amount']

                combined['cash_balance'] = (combined['cash_dr'] - combined['cash_cr']).cumsum()
                combined['bank_balance'] = (combined['bank_dr'] - combined['bank_cr']).cumsum()

                display = combined[[
                    'tx_date', 'description', 'cash_dr', 'bank_dr',
                    'cash_cr', 'bank_cr', 'cash_balance', 'bank_balance'
                ]].copy()
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
                download_options(
                    display,
                    filename_base=f"cashbook_{start_date}_{end_date}",
                    title="Two-Column Cashbook"
                )
        except Exception as e:
            st.error(f"Error loading cashbook: {str(e)}")


# ────────────────────────────────────────────────
# Audit Log
# ────────────────────────────────────────────────
elif page == "Audit Log":
    require_role(["Admin", "Accountant"])
    st.header("Audit Log")

    try:
        with db_connection() as conn:
            df_audit = pd.read_sql(
                """
                SELECT performed_at as "Performed At",
                       performed_by as "Performed By",
                       action as Action,
                       details as Details
                FROM audit_log
                ORDER BY performed_at DESC
                LIMIT 500
                """,
                conn
            )
        if df_audit.empty:
            st.info("No audit entries")
        else:
            st.dataframe(df_audit, use_container_width=True)
            download_options(df_audit, filename_base="audit_log", title="Audit Log")
    except Exception as e:
        st.error(f"Error loading audit log: {str(e)}")


# ────────────────────────────────────────────────
# Fee Management (full page with all 5 tabs)
# ────────────────────────────────────────────────
elif page == "Fee Management":
    require_role(["Admin", "Accountant"])
    st.header("Fee Management")

    tab_term, tab_define, tab_generate, tab_edit_inv, tab_delete_inv = st.tabs(
        ["Define Terms", "Define Fee Structure", "Generate Invoice", "Edit Invoice", "Delete Invoice"]
    )

    with tab_term:
        st.subheader("Define Academic Terms")

        with st.form("define_term_form"):
            academic_year = st.text_input("Academic Year (e.g., 2025/2026)")
            term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
            start_date = st.date_input("Start Date")
            end_date = st.date_input("End Date")
            submit_term = st.form_submit_button("Create/Update Term")

        if submit_term:
            if start_date > end_date:
                st.error("Start date must be before end date")
            else:
                try:
                    with db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT id FROM terms WHERE academic_year = %s AND term = %s",
                                (academic_year, term)
                            )
                            existing = cur.fetchone()
                            if existing:
                                cur.execute("""
                                    UPDATE terms
                                    SET start_date = %s, end_date = %s
                                    WHERE id = %s
                                """, (start_date.isoformat(), end_date.isoformat(), existing[0]))
                            else:
                                cur.execute("""
                                    INSERT INTO terms (academic_year, term, start_date, end_date)
                                    VALUES (%s, %s, %s, %s)
                                """, (academic_year, term, start_date.isoformat(), end_date.isoformat()))
                            conn.commit()
                    st.success("Term saved successfully")
                    log_action("term_update" if existing else "term_create", f"{term} {academic_year}", st.session_state.user['username'])
                    safe_rerun()
                except Exception as e:
                    if "unique" in str(e).lower():
                        st.error("Term for this academic year already exists")
                    else:
                        st.error(f"Error saving term: {str(e)}")

        st.subheader("Existing Terms")
        terms_df = get_terms()
        if terms_df.empty:
            st.info("No terms defined yet")
        else:
            st.dataframe(terms_df[['academic_year', 'term', 'start_date', 'end_date']], use_container_width=True)

    with tab_define:
        st.subheader("Define Fee Structure")
        try:
            with db_connection() as conn:
                classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
        except Exception:
            classes = pd.DataFrame()

        if classes.empty:
            st.info("No classes defined. Add classes in Students tab.")
        else:
            with st.form("fee_structure_form"):
                cls_name = st.selectbox("Class", classes["name"].tolist())
                cls_id = int(classes[classes["name"] == cls_name]["id"].iloc[0])
                term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
                academic_year = st.text_input("Academic Year (e.g., 2025/2026)")
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
                    with db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT id FROM fee_structure WHERE class_id = %s AND term = %s AND academic_year = %s",
                                (cls_id, term, academic_year)
                            )
                            existing = cur.fetchone()
                            if existing:
                                cur.execute("""
                                    UPDATE fee_structure
                                    SET tuition_fee = %s, uniform_fee = %s, activity_fee = %s,
                                        exam_fee = %s, library_fee = %s, other_fee = %s,
                                        total_fee = %s, created_at = CURRENT_TIMESTAMP
                                    WHERE id = %s
                                """, (tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee,
                                      total_fee, existing[0]))
                            else:
                                cur.execute("""
                                    INSERT INTO fee_structure (class_id, term, academic_year, tuition_fee, uniform_fee,
                                                               activity_fee, exam_fee, library_fee, other_fee, total_fee)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """, (cls_id, term, academic_year, tuition_fee, uniform_fee, activity_fee,
                                      exam_fee, library_fee, other_fee, total_fee))
                            conn.commit()
                    st.success("Fee structure saved successfully")
                    log_action("fee_structure_update" if existing else "fee_structure_create",
                               f"class {cls_name} term {term} year {academic_year} total {total_fee}",
                               st.session_state.user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error saving fee structure: {str(e)}")

    with tab_generate:
        st.subheader("Generate Invoice")
        try:
            with db_connection() as conn:
                students = pd.read_sql(
                    """
                    SELECT s.id, s.name, c.name as class_name
                    FROM students s
                    JOIN classes c ON s.class_id = c.id
                    ORDER BY s.name
                    """,
                    conn
                )
        except Exception:
            students = pd.DataFrame()

        if students.empty:
            st.info("No students to invoice")
        else:
            selected = st.selectbox(
                "Select Student",
                students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1),
                key="select_student_for_invoice"
            )
            student_id = int(selected.split("(ID: ")[1].replace(")", ""))

            try:
                with db_connection() as conn:
                    fee_options = pd.read_sql(
                        """
                        SELECT fs.id, c.name as class_name, fs.term, fs.academic_year, fs.total_fee
                        FROM fee_structure fs
                        JOIN classes c ON fs.class_id = c.id
                        WHERE fs.class_id = (SELECT class_id FROM students WHERE id = %s)
                        ORDER BY fs.academic_year DESC
                        """,
                        conn, params=(student_id,)
                    )
            except Exception:
                fee_options = pd.DataFrame()

            if fee_options.empty:
                st.info("No fee structure defined for this student's class yet.")
            else:
                chosen = st.selectbox(
                    "Choose Fee Structure",
                    fee_options.apply(lambda x: f"{x['academic_year']} - {x['term']} (USh {x['total_fee']:,.0f})", axis=1),
                    key="select_fee_structure"
                )
                fee_row = fee_options[fee_options.apply(lambda x: f"{x['academic_year']} - {x['term']} (USh {x['total_fee']:,.0f})", axis=1) == chosen].iloc[0]

                issue_date = st.date_input("Issue Date", date.today())
                due_date = st.date_input("Due Date", date.today())
                notes = st.text_area("Notes")

                if st.button("Create Invoice"):
                    try:
                        with db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    """
                                    SELECT id FROM invoices
                                    WHERE student_id = %s AND term = %s AND academic_year = %s
                                    """,
                                    (student_id, fee_row['term'], fee_row['academic_year'])
                                )
                                if cur.fetchone():
                                    st.error("An invoice already exists for this student, term, and academic year.")
                                else:
                                    inv_no = generate_invoice_number()
                                    total_amount = float(fee_row['total_fee'])
                                    cur.execute("""
                                        INSERT INTO invoices (
                                            invoice_number, student_id, issue_date, due_date, academic_year, term,
                                            total_amount, paid_amount, balance_amount, status, notes, created_by
                                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, 'Pending', %s, %s)
                                    """, (
                                        inv_no, student_id, issue_date.isoformat(), due_date.isoformat(),
                                        fee_row['academic_year'], fee_row['term'], total_amount, total_amount,
                                        notes, st.session_state.user['username']
                                    ))
                                conn.commit()
                        st.success(f"Invoice {inv_no} created successfully for USh {total_amount:,.0f}")
                        log_action(
                            "create_invoice",
                            f"Created {inv_no} for student {student_id} - {total_amount}",
                            st.session_state.user['username']
                        )
                        safe_rerun()
                    except Exception as e:
                        st.error(f"Error creating invoice: {str(e)}")

    with tab_edit_inv:
        st.subheader("Edit Invoice")
        try:
            with db_connection() as conn:
                invoices = pd.read_sql(
                    """
                    SELECT i.id, i.invoice_number, s.name as student_name,
                           i.total_amount, i.paid_amount, i.balance_amount
                    FROM invoices i
                    JOIN students s ON i.student_id = s.id
                    ORDER BY i.issue_date DESC
                    """,
                    conn
                )
        except Exception:
            invoices = pd.DataFrame()

        if invoices.empty:
            st.info("No invoices available to edit")
        else:
            selected_inv = st.selectbox("Select Invoice", invoices['invoice_number'].tolist())
            try:
                with db_connection() as conn:
                    inv_row = pd.read_sql("SELECT * FROM invoices WHERE invoice_number = %s", conn, params=(selected_inv,)).iloc[0]
            except Exception:
                st.error("Could not load invoice details")
                inv_row = None

            if inv_row is not None:
                with st.form("edit_invoice_form"):
                    issue_date = st.date_input("Issue Date", value=safe_parse_date(inv_row['issue_date']))
                    due_date = st.date_input("Due Date", value=safe_parse_date(inv_row['due_date']))
                    total_amount = st.number_input("Total Amount (USh)", min_value=0.0, value=float(inv_row['total_amount']), step=1000.0)
                    notes = st.text_area("Notes", value=inv_row['notes'] or "")
                    submit_edit = st.form_submit_button("Update Invoice")

                    if submit_edit:
                        try:
                            new_balance = total_amount - float(inv_row['paid_amount'] or 0)
                            new_status = 'Fully Paid' if new_balance <= 0 else 'Partially Paid' if inv_row['paid_amount'] > 0 else 'Pending'
                            with db_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        UPDATE invoices
                                        SET issue_date = %s, due_date = %s, total_amount = %s,
                                            balance_amount = %s, status = %s, notes = %s
                                        WHERE id = %s
                                    """, (issue_date.isoformat(), due_date.isoformat(), total_amount,
                                          new_balance, new_status, notes, inv_row['id']))
                                conn.commit()
                            st.success("Invoice updated successfully")
                            log_action("edit_invoice", f"Updated invoice {selected_inv} to {total_amount}", st.session_state.user['username'])
                            safe_rerun()
                        except Exception as e:
                            st.error(f"Error updating invoice: {str(e)}")

    with tab_delete_inv:
        require_role(["Admin"])
        st.subheader("Delete Invoice")
        st.warning("This action is permanent and cannot be undone. Related payments will remain in the system.")

        try:
            with db_connection() as conn:
                invoices = pd.read_sql("SELECT id, invoice_number FROM invoices ORDER BY issue_date DESC", conn)
        except Exception:
            invoices = pd.DataFrame()

        if invoices.empty:
            st.info("No invoices to delete")
        else:
            selected_inv = st.selectbox("Select Invoice to Delete", invoices['invoice_number'].tolist(), key="del_inv_select")
            inv_id = int(invoices[invoices['invoice_number'] == selected_inv]['id'].iloc[0])

            confirm = st.checkbox(f"Yes, permanently delete invoice {selected_inv}")
            if confirm and st.button("Confirm Delete", type="primary"):
                try:
                    with db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM invoices WHERE id = %s", (inv_id,))
                        conn.commit()
                    st.success(f"Invoice {selected_inv} deleted successfully")
                    log_action("delete_invoice", f"Deleted invoice {selected_inv} (ID: {inv_id})", st.session_state.user['username'])
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error deleting invoice: {str(e)}")


# ────────────────────────────────────────────────
# User Settings
# ────────────────────────────────────────────────
elif page == "User Settings":
    st.header("User Settings")
    st.markdown("Manage your account preferences and security.")

    try:
        with db_connection() as conn:
            user = st.session_state.user
            user_id = user["id"]
            current_username = user["username"]
            current_full_name = user.get("full_name", current_username)
    except Exception:
        st.error("Could not load user details")
        current_full_name = current_username

    tab_profile, tab_password = st.tabs(["Profile", "Change Password"])

    with tab_profile:
        st.subheader("Update Profile")
        with st.form("update_profile_form"):
            new_full_name = st.text_input("Full Name / Display Name", value=current_full_name)
            submit_profile = st.form_submit_button("Save Profile Changes")

        if submit_profile:
            if not new_full_name.strip():
                st.error("Full name cannot be empty")
            else:
                try:
                    with db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE users SET full_name = %s WHERE id = %s",
                                (new_full_name.strip(), user_id)
                            )
                        conn.commit()
                    st.session_state.user["full_name"] = new_full_name.strip()
                    st.success("Profile updated successfully")
                    log_action(
                        "update_profile",
                        f"User {current_username} changed full name to {new_full_name}",
                        current_username
                    )
                    safe_rerun()
                except Exception as e:
                    st.error(f"Error updating profile: {str(e)}")

    with tab_password:
        st.subheader("Change Password")
        with st.form("change_password_form"):
            current_password = st.text_input("Current Password", type="password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            submit_password = st.form_submit_button("Change Password")

        if submit_password:
            if not current_password or not new_password or not confirm_password:
                st.error("All password fields are required")
            elif new_password != confirm_password:
                st.error("New password and confirmation do not match")
            elif len(new_password) < 6:
                st.error("New password must be at least 6 characters long")
            else:
                try:
                    with db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
                            db_user = cur.fetchone()
                            if db_user and verify_password(db_user[0], current_password):
                                new_hash = hash_password(new_password)
                                cur.execute(
                                    "UPDATE users SET password_hash = %s WHERE id = %s",
                                    (new_hash, user_id)
                                )
                                conn.commit()
                                st.success("Password changed successfully! Please log in again with the new password.")
                                log_action("change_password", f"User {current_username} changed password", current_username)
                            else:
                                st.error("Current password is incorrect")
                except Exception as e:
                    st.error(f"Error changing password: {str(e)}")

    st.markdown("---")
    st.caption("For security reasons, major account changes (role, username) can only be performed by an Administrator.")


# ────────────────────────────────────────────────
# Footer
# ────────────────────────────────────────────────
st.markdown("---")
st.caption(f"© COSNA School Management System • {datetime.now().year}")
st.caption("Developed for Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana")
