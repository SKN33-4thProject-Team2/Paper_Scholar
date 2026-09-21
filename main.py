from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Paper Scholar Backend", version="1.0.0")

# CORS 설정 (프론트엔드 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    question: str

@app.get("/")
def read_root():
    return {"message": "Paper Scholar API is running successfully."}

@app.post("/api/chat")
def chat_with_paper(request: QueryRequest):
    try:
        # TODO: 여기에 LangChain / RAG 챗봇 로직 연결
        user_query = request.question
        response_answer = f"Received your paper query: {user_query}"
        return {"status": "success", "answer": response_answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))