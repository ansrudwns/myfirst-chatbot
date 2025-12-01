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
    final_title = title
    c.execute("INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)", 
              (session_id, final_title, timestamp))
    conn.commit()
    conn.close()
    return session_id

def update_session_title(session_id, new_title):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title, session_id))
    conn.commit()
    conn.close()

# [신규 기능] 세션 삭제 함수
def delete_session(session_id):
    """특정 세션과 관련 메시지를 모두 삭제합니다."""
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

# [복구된 기능] 대화 내용 검색 함수
def search_history(keyword):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    query = f"%{keyword}%"
    # 메시지 내용에서 검색하고, 어떤 세션인지 함께 가져옴 (중복 제거)
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

# --- [API 관련 함수] ---
def translate_to_english_keyword(user_query):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a research assistant. Convert the user's query into concise English keywords suitable for searching academic papers on ArXiv. Return ONLY the keywords, no other text."},
                {"role": "user", "content": user_query}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return user_query

def search_arxiv(query, max_results=3):
    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        results = list(client.results(search))
        
        if not results:
            return None, 0

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

# 세션 상태 관리
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

# --- [사이드바 UI] ---
with st.sidebar:
    st.title("🗂️ 대화 관리")
    
    # 1. 새 대화 버튼
    if st.button("➕ 새 대화 시작", use_container_width=True):
        new_id = create_session()
        st.session_state.current_session_id = new_id
        st.rerun()
    
    st.divider()

    # 2. [복구 및 개선] 대화 검색 기능
    search_query = st.text_input("🔍 대화 내역 검색", placeholder="키워드 (예: Transformer)")
    if search_query:
        st.caption("검색 결과 (클릭 시 이동)")
        results = search_history(search_query)
        if results:
            for s_id, s_title, content_snippet in results:
                # 검색 결과 버튼 (내용 미리보기 포함)
                snippet = content_snippet[:20] + "..." if len(content_snippet) > 20 else content_snippet
                label = f"📄 {s_title}\nMatch: {snippet}"
                
                # 버튼 클릭 시 해당 세션으로 이동
                if st.button(label, key=f"search_{s_id}_{uuid.uuid4()}", use_container_width=True):
                    st.session_state.current_session_id = s_id
                    st.rerun()
        else:
            st.info("검색 결과가 없습니다.")
    
    st.divider()

    # 3. [신규 기능] 현재 대화 설정 (수정 및 삭제)
    if st.session_state.current_session_id:
        current_title, _ = get_session_info(st.session_state.current_session_id)
        
        with st.expander("⚙️ 현재 대화 설정", expanded=False):
            # 제목 수정
            new_title_input = st.text_input("제목 변경", value=current_title)
            if st.button("변경 저장", use_container_width=True):
                update_session_title(st.session_state.current_session_id, new_title_input)
                st.rerun()
            
            st.write("") # 여백
            
            # 대화 삭제
            if st.button("🗑️ 이 대화 삭제", type="primary", use_container_width=True):
                delete_session(st.session_state.current_session_id)
                st.session_state.current_session_id = None # 세션 초기화
                st.rerun() # 앱 리로드

        st.divider()

    # 4. 최근 대화 목록
    st.subheader("🕒 최근 대화 목록")
    sessions = get_all_sessions()
    
    for s_id, s_title, s_date in sessions:
        label = f"{s_title}\n{s_date}"
        # 현재 선택된 세션은 버튼 스타일을 다르게 할 수도 있으나, Streamlit 기본 버튼 사용
        if st.button(label, key=s_id, use_container_width=True):
            st.session_state.current_session_id = s_id
            st.rerun()

# --- [메인 화면 UI] ---

# 세션 로드 로직
if not st.session_state.current_session_id:
    # 세션이 없거나(삭제됨) 초기 상태일 때
    # 남은 세션이 있으면 가장 최신 것, 없으면 새로 생성
    all_sessions = get_all_sessions()
    if all_sessions:
        st.session_state.current_session_id = all_sessions[0][0]
    else:
        st.session_state.current_session_id = create_session()

# 현재 세션 정보 표시
session_title, session_date = get_session_info(st.session_state.current_session_id)
st.title(f"🎓 {session_title}")
st.caption(f"생성일: {session_date} | Paper Mate Pro")

# 대화 내용 출력
current_messages = get_messages(st.session_state.current_session_id)
for msg in current_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 사용자 입력 처리
if prompt := st.chat_input("논문 주제를 입력하세요 (한글/영어 자동 지원)"):
    
    st.chat_message("user").markdown(prompt)
    save_message(st.session_state.current_session_id, "user", prompt)

    with st.spinner(f"🌏 '{prompt}' 분석 중..."):
        try:
            # 1. 영어 키워드 변환
            english_query = translate_to_english_keyword(prompt)
            st.toast(f"검색어 변환: {english_query}")

            # 2. ArXiv 검색
            search_context, paper_count = search_arxiv(english_query)
            
            if not search_context:
                assistant_reply = f"'{english_query}'(으)로 검색했으나 결과가 없습니다."
            else:
                full_prompt = f"""
                사용자가 '{prompt}'(영어: {english_query})에 대한 논문을 찾고 있습니다.
                
                [지시사항]
                1. 총 {paper_count}개의 논문 모두에 대해 답변하세요.
                2. 한국어 요약 필수.
                3. APA 인용에 반드시 URL 포함.
                
                [검색 데이터]
                {search_context}
                
                --- 답변 형식 ---
                ### [번호]. [제목] (연도)
                * **요약:** (한국어 3문장)
                * **APA Citation:** (저자. (연도). 제목. *ArXiv*. URL)
                * **PDF 링크:** (URL)
                ---
                """
                
                messages_for_api = [{"role": "system", "content": "당신은 논문 전문가입니다."}]
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
            
        except Exception as e:
            st.error(f"오류: {e}")
