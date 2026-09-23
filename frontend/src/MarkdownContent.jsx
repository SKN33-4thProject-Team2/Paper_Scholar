import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'

function normalizeMathMarkdown(value = '') {
  return value
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, math) => `$$\n${math.trim()}\n$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_match, math) => `$${math.trim()}$`)
}

export default function MarkdownContent({ text }) {
  return (
    <div className="artifact-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {normalizeMathMarkdown(text)}
      </ReactMarkdown>
    </div>
  )
}
