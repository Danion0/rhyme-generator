import streamlit as st
import stripe
from openai import OpenAI
import sqlite3
import hashlib
from datetime import datetime

# Page config
st.set_page_config(page_title="Gift Rhyme Generator", page_icon="🎁")

# Configure API keys from Streamlit secrets
stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Database functions
def init_db():
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (email TEXT PRIMARY KEY, 
                  password TEXT, 
                  credits INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rhyme_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT,
                  rhyme TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(email, password):
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute("INSERT INTO users (email, password) VALUES (?, ?)",
              (email, hash_password(password)))
    conn.commit()
    conn.close()

def verify_user(email, password):
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE email = ?", (email,))
    result = c.fetchone()
    conn.close()
    if result and result[0] == hash_password(password):
        return True
    return False

def get_credits(email):
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE email = ?", (email,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def update_credits(email, credits):
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = ? WHERE email = ?", (credits, email))
    conn.commit()
    conn.close()

def save_rhyme(email, rhyme):
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute("INSERT INTO rhyme_history (email, rhyme) VALUES (?, ?)", 
              (email, rhyme))
    conn.commit()
    conn.close()

def get_rhyme_history(email):
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute("SELECT rhyme, created_at FROM rhyme_history WHERE email = ? ORDER BY created_at DESC", 
              (email,))
    history = c.fetchall()
    conn.close()
    return history

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
                    'unit_amount': 10000,  # 100 SEK in öre
                    'product_data': {
                        'name': '10 Rhyme Credits',
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
    st.write("Webhook handler started")  # Debug log
    if 'stripe_webhook' in st.query_params:
        try:
            webhook_secret = st.secrets["STRIPE_WEBHOOK_SECRET"]
            st.write("Got webhook secret")  # Debug log
            
            event = stripe.Event.construct_from(
                st.query_params['stripe_webhook'],
                stripe.api_key
            )
            
            st.write(f"Event type: {event.type}")  # Debug log
            
            if event.type == 'checkout.session.completed':
                session = event.data.object
                email = session.metadata.get('email')
                st.write(f"Processing payment for email: {email}")  # Debug log
                
                if email:
                    current_credits = get_credits(email)
                    st.write(f"Current credits: {current_credits}")  # Debug log
                    update_credits(email, current_credits + 10)
                    new_credits = get_credits(email)
                    st.write(f"New credits balance: {new_credits}")  # Debug log
                else:
                    st.write("No email found in metadata")  # Debug log
        except Exception as e:
            st.error(f"Webhook error: {str(e)}")
            st.write(f"Full error details: {type(e).__name__}: {str(e)}")  # Debug log

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
    if st.query_params.get('success') == 'true':
        st.success("Payment successful! 10 credits have been added to your account.")
        # Clear URL parameters
        st.query_params.clear()
    elif 'canceled' in st.query_params:
        st.warning("Payment canceled.")
        st.query_params.clear()

    # Session state initialization
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'email' not in st.session_state:
        st.session_state.email = None

    st.title("🎁 Gift Rhyme Generator")

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
                        st.success("Registration successful! Please login.")
                    except Exception as e:
                        st.error("Registration failed. Email might already exist.")
        
        else:
            st.write(f"Logged in as: {st.session_state.email}")
            credits = get_credits(st.session_state.email)
            st.write(f"Credits remaining: {credits}")
            
            if credits < 3:
                if st.button("Buy 10 Credits (100 SEK)"):
                    checkout_session = create_checkout_session(st.session_state.email)
                    if checkout_session:
                        st.markdown(f"""
                            <a href="{checkout_session.url}" target="_blank">
                                <button style="background-color: #4CAF50; color: white; padding: 12px 20px; border: none; border-radius: 4px; cursor: pointer;">
                                    Proceed to Payment
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
        if st.session_state.logged_in:
            debug_user_info(st.session_state.email)
        if credits > 0:
            with st.form("rhyme_form"):
                gift = st.text_input("What is the gift?")
                recipient = st.text_input("Who is the gift for?")
                background = st.text_area("Tell us about the recipient (interests, personality, etc.)")
                style = st.selectbox(
                    "Choose the rhyme style",
                    ["Funny", "Romantic", "Classical", "Modern", "Children's Rhyme"]
                )
                
                submit_button = st.form_submit_button("Generate Rhyme (Uses 1 Credit)")
            
            if submit_button:
                rhyme = generate_rhyme(gift, recipient, background, style)
                if rhyme:
                    st.success("Your custom rhyme is ready!")
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
            st.warning("You need to purchase credits to generate rhymes.")
        
        # Show rhyme history
        st.subheader("Your Previous Rhymes")
        history = get_rhyme_history(st.session_state.email)
        for rhyme, created_at in history:
            with st.expander(f"Rhyme from {created_at}"):
                st.text(rhyme)

def debug_user_info(email):
    conn = sqlite3.connect('rhyme_users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    user_data = c.fetchone()
    conn.close()
    st.write(f"User data: {user_data}")  # Debug log
    return user_data

if __name__ == "__main__":
    main()