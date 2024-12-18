import streamlit as st
import stripe
import openai
import sqlite3
import hashlib
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configure API keys
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
openai.api_key = os.getenv('OPENAI_API_KEY')

# Database setup
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
    result = c.fetch_one()
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

def create_checkout_session(email):
    try:
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
            success_url=f"{os.getenv('DOMAIN')}/success?email={email}",
            cancel_url=f"{os.getenv('DOMAIN')}/cancel",
            metadata={'email': email}
        )
        return checkout_session
    except Exception as e:
        st.error(f"Error creating checkout session: {str(e)}")
        return None

def generate_rhyme(gift, recipient, background, style):
    try:
        prompt = f"""Create a rhyming poem about a gift with the following details:
        Gift: {gift}
        Recipient: {recipient}
        Background: {background}
        Style: {style}
        
        The poem should be personal, fun, and incorporate the recipient's background."""

        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a creative poet who specializes in gift-giving rhymes."},
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Error generating rhyme: {str(e)}")
        return None

def main():
    init_db()
    st.title("🎁 Gift Rhyme Generator")
    
    # Session state
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'email' not in st.session_state:
        st.session_state.email = None

    # Login/Register sidebar
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

if __name__ == "__main__":
    main()