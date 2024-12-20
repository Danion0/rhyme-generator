import streamlit as st
import stripe
from openai import OpenAI
import psycopg2
from psycopg2 import pool
import hashlib
from datetime import datetime

def test_db_connection():
    conn = get_conn()
    if not conn:
        st.error("❌ Could not connect to database")
        return False
    
    try:
        with conn.cursor() as cur:
            # Try to execute a simple query
            cur.execute("SELECT 1")
            result = cur.fetchone()
            if result and result[0] == 1:
                st.success("✅ Database connection successful!")
                return True
            else:
                st.error("❌ Database query failed")
                return False
    except Exception as e:
        st.error(f"❌ Database test failed: {str(e)}")
        return False
    finally:
        put_conn(conn)

# Page config
st.set_page_config(page_title="AI Powered Julrims Generator - Registera nu för att få ett gratis rim!", page_icon="🎁")
if st.sidebar.button("Test Database Connection"):
    test_db_connection()

# Configure API keys from Streamlit secrets
stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Initialize connection pool
@st.cache_resource
def init_connection_pool():
    return psycopg2.pool.SimpleConnectionPool(
        1, 20,
        dsn=st.secrets["DATABASE_URL"]
    )

# Get database connection from pool
def get_conn():
    try:
        return st.session_state.db_pool.getconn()
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

# Return connection to pool
def put_conn(conn):
    try:
        st.session_state.db_pool.putconn(conn)
    except Exception as e:
        st.error(f"Failed to return connection to pool: {e}")

# Database functions
def init_db():
    conn = get_conn()
    if not conn:
        return
    
    try:
        with conn.cursor() as cur:
            # Create users table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    credits INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create rhyme history table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS rhyme_history (
                    id SERIAL PRIMARY KEY,
                    email TEXT REFERENCES users(email),
                    rhyme TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
        conn.commit()
    except Exception as e:
        st.error(f"Database initialization failed: {e}")
    finally:
        put_conn(conn)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(email, password):
    conn = get_conn()
    if not conn:
        return
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (email, password, credits) 
                VALUES (%s, %s, 1)
            """, (email, hash_password(password)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        put_conn(conn)

def verify_user(email, password):
    conn = get_conn()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password FROM users WHERE email = %s", (email,))
            result = cur.fetchone()
            return result and result[0] == hash_password(password)
    finally:
        put_conn(conn)

def get_credits(email):
    conn = get_conn()
    if not conn:
        return 0
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT credits FROM users WHERE email = %s", (email,))
            result = cur.fetchone()
            return result[0] if result else 0
    finally:
        put_conn(conn)

def update_credits(email, credits):
    conn = get_conn()
    if not conn:
        return
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users 
                SET credits = %s 
                WHERE email = %s
            """, (credits, email))
        conn.commit()
    except Exception as e:
        conn.rollback()
        st.error(f"Failed to update credits: {e}")
    finally:
        put_conn(conn)

def save_rhyme(email, rhyme):
    conn = get_conn()
    if not conn:
        return
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rhyme_history (email, rhyme)
                VALUES (%s, %s)
            """, (email, rhyme))
        conn.commit()
    except Exception as e:
        conn.rollback()
        st.error(f"Failed to save rhyme: {e}")
    finally:
        put_conn(conn)

def get_rhyme_history(email):
    conn = get_conn()
    if not conn:
        return []
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rhyme, created_at 
                FROM rhyme_history 
                WHERE email = %s 
                ORDER BY created_at DESC
            """, (email,))
            return cur.fetchall()
    finally:
        put_conn(conn)

# Initialize connection pool at startup
if 'db_pool' not in st.session_state:
    st.session_state.db_pool = init_connection_pool()

# Stripe functions
def get_streamlit_url():
    # Check if running on Streamlit Cloud
    if st.secrets.get("HOSTNAME"):
        return f"https://{st.secrets['HOSTNAME']}"
    return "http://localhost:8501"  # Local development fallback

def create_checkout_session(email):
    try:
        base_url = get_streamlit_url()
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'sek',
                    'unit_amount': 5000,  # 100 SEK in öre
                    'product_data': {
                        'name': '5 Julrims Credits',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{base_url}?success=true&email={email}",
            cancel_url=f"{base_url}?canceled=true",
            metadata={'email': email}
        )
        return checkout_session
    except Exception as e:
        st.error(f"Error creating checkout session: {str(e)}")
        return None

def handle_webhook():
    #st.write("Webhook handler started")  # Debug log
    if 'stripe_webhook' in st.query_params:
        try:
            # Parse the webhook data directly from the query parameters
            webhook_data = st.query_params['stripe_webhook']
            
            # If webhook_data is a string, try to parse it
            if isinstance(webhook_data, str):
                import json
                webhook_data = json.loads(webhook_data)
            
            # Extract the session data
            if webhook_data.get('object', {}).get('object') == 'checkout.session':
                session = webhook_data['object']
                email = session['metadata'].get('email')
                payment_status = session.get('payment_status')
                
                st.write(f"Processing payment for email: {email}")
                st.write(f"Payment status: {payment_status}")
                
                if email and payment_status == 'paid':
                    current_credits = get_credits(email)
                    st.write(f"Current credits: {current_credits}")
                    update_credits(email, current_credits + 5)
                    new_credits = get_credits(email)
                    st.write(f"New credits balance: {new_credits}")
            else:
                st.write("Invalid webhook data format")
                
        except Exception as e:
            st.error(f"Webhook error: {str(e)}")
            st.write(f"Full error details: {type(e).__name__}: {str(e)}")

