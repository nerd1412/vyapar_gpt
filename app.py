import os
import re
import sqlite3
from io import BytesIO
import streamlit as st
from hashlib import sha256
import time
import uuid

# Groq OpenAI-compatible client
from openai import OpenAI

# Optional imports for PDFs
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except Exception:
    A4 = None
    canvas = None

try:
    import PyPDF2
except Exception:
    PyPDF2 = None

# =========================
# DATABASE SETUP
# =========================
DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create users table
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        first_name TEXT,
        last_name TEXT,
        email TEXT,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Create password_reset_tokens table
    c.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        used BOOLEAN DEFAULT FALSE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
    # Create chat_history table
    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    return sha256(password.encode()).hexdigest()

def register_user(username, password, first_name, last_name, email="", phone=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password, first_name, last_name, email, phone) VALUES (?, ?, ?, ?, ?, ?)",
            (username, hash_password(password), first_name, last_name, email, phone)
        )
        conn.commit()
        return True, "Registration successful!"
    except sqlite3.IntegrityError:
        return False, "Username already exists."
    finally:
        conn.close()

def authenticate_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", 
              (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    return user

# def create_password_reset_token(user_id):
#     conn = sqlite3.connect(DB_PATH)
#     c = conn.cursor()
#     token = str(uuid.uuid4())
#     expires_at = time.time() + 3600  # 1 hour from now
#     c.execute(
#         "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
#         (user_id, token, expires_at)
#     )
#     conn.commit()
#     conn.close()
#     return token

def create_password_reset_token(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    token = str(uuid.uuid4())
    expires_at = time.time() + 3600  # 1 hour from now
    c.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at)
    )
    conn.commit()
    conn.close()
    return token

def send_reset_email(email, token):
    """Mock email sending function - in production, integrate with real email service"""
    reset_link = f"https://your-app-url.com?token={token}"
    email_body = f"""
    <p>You requested a password reset for VyaparGPT.</p>
    <p>Click this link to reset your password (valid for 1 hour):</p>
    <p><a href="{reset_link}">{reset_link}</a></p>
    <p>If you didn't request this, please ignore this email.</p>
    """
    
    # In production, use a real email service like SendGrid, AWS SES, etc.
    print(f"Would send email to {email} with body:\n{email_body}")
    return True

def show_password_reset():
    if st.session_state.reset_token:
        # Token is present - show password update form
        user = validate_reset_token(st.session_state.reset_token)
        if user:
            st.subheader("Reset Your Password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            
            if st.button("Update Password"):
                if new_password == confirm_password:
                    update_password(user[0], new_password)
                    st.success("Password updated successfully! Please login with your new password.")
                    st.session_state.reset_token = None
                    st.rerun()
                else:
                    st.error("Passwords do not match!")
        else:
            st.error("Invalid or expired reset token")
            st.session_state.reset_token = None
    else:
        # No token - show username input form
        st.subheader("Forgot Password")
        username = st.text_input("Enter your username")
        
        if st.button("Send Reset Link"):
            user = get_user_by_username(username)
            if user:
                token = create_password_reset_token(user[0])
                user_email = user[5]  # email is at index 5
                
                if user_email:  # If user registered with email
                    if send_reset_email(user_email, token):
                        st.success("Password reset link sent to your email address!")
                    else:
                        st.error("Failed to send email. Please try again later.")
                else:
                    # For users without email, show the token directly
                    st.warning("No email address on file. Please use this reset token:")
                    st.code(token)
                    st.info("Copy this token and use it to reset your password")
            else:
                st.error("Username not found")

def validate_reset_token(token):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT u.* FROM password_reset_tokens t
        JOIN users u ON t.user_id = u.id
        WHERE t.token = ? AND t.expires_at > ? AND t.used = FALSE
    """, (token, time.time()))
    user = c.fetchone()
    conn.close()
    return user

def update_password(user_id, new_password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (hash_password(new_password), user_id))
    c.execute(
        "UPDATE password_reset_tokens SET used = TRUE WHERE user_id = ?",
        (user_id,))
    conn.commit()
    conn.close()

def save_chat_message(user_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content))
    conn.commit()
    conn.close()

def load_chat_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT role, content FROM chat_history 
        WHERE user_id = ? 
        ORDER BY timestamp ASC
    """, (user_id,))
    messages = [{"role": row[0], "content": row[1]} for row in c.fetchall()]
    conn.close()
    
    # Ensure system message is always first
    if not messages or messages[0]["role"] != "system":
        system_message = {
            "role": "system",
            "content": "You are VyaparGPT, an AI assistant helping Indian MSMEs with business, compliance, invoices, legal, HR, and documents."
        }
        messages.insert(0, system_message)
    return messages

