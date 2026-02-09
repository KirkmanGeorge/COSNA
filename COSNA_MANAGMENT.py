import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import time
import random
import string

# ─── Page config ───────────────────────────────────────────────────────
st.set_page_config(page_title="COSNA School Management", layout="wide", initial_sidebar_state="expanded")
st.title("COSNA School Management System")
st.markdown("Students • Uniforms • Finances • Reports")

# ─── Simple login ──────────────────────────────────────────────────────
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username == "admin" and password == "costa2026":
            st.session_state.logged_in = True
            st.success("Logged in!")
            st.rerun()
        else:
            st.error("Invalid credentials")
    st.stop()

with st.sidebar:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

# ─── Database helpers ──────────────────────────────────────────────────
def get_db_connection():
    return sqlite3.connect('cosna_school.db', check_same_thread=False)

def generate_receipt_number(prefix="RCPT"):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_invoice_number(prefix="INV"):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_voucher_number(prefix="VCH"):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

# ─── Initialize database ───────────────────────────────────────────────
# (your original initialize_database function - unchanged)
def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # expense_categories with category_type (your original code)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='expense_categories'")
    table_exists = cursor.fetchone()
    
    if table_exists:
        try:
            cursor.execute("SELECT category_type FROM expense_categories LIMIT 1")
            category_type_exists = True
        except sqlite3.OperationalError:
            category_type_exists = False
        
        if not category_type_exists:
            cursor.execute('''
                CREATE TABLE expense_categories_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    name TEXT UNIQUE,
                    category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense', 'Income'))
                )
            ''')
            cursor.execute("INSERT INTO expense_categories_new (name, category_type) SELECT name, 'Expense' FROM expense_categories")
            cursor.execute("DROP TABLE expense_categories")
            cursor.execute("ALTER TABLE expense_categories_new RENAME TO expense_categories")
            conn.commit()
    else:
        cursor.execute('''
            CREATE TABLE expense_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT UNIQUE,
                category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense', 'Income'))
            )
        ''')
    
    # Other tables...
    cursor.execute('''CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT, 
            age INTEGER, 
            enrollment_date DATE, 
            class_id INTEGER,
            student_type TEXT DEFAULT 'Returning',
            registration_fee_paid BOOLEAN DEFAULT 0,
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS uniform_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT UNIQUE, gender TEXT, is_shared INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER UNIQUE, stock INTEGER DEFAULT 0, unit_price REAL DEFAULT 0.0, FOREIGN KEY(category_id) REFERENCES uniform_categories(id))''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            date DATE, 
            voucher_number TEXT UNIQUE,
            amount REAL, 
            category_id INTEGER,
            description TEXT,
            payment_method TEXT CHECK(payment_method IN ('Cash', 'Bank Transfer', 'Mobile Money', 'Cheque')),
            payee TEXT,
            attachment_path TEXT,
            approved_by TEXT,
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
            payment_method TEXT CHECK(payment_method IN ('Cash', 'Bank Transfer', 'Mobile Money', 'Cheque')),
            payer TEXT,
            student_id INTEGER DEFAULT NULL,
            attachment_path TEXT,
            received_by TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(category_id) REFERENCES expense_categories(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fee_structure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER,
            term TEXT CHECK(term IN ('Term 1', 'Term 2', 'Term 3')),
            academic_year TEXT,
            tuition_fee REAL DEFAULT 0,
            uniform_fee REAL DEFAULT 0,
            activity_fee REAL DEFAULT 0,
            exam_fee REAL DEFAULT 0,
            library_fee REAL DEFAULT 0,
            other_fee REAL DEFAULT 0,
            total_fee REAL DEFAULT 0,
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
            status TEXT CHECK(status IN ('Pending', 'Partially Paid', 'Fully Paid', 'Overdue')),
            notes TEXT,
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
            payment_method TEXT CHECK(payment_method IN ('Cash', 'Bank Transfer', 'Mobile Money', 'Cheque')),
            reference_number TEXT,
            received_by TEXT,
            notes TEXT,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')
    
    conn.commit()

    # Seed data (your original seeds)
    uniform_seeds = [
        ('Boys Main Shorts', 'boys', 0),
        ('Button Shirts Main', 'shared', 1),
        ('Boys Stockings', 'boys', 0),
        ('Boys Sports Shorts', 'boys', 0),
        ('Shared Sports T-Shirts', 'shared', 1),
        ('Girls Main Dresses', 'girls', 0)
    ]
    for name, gender, shared in uniform_seeds:
        cursor.execute("SELECT id FROM uniform_categories WHERE category = ?", (name,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO uniform_categories (category, gender, is_shared) VALUES (?, ?, ?)", (name, gender, shared))
            conn.commit()
            cat_id = cursor.lastrowid
            cursor.execute("INSERT INTO uniforms (category_id, stock, unit_price) VALUES (?, 0, 0.0)", (cat_id,))
            conn.commit()

    expense_seeds = [
        ('Medical', 'Expense'),
        ('Salaries', 'Expense'),
        ('Utilities', 'Expense'),
        ('Maintenance', 'Expense'),
        ('Supplies', 'Expense'),
        ('Transport', 'Expense'),
        ('Events', 'Expense'),
        ('Tuition Fees', 'Income'),
        ('Registration Fees', 'Income'),
        ('Uniform Sales', 'Income'),
        ('Donations', 'Income'),
        ('Other Income', 'Income')
    ]
    
    for cat, cat_type in expense_seeds:
        cursor.execute("SELECT id FROM expense_categories WHERE name = ?", (cat,))
        if not cursor.fetchone():
            try:
                cursor.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, ?)", (cat, cat_type))
                conn.commit()
            except sqlite3.IntegrityError:
                cursor.execute("INSERT INTO expense_categories (name) VALUES (?)", (cat,))
                conn.commit()
    
    # Add missing columns safely
    for table, cols in [
        ('incomes', ['receipt_number TEXT UNIQUE', 'category_id INTEGER', 'description TEXT', 'payment_method TEXT', 'payer TEXT', 'attachment_path TEXT', 'received_by TEXT']),
        ('expenses', ['voucher_number TEXT UNIQUE', 'description TEXT', 'payment_method TEXT', 'payee TEXT', 'attachment_path TEXT', 'approved_by TEXT'])
    ]:
        for col_def in cols:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass  # column already exists
    
    conn.commit()
    conn.close()

initialize_database()

# ─── Navigation ────────────────────────────────────────────────────────
page = st.sidebar.radio("Menu", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report", "Fee Management"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    conn = get_db_connection()
    st.header("📊 Financial Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    total_income = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    col1.metric("Total Income", f"USh {total_income:,.0f}")
    
    total_expenses = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col2.metric("Total Expenses", f"USh {total_expenses:,.0f}")
    
    net_balance = total_income - total_expenses
    col3.metric("Net Balance", f"USh {net_balance:,.0f}", delta=f"USh {net_balance:,.0f}")
    
    try:
        outstanding_fees = conn.execute("SELECT SUM(balance_amount) FROM invoices WHERE status != 'Fully Paid'").fetchone()[0] or 0
    except:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Recent Income (Last 5)")
        try:
            df_inc = pd.read_sql("SELECT date, amount, source FROM incomes ORDER BY date DESC LIMIT 5", conn)
            st.dataframe(df_inc, width='stretch')
        except:
            st.info("No income records yet")
    
    with col2:
        st.subheader("Recent Expenses (Last 5)")
        try:
            df_exp = pd.read_sql("""
                SELECT e.date, e.amount, ec.name as category
                FROM expenses e 
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                ORDER BY e.date DESC LIMIT 5
            """, conn)
            st.dataframe(df_exp, width='stretch')
        except:
            try:
                df_exp = pd.read_sql("SELECT date, amount FROM expenses ORDER BY date DESC LIMIT 5", conn)
                st.dataframe(df_exp, width='stretch')
            except:
                st.info("No expense records yet")
    
    st.subheader("Monthly Financial Summary")
    try:
        df_monthly = pd.read_sql("""
            SELECT 
                strftime('%Y-%m', date) as month,
                SUM(amount) as total_amount,
                'Income' as type
            FROM incomes
            GROUP BY strftime('%Y-%m', date)
            
            UNION ALL
            
            SELECT 
                strftime('%Y-%m', date) as month,
                SUM(amount) as total_amount,
                'Expense' as type
            FROM expenses
            GROUP BY strftime('%Y-%m', date)
            
            ORDER BY month DESC
            LIMIT 12
        """, conn)
        
        if not df_monthly.empty:
            df_pivot = df_monthly.pivot_table(index='month', columns='type', values='total_amount', aggfunc='sum').fillna(0)
            df_pivot['Net Balance'] = df_pivot.get('Income', 0) - df_pivot.get('Expense', 0)
            st.dataframe(df_pivot, width='stretch')
        else:
            st.info("No financial data available")
    except:
        st.info("No monthly data available")
    
    conn.close()

# ─── Students (your original code with PDF added) ──────────────────────
elif page == "Students":
    # ... (keep your full original Students code here)
    # Add PDF export in tab_view if not already present:
    # After st.dataframe(df, width='stretch')
    if not df.empty:
        pdf_buf = BytesIO()
        pdf = canvas.Canvas(pdf_buf, pagesize=letter)
        pdf.drawString(100, 750, "Students List")
        y = 720
        for _, row in df.iterrows():
            pdf.drawString(100, y, f"{row['name']} - Class: {row.get('class_name', 'N/A')}")
            y -= 20
            if y < 100:
                pdf.showPage()
                y = 750
        pdf.save()
        pdf_buf.seek(0)
        st.download_button("Download PDF", pdf_buf, "students.pdf", "application/pdf")

# ─── Uniforms (your original code) ─────────────────────────────────────
elif page == "Uniforms":
    # ... (your full original Uniforms code - unchanged)

# ─── Finances (your original code with fixes) ──────────────────────────
elif page == "Finances":
    st.header("💼 Advanced Financial Management")
    
    tab_income, tab_expense, tab_categories, tab_reports = st.tabs(["Income Records", "Expense Records", "Categories", "Financial Reports"])
    
    # Income tab (your original code)
    with tab_income:
        # ... (keep your original income recording and records display)
        # Add PDF export in income_records display:
        if not income_records.empty:
            pdf_buf = BytesIO()
            pdf = canvas.Canvas(pdf_buf, pagesize=letter)
            pdf.drawString(100, 750, "Income Records")
            y = 730
            for _, row in income_records.iterrows():
                pdf.drawString(100, y, f"{row['date']} | USh {row['amount']:,.0f} | {row.get('source', 'N/A')}")
                y -= 20
                if y < 100:
                    pdf.showPage()
                    y = 750
            pdf.save()
            pdf_buf.seek(0)
            st.download_button("Download Income PDF", pdf_buf, f"income_{start_date}_{end_date}.pdf", "application/pdf")

    # Expense tab (fixed & improved)
    with tab_expense:
        st.subheader("Record Expense")
        
        with st.form("add_expense"):
            col1, col2 = st.columns(2)
            
            with col1:
                date = st.date_input("Date", datetime.today())
                voucher_number = st.text_input("Voucher Number", value=generate_voucher_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
                
                conn = get_db_connection()
                expense_cats = pd.read_sql("SELECT id, name FROM expense_categories ORDER BY name", conn)
                if not expense_cats.empty:
                    expense_category = st.selectbox("Expense Category (required)", expense_cats["name"])
                    category_id = expense_cats[expense_cats["name"] == expense_category]["id"].iloc[0]
                else:
                    st.error("No categories found - add in Categories tab")
                    category_id = None
            
            with col2:
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                payee = st.text_input("Payee")
                approved_by = st.text_input("Approved By", "Admin")
                description = st.text_area("Description (required for statements)")
            
            if st.form_submit_button("Record Expense"):
                if not voucher_number:
                    st.error("Voucher Number required")
                elif category_id is None:
                    st.error("Select category")
                elif not description.strip():
                    st.error("Description required for financial reporting")
                else:
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT INTO expenses (date, voucher_number, amount, category_id, description, payment_method, payee, approved_by)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (date, voucher_number, amount, category_id, description.strip(), payment_method, payee, approved_by))
                        conn.commit()
                        st.success("Expense saved")
                    except Exception as e:
                        st.error(f"Save failed: {e}")
                    conn.close()
                    st.rerun()
        
        # Expense Records
        st.subheader("Expense Records")
        col1, col2 = st.columns(2)
        start_date = col1.date_input("From", datetime(datetime.today().year, 1, 1))
        end_date = col2.date_input("To", datetime.today())
        
        conn = get_db_connection()
        try:
            expense_records = pd.read_sql("""
                SELECT e.date, e.amount, ec.name as category, e.description, e.payment_method, e.payee
                FROM expenses e
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                WHERE e.date BETWEEN ? AND ?
                ORDER BY e.date DESC
            """, conn, params=(start_date, end_date))
            
            if not expense_records.empty:
                st.dataframe(expense_records, width='stretch')
                
                total = expense_records['amount'].sum()
                st.info(f"Total Expenses: USh {total:,.0f}")
                
                # Excel
                buf = BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    expense_records.to_excel(writer, index=False)
                buf.seek(0)
                st.download_button("Download Excel", buf, f"expenses_{start_date}_{end_date}.xlsx")
                
                # PDF
                pdf_buf = BytesIO()
                pdf = canvas.Canvas(pdf_buf, pagesize=letter)
                pdf.drawString(100, 750, "Expense Report")
                y = 720
                for _, row in expense_records.iterrows():
                    pdf.drawString(100, y, f"{row['date']} | {row['amount']:,.0f} | {row['category']} | {row['description'][:60]}")
                    y -= 20
                    if y < 100:
                        pdf.showPage()
                        y = 750
                pdf.save()
                pdf_buf.seek(0)
                st.download_button("Download PDF", pdf_buf, f"expenses_{start_date}_{end_date}.pdf")
            else:
                st.info("No expenses in period")
        except Exception as e:
            st.error(f"Query failed: {e}")
        conn.close()

    # Categories tab (your original)
    with tab_categories:
        # ... (your original code)

    # Reports tab (your original with exports added)
    with tab_reports:
        # ... (your original report logic)
        # Add Excel + PDF in each sub-report as shown in expense example above

# ─── Financial Report (fixed) ──────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")

    col1, col2 = st.columns(2)
    start = col1.date_input("Start Date", datetime(datetime.today().year, 1, 1))
    end = col2.date_input("End Date", datetime.today())

    if st.button("Generate Report"):
        conn = get_db_connection()
        
        # Safe expense query (no voucher_number assumption)
        exp = pd.read_sql_query("""
            SELECT e.date, e.amount, ec.name AS category, e.description
            FROM expenses e
            LEFT JOIN expense_categories ec ON e.category_id = ec.id
            WHERE e.date BETWEEN ? AND ?
            ORDER BY e.date DESC
        """, conn, params=(start, end))
        
        inc = pd.read_sql_query("""
            SELECT date, amount, source, description
            FROM incomes
            WHERE date BETWEEN ? AND ?
            ORDER BY date DESC
        """, conn, params=(start, end))

        total_exp = exp['amount'].sum() if not exp.empty else 0
        total_inc = inc['amount'].sum() if not inc.empty else 0
        balance = total_inc - total_exp

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Income", f"USh {total_inc:,.0f}")
        col2.metric("Total Expenses", f"USh {total_exp:,.0f}")
        col3.metric("Balance", f"USh {balance:,.0f}")

        tab1, tab2 = st.tabs(["Incomes", "Expenses"])
        with tab1:
            if not inc.empty:
                st.dataframe(inc)
            else:
                st.info("No incomes")
        with tab2:
            if not exp.empty:
                st.dataframe(exp)
            else:
                st.info("No expenses")

        # PDF (safe - no voucher_number)
        pdf_buf = BytesIO()
        pdf = canvas.Canvas(pdf_buf, pagesize=letter)
        pdf.drawString(100, 750, "Financial Report")
        pdf.drawString(100, 730, f"Period: {start} to {end}")
        y = 680
        pdf.drawString(100, y, f"Income: {total_inc:,.0f}   Expenses: {total_exp:,.0f}   Balance: {balance:,.0f}")
        pdf.save()
        pdf_buf.seek(0)
        st.download_button("Download PDF", pdf_buf, f"report_{start}_{end}.pdf")

        # Excel
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            inc.to_excel(writer, sheet_name='Incomes', index=False)
            exp.to_excel(writer, sheet_name='Expenses', index=False)
        buf.seek(0)
        st.download_button("Download Excel", buf, f"report_{start}_{end}.xlsx")

        conn.close()

# ─── Fee Management (fixed student lookup + preview) ───────────────────
elif page == "Fee Management":
    st.header("🎓 Fee Management System")
    
    tab_structure, tab_invoices, tab_payments = st.tabs(["Fee Structure", "Generate Invoices", "Payment Records"])
    
    with tab_structure:
        # your original fee structure code
        pass  # keep your code here
    
    with tab_invoices:
        st.subheader("Generate Student Invoices")
        conn = get_db_connection()
        
        with st.form("generate_invoice"):
            col1, col2 = st.columns(2)
            
            with col1:
                classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                selected_class = st.selectbox("Class", classes["name"] if not classes.empty else ["No classes"])
                class_id = classes[classes["name"] == selected_class]["id"].iloc[0] if not classes.empty else None
            
            with col2:
                issue_date = st.date_input("Issue Date", datetime.today())
                due_date = st.date_input("Due Date", datetime.today())
                invoice_number = st.text_input("Invoice Number", generate_invoice_number())
                notes = st.text_area("Notes")
            
            selected_students = []
            if class_id:
                students = pd.read_sql("SELECT id, name FROM students WHERE class_id = ? ORDER BY name", conn, params=(class_id,))
                if students.empty:
                    st.warning(f"No students in {selected_class}")
                else:
                    selected_students = st.multiselect(
                        "Select Students",
                        options=students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1).tolist(),
                        default=[]
                    )
            else:
                st.info("Select a class first")
            
            fee_amount = st.number_input("Fee per Student (USh)", min_value=0.0, step=1000.0)
            
            if st.form_submit_button("📄 Generate Invoices"):
                if not class_id:
                    st.error("Select class")
                elif fee_amount <= 0:
                    st.error("Amount > 0")
                elif not selected_students:
                    st.error("Select students")
                else:
                    cursor = conn.cursor()
                    created = []
                    for sel in selected_students:
                        sid = int(sel.split("ID: ")[1][:-1])
                        name = sel.split(" (ID")[0]
                        inv = f"{invoice_number}-{sid}"
                        cursor.execute("""
                            INSERT INTO invoices (invoice_number, student_id, issue_date, due_date, academic_year, term, total_amount, balance_amount, status, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
                        """, (inv, sid, issue_date, due_date, f"{datetime.today().year}/{datetime.today().year+1}", "Term 1", fee_amount, fee_amount, notes))
                        created.append({'Invoice': inv, 'Student': name, 'Amount': fee_amount})
                    conn.commit()
                    st.success(f"Generated {len(created)} invoices")
                    with st.expander("Preview"):
                        st.dataframe(pd.DataFrame(created))
        
        conn.close()
    
    with tab_payments:
        # your original payment records code
        pass

st.sidebar.info("Logged in as admin – Professional Financial Management System")
