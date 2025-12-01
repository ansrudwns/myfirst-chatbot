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
# (.env 파일에 AZURE_OAI_KEY, AZURE_OAI_ENDPOINT 설정 필수)
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OAI_KEY"),
    api_version="2024-05-01-preview",
    azure_endpoint=os.getenv("AZURE_OAI_ENDPOINT")
)

# --- [데이터베이스 관리 함수] SQLite 사용 ---
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
    final_title = f"{title} ({timestamp})"
    c.execute("INSERT INTO sessions (id, title) VALUES (?, ?)", (session_id, final_title))
    conn.commit()
    conn.close()
    return session_id

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
    c.execute("SELECT id, title FROM sessions ORDER BY created_at DESC")
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

# --- [핵심 수정] ArXiv 논문 검색 함수 (안정성 강화) ---
def search_arxiv(query, max_results=3):
    try:
        # 1. Client 명시적 생성 (네트워크 오류 방지)
        client = arxiv.Client()
        
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        results_text = []
        
        # 2. 제너레이터를 리스트로 변환하여 데이터 확보 확실하게 처리
        results = list(client.results(search))
        
        # 디버깅: 몇 개 찾았는지 콘솔에 출력
        print(f"[DEBUG] 검색어: '{query}' / 찾은 논문 수: {len(results)}")

        if not results:
            return None

        for result in results:
            authors = ", ".join([author.name for author in result.authors])
            published_year = result.published.strftime("%Y")
            
            # 3. PDF URL 확보
            pdf_link = result.pdf_url
            
            paper_data = f"""
            [Paper ID: {result.entry_id}]
            - Title: {result.title}
            - Authors: {authors}
            - Published Year: {published_year}
            - Abstract: {result.summary.replace(chr(10), " ")} 
            - PDF Link: {pdf_link}
            """
            results_text.append(paper_data)
        
        return "\n\n".join(results_text)

    except Exception as e:
        st.error(f"ArXiv 검색 시스템 오류: {str(e)}")
        return None

# --- [메인 앱 로직] ---

# 0. DB 초기화
init_db()

# 세션 상태 초기화
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

# --- [사이드바] ---
with st.sidebar:
    st.header("🗂️ 대화 관리")
    
    if st.button("➕ 새 대화 시작", use_container_width=True):
        new_id = create_session()
        st.session_state.current_session_id = new_id
        st.rerun()

    st.divider()

    search_query = st.text_input("🔍 대화 검색", placeholder="키워드 입력...")
    if search_query:
        st.subheader("검색 결과")
        results = search_history(search_query)
        if results:
            for session_id, title, content_snippet in results:
                snippet = content_snippet[:30] + "..." if len(content_snippet) > 30 else content_snippet
                if st.button(f"📄 {title}\nRunning: {snippet}", key=f"search_{session_id}_{uuid.uuid4()}"):
                    st.session_state.current_session_id = session_id
                    st.rerun()
        else:
            st.info("검색 결과가 없습니다.")
            
    st.divider()

    st.subheader("🕒 최근 대화")
    sessions = get_all_sessions()
    for s_id, s_title in sessions:
        if st.button(s_title, key=s_id, use_container_width=True):
            st.session_state.current_session_id = s_id
            st.rerun()

# --- [메인 화면] ---

if not st.session_state.current_session_id:
    if sessions:
        st.session_state.current_session_id = sessions[0][0]
    else:
        st.session_state.current_session_id = create_session()

st.title("🎓 Paper Mate Pro")

current_messages = get_messages(st.session_state.current_session_id)

for msg in current_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("논문 주제를 입력하세요 (예: RAG, Transformer)..."):
    
    st.chat_message("user").markdown(prompt)
    save_message(st.session_state.current_session_id, "user", prompt)

    with st.spinner(f"🔎 '{prompt}' 관련 논문을 ArXiv에서 검색 중입니다..."):
        try:
            # 검색 실행
            search_context = search_arxiv(prompt)
            
            if not search_context:
                assistant_reply = "검색 결과가 없습니다. 영어로 검색하거나 다른 키워드를 시도해 보세요."
            else:
                # 검색된 논문 개수 확인 (프롬프트 주입용)
                paper_count = search_context.count("Paper ID:")
                
                # --- [핵심 수정] 프롬프트 강화 ---
                full_prompt = f"""
                사용자가 '{prompt}'에 대한 논문을 찾고 있습니다.
                
                [지시사항]
                1. 아래 [검색된 논문 데이터]에는 **총 {paper_count}개의 논문**이 있습니다.
                2. 반드시 **{paper_count}개 논문 모두**에 대해 각각 답변을 작성하세요. 절대 하나로 합치거나 생략하지 마세요.
                3. APA 인용 작성 시, 논문이 ArXiv 소스이므로 **반드시 URL을 포함**하세요.
                
                [검색된 논문 데이터]
                {search_context}
                
                --- 답변 형식 (각 논문마다 반복) ---
                ### [번호]. [논문 제목] (연도)
                * **핵심 요약:** (한국어 3문장 이내)
                * **APA Citation:** (저자. (연도). 제목. *ArXiv*. URL 형식 준수)
                * **PDF 링크:** (URL)
                
                ---
                """
                
                messages_for_api = [{"role": "system", "content": "당신은 논문 검색 및 인용 전문가입니다."}]
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
            st.error(f"오류가 발생했습니다: {e}")
