import os
import re
import sqlite3
from io import BytesIO
import streamlit as st
from hashlib import sha256

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
    # Create users table if it doesn't exist
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
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user


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
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "system", "content": "You are VyaparGPT, an AI assistant helping Indian MSMEs with business, compliance, invoices, legal, HR, and documents."}
        ]
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
    )
    return resp.choices[0].message.content

def detect_intent(user_text: str):
    text = user_text.lower()
    if any(k in text for k in ["invoice", "bill", "create bill", "create invoice"]):
        name_match = re.search(r"(?:invoice|bill)\s+(?:for|to)\s+([a-zA-Z]+)", text)
        amt_match = re.search(r"(?:₹|rs\.?\s*)?(\d{2,7}(?:\.\d{1,2})?)", text)
        cust = name_match.group(1).strip().title() if name_match else ""
        amt = float(amt_match.group(1)) if amt_match else 0.0
        return ("invoice", {"customer": cust, "amount": amt})
    if any(k in text for k in ["upload", "document", "notice", "pdf", "explain my document", "gst document"]):
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
# LOGIN & REGISTRATION
# =========================
st.sidebar.title("👤 User Access")
if st.session_state.logged_in_user is None:
    action = st.sidebar.radio("Select Action", ["Login", "Register"])
    
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
                # Store user details in session state for chat bot access
                st.session_state.user_details = {
                    "first_name": user[3],
                    "last_name": user[4],
                    "email": user[5],
                    "phone": user[6]
                }
                st.success(f"Welcome {user[3]} {user[4]}!")
                st.rerun()
            else:
                st.error("Invalid username or password.")
else:
    st.sidebar.success(f"Logged in as: {st.session_state.logged_in_user[3]} {st.session_state.logged_in_user[4]}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in_user = None
        st.session_state.user_details = {}
        st.rerun()


# =========================
# NAVIGATION
# =========================
if st.session_state.logged_in_user:
    nav_labels = ["Overview", "Chat Assistant", "Invoice Generator", "Explain Document", "Legal Doc Generator"]
    option = st.sidebar.radio("Navigate", nav_labels, index=nav_labels.index(st.session_state.active_tab))

    if st.sidebar.button("🧹 Clear Chat"):
        st.session_state.messages = []

    # =========================
    # OVERVIEW
    # =========================
    if option == "Overview":
        # Display welcome message if user is logged in
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
        if st.session_state.user_details:
            user_info = st.session_state.user_details
            st.session_state.messages[0] = {
                "role": "system",
                "content": f"""You are VyaparGPT, an AI assistant helping Indian MSMEs with business, compliance, invoices, legal, HR, and documents.
                The current user is {user_info['first_name']} {user_info['last_name']}.
                Contact details - Email: {user_info.get('email', 'not provided')}, Phone: {user_info.get('phone', 'not provided')}."""
            }

        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.chat_message("user").markdown(msg["content"])
            elif msg["role"] == "assistant":
                st.chat_message("assistant").markdown(msg["content"])

        user_input = st.chat_input("Ask your question… (e.g., 'Generate invoice for Anil ₹5000')")
        if user_input:
            st.session_state.messages.append({"role": "user", "content": user_input})
            st.chat_message("user").markdown(user_input)

            intent, data = detect_intent(user_input)
            st.session_state.last_intent = intent

            if intent == "invoice":
                st.session_state.invoice_customer = data.get("customer", "") or st.session_state.invoice_customer
                amt = data.get("amount", 0.0)
                st.session_state.invoice_amount = amt if amt else st.session_state.invoice_amount
                st.session_state.active_tab = "Invoice Generator"
                st.rerun()

            elif intent == "document":
                st.session_state.active_tab = "Explain Document"
                st.rerun()

            with st.spinner("Thinking..."):
                bot_reply = llm_chat(st.session_state.messages, model=DEFAULT_MODEL, max_tokens=2000)

            st.session_state.messages.append({"role": "assistant", "content": bot_reply})
            st.chat_message("assistant").markdown(bot_reply)

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
                with st.spinner("Analyzing document with AI..."):
                    explanation = llm_chat(msgs, model=DEFAULT_MODEL, max_tokens=600)

                st.subheader("🧠 AI Explanation")
                st.write(explanation)

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