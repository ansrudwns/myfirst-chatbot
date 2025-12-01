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

# --- [데이터베이스 관리 함수] SQLite 사용 ---
DB_NAME = "chat_history.db"

def init_db():
    """데이터베이스와 테이블을 초기화합니다."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 세션(대화방) 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 메시지 테이블
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
    """새로운 대화 세션을 생성합니다."""
    session_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    final_title = f"{title} ({timestamp})"
    c.execute("INSERT INTO sessions (id, title) VALUES (?, ?)", (session_id, final_title))
    conn.commit()
    conn.close()
    return session_id

def save_message(session_id, role, content):
    """메시지를 DB에 저장합니다."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", 
              (session_id, role, content))
    conn.commit()
    conn.close()

def get_messages(session_id):
    """특정 세션의 모든 메시지를 가져옵니다."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

def get_all_sessions():
    """모든 대화 세션 목록을 가져옵니다 (최신순)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, title FROM sessions ORDER BY created_at DESC")
    sessions = c.fetchall()
    conn.close()
    return sessions

def search_history(keyword):
    """키워드로 대화 내용을 검색합니다."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    query = f"%{keyword}%"
    # 메시지 내용에서 검색하고, 어떤 세션인지 함께 가져옴
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

# --- [핵심 기능] ArXiv 논문 검색 함수 ---
def search_arxiv(query, max_results=3):
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance
    )
    results_text = []
    for result in search.results():
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
    return "\n\n".join(results_text)

# --- [메인 앱 로직] ---

# 0. DB 초기화 (앱 시작 시 한 번 실행)
init_db()

# 세션 상태 초기화
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

# --- [사이드바] : 대화 목록 및 검색 ---
with st.sidebar:
    st.header("🗂️ 대화 관리")
    
    # 1. 새 대화 시작 버튼
    if st.button("➕ 새 대화 시작", use_container_width=True):
        new_id = create_session()
        st.session_state.current_session_id = new_id
        st.rerun()

    st.divider()

    # 2. 대화 검색 기능
    search_query = st.text_input("🔍 대화 검색", placeholder="키워드 입력...")
    if search_query:
        st.subheader("검색 결과")
        results = search_history(search_query)
        if results:
            for session_id, title, content_snippet in results:
                # 검색된 대화로 이동하는 버튼
                # 내용이 너무 길면 잘라서 보여줌
                snippet = content_snippet[:30] + "..." if len(content_snippet) > 30 else content_snippet
                if st.button(f"📄 {title}\nRunning: {snippet}", key=f"search_{session_id}_{uuid.uuid4()}"):
                    st.session_state.current_session_id = session_id
                    st.rerun()
        else:
            st.info("검색 결과가 없습니다.")
            
    st.divider()

    # 3. 과거 대화 목록 (History)
    st.subheader("🕒 최근 대화")
    sessions = get_all_sessions()
    for s_id, s_title in sessions:
        if st.button(s_title, key=s_id, use_container_width=True):
            st.session_state.current_session_id = s_id
            st.rerun()

# --- [메인 화면] ---

# 세션이 선택되지 않았다면 가장 최근 세션을 불러오거나 새로 만듦
if not st.session_state.current_session_id:
    if sessions:
        st.session_state.current_session_id = sessions[0][0] # 가장 최근 대화
    else:
        st.session_state.current_session_id = create_session() # 대화가 하나도 없으면 생성

st.title("🎓 Paper Mate Pro")

# 현재 세션의 메시지 불러오기
current_messages = get_messages(st.session_state.current_session_id)

# 화면에 메시지 출력
for msg in current_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 사용자 입력 처리
if prompt := st.chat_input("논문 주제를 입력하세요..."):
    
    # (1) 사용자 메시지 표시 및 저장
    st.chat_message("user").markdown(prompt)
    save_message(st.session_state.current_session_id, "user", prompt)

    # (2) 로딩 및 처리
    with st.spinner(f"🔎 '{prompt}' 분석 중..."):
        try:
            # ArXiv 검색
            search_context = search_arxiv(prompt)
            
            if not search_context:
                assistant_reply = "검색 결과가 없습니다. 다른 키워드로 시도해 보세요."
            else:
                full_prompt = f"""
                사용자가 '{prompt}'에 대한 논문을 찾고 있습니다.
                아래 검색된 논문 데이터를 바탕으로 답변해주세요.
                
                [검색된 논문 데이터]
                {search_context}
                
                --- 답변 형식 ---
                1. [논문 제목] (연도)
                2. 한국어 핵심 요약 (3문장)
                3. APA Citation
                4. PDF 링크
                """
                
                # GPT 호출 (이전 대화 맥락 포함)
                # DB에서 가져온 메시지 형식을 API 형식에 맞춤
                messages_for_api = [{"role": "system", "content": "당신은 논문 검색 도우미입니다."}]
                messages_for_api.extend(current_messages) # 이전 대화 기록 추가
                messages_for_api.append({"role": "user", "content": full_prompt})

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages_for_api
                )
                assistant_reply = response.choices[0].message.content

            # (3) AI 응답 표시 및 저장
            with st.chat_message("assistant"):
                st.markdown(assistant_reply)
            
            save_message(st.session_state.current_session_id, "assistant", assistant_reply)
            
        except Exception as e:
            st.error(f"오류가 발생했습니다: {e}")