def clear_chat_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# =========================
# CONFIG & PAGE SETUP
# =========================
st.set_page_config(page_title="VyaparGPT", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
      .small-note { color: #666; font-size: 0.9rem; }
      .section { padding: 0.25rem 0 1rem 0; }
      .welcome-message { 
          background-color: #e6f3ff;
          padding: 1rem;
          border-radius: 0.5rem;
          margin-bottom: 1rem;
          border-left: 4px solid #1e88e5;
      }
      .welcome-message h3 {
          color: #1a237e;
          margin-top: 0;
      }
      .welcome-message p {
          color: #0d47a1;
          margin-bottom: 0;
      }
      .typing {
          display: inline-block;
      }
      .typing-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background-color: #666;
          display: inline-block;
          margin: 0 2px;
          animation: typing-animation 1.4s infinite ease-in-out;
      }
      .typing-dot:nth-child(1) {
          animation-delay: 0s;
      }
      .typing-dot:nth-child(2) {
          animation-delay: 0.2s;
      }
      .typing-dot:nth-child(3) {
          animation-delay: 0.4s;
      }
      @keyframes typing-animation {
          0%, 60%, 100% { transform: translateY(0); }
          30% { transform: translateY(-5px); }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# GROQ CLIENT SETUP
# =========================
GROQ_API_KEY = "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"
client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
DEFAULT_MODEL = "llama-3.1-8b-instant"

# =========================
# SESSION STATE
# =========================
def init_state():
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = "Overview"
    if "invoice_customer" not in st.session_state:
        st.session_state.invoice_customer = ""
    if "invoice_amount" not in st.session_state:
        st.session_state.invoice_amount = 0.0
    if "debug" not in st.session_state:
        st.session_state.debug = False
    if "last_intent" not in st.session_state:
        st.session_state.last_intent = "none"
    if "logged_in_user" not in st.session_state:
        st.session_state.logged_in_user = None
    if "user_details" not in st.session_state:
        st.session_state.user_details = {}
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "system", "content": "You are VyaparGPT, an AI assistant helping Indian MSMEs with business, compliance, invoices, legal, HR, and documents."}
        ]
    if "typing_complete" not in st.session_state:
        st.session_state.typing_complete = False
    if "current_response" not in st.session_state:
        st.session_state.current_response = ""
    if "reset_token" not in st.session_state:
        st.session_state.reset_token = None

init_state()
init_db()

# =========================
# HELPERS
# =========================
def llm_chat(messages, model=DEFAULT_MODEL, max_tokens=800):
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        stream=True
    )
    return resp

def detect_intent(user_text: str):
    text = user_text.lower()
    
    # More precise invoice detection
    invoice_phrases = [
        "create invoice", "generate invoice", "make invoice",
        "create bill", "generate bill", "make bill",
        "invoice for", "bill for"
    ]
    if any(phrase in text for phrase in invoice_phrases):
        name_match = re.search(r"(?:invoice|bill|for)\s+(?:for|to|of)?\s*([a-zA-Z\s]+?)\s*(?:for|of|₹|rs|rupees|amount)", text)
        amt_match = re.search(r"(?:₹|rs\.?|rupees?|inr)\s*(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)", text) or \
                   re.search(r"\b(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:₹|rs|rupees|inr)?\b", text)
        
        cust = name_match.group(1).strip().title() if name_match else ""
        amt = float(amt_match.group(1).replace(',', '')) if amt_match else 0.0
        return ("invoice", {"customer": cust, "amount": amt})
    
    # Strict document detection - only when user explicitly mentions uploading
    doc_phrases = [
        "upload document", "explain document", "analyze document",
        "upload pdf", "explain pdf", "analyze pdf",
        "upload gst", "explain gst", "analyze notice",
        "can you analyze this", "help me understand this document"
    ]
    # Only trigger if user explicitly mentions uploading or analyzing a document
    has_upload_words = any(word in text for word in ["upload", "analyze", "explain"])
    has_doc_words = any(word in text for word in ["document", "pdf", "gst", "notice"])
    if (has_upload_words and has_doc_words) or any(phrase in text for phrase in doc_phrases):
        return ("document", {})
    
    return ("chat", {})

def generate_invoice_pdf(customer: str, amount: float) -> BytesIO:
    if canvas is None or A4 is None:
        raise RuntimeError("reportlab not installed. Run: pip install reportlab")
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(72, height - 72, "VyaparGPT - Invoice")
    pdf.setFont("Helvetica", 12)
    y = height - 120
    pdf.drawString(72, y, f"Customer: {customer or '-'}"); y -= 20
    pdf.drawString(72, y, f"Amount: ₹{amount:,.2f}"); y -= 20
    pdf.drawString(72, y, "Status: Pending"); y -= 30
    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawString(72, 72, "Generated by VyaparGPT (demo)")
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer

