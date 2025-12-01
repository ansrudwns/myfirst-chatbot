import streamlit as st
import os
import arxiv
import sqlite3
import uuid
from datetime import datetime
from openai import AzureOpenAI
from dotenv import load_dotenv

# 1. 환경 변수 로드
load_dotenv()

# Streamlit 페이지 설정
st.set_page_config(page_title="Paper Mate Pro", page_icon="📚", layout="wide")

# 2. Azure OpenAI 클라이언트 설정
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OAI_KEY"),
    api_version="2024-05-01-preview",
    azure_endpoint=os.getenv("AZURE_OAI_ENDPOINT")
)

# --- [데이터베이스 관리 함수] ---
DB_NAME = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    ''')
    conn.commit()
    conn.close()

def create_session(title="새로운 대화"):
    session_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute("INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)", 
              (session_id, title, timestamp))
    conn.commit()
    conn.close()
    return session_id

def update_session_title(session_id, new_title):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title, session_id))
    conn.commit()
    conn.close()

def delete_session(session_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

def get_session_info(session_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT title, created_at FROM sessions WHERE id = ?", (session_id,))
    row = c.fetchone()
    conn.close()
    return row if row else ("알 수 없음", "")

def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", 
              (session_id, role, content))
    conn.commit()
    conn.close()

def get_messages(session_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

def get_all_sessions():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
    sessions = c.fetchall()
    conn.close()
    return sessions

def search_history(keyword):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    query = f"%{keyword}%"
    c.execute('''
        SELECT DISTINCT s.id, s.title, m.content 
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE m.content LIKE ?
        ORDER BY m.created_at DESC
    ''', (query,))
    results = c.fetchall()
    conn.close()
    return results

# --- [API 및 LLM 기능 함수] ---

def translate_to_english_keyword(user_query):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Translate/Summarize user query to English keywords for ArXiv search. Only keywords."},
                {"role": "user", "content": user_query}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return user_query

def generate_auto_title(user_query):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Summarize the user's query into a concise Korean title (max 15 characters, no quotes)."},
                {"role": "user", "content": user_query}
            ]
        )
        return response.choices[0].message.content.strip()
    except:
        return "새로운 대화"

def search_arxiv(query, max_results=3):
    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results * 4,
            sort_by=arxiv.SortCriterion.Relevance
        )
        results = list(client.results(search))
        
        if not results:
            return None, 0

        results.sort(key=lambda x: x.published, reverse=True)
        results = results[:max_results]

        results_text = []
        for result in results:
            authors = ", ".join([author.name for author in result.authors])
            published_year = result.published.strftime("%Y")
            
            paper_data = f"""
            [Paper ID: {result.entry_id}]
            - Title: {result.title}
            - Authors: {authors}
            - Published Year: {published_year}
            - Abstract: {result.summary.replace(chr(10), " ")} 
            - PDF Link: {result.pdf_url}
            """
            results_text.append(paper_data)
        
        return "\n\n".join(results_text), len(results)

    except Exception as e:
        st.error(f"ArXiv 검색 오류: {e}")
        return None, 0

# --- [메인 앱 로직] ---

init_db()

if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

# --- [사이드바] ---
with st.sidebar:
    st.title("🗂️ 대화 관리")
    
    if st.button("➕ 새 대화 시작", use_container_width=True):
        new_id = create_session()
        st.session_state.current_session_id = new_id
        st.rerun()
    
    st.divider()

    # 1. 검색 (수정됨: Duplicate Key 오류 해결)
    search_query = st.text_input("🔍 대화 검색", placeholder="키워드...")
    if search_query:
        st.caption("검색 결과")
        results = search_history(search_query)
        if results:
            # enumerate를 사용하여 각 결과에 고유 번호(idx) 부여
            for idx, (s_id, s_title, content_snippet) in enumerate(results):
                snippet = content_snippet[:20] + "..."
                
                # [수정 핵심] Key를 '세션ID + 순서번호'로 조합하여 절대 겹치지 않게 함
                btn_key = f"search_res_{s_id}_{idx}" 
                
                if st.button(f"📄 {s_title}\nMatch: {snippet}", key=btn_key, use_container_width=True):
                    st.session_state.current_session_id = s_id
                    st.rerun()
        else:
            st.info("결과 없음")
    
    st.divider()

    # 2. 최근 대화 목록
    st.subheader("🕒 최근 대화 목록")
    sessions = get_all_sessions()
    
    for s_id, s_title, s_date in sessions:
        with st.expander(f"{s_title} ({s_date})"):
            col1, col2 = st.columns([3, 1])
            with col1:
                new_name = st.text_input("제목", value=s_title, key=f"input_{s_id}", label_visibility="collapsed")
            with col2:
                if st.button("💾", key=f"save_{s_id}", use_container_width=True):
                    update_session_title(s_id, new_name)
                    st.rerun()

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("📂 열기", key=f"open_{s_id}", use_container_width=True):
                    st.session_state.current_session_id = s_id
                    st.rerun()
            with col_b:
                if st.button("🗑️ 삭제", key=f"del_{s_id}", type="primary", use_container_width=True):
                    delete_session(s_id)
                    if st.session_state.current_session_id == s_id:
                        st.session_state.current_session_id = None
                    st.rerun()

# --- [메인 화면] ---

if not st.session_state.current_session_id:
    all_sessions = get_all_sessions()
    if all_sessions:
        st.session_state.current_session_id = all_sessions[0][0]
    else:
        st.session_state.current_session_id = create_session()

current_messages = get_messages(st.session_state.current_session_id)
is_first_message = len(current_messages) == 0

session_title, session_date = get_session_info(st.session_state.current_session_id)
st.title(f"🎓 {session_title}")
st.caption(f"생성일: {session_date} | Paper Mate Pro")

for msg in current_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("논문 주제를 입력하세요 (자동 제목 생성됨)..."):
    
    st.chat_message("user").markdown(prompt)
    save_message(st.session_state.current_session_id, "user", prompt)

    with st.spinner(f"🌏 '{prompt}' 분석 중..."):
        try:
            english_query = translate_to_english_keyword(prompt)
            st.toast(f"검색어 변환: {english_query}")

            search_context, paper_count = search_arxiv(english_query)
            
            if not search_context:
                assistant_reply = "검색 결과가 없습니다."
            else:
                full_prompt = f"""
                사용자: '{prompt}'
                
                [지시사항]
                1. {paper_count}개 논문 모두 답변.
                2. 한국어 요약 & APA 인용(URL 포함).
                
                [검색 데이터]
                {search_context}
                
                --- 답변 형식 ---
                ### [번호]. [제목] (연도)
                * **요약:** (한국어)
                * **APA Citation:** (URL 포함)
                * **PDF 링크:** (URL)
                ---
                """
                messages_for_api = [{"role": "system", "content": "논문 검색 도우미입니다."}]
                messages_for_api.extend(current_messages)
                messages_for_api.append({"role": "user", "content": full_prompt})

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages_for_api
                )
                assistant_reply = response.choices[0].message.content

            with st.chat_message("assistant"):
                st.markdown(assistant_reply)
            
            save_message(st.session_state.current_session_id, "assistant", assistant_reply)
            
            if is_first_message:
                auto_title = generate_auto_title(prompt)
                update_session_title(st.session_state.current_session_id, auto_title)
                st.rerun()
            
        except Exception as e:
            st.error(f"오류: {e}")
