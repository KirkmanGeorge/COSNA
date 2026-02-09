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

# ─── Database ──────────────────────────────────────────────────────────
def get_db_connection():
    """Create a new database connection for each query"""
    return sqlite3.connect('cosna_school.db', check_same_thread=False)

def generate_receipt_number(prefix="RCPT"):
    """Generate unique receipt number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_invoice_number(prefix="INV"):
    """Generate unique invoice number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

def generate_voucher_number(prefix="VCH"):
    """Generate unique voucher number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{random_chars}"

# ─── Initialize database ───────────────────────────────────────────────
def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Existing tables
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
    
    # Enhanced expense categories with type
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expense_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT UNIQUE,
            category_type TEXT DEFAULT 'Expense' CHECK(category_type IN ('Expense', 'Income'))
        )
    ''')
    
    # Enhanced expenses table with voucher numbers
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
    
    # Enhanced incomes table with receipt numbers
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
    
    # Fee structure table
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
    
    # Student invoices table
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
    
    # Invoice items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            description TEXT,
            amount REAL,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')
    
    # Payments table linking to invoices
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

    # Seed uniforms
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

    # Enhanced expense/income categories
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
            cursor.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, ?)", (cat, cat_type))
            conn.commit()
    
    # Check for existing columns and add if missing
    try:
        cursor.execute("SELECT receipt_number FROM incomes LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE incomes ADD COLUMN receipt_number TEXT UNIQUE")
        cursor.execute("ALTER TABLE incomes ADD COLUMN category_id INTEGER")
        cursor.execute("ALTER TABLE incomes ADD COLUMN description TEXT")
        cursor.execute("ALTER TABLE incomes ADD COLUMN payment_method TEXT")
        cursor.execute("ALTER TABLE incomes ADD COLUMN payer TEXT")
        cursor.execute("ALTER TABLE incomes ADD COLUMN attachment_path TEXT")
        cursor.execute("ALTER TABLE incomes ADD COLUMN received_by TEXT")
    
    try:
        cursor.execute("SELECT voucher_number FROM expenses LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE expenses ADD COLUMN voucher_number TEXT UNIQUE")
        cursor.execute("ALTER TABLE expenses ADD COLUMN description TEXT")
        cursor.execute("ALTER TABLE expenses ADD COLUMN payment_method TEXT")
        cursor.execute("ALTER TABLE expenses ADD COLUMN payee TEXT")
        cursor.execute("ALTER TABLE expenses ADD COLUMN attachment_path TEXT")
        cursor.execute("ALTER TABLE expenses ADD COLUMN approved_by TEXT")
    
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
    
    # Total Income
    total_income = conn.execute("SELECT SUM(amount) FROM incomes").fetchone()[0] or 0
    col1.metric("Total Income", f"USh {total_income:,.0f}")
    
    # Total Expenses
    total_expenses = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    col2.metric("Total Expenses", f"USh {total_expenses:,.0f}")
    
    # Net Balance
    net_balance = total_income - total_expenses
    col3.metric("Net Balance", f"USh {net_balance:,.0f}", delta=f"USh {net_balance:,.0f}")
    
    # Outstanding Fees
    try:
        outstanding_fees = conn.execute("SELECT SUM(balance_amount) FROM invoices WHERE status != 'Fully Paid'").fetchone()[0] or 0
    except:
        outstanding_fees = 0
    col4.metric("Outstanding Fees", f"USh {outstanding_fees:,.0f}")
    
    # Recent Transactions
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Recent Income (Last 5)")
        df_inc = pd.read_sql("""
            SELECT date, receipt_number, amount, source, payment_method 
            FROM incomes 
            ORDER BY date DESC LIMIT 5
        """, conn)
        st.dataframe(df_inc, width='stretch')
    
    with col2:
        st.subheader("Recent Expenses (Last 5)")
        df_exp = pd.read_sql("""
            SELECT e.date, e.voucher_number, e.amount, ec.name as category, e.payment_method
            FROM expenses e 
            LEFT JOIN expense_categories ec ON e.category_id = ec.id
            ORDER BY e.date DESC LIMIT 5
        """, conn)
        st.dataframe(df_exp, width='stretch')
    
    # Monthly Summary
    st.subheader("Monthly Financial Summary")
    df_monthly = pd.read_sql("""
        SELECT 
            strftime('%Y-%m', date) as month,
            SUM(CASE WHEN ec.category_type = 'Income' THEN i.amount ELSE 0 END) as total_income,
            SUM(CASE WHEN ec.category_type = 'Expense' THEN e.amount ELSE 0 END) as total_expense,
            SUM(CASE WHEN ec.category_type = 'Income' THEN i.amount ELSE 0 END) - 
            SUM(CASE WHEN ec.category_type = 'Expense' THEN e.amount ELSE 0 END) as net_balance
        FROM incomes i
        LEFT JOIN expense_categories ec ON i.category_id = ec.id
        LEFT JOIN expenses e ON strftime('%Y-%m', i.date) = strftime('%Y-%m', e.date)
        GROUP BY strftime('%Y-%m', i.date)
        ORDER BY month DESC
        LIMIT 6
    """, conn)
    st.dataframe(df_monthly, width='stretch')
    
    conn.close()

# ─── Students ──────────────────────────────────────────────────────────
elif page == "Students":
    # ... (keep existing student code, but add fee management link)
    st.header("Students")
    
    tab_view, tab_add, tab_fees = st.tabs(["View & Export", "Add Student", "Student Fees"])
    
    # ... existing student code in tab_view and tab_add ...
    
    with tab_fees:
        st.subheader("Student Fee Management")
        conn = get_db_connection()
        
        # Select student
        students = pd.read_sql("""
            SELECT s.id, s.name, c.name as class_name 
            FROM students s 
            LEFT JOIN classes c ON s.class_id = c.id 
            ORDER BY s.name
        """, conn)
        
        if not students.empty:
            selected_student = st.selectbox("Select Student", 
                students.apply(lambda x: f"{x['name']} - {x['class_name']} (ID: {x['id']})", axis=1))
            student_id = int(selected_student.split("(ID: ")[1].replace(")", ""))
            
            # Get student invoices
            invoices = pd.read_sql("""
                SELECT * FROM invoices 
                WHERE student_id = ? 
                ORDER BY issue_date DESC
            """, conn, params=(student_id,))
            
            if not invoices.empty:
                st.dataframe(invoices[['invoice_number', 'issue_date', 'due_date', 'total_amount', 'paid_amount', 'balance_amount', 'status']], width='stretch')
                
                # Record payment
                with st.expander("Record Payment"):
                    with st.form("record_payment"):
                        selected_invoice = st.selectbox("Select Invoice", invoices['invoice_number'].tolist())
                        invoice_id = invoices[invoices['invoice_number'] == selected_invoice]['id'].iloc[0]
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            payment_date = st.date_input("Payment Date", datetime.today())
                            amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0)
                            payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                        
                        with col2:
                            reference_number = st.text_input("Reference Number")
                            receipt_number = st.text_input("Receipt Number", value=generate_receipt_number())
                            notes = st.text_area("Notes")
                        
                        if st.form_submit_button("Record Payment"):
                            # Update invoice
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE invoices 
                                SET paid_amount = paid_amount + ?, 
                                    balance_amount = balance_amount - ?,
                                    status = CASE 
                                        WHEN balance_amount - ? <= 0 THEN 'Fully Paid'
                                        WHEN paid_amount + ? > 0 THEN 'Partially Paid'
                                        ELSE status
                                    END
                                WHERE id = ?
                            """, (amount, amount, amount, amount, invoice_id))
                            
                            # Record payment
                            cursor.execute("""
                                INSERT INTO payments (invoice_id, receipt_number, payment_date, amount, 
                                                     payment_method, reference_number, notes, received_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (invoice_id, receipt_number, payment_date, amount, payment_method, reference_number, notes, "Admin"))
                            
                            # Record income
                            cursor.execute("""
                                INSERT INTO incomes (date, receipt_number, amount, source, category_id, 
                                                    payment_method, payer, received_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (payment_date, receipt_number, amount, "Tuition Fee Payment", 
                                  8, payment_method, students[students['id'] == student_id]['name'].iloc[0], "Admin"))
                            
                            conn.commit()
                            st.success("Payment recorded successfully!")
            else:
                st.info("No invoices found for this student")
        
        conn.close()

# ─── Uniforms ──────────────────────────────────────────────────────────
elif page == "Uniforms":
    # ... (keep existing uniform code) ...

# ─── Finances ──────────────────────────────────────────────────────────
elif page == "Finances":
    st.header("💼 Advanced Financial Management")
    
    tab_income, tab_expense, tab_categories, tab_reports = st.tabs(["Income Records", "Expense Records", "Categories", "Financial Reports"])
    
    # ─── INCOME TAB ────────────────────────────────────────────────────
    with tab_income:
        st.subheader("Record Income")
        
        with st.form("add_income"):
            col1, col2 = st.columns(2)
            
            with col1:
                date = st.date_input("Date", datetime.today())
                receipt_number = st.text_input("Receipt Number", value=generate_receipt_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0, value=0.0)
                
                # Income categories
                conn = get_db_connection()
                income_cats = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
                income_source = st.selectbox("Income Category", income_cats["name"])
                category_id = income_cats[income_cats["name"] == income_source]["id"].iloc[0] if not income_cats.empty else None
                
                # Link to student if applicable
                students = pd.read_sql("SELECT id, name FROM students ORDER BY name", conn)
                payer_options = ["Select Payer"] + students["name"].tolist() + ["Other"]
                payer = st.selectbox("Payer", payer_options)
                
                if payer != "Select Payer" and payer != "Other":
                    student_id = students[students["name"] == payer]["id"].iloc[0]
                else:
                    student_id = None
                    if payer == "Other":
                        payer = st.text_input("Enter Payer Name")
            
            with col2:
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"])
                received_by = st.text_input("Received By", "Admin")
                description = st.text_area("Description")
                
                # Optional attachment
                uploaded_file = st.file_uploader("Upload Receipt/Attachment", type=['pdf', 'jpg', 'png', 'jpeg'])
                attachment_path = None
                if uploaded_file is not None:
                    attachment_path = f"receipts/{receipt_number}_{uploaded_file.name}"
                    # In production, save the file: uploaded_file.save(attachment_path)
            
            col1, col2, col3 = st.columns([1, 1, 2])
            with col2:
                if st.form_submit_button("💰 Record Income", type="primary"):
                    if not receipt_number:
                        st.error("Receipt Number is required!")
                    else:
                        cursor = conn.cursor()
                        try:
                            cursor.execute("""
                                INSERT INTO incomes (date, receipt_number, amount, source, category_id, 
                                                    description, payment_method, payer, student_id, 
                                                    attachment_path, received_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (date, receipt_number, amount, income_source, category_id, description, 
                                  payment_method, payer, student_id, attachment_path, received_by))
                            conn.commit()
                            st.success(f"Income of USh {amount:,.0f} recorded successfully! Receipt: {receipt_number}")
                            conn.close()
                            time.sleep(1)
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Receipt number already exists. Please generate a new one.")
            
            conn.close()
        
        # Income Records
        st.subheader("Income Records")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="income_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="income_end")
        with col3:
            filter_category = st.selectbox("Filter by Category", ["All Categories"] + income_cats["name"].tolist())
        
        query = """
            SELECT i.date, i.receipt_number, i.amount, i.source, i.payer, 
                   i.payment_method, i.received_by, i.description
            FROM incomes i
            LEFT JOIN expense_categories ec ON i.category_id = ec.id
            WHERE i.date BETWEEN ? AND ?
        """
        params = [start_date, end_date]
        
        if filter_category != "All Categories":
            query += " AND ec.name = ?"
            params.append(filter_category)
        
        query += " ORDER BY i.date DESC"
        
        conn = get_db_connection()
        income_records = pd.read_sql_query(query, conn, params=params)
        
        if not income_records.empty:
            st.dataframe(income_records, width='stretch')
            
            # Summary
            total_income = income_records['amount'].sum()
            st.info(f"**Total Income for period:** USh {total_income:,.0f}")
            
            # Export
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                income_records.to_excel(writer, sheet_name='Income Records', index=False)
            buf.seek(0)
            st.download_button("📥 Download Income Report", buf, f"income_report_{start_date}_{end_date}.xlsx", 
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("No income records found for the selected period")
        
        conn.close()
    
    # ─── EXPENSE TAB ───────────────────────────────────────────────────
    with tab_expense:
        st.subheader("Record Expense")
        
        with st.form("add_expense"):
            col1, col2 = st.columns(2)
            
            with col1:
                date = st.date_input("Date", datetime.today(), key="expense_date")
                voucher_number = st.text_input("Voucher Number", value=generate_voucher_number())
                amount = st.number_input("Amount (USh)", min_value=0.0, step=1000.0, value=0.0, key="expense_amount")
                
                # Expense categories
                conn = get_db_connection()
                expense_cats = pd.read_sql("SELECT id, name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name", conn)
                expense_category = st.selectbox("Expense Category", expense_cats["name"])
                category_id = expense_cats[expense_cats["name"] == expense_category]["id"].iloc[0] if not expense_cats.empty else None
            
            with col2:
                payment_method = st.selectbox("Payment Method", ["Cash", "Bank Transfer", "Mobile Money", "Cheque"], key="expense_payment")
                payee = st.text_input("Payee/Beneficiary")
                approved_by = st.text_input("Approved By", "Admin")
                description = st.text_area("Description", key="expense_desc")
                
                # Optional attachment
                uploaded_file = st.file_uploader("Upload Voucher/Attachment", type=['pdf', 'jpg', 'png', 'jpeg'], key="expense_upload")
                attachment_path = None
                if uploaded_file is not None:
                    attachment_path = f"vouchers/{voucher_number}_{uploaded_file.name}"
            
            col1, col2, col3 = st.columns([1, 1, 2])
            with col2:
                if st.form_submit_button("💳 Record Expense", type="primary"):
                    if not voucher_number:
                        st.error("Voucher Number is required!")
                    else:
                        cursor = conn.cursor()
                        try:
                            cursor.execute("""
                                INSERT INTO expenses (date, voucher_number, amount, category_id, 
                                                     description, payment_method, payee, 
                                                     attachment_path, approved_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (date, voucher_number, amount, category_id, description, 
                                  payment_method, payee, attachment_path, approved_by))
                            conn.commit()
                            st.success(f"Expense of USh {amount:,.0f} recorded successfully! Voucher: {voucher_number}")
                            conn.close()
                            time.sleep(1)
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Voucher number already exists. Please generate a new one.")
            
            conn.close()
        
        # Expense Records
        st.subheader("Expense Records")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="expense_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="expense_end")
        with col3:
            filter_category = st.selectbox("Filter by Category", ["All Categories"] + expense_cats["name"].tolist(), key="expense_filter")
        
        query = """
            SELECT e.date, e.voucher_number, e.amount, ec.name as category, e.payee, 
                   e.payment_method, e.approved_by, e.description
            FROM expenses e
            LEFT JOIN expense_categories ec ON e.category_id = ec.id
            WHERE e.date BETWEEN ? AND ?
        """
        params = [start_date, end_date]
        
        if filter_category != "All Categories":
            query += " AND ec.name = ?"
            params.append(filter_category)
        
        query += " ORDER BY e.date DESC"
        
        conn = get_db_connection()
        expense_records = pd.read_sql_query(query, conn, params=params)
        
        if not expense_records.empty:
            st.dataframe(expense_records, width='stretch')
            
            # Summary
            total_expense = expense_records['amount'].sum()
            st.info(f"**Total Expenses for period:** USh {total_expense:,.0f}")
            
            # Export
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                expense_records.to_excel(writer, sheet_name='Expense Records', index=False)
            buf.seek(0)
            st.download_button("📥 Download Expense Report", buf, f"expense_report_{start_date}_{end_date}.xlsx", 
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("No expense records found for the selected period")
        
        conn.close()
    
    # ─── CATEGORIES TAB ────────────────────────────────────────────────
    with tab_categories:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Income Categories")
            conn = get_db_connection()
            income_cats = pd.read_sql("SELECT name FROM expense_categories WHERE category_type = 'Income' ORDER BY name", conn)
            st.dataframe(income_cats, width='stretch')
            
            with st.expander("Add Income Category"):
                with st.form("add_income_category"):
                    new_cat = st.text_input("New Income Category")
                    if st.form_submit_button("Add Category") and new_cat:
                        cursor = conn.cursor()
                        try:
                            cursor.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, 'Income')", (new_cat,))
                            conn.commit()
                            st.success(f"Income category '{new_cat}' added")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Category already exists")
        
        with col2:
            st.subheader("Expense Categories")
            expense_cats = pd.read_sql("SELECT name FROM expense_categories WHERE category_type = 'Expense' ORDER BY name", conn)
            st.dataframe(expense_cats, width='stretch')
            
            with st.expander("Add Expense Category"):
                with st.form("add_expense_category"):
                    new_cat = st.text_input("New Expense Category")
                    if st.form_submit_button("Add Category") and new_cat:
                        cursor = conn.cursor()
                        try:
                            cursor.execute("INSERT INTO expense_categories (name, category_type) VALUES (?, 'Expense')", (new_cat,))
                            conn.commit()
                            st.success(f"Expense category '{new_cat}' added")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Category already exists")
        
        conn.close()
    
    # ─── REPORTS TAB ───────────────────────────────────────────────────
    with tab_reports:
        st.subheader("Advanced Financial Reports")
        
        report_type = st.selectbox("Select Report Type", [
            "Income Statement",
            "Expense Analysis", 
            "Payment Method Summary",
            "Category-wise Summary",
            "Daily Transaction Report"
        ])
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="report_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="report_end")
        
        conn = get_db_connection()
        
        if report_type == "Income Statement":
            st.subheader("Income Statement")
            
            # Income Summary
            income_summary = pd.read_sql("""
                SELECT 
                    ec.name as category,
                    COUNT(*) as transactions,
                    SUM(i.amount) as total_amount,
                    AVG(i.amount) as average_amount
                FROM incomes i
                LEFT JOIN expense_categories ec ON i.category_id = ec.id
                WHERE i.date BETWEEN ? AND ?
                GROUP BY ec.name
                ORDER BY total_amount DESC
            """, conn, params=(start_date, end_date))
            
            if not income_summary.empty:
                st.dataframe(income_summary, width='stretch')
                
                # Chart
                st.bar_chart(income_summary.set_index('category')['total_amount'])
            else:
                st.info("No income data for the selected period")
        
        elif report_type == "Expense Analysis":
            st.subheader("Expense Analysis")
            
            expense_summary = pd.read_sql("""
                SELECT 
                    ec.name as category,
                    COUNT(*) as transactions,
                    SUM(e.amount) as total_amount,
                    AVG(e.amount) as average_amount
                FROM expenses e
                LEFT JOIN expense_categories ec ON e.category_id = ec.id
                WHERE e.date BETWEEN ? AND ?
                GROUP BY ec.name
                ORDER BY total_amount DESC
            """, conn, params=(start_date, end_date))
            
            if not expense_summary.empty:
                st.dataframe(expense_summary, width='stretch')
                
                # Pie chart
                st.write("Expense Distribution")
                st.dataframe(expense_summary[['category', 'total_amount']].set_index('category'))
            else:
                st.info("No expense data for the selected period")
        
        elif report_type == "Payment Method Summary":
            st.subheader("Payment Method Summary")
            
            # Income by payment method
            income_methods = pd.read_sql("""
                SELECT 
                    payment_method,
                    COUNT(*) as transactions,
                    SUM(amount) as total_amount
                FROM incomes
                WHERE date BETWEEN ? AND ?
                GROUP BY payment_method
                ORDER BY total_amount DESC
            """, conn, params=(start_date, end_date))
            
            # Expense by payment method
            expense_methods = pd.read_sql("""
                SELECT 
                    payment_method,
                    COUNT(*) as transactions,
                    SUM(amount) as total_amount
                FROM expenses
                WHERE date BETWEEN ? AND ?
                GROUP BY payment_method
                ORDER BY total_amount DESC
            """, conn, params=(start_date, end_date))
            
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Income by Payment Method**")
                if not income_methods.empty:
                    st.dataframe(income_methods, width='stretch')
                else:
                    st.info("No income data")
            
            with col2:
                st.write("**Expense by Payment Method**")
                if not expense_methods.empty:
                    st.dataframe(expense_methods, width='stretch')
                else:
                    st.info("No expense data")
        
        elif report_type == "Category-wise Summary":
            st.subheader("Category-wise Summary")
            
            summary = pd.read_sql("""
                SELECT 
                    ec.name as category,
                    ec.category_type as type,
                    COUNT(CASE WHEN ec.category_type = 'Income' THEN i.id ELSE e.id END) as transactions,
                    SUM(CASE WHEN ec.category_type = 'Income' THEN i.amount ELSE e.amount END) as total_amount
                FROM expense_categories ec
                LEFT JOIN incomes i ON ec.id = i.category_id AND i.date BETWEEN ? AND ?
                LEFT JOIN expenses e ON ec.id = e.category_id AND e.date BETWEEN ? AND ?
                GROUP BY ec.name, ec.category_type
                HAVING total_amount IS NOT NULL
                ORDER BY type, total_amount DESC
            """, conn, params=(start_date, end_date, start_date, end_date))
            
            if not summary.empty:
                st.dataframe(summary, width='stretch')
            else:
                st.info("No data for the selected period")
        
        elif report_type == "Daily Transaction Report":
            st.subheader("Daily Transaction Report")
            
            daily_report = pd.read_sql("""
                SELECT 
                    date,
                    'Income' as type,
                    receipt_number as reference,
                    source as description,
                    amount,
                    payment_method
                FROM incomes
                WHERE date BETWEEN ? AND ?
                
                UNION ALL
                
                SELECT 
                    date,
                    'Expense' as type,
                    voucher_number as reference,
                    description,
                    amount * -1 as amount,
                    payment_method
                FROM expenses
                WHERE date BETWEEN ? AND ?
                
                ORDER BY date DESC, type
            """, conn, params=(start_date, end_date, start_date, end_date))
            
            if not daily_report.empty:
                st.dataframe(daily_report, width='stretch')
                
                # Daily summary
                daily_summary = pd.read_sql("""
                    SELECT 
                        date,
                        SUM(CASE WHEN type = 'Income' THEN amount ELSE 0 END) as total_income,
                        SUM(CASE WHEN type = 'Expense' THEN amount ELSE 0 END) as total_expense,
                        SUM(amount) as net_balance
                    FROM (
                        SELECT date, 'Income' as type, amount FROM incomes
                        UNION ALL
                        SELECT date, 'Expense' as type, amount * -1 as amount FROM expenses
                    )
                    WHERE date BETWEEN ? AND ?
                    GROUP BY date
                    ORDER BY date DESC
                """, conn, params=(start_date, end_date))
                
                st.write("**Daily Summary**")
                st.dataframe(daily_summary, width='stretch')
            else:
                st.info("No transactions for the selected period")
        
        conn.close()

# ─── Financial Report (Existing) ──────────────────────────────────────
elif page == "Financial Report":
    # ... (keep existing financial report code, enhanced with new fields) ...

# ─── NEW: Fee Management ──────────────────────────────────────────────
elif page == "Fee Management":
    st.header("🎓 Fee Management System")
    
    tab_structure, tab_invoices, tab_payments = st.tabs(["Fee Structure", "Generate Invoices", "Payment Records"])
    
    with tab_structure:
        st.subheader("Define Fee Structure")
        
        conn = get_db_connection()
        
        with st.form("fee_structure_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                selected_class = st.selectbox("Class", classes["name"])
                class_id = classes[classes["name"] == selected_class]["id"].iloc[0] if not classes.empty else None
                
                term = st.selectbox("Term", ["Term 1", "Term 2", "Term 3"])
                academic_year = st.text_input("Academic Year", f"{datetime.today().year}/{datetime.today().year+1}")
            
            with col2:
                tuition_fee = st.number_input("Tuition Fee (USh)", min_value=0.0, value=0.0)
                uniform_fee = st.number_input("Uniform Fee (USh)", min_value=0.0, value=0.0)
                activity_fee = st.number_input("Activity Fee (USh)", min_value=0.0, value=0.0)
                exam_fee = st.number_input("Exam Fee (USh)", min_value=0.0, value=0.0)
                library_fee = st.number_input("Library Fee (USh)", min_value=0.0, value=0.0)
                other_fee = st.number_input("Other Fees (USh)", min_value=0.0, value=0.0)
            
            total_fee = tuition_fee + uniform_fee + activity_fee + exam_fee + library_fee + other_fee
            st.info(f"**Total Fee:** USh {total_fee:,.0f}")
            
            if st.form_submit_button("Save Fee Structure"):
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO fee_structure 
                    (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, 
                     exam_fee, library_fee, other_fee, total_fee)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (class_id, term, academic_year, tuition_fee, uniform_fee, activity_fee, 
                      exam_fee, library_fee, other_fee, total_fee))
                conn.commit()
                st.success("Fee structure saved successfully!")
        
        # View existing fee structures
        st.subheader("Existing Fee Structures")
        fee_structures = pd.read_sql("""
            SELECT fs.id, c.name as class, fs.term, fs.academic_year, 
                   fs.tuition_fee, fs.uniform_fee, fs.activity_fee, 
                   fs.exam_fee, fs.library_fee, fs.other_fee, fs.total_fee
            FROM fee_structure fs
            LEFT JOIN classes c ON fs.class_id = c.id
            ORDER BY fs.academic_year DESC, fs.term, c.name
        """, conn)
        
        if not fee_structures.empty:
            st.dataframe(fee_structures, width='stretch')
        else:
            st.info("No fee structures defined yet")
        
        conn.close()
    
    with tab_invoices:
        st.subheader("Generate Student Invoices")
        
        conn = get_db_connection()
        
        with st.form("generate_invoice"):
            col1, col2 = st.columns(2)
            
            with col1:
                # Select class
                classes = pd.read_sql("SELECT id, name FROM classes ORDER BY name", conn)
                selected_class = st.selectbox("Class", classes["name"])
                class_id = classes[classes["name"] == selected_class]["id"].iloc[0] if not classes.empty else None
                
                # Get fee structure for class
                fee_structures = pd.read_sql("""
                    SELECT id, term, academic_year, total_fee 
                    FROM fee_structure 
                    WHERE class_id = ? 
                    ORDER BY academic_year DESC, term
                """, conn, params=(class_id,))
                
                if not fee_structures.empty:
                    fee_structure_options = fee_structures.apply(
                        lambda x: f"{x['academic_year']} - {x['term']} (USh {x['total_fee']:,.0f})", 
                        axis=1
                    )
                    selected_fee = st.selectbox("Fee Structure", fee_structure_options)
                    fee_structure_id = fee_structures.iloc[fee_structure_options.tolist().index(selected_fee)]['id']
                else:
                    st.error("No fee structure defined for this class")
                    fee_structure_id = None
            
            with col2:
                issue_date = st.date_input("Issue Date", datetime.today())
                due_date = st.date_input("Due Date", datetime.today())
                invoice_number = st.text_input("Invoice Number", value=generate_invoice_number())
                notes = st.text_area("Notes")
            
            # Get students in selected class
            students = pd.read_sql("""
                SELECT id, name FROM students 
                WHERE class_id = ? 
                ORDER BY name
            """, conn, params=(class_id,))
            
            if not students.empty:
                st.write(f"**Students in {selected_class}:** {len(students)} students")
                
                # Multi-select for students
                selected_students = st.multiselect(
                    "Select Students to Invoice",
                    students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1),
                    default=students.apply(lambda x: f"{x['name']} (ID: {x['id']})", axis=1).tolist()
                )
                
                if st.form_submit_button("📄 Generate Invoices"):
                    if fee_structure_id:
                        fee_details = fee_structures[fee_structures['id'] == fee_structure_id].iloc[0]
                        
                        cursor = conn.cursor()
                        invoices_created = 0
                        
                        for student_option in selected_students:
                            student_id = int(student_option.split("(ID: ")[1].replace(")", ""))
                            
                            # Generate invoice
                            cursor.execute("""
                                INSERT INTO invoices 
                                (invoice_number, student_id, issue_date, due_date, academic_year, 
                                 term, total_amount, paid_amount, balance_amount, status, notes)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'Pending', ?)
                            """, (
                                f"{invoice_number}-{student_id}",
                                student_id,
                                issue_date,
                                due_date,
                                fee_details['academic_year'],
                                fee_details['term'],
                                fee_details['total_fee'],
                                fee_details['total_fee'],
                                notes
                            ))
                            
                            # Add invoice items
                            invoice_id = cursor.lastrowid
                            
                            # Add fee breakdown as items
                            fee_breakdown = pd.read_sql("""
                                SELECT tuition_fee, uniform_fee, activity_fee, exam_fee, library_fee, other_fee
                                FROM fee_structure WHERE id = ?
                            """, conn, params=(fee_structure_id,)).iloc[0]
                            
                            items = [
                                ("Tuition Fee", fee_breakdown['tuition_fee']),
                                ("Uniform Fee", fee_breakdown['uniform_fee']),
                                ("Activity Fee", fee_breakdown['activity_fee']),
                                ("Exam Fee", fee_breakdown['exam_fee']),
                                ("Library Fee", fee_breakdown['library_fee']),
                                ("Other Fees", fee_breakdown['other_fee'])
                            ]
                            
                            for description, amount in items:
                                if amount > 0:
                                    cursor.execute("""
                                        INSERT INTO invoice_items (invoice_id, description, amount)
                                        VALUES (?, ?, ?)
                                    """, (invoice_id, description, amount))
                            
                            invoices_created += 1
                        
                        conn.commit()
                        st.success(f"✅ {invoices_created} invoices generated successfully!")
                    else:
                        st.error("Please select a fee structure")
            else:
                st.info(f"No students found in {selected_class}")
        
        conn.close()
    
    with tab_payments:
        st.subheader("Payment Records")
        
        conn = get_db_connection()
        
        # Filter options
        col1, col2, col3 = st.columns(3)
        with col1:
            start_date = st.date_input("Start Date", datetime(datetime.today().year, 1, 1), key="payment_start")
        with col2:
            end_date = st.date_input("End Date", datetime.today(), key="payment_end")
        with col3:
            payment_method_filter = st.selectbox("Payment Method", ["All Methods", "Cash", "Bank Transfer", "Mobile Money", "Cheque"])
        
        query = """
            SELECT p.payment_date, p.receipt_number, p.amount, p.payment_method, 
                   p.reference_number, p.received_by, p.notes,
                   i.invoice_number, s.name as student_name, c.name as class_name
            FROM payments p
            LEFT JOIN invoices i ON p.invoice_id = i.id
            LEFT JOIN students s ON i.student_id = s.id
            LEFT JOIN classes c ON s.class_id = c.id
            WHERE p.payment_date BETWEEN ? AND ?
        """
        params = [start_date, end_date]
        
        if payment_method_filter != "All Methods":
            query += " AND p.payment_method = ?"
            params.append(payment_method_filter)
        
        query += " ORDER BY p.payment_date DESC"
        
        payment_records = pd.read_sql_query(query, conn, params=params)
        
        if not payment_records.empty:
            st.dataframe(payment_records, width='stretch')
            
            # Summary
            total_payments = payment_records['amount'].sum()
            st.info(f"**Total Payments:** USh {total_payments:,.0f}")
            
            # Export
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                payment_records.to_excel(writer, sheet_name='Payment Records', index=False)
            buf.seek(0)
            st.download_button("📥 Download Payment Report", buf, f"payment_report_{start_date}_{end_date}.xlsx", 
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("No payment records found for the selected period")
        
        conn.close()

st.sidebar.info("Logged in as admin – Professional Financial Management System")