def read_pdf_text(uploaded_file, max_chars=8000) -> str:
    if PyPDF2 is None:
        raise RuntimeError("PyPDF2 not installed. Run: pip install PyPDF2")
    reader = PyPDF2.PdfReader(uploaded_file)
    text_chunks = []
    for page in reader.pages:
        try:
            text_chunks.append(page.extract_text() or "")
        except Exception:
            pass
        if sum(len(t) for t in text_chunks) > max_chars:
            break
    text = "\n".join(text_chunks)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text.strip()

def generate_legal_doc_pdf(doc_type: str, name: str) -> BytesIO:
    if canvas is None or A4 is None:
        raise RuntimeError("reportlab not installed. Run: pip install reportlab")
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, height - 72, f"{doc_type}")
    pdf.setFont("Helvetica", 12)
    y = height - 120
    if doc_type == "Offer Letter":
        lines = [
            f"Dear {name or 'Candidate'},",
            "We are pleased to offer you a position at our company.",
            "This offer is subject to company policies and applicable laws.",
            "Please sign and return to confirm your acceptance.",
        ]
    elif doc_type == "NDA":
        lines = [
            f"Non-Disclosure Agreement with {name or 'Party'}",
            "The parties agree to keep confidential information private.",
            "This agreement covers disclosures, obligations, and term.",
        ]
    else:
        lines = [
            "Leave Policy (Summary)",
            "- Earned Leave, Casual Leave, Sick Leave as per policy.",
            "- Prior approval required for planned leaves.",
            "- Medical certificate may be required for extended sick leave.",
        ]
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawString(72, 72, "Generated by VyaparGPT (demo)")
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer

