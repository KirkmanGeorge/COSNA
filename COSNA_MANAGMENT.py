import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import secrets  # For generating reset codes
import smtplib
from email.mime.text import MIMEText
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ─── Page config & basic styling ───────────────────────────────────────
st.set_page_config(page_title="Costa School Management", layout="wide")
st.title("Costa School Management System")
st.markdown("Login-based system for students, uniforms, expenses & income")

# ─── SQLite connection (persistent file) ───────────────────────────────
@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect('costa_school.db', check_same_thread=False)
    return conn

conn = get_db_connection()
cursor = conn.cursor()

# Create tables if not exist (added users table)
cursor.execute('''CREATE TABLE IF NOT EXISTS users
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   username TEXT UNIQUE,
                   password TEXT,
                   email TEXT UNIQUE,
                   reset_code TEXT,
                   reset_expiry DATETIME)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS classes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS students
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT, age INTEGER, enrollment_date DATE,
                   class_id INTEGER, FOREIGN KEY(class_id) REFERENCES classes(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS uniforms
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   type TEXT, size TEXT, stock INTEGER, unit_cost REAL)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS expenses
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, category TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS incomes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date DATE, amount REAL, source TEXT)''')

# Add default admin if not exists
cursor.execute("SELECT * FROM users WHERE username = 'admin'")
if not cursor.fetchone():
    cursor.execute("INSERT INTO users (username, password, email) VALUES (?, ?, ?)",
                   ('admin', 'costa2026', 'admin@costa.school'))  # Change email to school one
    conn.commit()

conn.commit()

# ─── Session state ─────────────────────────────────────────────────────
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'reset_mode' not in st.session_state:
    st.session_state.reset_mode = False
if 'reset_username' not in st.session_state:
    st.session_state.reset_username = None

# ─── Email sending function (configure in secrets.toml) ────────────────
def send_reset_email(email, code):
    try:
        smtp_server = st.secrets["smtp"]["server"]
        smtp_port = st.secrets["smtp"]["port"]
        sender_email = st.secrets["smtp"]["sender"]
        sender_password = st.secrets["smtp"]["password"]

        msg = MIMEText(f"Your password reset code is: {code}\nIt expires in 30 minutes.")
        msg['Subject'] = 'Costa School Password Reset'
        msg['From'] = sender_email
        msg['To'] = email

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Email sending failed: {str(e)}")
        return False

