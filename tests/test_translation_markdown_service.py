"""번역용 Markdown 청킹의 구조 보존 테스트."""

from __future__ import annotations

import unittest

from tests import SRC_DIR  # noqa: F401 - src 경로를 sys.path에 등록한다.

from services.translation_markdown_service import split_markdown


class TranslationMarkdownChunkTest(unittest.TestCase):
    def test_moves_inline_math_whole_to_next_chunk(self) -> None:
        chunks = split_markdown("abcdefgh$E=mc^2$tail", max_chars=12)

        self.assertEqual(chunks, ["abcdefgh", "$E=mc^2$tail"])

    def test_keeps_parenthesized_math_whole_at_chunk_boundary(self) -> None:
        chunks = split_markdown(r"abcdefgh\(x + y\)tail", max_chars=12)

        self.assertEqual(chunks, ["abcdefgh", r"\(x + y\)tai", "l"])
        self.assertTrue(all(r"\(" not in chunk or r"\)" in chunk for chunk in chunks))

    def test_keeps_display_math_whole_when_surrounded_by_long_text(self) -> None:
        formula = "$$\\sum_{i=1}^{n} x_i$$"
        chunks = split_markdown(f"abcdefgh{formula}tail", max_chars=12)

        self.assertIn(formula, chunks)
        self.assertTrue(all(not ("$$" in chunk and chunk != formula) for chunk in chunks))

    def test_keeps_latex_environment_whole_even_when_over_limit(self) -> None:
        formula = r"\begin{align}a &= b + c\\d &= e\end{align}"
        chunks = split_markdown(f"prefixtext{formula}suffix", max_chars=10)

        self.assertIn(formula, chunks)
        self.assertEqual(sum(chunk.count(r"\begin{align}") for chunk in chunks), 1)
        self.assertEqual(sum(chunk.count(r"\end{align}") for chunk in chunks), 1)


if __name__ == "__main__":
    unittest.main()