# =========================
# PASSWORD RESET FUNCTIONS
# =========================
def show_password_reset():
    if st.session_state.reset_token:
        # Token is present - show password update form
        user = validate_reset_token(st.session_state.reset_token)
        if user:
            st.subheader("Reset Your Password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            
            if st.button("Update Password"):
                if new_password == confirm_password:
                    update_password(user[0], new_password)
                    st.success("Password updated successfully! Please login with your new password.")
                    st.session_state.reset_token = None
                    st.rerun()
                else:
                    st.error("Passwords do not match!")
        else:
            st.error("Invalid or expired reset token")
            st.session_state.reset_token = None
    else:
        # No token - show email input form
        st.subheader("Forgot Password")
        username = st.text_input("Enter your username")
        
        if st.button("Send Reset Link"):
            user = get_user_by_username(username)
            if user:
                token = create_password_reset_token(user[0])
                # In a real app, you would send this token via email
                st.success(f"Reset token generated (would be sent via email in production): {token}")
                st.info("For demo purposes, you can use this token to reset your password")
            else:
                st.error("Username not found")

# =========================
# LOGIN & REGISTRATION
# =========================
st.sidebar.title("👤 User Access")
if st.session_state.logged_in_user is None:
    if st.session_state.get("reset_token"):
        show_password_reset()
    else:
        action = st.sidebar.radio("Select Action", ["Login", "Register", "Forgot Password"])
        
        if action == "Register":
            st.sidebar.subheader("📝 Register New Account")
            first_name = st.sidebar.text_input("First Name")
            last_name = st.sidebar.text_input("Last Name")
            username = st.sidebar.text_input("Username")
            password = st.sidebar.text_input("Password", type="password")
            email = st.sidebar.text_input("Email (optional)")
            phone = st.sidebar.text_input("Phone (optional)")
            if st.sidebar.button("Register"):
                success, msg = register_user(username, password, first_name, last_name, email, phone)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
        
        elif action == "Login":
            st.sidebar.subheader("🔑 Login")
            username = st.sidebar.text_input("Username")
            password = st.sidebar.text_input("Password", type="password")
            if st.sidebar.button("Login"):
                user = authenticate_user(username, password)
                if user:
                    st.session_state.logged_in_user = user
                    st.session_state.user_details = {
                        "first_name": user[3],
                        "last_name": user[4],
                        "email": user[5],
                        "phone": user[6]
                    }
                    # Load user's chat history
                    st.session_state.messages = load_chat_history(user[0])
                    st.success(f"Welcome {user[3]} {user[4]}!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        
        elif action == "Forgot Password":
            st.session_state.reset_token = None
            show_password_reset()
else:
    st.sidebar.success(f"Logged in as: {st.session_state.logged_in_user[3]} {st.session_state.logged_in_user[4]}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in_user = None
        st.session_state.user_details = {}
        st.session_state.messages = [
            {"role": "system", "content": "You are VyaparGPT, an AI assistant helping Indian MSMEs with business, compliance, invoices, legal, HR, and documents."}
        ]
        st.rerun()

# =========================
# NAVIGATION
# =========================
if st.session_state.logged_in_user:
    nav_labels = ["Overview", "Chat Assistant", "Invoice Generator", "Explain Document", "Legal Doc Generator"]
    option = st.sidebar.radio("Navigate", nav_labels, index=nav_labels.index(st.session_state.active_tab))

    if st.sidebar.button("🧹 Clear Chat"):
        clear_chat_history(st.session_state.logged_in_user[0])
        st.session_state.messages = [
            {"role": "system", "content": "You are VyaparGPT, an AI assistant helping Indian MSMEs with business, compliance, invoices, legal, HR, and documents."}
        ]
        st.rerun()

    # =========================
    # OVERVIEW
    # =========================
    if option == "Overview":
        if st.session_state.logged_in_user:
            first_name = st.session_state.user_details.get("first_name", "")
            last_name = st.session_state.user_details.get("last_name", "")
            st.markdown(
                f"""
                <div class="welcome-message">
                    <h3>👋 Welcome back, {first_name} {last_name}!</h3>
                    <p>We're glad to see you again. How can we assist you today?</p>
                </div>
                """,
                unsafe_allow_html=True
            )
        
        st.title("📊 VyaparGPT — MSME AI Assistant")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### 💬 Chat Assistant")
            st.write("Ask about MSME compliance, loans, HR/legal, marketing, and business ops.")
        with col2:
            st.markdown("### 🧾 Invoice Generator")
            st.write("Create and download professional invoices as PDFs.")
        with col3:
            st.markdown("### 📄 Document Explainer")
            st.write("Upload GST/compliance PDFs and get AI explanations.")

        st.markdown("---")
        col4, col5 = st.columns(2)
        with col4:
            st.markdown("### ⚖️ Legal & HR")
            st.write("Generate simple Offer Letters, NDAs, and Leave Policies as PDFs.")
        with col5:
            st.markdown("### 🚀 Business Help")
            st.write("Guidance on Udyam, loans/subsidies, GeM/ONDC, trademarks, exports, and more.")

        st.info("Use the sidebar to explore each module. Everything works with free tooling.")

    # =========================
    # CHAT ASSISTANT
    # =========================
    elif option == "Chat Assistant":
        st.header("💬 Compliance / Business Chat")

        # Update system message to include user details if available
        if st.session_state.user_details and len(st.session_state.messages) > 0:
            user_info = st.session_state.user_details
            st.session_state.messages[0] = {
                "role": "system",
                "content": f"""You are VyaparGPT, an AI assistant helping Indian MSMEs with business, compliance, invoices, legal, HR, and documents.
                The current user is {user_info['first_name']} {user_info['last_name']}.
                Contact details - Email: {user_info.get('email', 'not provided')}, Phone: {user_info.get('phone', 'not provided')}."""
            }

        # Display chat messages (skip system message)
        for msg in st.session_state.messages[1:]:
            if msg["role"] == "user":
                st.chat_message("user").markdown(msg["content"])
            elif msg["role"] == "assistant":
                st.chat_message("assistant").markdown(msg["content"])

        user_input = st.chat_input("Ask your question… (e.g., 'Generate invoice for Anil ₹5000')")
        if user_input:
            # Save user message to DB and session
            save_chat_message(st.session_state.logged_in_user[0], "user", user_input)
            st.session_state.messages.append({"role": "user", "content": user_input})
            st.chat_message("user").markdown(user_input)

            intent, data = detect_intent(user_input)
            st.session_state.last_intent = intent

            if intent == "invoice":
                customer = data.get("customer", "") or st.session_state.invoice_customer
                amount = data.get("amount", 0.0) or st.session_state.invoice_amount
                
                st.session_state.invoice_customer = customer
                st.session_state.invoice_amount = amount
                
                if customer and amount:
                    reply = f"Sure! Taking you to the Invoice Generator for {customer} with amount ₹{amount:,.2f}..."
                elif customer:
                    reply = f"Understood! Preparing invoice for {customer}. Please enter the amount."
                elif amount:
                    reply = f"Got it! Preparing invoice for ₹{amount:,.2f}. Please enter customer name."
                else:
                    reply = "Taking you to the Invoice Generator..."
                
                # Save assistant message to DB and session
                save_chat_message(st.session_state.logged_in_user[0], "assistant", reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.chat_message("assistant").markdown(reply)
                
                st.session_state.active_tab = "Invoice Generator"
                st.rerun()

            elif intent == "document":
                reply = "Please upload your document in the Document Explainer section and I'll analyze it for you."
                # Save assistant message to DB and session
                save_chat_message(st.session_state.logged_in_user[0], "assistant", reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.chat_message("assistant").markdown(reply)
                st.session_state.active_tab = "Explain Document"
                st.rerun()

            # For regular chat queries - stream the response
            with st.spinner("Thinking..."):
                response_container = st.empty()
                full_response = ""
                
                # Stream the response
                for chunk in llm_chat(st.session_state.messages):
                    if chunk.choices[0].delta.content:
                        full_response += chunk.choices[0].delta.content
                        response_container.markdown(full_response + "▌")
                
                # Save the complete response
                save_chat_message(st.session_state.logged_in_user[0], "assistant", full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                response_container.markdown(full_response)

    # =========================
    # INVOICE GENERATOR
    # =========================
    elif option == "Invoice Generator":
        st.header("🧾 Create Invoice")

        customer = st.text_input("Customer Name", value=st.session_state.get("invoice_customer", ""))
        amount = st.number_input("Amount (₹)", min_value=0.0, value=float(st.session_state.get("invoice_amount", 0.0)))
        if st.button("Generate Invoice"):
            try:
                pdf_buffer = generate_invoice_pdf(customer, amount)
                st.success(f"✅ Invoice ready for {customer} — ₹{amount:,.2f}")
                st.download_button(
                    "⬇️ Download Invoice PDF",
                    data=pdf_buffer,
                    file_name=f"invoice_{customer or 'customer'}.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.error(f"Could not generate PDF. {e}")
                st.caption("Tip: Install ReportLab → `pip install reportlab`")

    # =========================
    # DOCUMENT EXPLAINER
    # =========================
    elif option == "Explain Document":
        st.header("📄 Upload & Explain Document")

        uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])
        if uploaded_file is not None:
            try:
                text = read_pdf_text(uploaded_file, max_chars=8000)
                st.success("✅ File uploaded & parsed.")
                with st.expander("Preview extracted text (first 1,500 chars)"):
                    st.text(text[:1500] + ("..." if len(text) > 1500 else ""))

                summary_prompt = (
                    "You are an MSME compliance assistant. Explain this document in simple language, "
                    "list key points, deadlines, and required actions.\n\n"
                    f"Document text:\n{text}"
                )
                msgs = st.session_state.messages + [{"role": "user", "content": summary_prompt}]
                
                # Stream the document explanation
                response_container = st.empty()
                full_response = ""
                
                for chunk in llm_chat(msgs):
                    if chunk.choices[0].delta.content:
                        full_response += chunk.choices[0].delta.content
                        response_container.markdown(full_response + "▌")
                
                st.subheader("🧠 AI Explanation")
                response_container.markdown(full_response)
                
                # Save to chat history
                save_chat_message(st.session_state.logged_in_user[0], "user", summary_prompt)
                save_chat_message(st.session_state.logged_in_user[0], "assistant", full_response)
                st.session_state.messages.extend([
                    {"role": "user", "content": summary_prompt},
                    {"role": "assistant", "content": full_response}
                ])

            except Exception as e:
                st.error(f"Could not read or analyze the PDF. {e}")
                st.caption("Tip: Install PyPDF2 → `pip install PyPDF2`")
        else:
            st.info("Drop a PDF above to get started.")

    # =========================
    # LEGAL DOC GENERATOR
    # =========================
    elif option == "Legal Doc Generator":
        st.header("⚖️ Legal & HR Documents")

        doc_type = st.selectbox("Choose Document Type", ["Offer Letter", "NDA", "Leave Policy"])
        name = st.text_input("Employee/Party Name")
        if st.button("Generate Document PDF"):
            try:
                pdf_buffer = generate_legal_doc_pdf(doc_type, name)
                st.success(f"✅ {doc_type} generated for {name or '—'}")
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf_buffer,
                    file_name=f"{doc_type.replace(' ', '_').lower()}_{name or 'document'}.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.error(f"Could not generate PDF. {e}")
                st.caption("Tip: Install ReportLab → `pip install reportlab`")

# Handle password reset token from URL
# if not st.session_state.get("reset_token") and "token" in st.experimental_get_query_params():
#     st.session_state.reset_token = st.experimental_get_query_params()["token"][0]
#     st.rerun()
if not st.session_state.get("reset_token") and "token" in st.query_params:
    st.session_state.reset_token = st.query_params["token"]
    st.rerun()