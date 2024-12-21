import streamlit as st
import stripe
from openai import OpenAI
import sqlite3
import hashlib
from datetime import datetime
import time 
import pandas as pd

# Page config
st.set_page_config(page_title="AI Powered Julrims Generator - Registera nu för att få ett gratis rim!", page_icon="🎁")

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
                  credits INTEGER DEFAULT 1,
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
    c.execute("""
        INSERT INTO users (email, password, credits) 
        VALUES (?, ?, 1)
    """, (email, hash_password(password)))
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
    try:
        # First verify current credits
        c.execute("SELECT credits FROM users WHERE email = ?", (email,))
        #old_credits = c.fetchone()[0]
        #st.write(f"Debug - Old credits: {old_credits}")  # Debug log

        # Update credits
        c.execute("UPDATE users SET credits = ? WHERE email = ?", (credits, email))
        conn.commit()

        # Verify the update
        c.execute("SELECT credits FROM users WHERE email = ?", (email,))
        #new_credits = c.fetchone()[0]
        #st.write(f"Debug - New credits: {new_credits}")  # Debug log

        #if new_credits != credits:
        #    st.error("Credit update failed to save correctly")
    except Exception as e:
        st.error(f"Error updating credits: {e}")
    finally:
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
    if 'stripe_webhook' in st.query_params:
        try:
            webhook_data = st.query_params['stripe_webhook']
            if isinstance(webhook_data, str):
                import json
                webhook_data = json.loads(webhook_data)
            
            if webhook_data.get('object', {}).get('object') == 'checkout.session':
                session = webhook_data['object']
                email = session['metadata'].get('email')
                payment_status = session.get('payment_status')
                
                if email and payment_status == 'paid':
                    current_credits = get_credits(email)
                    update_credits(email, current_credits + 5)
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
            update_credits(email, current_credits + 5)
            st.write("Dina credits har uppdaterats. Vänligen logga in igen.")
        st.success("Betalningen gick bra. Ditt account har uppdaterats med 5 credits. Vänligen logga in igen.")
        st.query_params.clear()
    elif 'canceled' in st.query_params:
        st.warning("Payment canceled.")
        st.query_params.clear()

    # Session state initialization
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'email' not in st.session_state:
        st.session_state.email = None

    st.title("🎁 Julrims Generator - Registera nu för att få ett gratis rim!")

    # Move login/register to main content for better mobile visibility
    if not st.session_state.logged_in:
        st.markdown("### Logga in eller Registrera")
        login_tab, register_tab = st.tabs(["Login", "Register"])
        
        with login_tab:
            col1, col2 = st.columns([2,1])
            with col1:
                login_email = st.text_input("Email", key="login_email")
                login_password = st.text_input("Password", type="password", key="login_password")
                if st.button("Login", type="primary"):  # Make button more prominent
                    if verify_user(login_email, login_password):
                        st.session_state.logged_in = True
                        st.session_state.email = login_email
                        st.rerun()
                    else:
                        st.error("Invalid credentials")
        
        with register_tab:
            col1, col2 = st.columns([2,1])
            with col1:
                reg_email = st.text_input("Email", key="reg_email")
                reg_password = st.text_input("Password", type="password", key="reg_password")
                if st.button("Register", type="primary"):
                    try:
                        create_user(reg_email, reg_password)
                        st.success("Registreringen gick bra! Du får en gratis credit. Vänligen logga in.")
                    except Exception as e:
                        st.error("Registreringen misslyckades. Emailen finns säkert redan.")
    
    # Keep the rest of your sidebar content for logged-in users
    with st.sidebar:
        if st.session_state.logged_in:
            st.write(f"Logged in as: {st.session_state.email}")
            credits = get_credits(st.session_state.email)
            st.write(f"Credits remaining: {credits}")
            
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.email = None
                st.rerun()
            
            # Admin Panel - Add here
            if st.session_state.email == st.secrets["ADMIN_EMAIL"]:
                st.sidebar.markdown("---")
                st.sidebar.markdown("### Admin Panel")
                
                if st.sidebar.button("View User Statistics"):
                    # Get all users
                    conn = sqlite3.connect('rhyme_users.db')
                    c = conn.cursor()
                    
                    # Get user statistics
                    c.execute("""
                        SELECT 
                            users.email,
                            users.credits,
                            users.created_at,
                            COUNT(DISTINCT rhyme_history.id) as rhyme_count
                        FROM users
                        LEFT JOIN rhyme_history ON users.email = rhyme_history.email
                        GROUP BY users.email
                        ORDER BY users.created_at DESC
                    """)
                    users = c.fetchall()
                    
                    # CSV Export
                    import pandas as pd
                    user_data = []
                    for user in users:
                        c.execute("""
                            SELECT rhyme, created_at 
                            FROM rhyme_history 
                            WHERE email = ?
                        """, (user[0],))
                        rhymes = c.fetchall()
                        
                        user_data.append({
                            'Email': user[0],
                            'Credits': user[1],
                            'Created At': user[2],
                            'Total Rhymes': user[3],
                            'Last Rhyme Date': rhymes[0][1] if rhymes else 'No rhymes'
                        })
                    
                    df = pd.DataFrame(user_data)
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="Download User Data CSV",
                        data=csv,
                        file_name="user_statistics.csv",
                        mime="text/csv"
                    )
                    
                    # Display statistics
                    total_users = len(users)
                    total_rhymes = sum(user[3] for user in users)
                    total_credits = sum(user[1] for user in users)
                    
                    st.markdown("### Overall Statistics")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Users", total_users)
                    with col2:
                        st.metric("Total Rhymes", total_rhymes)
                    with col3:
                        st.metric("Total Credits", total_credits)
                    
                    # User Details
                    st.markdown("### User Details")
                    for user in users:
                        with st.expander(f"User: {user[0]}"):
                            col1, col2 = st.columns([2,1])
                            with col1:
                                st.write(f"Created: {user[2]}")
                                st.write(f"Total Rhymes Generated: {user[3]}")
                            
                            with col2:
                                st.write(f"Current Credits: {user[1]}")
                                new_credits = st.number_input(
                                    "Set Credits", 
                                    min_value=0, 
                                    value=user[1], 
                                    key=f"input_{user[0]}"
                                )
                                if st.button("Save", key=f"save_{user[0]}"):
                                    st.write(f"Attempting to update credits from {user[1]} to {new_credits}")  # Debug log
                                    update_credits(user[0], new_credits)
                                    time.sleep(1)
                                    st.rerun() 
                            
                            # Rhyme history
                            c.execute("""
                                SELECT rhyme, created_at 
                                FROM rhyme_history 
                                WHERE email = ? 
                                ORDER BY created_at DESC
                            """, (user[0],))
                            rhymes = c.fetchall()
                            
                            if rhymes:
                                st.write("#### Rhyme History")
                                for i, rhyme in enumerate(rhymes, 1):
                                    st.write(f"**Rhyme {i} - {rhyme[1]}**")
                                    st.text(rhyme[0])
                                    st.write("---")
                    
                    conn.close()   
            if credits < 20:
                st.markdown("### Köp Credits")
                col1, col2 = st.columns([2,1])
                with col1:
                    if st.button("Köp 5 Credits (50 SEK)", type="primary"):
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