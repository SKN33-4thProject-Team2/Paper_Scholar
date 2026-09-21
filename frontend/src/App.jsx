// 데이터 순회 및 참조 시 옵셔널 체이닝 및 빈 배열 기본값 적용 구간
{activeView === 'translations'
  ? (paperPage?.results || []).filter((paper) => paper.translation_count > 0).length
  : paperPage?.count ?? 0}편

{!libraryLoading && activeView === 'library' && (paperPage?.results || []).length === 0 && (
  <div className="empty-state">저장된 논문이 없습니다.</div>
)}

{!libraryLoading && activeView === 'translations' && (paperPage?.results || []).filter((paper) => paper.translation_count > 0).length === 0 && (
  <div className="empty-state">아직 번역된 논문이 없습니다.<br />논문 상세 화면에서 번역을 시작해 보세요.</div>
)}

{!libraryLoading && activeView === 'library' && (paperPage?.results || []).map((paper) => (
  <PaperCard key={paper.arxiv_id} paper={paper} isSelected={selectedId === paper.arxiv_id} onSelect={selectPaper} />
))}