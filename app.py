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

# --- [인용 스타일 데이터] ---
CITATION_STYLES = {
    "심리학, 교육, 사회과학 - APA": "APA Style (7th Edition)",
    "인문학, 문학 - MLA": "MLA Style (9th Edition)",
    "인문학, 문학2 - Chicago NB": "Chicago Style (Notes and Bibliography)",
    "공학 - IEEE": "IEEE Style",
    "의학 - AMA": "AMA Style",
    "의학2 - Vancouver": "Vancouver Style",
    "자연과학 - Harvard": "Harvard Style",
    "자연과학2 - APA": "APA Style (7th Edition)",
    "자연과학3 - Chicago AD": "Chicago Style (Author-Date)",
}

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
        # [로직 유지] 관련도순으로 넉넉히(4배수) 가져온 뒤 -> 최신순 정렬
        search = arxiv.Search(
            query=query,
            max_results=max_results * 4, 
            sort_by=arxiv.SortCriterion.Relevance
        )
        results = list(client.results(search))
        
        if not results:
            return None, 0

        # 최신순 정렬 (내림차순)
        results.sort(key=lambda x: x.published, reverse=True)
        # 사용자 설정 개수(max_results)만큼 자르기
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

# --- [사이드바 UI 구성 (요청 순서 반영)] ---
with st.sidebar:
    st.title("🗂️ 대화 관리")
    
    # 1. 대화 검색 (가장 위)
    search_query = st.text_input("🔍 대화 검색", placeholder="키워드 입력...")
    if search_query:
        st.caption("검색 결과")
        results = search_history(search_query)
        if results:
            for idx, (s_id, s_title, content_snippet) in enumerate(results):
                snippet = content_snippet[:20] + "..."
                btn_key = f"search_res_{s_id}_{idx}" 
                if st.button(f"📄 {s_title}\nMatch: {snippet}", key=btn_key, use_container_width=True):
                    st.session_state.current_session_id = s_id
                    st.rerun()
        else:
            st.info("결과 없음")

    st.divider()

    # 2. 새 대화 시작
    if st.button("➕ 새 대화 시작", use_container_width=True):
        new_id = create_session()
        st.session_state.current_session_id = new_id
        st.rerun()

    st.divider()

    # 3. 설정 섹션 (인용 형식 & 논문 개수)
    st.subheader("⚙️ 검색 옵션 설정")
    
    # (1) 인용 형식 설정 (드롭다운)
    selected_style_key = st.selectbox(
        "논문 분야 (인용 형식)",
        options=list(CITATION_STYLES.keys()),
        index=0
    )
    target_citation_style = CITATION_STYLES[selected_style_key]

    # (2) [신규 기능] 논문 개수 설정 (숫자 입력)
    target_paper_count = st.number_input(
        "검색할 논문 개수 (최신순)",
        min_value=1,
        max_value=10,
        value=3, # 기본값 3
        step=1,
        help="설정한 개수만큼 최신 논문을 가져옵니다."
    )
    
    st.info(f"설정: **{target_citation_style}**, **{target_paper_count}개**")

    st.divider()

    # 4. 최근 대화 목록 (가장 아래)
    st.subheader("🕒 최근 대화 목록")
    sessions = get_all_sessions()
    
    for s_id, s_title, s_date in sessions:
        with st.expander(f"{s_title} ({s_date})"):
            col1, col2 = st.columns([3, 1])
            with col1:
                new_name = st.text_input("제목", value=s_title, key=f"input_{s_id}", label_visibility="collapsed")
            w색 중... ({target_paper_count}개)"):
        try:
            english_query = translate_to_english_keyword(prompt)
            st.toast(f"검색어 변환: {english_query}")

            # [수정] 사용자가 설정한 개수(target_paper_count)를 함수에 전달
            search_context, paper_count = search_arxiv(english_query, max_results=target_paper_count)
            
            if not search_context:
                assistant_reply = "검색 결과가 없습니다."
            else:
                full_prompt = f"""
                사용자: '{prompt}'
                
                [지시사항]
                1. 검색된 **{paper_count}개** 논문 모두에 대해 답변하세요.
                2. 한국어 요약 필수.
                3. 인용구는 **'{target_citation_style}'** 형식을 따르세요 (URL 필수 포함).
                
                [검색 데이터]
                {search_context}
                
                --- 답변 형식 ---
                ### [번호]. [제목] (연도)
                * **요약:** (한국어)
                * **Citation ({target_citation_style}):** (형식 준수, URL 포함)
                * **PDF 링크:** (URL)
                ---
                """
                messages_for_api = [{"role": "system", "content": "논문 검색 및 인용 전문가입니다."}]
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
