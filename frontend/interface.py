"""Presentation and URL navigation for the MedRAG Streamlit interface."""
from html import escape
from pathlib import Path

import streamlit as st

from medrag.topics import TOPICS, topic_label


def apply_theme():
    st.markdown(f"<style>{Path(__file__).with_name('theme.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def navigate(page, view=None):
    st.query_params['page'] = page
    if view:
        st.query_params['view'] = view
    st.rerun()


def navbar(authenticated=False, sign_out=None):
    busy = bool(st.session_state.get('auth_action'))
    with st.container(key='navbar'):
        brand, *actions = st.columns([5, 1.3, 1.2, 1.8], vertical_alignment='center')
        brand.markdown('<div class="mr-brand"><span>+</span> MEDRAG</div>', unsafe_allow_html=True)
        if authenticated:
            if sign_out and actions[-1].button('Sign out', use_container_width=True, disabled=busy):
                sign_out()
        else:
            current = st.query_params.get('page', 'overview')
            for column, label, page in zip(actions, ['Overview', 'Log in', 'Create account'], ['overview', 'login', 'signup']):
                if column.button(label, type='primary' if current == page else 'secondary', use_container_width=True, disabled=busy):
                    navigate(page)


def landing():
    st.html('''<section class="mr-hero">
      <div><div class="mr-eyebrow">YOUR EVIDENCE, CONNECTED</div>
      <h1>Less searching.<br>More understanding.</h1>
      <p>Explore medical literature, ask questions in your language, and follow every answer back to its sources.</p>
      <div class="mr-actions"><a class="mr-cta" href="?page=signup" target="_self">Start your research ↗</a><a class="mr-secondary" href="?page=login" target="_self">Explore the workspace</a></div>
      <p class="mr-small">PubMed research · WHO guidelines · OpenFDA drug labels</p></div>
      <div class="mr-demo"><div class="mr-eyebrow">RESEARCH WORKSPACE · ILLUSTRATION</div>
      <div class="mr-question">How can I explore the evidence on type 2 diabetes?</div>
      <h3>Begin with the sources.</h3><p>Ask a focused question, review the supporting literature, and compare the original guidance in context.</p>
      <span class="mr-tag">Cited answers</span><span class="mr-tag">Private PDFs</span>
      <div class="mr-source-preview">Evidence alongside every conversation<p class="mr-small">Open original references, excerpts, and available figures.</p></div></div>
      </section><section class="mr-features">
      <article><div class="mr-feature-icon">01</div><h3>Research with context</h3><p>Search across curated medical topics and inspect the evidence behind an answer.</p></article>
      <article><div class="mr-feature-icon">02</div><h3>Bring your own papers</h3><p>Add PDFs to a private chat and ask questions about their contents.</p></article>
      <article><div class="mr-feature-icon">03</div><h3>Continue in your language</h3><p>Ask naturally, revisit saved conversations, and keep your research together.</p></article></section>''')
    footer()


def account_form(page):
    signup = page == 'signup'
    busy = bool(st.session_state.get('auth_action'))
    with st.container(key='account'):
        intro, form = st.columns([1, 1], gap='large', vertical_alignment='center')
        with intro:
            st.html('<div class="mr-auth-intro"><div class="mr-eyebrow">A CLEARER PATH TO EVIDENCE</div><h1>' +
                    ('A workspace for<br>your next question.' if signup else 'Your research.<br>Ready to continue.') +
                    '</h1><p>Return to your conversations, private documents, and the questions that matter.</p><div class="mr-step">01 &nbsp; Ask focused research questions</div><div class="mr-step">02 &nbsp; Review cited source material</div><div class="mr-step">03 &nbsp; Continue where you left off</div></div>')
        with form:
            with st.form('login' if not signup else 'signup'):
                st.title('Create your account' if signup else 'Welcome back')
                st.caption('Start building your research workspace.' if signup else 'Log in to your MedRAG workspace.')
                username = st.text_input('Username', max_chars=64, placeholder='Choose a username' if signup else 'Enter your username')
                password = st.text_input('Password', type='password', max_chars=128, placeholder='At least 12 characters')
                confirm = st.text_input('Confirm password', type='password', max_chars=128) if signup else password
                submitted = st.form_submit_button('Please wait…' if busy else 'Create account →' if signup else 'Log in →', type='primary', use_container_width=True, disabled=busy)
                if submitted:
                    if signup and password != confirm:
                        st.session_state.auth_feedback = {'title': 'Check your password', 'message': 'The passwords do not match.', 'success': False}
                        st.rerun()
                    elif not username or not password:
                        st.session_state.auth_feedback = {'title': 'Complete your details', 'message': 'Enter your username and password.', 'success': False}
                        st.rerun()
                    else:
                        return {'action': 'register' if signup else 'login', 'credentials': {'username': username, 'password': password}}
            if st.button('Already have an account? Log in' if signup else 'New to MedRAG? Create an account', type='tertiary', disabled=busy):
                navigate('login' if signup else 'signup')
    footer()
    return None


def show_auth_feedback():
    feedback = st.session_state.pop('auth_feedback', None)
    if not feedback:
        return

    @st.dialog(feedback['title'], dismissible=True)
    def feedback_dialog():
        if feedback['success']:
            st.success(feedback['message'])
        else:
            st.error(feedback['message'])
        if st.button('Continue to workspace' if feedback['success'] else 'Try again', type='primary', use_container_width=True):
            st.rerun()

    feedback_dialog()


def topics():
    sources = [
        ('PubMed', 'Research literature', 'https://pubmed.ncbi.nlm.nih.gov/'),
        ('World Health Organization', 'Guideline documents and available source figures', 'https://www.who.int/'),
        ('OpenFDA', 'Drug label information', 'https://open.fda.gov/'),
    ]
    st.html('<section class="mr-source-directory"><h1>Topics &amp; sources</h1><p class="mr-directory-intro">36 curated medical topics. Coverage varies by topic and source.</p>' +
            ''.join(f'<article><h2><a href="{url}" target="_blank" rel="noopener noreferrer">{name} ↗</a></h2><p>{description}</p></article>' for name, description, url in sources) +
            '<h2 class="mr-topics-heading">Topics</h2></section>')
    st.html('<div class="mr-topics" aria-label="36 medical topics">' + ''.join(f'<span class="mr-tag">{escape(topic_label(topic))}</span>' for topic in TOPICS) + '</div>')


def footer():
    st.html('<footer class="mr-footer"><span>MedRAG · Evidence for understanding</span><span>Educational research demo. Not a substitute for medical care.</span></footer>')
