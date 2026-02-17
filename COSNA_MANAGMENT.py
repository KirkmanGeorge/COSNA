# ===============================
# COSNA MANAGEMENT SYSTEM
# PostgreSQL (Supabase) Version
# ===============================

import streamlit as st
import psycopg2
import psycopg2.extras
import pandas as pd
import bcrypt
from datetime import datetime, date
from io import BytesIO

st.set_page_config(
    page_title="COSNA Management System",
    layout="wide"
)

# ===============================
# DATABASE CONNECTION
# ===============================

@st.cache_resource
def get_connection():
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        port=st.secrets["DB_PORT"],
        dbname=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def get_cursor():
    conn = get_connection()
    return conn, conn.cursor()

# ===============================
# PASSWORD FUNCTIONS
# ===============================

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())
# ===============================
# DATABASE TABLE CREATION
# (Same Structure as Original u1)
# ===============================

def create_tables():
    conn, cur = get_cursor()

    # USERS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            full_name TEXT
        )
    """)

    # TERMS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS terms (
            id SERIAL PRIMARY KEY,
            term_name TEXT NOT NULL,
            academic_year TEXT NOT NULL,
            UNIQUE(term_name, academic_year)
        )
    """)

    # STUDENTS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            admission_number TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            class TEXT,
            gender TEXT,
            parent_name TEXT,
            parent_contact TEXT,
            date_admitted DATE DEFAULT CURRENT_DATE
        )
    """)

    # PAYMENTS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
            amount NUMERIC NOT NULL,
            payment_type TEXT,
            term_id INTEGER REFERENCES terms(id),
            payment_date DATE DEFAULT CURRENT_DATE,
            receipt_number TEXT UNIQUE
        )
    """)

    # STAFF TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            full_name TEXT NOT NULL,
            position TEXT,
            contact TEXT,
            salary NUMERIC,
            date_employed DATE DEFAULT CURRENT_DATE
        )
    """)

    # UNIFORMS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uniforms (
            id SERIAL PRIMARY KEY,
            item_name TEXT NOT NULL,
            size TEXT,
            quantity INTEGER DEFAULT 0,
            unit_price NUMERIC
        )
    """)

    # UNIFORM SALES TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uniform_sales (
            id SERIAL PRIMARY KEY,
            student_id INTEGER REFERENCES students(id),
            uniform_id INTEGER REFERENCES uniforms(id),
            quantity INTEGER NOT NULL,
            total_amount NUMERIC NOT NULL,
            sale_date DATE DEFAULT CURRENT_DATE
        )
    """)

    # EXPENSES TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            expense_name TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            expense_date DATE DEFAULT CURRENT_DATE,
            description TEXT
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

# Call table creation at startup
create_tables()
# ===============================
# DEFAULT ADMIN USER
# ===============================

def seed_admin():
    conn, cur = get_cursor()

    cur.execute("""
        INSERT INTO users (username, password_hash, role, full_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """, (
        "admin",
        hash_password("costa2026"),
        "Admin",
        "Administrator"
    ))

    conn.commit()
    cur.close()
    conn.close()

seed_admin()
# ===============================
# AUTHENTICATION SYSTEM
# (Same Logic as Original u1)
# ===============================

if "user" not in st.session_state:
    st.session_state.user = None


def login_user(username, password):
    conn, cur = get_cursor()

    cur.execute(
        "SELECT * FROM users WHERE username = %s",
        (username,)
    )
    user = cur.fetchone()

    cur.close()
    conn.close()

    if user and verify_password(password, user["password_hash"]):
        return user
    return None


# ===============================
# LOGIN PAGE
# ===============================

if st.session_state.user is None:

    st.title("COSNA Management System")
    st.subheader("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_btn = st.form_submit_button("Login")

        if login_btn:
            user = login_user(username, password)

            if user:
                st.session_state.user = user
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Invalid credentials")

    st.stop()
def logout():
    st.session_state.user = None
    st.rerun()
# ===============================
# MAIN SYSTEM AFTER LOGIN
# ===============================

current_user = st.session_state.user

st.sidebar.title("COSNA Management")

st.sidebar.write(f"Logged in as: {current_user['full_name']}")
st.sidebar.write(f"Role: {current_user['role']}")

# ===============================
# TERM SELECTION
# ===============================

conn, cur = get_cursor()

cur.execute("""
    SELECT id, term_name, academic_year
    FROM terms
    ORDER BY academic_year DESC, term_name
""")
terms = cur.fetchall()

cur.close()
conn.close()

term_options = []
term_dict = {}

for t in terms:
    label = f"{t['term_name']} - {t['academic_year']}"
    term_options.append(label)
    term_dict[label] = t["id"]

selected_term_label = st.sidebar.selectbox(
    "Select Term",
    term_options if term_options else ["No Terms Available"]
)

selected_term_id = None
if term_options:
    selected_term_id = term_dict[selected_term_label]

# ===============================
# SIDEBAR MENU (Original Style)
# ===============================

menu = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Students",
        "Payments",
        "Uniforms",
        "Staff",
        "Expenses",
        "Terms",
        "Reports",
        "Logout"
    ]
)

if menu == "Logout":
    logout()
# ===============================
# DASHBOARD
# ===============================

if menu == "Dashboard":

    st.title("Dashboard")

    conn, cur = get_cursor()

    # Total Students
    cur.execute("SELECT COUNT(*) AS total FROM students")
    total_students = cur.fetchone()["total"]

    # Total Payments (Selected Term)
    total_payments = 0
    if selected_term_id:
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM payments WHERE term_id = %s",
            (selected_term_id,)
        )
        total_payments = cur.fetchone()["total"]

    # Total Expenses
    cur.execute("SELECT COALESCE(SUM(amount),0) AS total FROM expenses")
    total_expenses = cur.fetchone()["total"]

    cur.close()
    conn.close()

    col1, col2, col3 = st.columns(3)

    col1.metric("Total Students", total_students)
    col2.metric("Total Payments (Selected Term)", total_payments)
    col3.metric("Total Expenses", total_expenses)


# ===============================
# STUDENTS SECTION
# ===============================

if menu == "Students":

    st.title("Students")

    tab1, tab2 = st.tabs(["Add Student", "View Students"])

    # -------- ADD STUDENT --------
    with tab1:
        with st.form("add_student_form"):
            admission_number = st.text_input("Admission Number")
            full_name = st.text_input("Full Name")
            student_class = st.text_input("Class")
            gender = st.selectbox("Gender", ["Male", "Female"])
            parent_name = st.text_input("Parent Name")
            parent_contact = st.text_input("Parent Contact")

            submit_student = st.form_submit_button("Add Student")

            if submit_student:
                conn, cur = get_cursor()
                try:
                    cur.execute("""
                        INSERT INTO students
                        (admission_number, full_name, class, gender, parent_name, parent_contact)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (admission_number) DO NOTHING
                    """, (
                        admission_number,
                        full_name,
                        student_class,
                        gender,
                        parent_name,
                        parent_contact
                    ))

                    conn.commit()
                    st.success("Student added successfully.")
                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Error: {e}")

                cur.close()
                conn.close()

    # -------- VIEW STUDENTS --------
    with tab2:
        conn, cur = get_cursor()
        cur.execute("SELECT * FROM students ORDER BY full_name")
        students = cur.fetchall()
        cur.close()
        conn.close()

        if students:
            df_students = pd.DataFrame(students)
            st.dataframe(df_students)
        else:
            st.info("No students found.")


# ===============================
# PAYMENTS SECTION
# ===============================

if menu == "Payments":

    st.title("Payments")

    if not selected_term_id:
        st.warning("Please create and select a term first.")
        st.stop()

    conn, cur = get_cursor()

    # Fetch students
    cur.execute("SELECT id, full_name FROM students ORDER BY full_name")
    students = cur.fetchall()

    student_dict = {s["full_name"]: s["id"] for s in students}

    tab1, tab2 = st.tabs(["Record Payment", "View Payments"])

    # -------- RECORD PAYMENT --------
    with tab1:
        with st.form("payment_form"):

            student_name = st.selectbox("Select Student", list(student_dict.keys()))
            amount = st.number_input("Amount Paid", min_value=0.0)
            payment_type = st.selectbox("Payment Type", ["School Fees", "Development", "Other"])
            receipt_number = st.text_input("Receipt Number")

            submit_payment = st.form_submit_button("Record Payment")

            if submit_payment and amount > 0:

                try:
                    cur.execute("""
                        INSERT INTO payments
                        (student_id, amount, payment_type, term_id, receipt_number)
                        VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT (receipt_number) DO NOTHING
                    """, (
                        student_dict[student_name],
                        amount,
                        payment_type,
                        selected_term_id,
                        receipt_number
                    ))

                    conn.commit()
                    st.success("Payment recorded successfully.")
                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Error: {e}")

    # -------- VIEW PAYMENTS --------
    with tab2:

        cur.execute("""
            SELECT p.id, s.full_name, p.amount, p.payment_type,
                   p.receipt_number, p.payment_date
            FROM payments p
            JOIN students s ON p.student_id = s.id
            WHERE p.term_id = %s
            ORDER BY p.payment_date DESC
        """, (selected_term_id,))

        payments = cur.fetchall()

        if payments:
            df_payments = pd.DataFrame(payments)
            st.dataframe(df_payments)
        else:
            st.info("No payments recorded for this term.")

    cur.close()
    conn.close()
# ===============================
# TERMS SECTION
# ===============================

if menu == "Terms":

    st.title("Terms Management")

    tab1, tab2 = st.tabs(["Add Term", "View Terms"])

    # -------- ADD TERM --------
    with tab1:
        with st.form("add_term_form"):
            term_name = st.selectbox("Term Name", ["Term 1", "Term 2", "Term 3"])
            academic_year = st.text_input("Academic Year (e.g. 2026)")

            submit_term = st.form_submit_button("Add Term")

            if submit_term:
                conn, cur = get_cursor()
                try:
                    cur.execute("""
                        INSERT INTO terms (term_name, academic_year)
                        VALUES (%s,%s)
                        ON CONFLICT (term_name, academic_year) DO NOTHING
                    """, (term_name, academic_year))

                    conn.commit()
                    st.success("Term added successfully.")
                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Error: {e}")

                cur.close()
                conn.close()

    # -------- VIEW TERMS --------
    with tab2:
        conn, cur = get_cursor()
        cur.execute("SELECT * FROM terms ORDER BY academic_year DESC")
        terms = cur.fetchall()
        cur.close()
        conn.close()

        if terms:
            st.dataframe(pd.DataFrame(terms))
        else:
            st.info("No terms available.")


# ===============================
# STAFF SECTION
# ===============================

if menu == "Staff":

    st.title("Staff Management")

    tab1, tab2 = st.tabs(["Add Staff", "View Staff"])

    with tab1:
        with st.form("add_staff_form"):
            full_name = st.text_input("Full Name")
            position = st.text_input("Position")
            contact = st.text_input("Contact")
            salary = st.number_input("Salary", min_value=0.0)

            submit_staff = st.form_submit_button("Add Staff")

            if submit_staff:
                conn, cur = get_cursor()
                try:
                    cur.execute("""
                        INSERT INTO staff (full_name, position, contact, salary)
                        VALUES (%s,%s,%s,%s)
                    """, (full_name, position, contact, salary))

                    conn.commit()
                    st.success("Staff added successfully.")
                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Error: {e}")

                cur.close()
                conn.close()

    with tab2:
        conn, cur = get_cursor()
        cur.execute("SELECT * FROM staff ORDER BY full_name")
        staff = cur.fetchall()
        cur.close()
        conn.close()

        if staff:
            st.dataframe(pd.DataFrame(staff))
        else:
            st.info("No staff records found.")


# ===============================
# UNIFORMS SECTION
# ===============================

if menu == "Uniforms":

    st.title("Uniform Management")

    tab1, tab2 = st.tabs(["Add Uniform", "View Uniforms"])

    with tab1:
        with st.form("add_uniform_form"):
            item_name = st.text_input("Item Name")
            size = st.text_input("Size")
            quantity = st.number_input("Quantity", min_value=0)
            unit_price = st.number_input("Unit Price", min_value=0.0)

            submit_uniform = st.form_submit_button("Add Uniform")

            if submit_uniform:
                conn, cur = get_cursor()
                try:
                    cur.execute("""
                        INSERT INTO uniforms (item_name, size, quantity, unit_price)
                        VALUES (%s,%s,%s,%s)
                    """, (item_name, size, quantity, unit_price))

                    conn.commit()
                    st.success("Uniform added successfully.")
                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Error: {e}")

                cur.close()
                conn.close()

    with tab2:
        conn, cur = get_cursor()
        cur.execute("SELECT * FROM uniforms ORDER BY item_name")
        uniforms = cur.fetchall()
        cur.close()
        conn.close()

        if uniforms:
            st.dataframe(pd.DataFrame(uniforms))
        else:
            st.info("No uniform records found.")


# ===============================
# EXPENSES SECTION
# ===============================

if menu == "Expenses":

    st.title("Expenses")

    tab1, tab2 = st.tabs(["Add Expense", "View Expenses"])

    with tab1:
        with st.form("add_expense_form"):
            expense_name = st.text_input("Expense Name")
            amount = st.number_input("Amount", min_value=0.0)
            description = st.text_area("Description")

            submit_expense = st.form_submit_button("Add Expense")

            if submit_expense:
                conn, cur = get_cursor()
                try:
                    cur.execute("""
                        INSERT INTO expenses (expense_name, amount, description)
                        VALUES (%s,%s,%s)
                    """, (expense_name, amount, description))

                    conn.commit()
                    st.success("Expense recorded successfully.")
                    st.rerun()

                except Exception as e:
                    conn.rollback()
                    st.error(f"Error: {e}")

                cur.close()
                conn.close()

    with tab2:
        conn, cur = get_cursor()
        cur.execute("SELECT * FROM expenses ORDER BY expense_date DESC")
        expenses = cur.fetchall()
        cur.close()
        conn.close()

        if expenses:
            st.dataframe(pd.DataFrame(expenses))
        else:
            st.info("No expenses recorded.")


# ===============================
# REPORTS SECTION
# ===============================

if menu == "Reports":

    st.title("Reports")

    conn, cur = get_cursor()

    # Total Income Per Term
    cur.execute("""
        SELECT t.term_name, t.academic_year,
               COALESCE(SUM(p.amount),0) as total_income
        FROM terms t
        LEFT JOIN payments p ON t.id = p.term_id
        GROUP BY t.term_name, t.academic_year
        ORDER BY t.academic_year DESC
    """)
    report_data = cur.fetchall()

    cur.close()
    conn.close()

    if report_data:
        st.dataframe(pd.DataFrame(report_data))
    else:
        st.info("No report data available.")
# ────────────────────────────────────────────────
# Footer
# ────────────────────────────────────────────────
st.markdown("---")
st.caption(f"© COSNA School Management System • {datetime.now().year}")
st.caption("Developed for Cosna Daycare, Nursery, Day and Boarding Primary School Kiyinda-Mityana")
