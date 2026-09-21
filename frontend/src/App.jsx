import { useState } from 'react'
import './App.css'

function App() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [loading, setLoading] = useState(false)
  
  // 추가된 뷰 상태 및 논문 데이터 상태 예시 (기본 구조 연동)
  const [activeView, setActiveView] = useState('library')
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [paperPage, setPaperPage] = useState({ results: [], count: 0 })

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!question.trim()) return

    setLoading(true)
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      })
      const data = await res.json()
      setAnswer(data.answer || 'No response')
    } catch (err) {
      setAnswer('Error connecting to backend.')
    } finally {
      setLoading(false)
    }
  }

  const selectPaper = (paper) => {
    setSelectedId(paper.arxiv_id)
  }

  return (
    <div style={{ padding: '40px', fontFamily: 'sans-serif', maxWidth: '800px', margin: '0 auto' }}>
      <h1>Paper Scholar RAG Chatbot</h1>
      
      {/* 뷰 전환 탭 예시 */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
        <button onClick={() => setActiveView('library')} style={{ padding: '8px 16px' }}>전체 논문 보관함</button>
        <button onClick={() => setActiveView('translations')} style={{ padding: '8px 16px' }}>번역된 논문</button>
      </div>

      {/* 데이터 개수 카운트 출력 (옵셔널 체이닝 적용) */}
      <div style={{ marginBottom: '15px', fontWeight: 'bold' }}>
        총 항목 수: {activeView === 'translations'
          ? (paperPage?.results || []).filter((paper) => paper.translation_count > 0).length
          : paperPage?.count ?? 0}편
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
        <input 
          type="text" 
          value={question} 
          onChange={(e) => setQuestion(e.target.value)} 
          placeholder="논문 내용에 대해 질문하세요..." 
          style={{ flex: 1, padding: '10px' }}
        />
        <button type="submit" disabled={loading} style={{ padding: '10px 20px' }}>
          {loading ? '검색 중...' : '전송'}
        </button>
      </form>

      {/* 저장된 논문이 없을 때의 빈 상태 화면 */}
      {!libraryLoading && activeView === 'library' && (paperPage?.results || []).length === 0 && (
        <div className="empty-state" style={{ padding: '20px', background: '#fafafa', textAlign: 'center', color: '#666' }}>
          저장된 논문이 없습니다.
        </div>
      )}

      {/* 번역된 논문이 없을 때의 빈 상태 화면 */}
      {!libraryLoading && activeView === 'translations' && (paperPage?.results || []).filter((paper) => paper.translation_count > 0).length === 0 && (
        <div className="empty-state" style={{ padding: '20px', background: '#fafafa', textAlign: 'center', color: '#666' }}>
          아직 번역된 논문이 없습니다.<br />논문 상세 화면에서 번역을 시작해 보세요.
        </div>
      )}

      {/* 논문 리스트 순회 렌더링 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {!libraryLoading && activeView === 'library' && (paperPage?.results || []).map((paper) => (
          <div 
            key={paper.arxiv_id} 
            onClick={() => selectPaper(paper)}
            style={{ padding: '15px', border: '1px solid #ddd', borderRadius: '5px', cursor: 'pointer', background: selectedId === paper.arxiv_id ? '#eef2ff' : '#fff' }}
          >
            <h4>{paper.title || '제목 없음'}</h4>
            <p>{paper.summary || '요약 정보가 없습니다.'}</p>
          </div>
        ))}
      </div>

      <div style={{ background: '#f4f4f4', padding: '15px', borderRadius: '5px', marginTop: '30px' }}>
        <h3>답변:</h3>
        <p>{answer || '질문을 입력하고 답변을 확인하세요.'}</p>
      </div>
    </div>
  )
}

export default App