# ─── Login / Reset Logic ───────────────────────────────────────────────
def login_page():
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        cursor.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if user and user[1] == password:  # Plain text for simplicity; hash in production
            st.session_state.logged_in = True
            st.session_state.user_id = user[0]
            st.success("Logged in!")
            st.rerun()
        else:
            st.error("Invalid credentials")

    # Forgot Password
    if st.button("Forgot Password?"):
        st.session_state.reset_mode = True
        st.rerun()

    if st.session_state.reset_mode:
        st.subheader("Reset Password")
        username = st.text_input("Enter your username for reset")
        if st.button("Send Reset Code"):
            cursor.execute("SELECT id, email FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            if user:
                code = secrets.token_hex(4).upper()  # 8-char code
                expiry = datetime.now() + timedelta(minutes=30)
                cursor.execute("UPDATE users SET reset_code = ?, reset_expiry = ? WHERE id = ?",
                               (code, expiry, user[0]))
                conn.commit()
                if send_reset_email(user[1], code):
                    st.success("Reset code sent to your school email!")
                    st.session_state.reset_username = username
                else:
                    st.error("Failed to send email. Check configuration.")
            else:
                st.error("Username not found")

        if st.session_state.reset_username:
            code_input = st.text_input("Enter reset code")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            if st.button("Change Password"):
                if new_password != confirm_password:
                    st.error("Passwords don't match")
                else:
                    cursor.execute("SELECT reset_code, reset_expiry FROM users WHERE username = ?",
                                   (st.session_state.reset_username,))
                    reset_data = cursor.fetchone()
                    if reset_data and reset_data[0] == code_input and datetime.now() < datetime.fromisoformat(reset_data[1]):
                        cursor.execute("UPDATE users SET password = ?, reset_code = NULL, reset_expiry = NULL WHERE username = ?",
                                       (new_password, st.session_state.reset_username))
                        conn.commit()
                        st.success("Password changed successfully!")
                        st.session_state.reset_mode = False
                        st.session_state.reset_username = None
                        st.rerun()
                    else:
                        st.error("Invalid or expired code")

if not st.session_state.logged_in:
    login_page()
    st.stop()

# Logout button
if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.rerun()

# ─── Sidebar navigation ────────────────────────────────────────────────
page = st.sidebar.radio("Navigate", ["Dashboard", "Students", "Uniforms", "Finances", "Financial Report"])

# ─── Dashboard ─────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Overview")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Students", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
    col2.metric("Total Uniform Items", conn.execute("SELECT SUM(stock) FROM uniforms").fetchone()[0] or 0)
    col3.metric("Net Balance (All Time)", 
                f"${conn.execute('SELECT SUM(amount) FROM incomes').fetchone()[0] or 0 - (conn.execute('SELECT SUM(amount) FROM expenses').fetchone()[0] or 0):,.2f}")

# ─── Students Page ─────────────────────────────────────────────────────
elif page == "Students":
    st.header("Students Management")
    
    tab1, tab2 = st.tabs(["View / Add", "Add Student"])
    
    with tab1:
        df = pd.read_sql_query("""
            SELECT s.id, s.name, s.age, s.enrollment_date, c.name as class_name
            FROM students s LEFT JOIN classes c ON s.class_id = c.id
        """, conn)
        st.dataframe(df, use_container_width=True)
        
        # Excel Export
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Students', index=False)
        output.seek(0)
        st.download_button(
            label="Download Students Excel Report",
            data=output,
            file_name="students_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    with tab2:
        st.subheader("Add New Student")
        with st.form("add_student"):
            name = st.text_input("Name")
            age = st.number_input("Age", min_value=5, max_value=25, step=1)
            enroll_date = st.date_input("Enrollment Date", value=datetime.today())
            classes_list = pd.read_sql("SELECT id, name FROM classes", conn)
            class_choice = st.selectbox("Class", classes_list['name'] if not classes_list.empty else ["No classes yet"])
            class_id = classes_list[classes_list['name'] == class_choice]['id'].values[0] if not classes_list.empty and class_choice != "No classes yet" else None
            
            submitted = st.form_submit_button("Add Student")
            if submitted and name and class_id:
                cursor.execute("INSERT INTO students (name, age, enrollment_date, class_id) VALUES (?, ?, ?, ?)",
                               (name, age, enroll_date, class_id))
                conn.commit()
                st.success("Student added!")
                st.rerun()

    # Add Class form (simple)
    with st.expander("Add New Class"):
        new_class = st.text_input("Class Name (e.g. P.1)")
        if st.button("Add Class") and new_class:
            try:
                cursor.execute("INSERT INTO classes (name) VALUES (?)", (new_class,))
                conn.commit()
                st.success(f"Class '{new_class}' added")
            except sqlite3.IntegrityError:
                st.error("Class already exists")

# ─── Uniforms Page ─────────────────────────────────────────────────────
elif page == "Uniforms":
    st.header("Uniforms Inventory")
    
    df_uniforms = pd.read_sql("SELECT * FROM uniforms", conn)
    st.dataframe(df_uniforms, use_container_width=True)
    
    # Excel Export
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_uniforms.to_excel(writer, sheet_name='Uniforms', index=False)
    output.seek(0)
    st.download_button(
        label="Download Uniforms Excel Report",
        data=output,
        file_name="uniforms_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    
    with st.form("add_uniform"):
        utype = st.text_input("Type (e.g. Shirt)")
        size = st.text_input("Size (e.g. M)")
        stock = st.number_input("Stock", min_value=0, step=1)
        cost = st.number_input("Unit Cost (UGX)", min_value=0.0, step=100.0)
        if st.form_submit_button("Add Uniform"):
            cursor.execute("INSERT INTO uniforms (type, size, stock, unit_cost) VALUES (?, ?, ?, ?)",
                           (utype, size, stock, cost))
            conn.commit()
            st.success("Uniform added")
            st.rerun()

# ─── Finances Page ─────────────────────────────────────────────────────
elif page == "Finances":
    st.header("Income & Expenses")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Add Expense")
        with st.form("add_expense"):
            exp_date = st.date_input("Date", value=datetime.today())
            exp_amount = st.number_input("Amount", min_value=0.0, step=1000.0)
            exp_cat = st.text_input("Category (e.g. Salaries)")
            if st.form_submit_button("Record Expense"):
                cursor.execute("INSERT INTO expenses (date, amount, category) VALUES (?, ?, ?)",
                               (exp_date, exp_amount, exp_cat))
                conn.commit()
                st.success("Expense recorded")

    with col2:
        st.subheader("Add Income")
        with st.form("add_income"):
            inc_date = st.date_input("Date", value=datetime.today())
            inc_amount = st.number_input("Amount", min_value=0.0, step=1000.0)
            inc_src = st.text_input("Source (e.g. Fees)")
            if st.form_submit_button("Record Income"):
                cursor.execute("INSERT INTO incomes (date, amount, source) VALUES (?, ?, ?)",
                               (inc_date, inc_amount, inc_src))
                conn.commit()
                st.success("Income recorded")

    # Quick views
    df_exp = pd.read_sql("SELECT * FROM expenses ORDER BY date DESC LIMIT 20", conn)
    df_inc = pd.read_sql("SELECT * FROM incomes ORDER BY date DESC LIMIT 20", conn)
    
    tab1, tab2 = st.tabs(["Recent Expenses", "Recent Incomes"])
    with tab1: st.dataframe(df_exp)
    with tab2: st.dataframe(df_inc)
    
    # Excel Exports
    col_export1, col_export2 = st.columns(2)
    with col_export1:
        output_exp = BytesIO()
        with pd.ExcelWriter(output_exp, engine='xlsxwriter') as writer:
            df_exp.to_excel(writer, sheet_name='Expenses', index=False)
        output_exp.seek(0)
        st.download_button(
            label="Download Expenses Excel",
            data=output_exp,
            file_name="expenses_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with col_export2:
        output_inc = BytesIO()
        with pd.ExcelWriter(output_inc, engine='xlsxwriter') as writer:
            df_inc.to_excel(writer, sheet_name='Incomes', index=False)
        output_inc.seek(0)
        st.download_button(
            label="Download Incomes Excel",
            data=output_inc,
            file_name="incomes_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ─── Financial Report ──────────────────────────────────────────────────
elif page == "Financial Report":
    st.header("Financial Report")
    
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start Date", value=datetime(datetime.today().year, 1, 1))
    end_date   = col2.date_input("End Date", value=datetime.today())
    
    if st.button("Generate Report"):
        query_exp = "SELECT * FROM expenses WHERE date BETWEEN ? AND ?"
        query_inc = "SELECT * FROM incomes WHERE date BETWEEN ? AND ?"
        
        df_exp = pd.read_sql_query(query_exp, conn, params=(start_date, end_date))
        df_inc = pd.read_sql_query(query_inc, conn, params=(start_date, end_date))
        
        total_exp = df_exp['amount'].sum()
        total_inc = df_inc['amount'].sum()
        balance = total_inc - total_exp
        
        st.metric("Total Income", f"USh {total_inc:,.0f}")
        st.metric("Total Expenses", f"USh {total_exp:,.0f}")
        st.metric("Balance", f"USh {balance:,.0f}", delta_color="normal")
        
        tab1, tab2 = st.tabs(["Income", "Expenses"])
        with tab1: st.dataframe(df_inc)
        with tab2: st.dataframe(df_exp)
        
        # PDF Export
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.drawString(100, 750, "Costa School Financial Report")
        pdf.drawString(100, 730, f"Period: {start_date} to {end_date}")
        y = 690
        pdf.drawString(100, y, f"Total Income: USh {total_inc:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Total Expenses: USh {total_exp:,.0f}"); y -= 40
        pdf.drawString(100, y, f"Balance: USh {balance:,.0f}")
        pdf.save()
        buffer.seek(0)
        
        st.download_button(
            label="Download PDF Report",
            data=buffer,
            file_name=f"costa_report_{start_date}_to_{end_date}.pdf",
            mime="application/pdf"
        )
        
        # Excel Export for Report
        output_report = BytesIO()
        with pd.ExcelWriter(output_report, engine='xlsxwriter') as writer:
            df_inc.to_excel(writer, sheet_name='Incomes', index=False)
            df_exp.to_excel(writer, sheet_name='Expenses', index=False)
            # Add summary sheet
            summary_df = pd.DataFrame({
                'Metric': ['Total Income', 'Total Expenses', 'Balance'],
                'Value': [total_inc, total_exp, balance]
            })
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
        output_report.seek(0)
        st.download_button(
            label="Download Excel Report",
            data=output_report,
            file_name=f"costa_financial_report_{start_date}_to_{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

st.sidebar.info("Data saved in SQLite file (persistent on Streamlit Cloud)")