# OpenAI function
def generate_rhyme(gift, recipient, background, style):
    try:
        prompt = f"""Du är en profissionell diktare, specifikt julrimdiktare. I Sverige är det en tradition att göra ett rim när du ger bort julklappar. 
        DU FÅR ALDRIG AVSLÖJA vad själva presenten är. Det här är din chans att visa vad generativt AI kan göra för folk som aldrig använt det förr. 
        Generera ett julrim för följande present, {gift} till {recipient}. Använd inte ordet {gift} i rimmet.
        Här är lite bakgrunds information on personen som får presenten, inkludera lite av det i rimmet så att det blir personligt: {background}
        Rimmet ska vara i följande stil: {style}"""


#        prompt = f"""Create a rhyming poem about a gift with the following details:
#        Gift: {gift}
#        Recipient: {recipient}
#        Background: {background}
#        Style: 
#        
#        The poem should be personal, fun, and incorporate the recipient's background."""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Error generating rhyme: {str(e)}")
        return None

# Main app
def main():
    init_db()
    
    # Handle webhook and payment success
    handle_webhook()
     # Check payment status from query params
    if st.query_params.get('success') == 'true':
        email = st.query_params.get('email')
        if email:
            # Double-check credits were added
            current_credits = get_credits(email)
            #st.write(f"Credits after payment: {current_credits}")
            if current_credits == 0:
                # Fallback credit update if webhook failed
                update_credits(email, 5)
                st.write("Dina credits har uppdaterats. Vänligen logga in igen.")
        st.success("Betalningen gick bra. Ditt account har uppdaterats med 5 credits.")
        st.query_params.clear()
    elif 'canceled' in st.query_params:
        st.warning("Payment canceled.")
        st.query_params.clear()

    # Session state initialization
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'email' not in st.session_state:
        st.session_state.email = None

    st.title("🎁 Julrims Generator")

    # Sidebar login/register
    with st.sidebar:
        if not st.session_state.logged_in:
            st.subheader("Login")
            login_tab, register_tab = st.tabs(["Login", "Register"])
            
            with login_tab:
                login_email = st.text_input("Email", key="login_email")
                login_password = st.text_input("Password", type="password", key="login_password")
                if st.button("Login"):
                    if verify_user(login_email, login_password):
                        st.session_state.logged_in = True
                        st.session_state.email = login_email
                        st.rerun()
                    else:
                        st.error("Invalid credentials")
            
            with register_tab:
                reg_email = st.text_input("Email", key="reg_email")
                reg_password = st.text_input("Password", type="password", key="reg_password")
                if st.button("Register"):
                    try:
                        create_user(reg_email, reg_password)
                        st.success("Registreringen gick bra! Vänligen logga in.")
                    except Exception as e:
                        st.error("Registreringen misslyckades. Emailen finns säkert redan.")
        
        else:
            st.write(f"Logged in as: {st.session_state.email}")
            credits = get_credits(st.session_state.email)
            st.write(f"Credits remaining: {credits}")
            
            if credits < 3:
                if st.button("Köp 5 Credits (50 SEK)"):
                    checkout_session = create_checkout_session(st.session_state.email)
                    if checkout_session:
                        st.markdown(f"""
                            <a href="{checkout_session.url}" target="_blank">
                                <button style="background-color: #4CAF50; color: white; padding: 12px 20px; border: none; border-radius: 4px; cursor: pointer;">
                                    Forsätt till betalning
                                </button>
                            </a>
                            """,
                            unsafe_allow_html=True
                        )
            
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.email = None
                st.rerun()

    # Main content
    if st.session_state.logged_in:
        credits = get_credits(st.session_state.email)

        if credits > 0:
            with st.form("rhyme_form"):
                gift = st.text_input("Vad är presenten för något?")
                recipient = st.text_input("Till vem är presenten?")
                background = st.text_area("Ge oss like bakgrund till personen i fråga.")
                style = st.selectbox(
                    "Välj stil på julrimmet",
                    ["Roligt", "Romantiskt", "Klassisk", "Modern", "Barnslig"]
                )
                
                submit_button = st.form_submit_button("Generera julrim (Använder 1 Credit)")
            
            if submit_button:
                rhyme = generate_rhyme(gift, recipient, background, style)
                if rhyme:
                    st.success("Ditt julrim är redo!")
                    st.markdown(f"```\n{rhyme}\n```")
                    
                    # Save rhyme and update credits
                    save_rhyme(st.session_state.email, rhyme)
                    update_credits(st.session_state.email, credits - 1)
                    
                    # Add download button
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"gift_rhyme_{timestamp}.txt"
                    st.download_button(
                        label="Download Rhyme",
                        data=rhyme,
                        file_name=filename,
                        mime="text/plain"
                    )
                    st.rerun()  # Refresh to update credit display
        
        else:
            st.warning("Du måste fylla på Credits för att kunna generera rim.")
        
        # Show rhyme history
        st.subheader("Rim historik")
        history = get_rhyme_history(st.session_state.email)
        for rhyme, created_at in history:
            with st.expander(f"Rim från {created_at}"):
                st.text(rhyme)


if __name__ == "__main__":
    main()