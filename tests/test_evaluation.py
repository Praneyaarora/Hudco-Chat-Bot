"""
Focused Unit Tests for the HUDCO Evaluation Harness.
Covers chunking, page mapping, BM25 scoring, schema validation, and citation checking.
NOTE: As per project guidelines, these tests are written but NOT executed without user approval.
"""

import unittest
from evaluation.schemas import (
    PageExtractionRecord,
    EvaluationChunk,
    EvaluationQuestion,
    RetrievalResultItem,
)
from evaluation.chunker import split_text_into_page_windows, EvaluationChunker
from evaluation.retriever_bm25 import tokenize, BM25Retriever
from evaluation.generator_ollama import validate_citations


class TestEvaluationHarness(unittest.TestCase):

    def test_chunk_id_determinism(self):
        """Test that chunk IDs are generated deterministically and contain section & page."""
        page = PageExtractionRecord(
            document_id="HUDCO_AR_2025_26_c412ce14",
            source_filename="ar26.pdf",
            section_id="sec_05",
            section_title="Directors' Report",
            physical_page=52,
            printed_page=50,
            char_count=400,
            is_empty=False,
            is_suspiciously_short=False,
            has_table=False,
            text="This is a test paragraph describing HUDCO directors report in detail.",
            warnings=[]
        )
        chunker = EvaluationChunker()
        chunks = chunker.chunk_pages([page])
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_id, "HUDCO_AR_2025_26_c412ce14_sec_05_p052_c00")
        self.assertEqual(chunks[0].physical_page, 52)
        self.assertEqual(chunks[0].printed_page, 50)

    def test_empty_page_handling(self):
        """Test that empty pages produce zero chunks."""
        page = PageExtractionRecord(
            document_id="HUDCO_AR_2025_26_c412ce14",
            source_filename="ar26.pdf",
            section_id="sec_19",
            section_title="HUDCO Offices",
            physical_page=520,
            printed_page=None,
            char_count=0,
            is_empty=True,
            is_suspiciously_short=False,
            has_table=False,
            text="",
            warnings=["EMPTY_PAGE"]
        )
        chunker = EvaluationChunker()
        chunks = chunker.chunk_pages([page])
        self.assertEqual(len(chunks), 0)

    def test_table_preservation_flag(self):
        """Test that table presence is propagated from page record to chunks."""
        page = PageExtractionRecord(
            document_id="HUDCO_AR_2025_26_c412ce14",
            source_filename="ar26.pdf",
            section_id="sec_01",
            section_title="Reference Information",
            physical_page=21,
            printed_page=19,
            char_count=500,
            is_empty=False,
            is_suspiciously_short=False,
            has_table=True,
            text="Financial Highlights: Revenue from Operations Rs. 13,150.40 Crore.",
            warnings=["TABLE_DETECTED"]
        )
        chunker = EvaluationChunker()
        chunks = chunker.chunk_pages([page])
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].has_table)

    def test_bm25_ranking_and_explanation(self):
        """Test that BM25 ranks the most relevant chunk highest with valid explanation."""
        c1 = EvaluationChunk(
            chunk_id="c01",
            document_id="doc1",
            source_filename="ar26.pdf",
            section_id="sec_02",
            section_title="Board of Directors",
            physical_page=22,
            printed_page=20,
            chunk_index=0,
            char_count=100,
            token_estimate=25,
            has_table=False,
            content="Shri Sanjay Kulshrestha is the Chairman and Managing Director of HUDCO.",
            sha256="abc1"
        )
        c2 = EvaluationChunk(
            chunk_id="c02",
            document_id="doc1",
            source_filename="ar26.pdf",
            section_id="sec_19",
            section_title="HUDCO Offices",
            physical_page=517,
            printed_page=515,
            chunk_index=0,
            char_count=100,
            token_estimate=25,
            has_table=False,
            content="HUDCO Managing Director office is at Lodhi Road New Delhi.",
            sha256="abc2"
        )

        retriever = BM25Retriever(chunks=[c1, c2])
        results = retriever.retrieve("Who is the Chairman and Managing Director?", top_k=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].chunk_id, "c01")
        self.assertGreater(results[0].score, results[1].score)
        self.assertIn("chairman", results[0].matched_terms)
        self.assertIn("Matched", results[0].explanation)

    def test_citation_validation(self):
        """Test citation validator checks cited chunks against retrieved chunks."""
        items = [
            RetrievalResultItem(
                rank=1,
                chunk_id="HUDCO_AR_sec02_p022_c00",
                score=5.2,
                matched_terms=["chairman"],
                explanation="test",
                document_id="doc",
                section_id="sec02",
                section_title="Directors",
                physical_page=22,
                printed_page=20,
                has_table=False,
                text="Shri Sanjay Kulshrestha is CMD."
            )
        ]

        # Valid citation
        answer_valid = "The Chairman is Shri Sanjay Kulshrestha [HUDCO_AR_sec02_p022_c00]."
        eval_v = validate_citations(answer_valid, items)
        self.assertEqual(len(eval_v["verified_chunk_ids"]), 1)
        self.assertEqual(len(eval_v["hallucinated_chunk_ids"]), 0)
        self.assertEqual(eval_v["citation_precision"], 1.0)
        self.assertFalse(eval_v["is_abstention"])

        # Hallucinated citation
        answer_hallucinated = "The Chairman is Sanjay [HUDCO_FAKE_CHUNK_999]."
        eval_h = validate_citations(answer_hallucinated, items)
        self.assertEqual(len(eval_h["verified_chunk_ids"]), 0)
        self.assertEqual(len(eval_h["hallucinated_chunk_ids"]), 1)
        self.assertEqual(eval_h["citation_precision"], 0.0)

        # Abstention answer
        answer_abstain = "INSUFFICIENT_EVIDENCE: The provided HUDCO passages do not contain information."
        eval_a = validate_citations(answer_abstain, items)
        self.assertTrue(eval_a["is_abstention"])

    def test_question_schema_validation(self):
        """Test EvaluationQuestion Pydantic validation on unanswerable query."""
        q = EvaluationQuestion(
            question_id="Q11",
            question="What is HUDCO's cryptocurrency policy?",
            category="unanswerable",
            expected_answer=None,
            expected_pdf_pages=[],
            expected_printed_pages=[],
            answerability="unanswerable",
            evaluation_notes="Unanswerable test"
        )
        self.assertEqual(q.answerability, "unanswerable")
        self.assertIsNone(q.expected_answer)
        self.assertEqual(len(q.expected_pdf_pages), 0)


class TestSyntheticRetrievalEvaluationMetrics(unittest.TestCase):
    """
    Synthetic regression tests for Section 4.2 metric definitions and distinct denominators.
    Validates manual calculations for:
    - Chunk Recall@1, @3, @5 vs Page Recall@1, @3, @5
    - Citation page accuracy at Rank 1 vs Citation precision across top 5
    - MRR at chunk level and page level
    - Abstention precision, recall, and F1
    - Multiple valid reference pages and multiple chunks per page
    """

    def setUp(self):
        from pipeline.core.contracts import CanonicalChunk

        import hashlib

        # Chunk A on page 22 (Chairman)
        content_a = "Shri Sanjay Kulshrestha is the Chairman and Managing Director of HUDCO."
        self.chunk_a = CanonicalChunk(
            chunk_id="chunk_syn_p022_a",
            document_id="doc_syn",
            version_id="v1",
            source_id="syn_doc",
            source_filename="syn.pdf",
            section_id="sec_02",
            section_title="Board of Directors",
            ancestor_headings=["Overview", "Board"],
            chunk_index_in_section=0,
            chunk_index_in_page=0,
            physical_page=22,
            printed_page="20",
            char_count=len(content_a),
            token_estimate=len(content_a) // 4,
            has_table=False,
            structured_tables=[],
            content=content_a,
            content_sha256=hashlib.sha256(content_a.encode("utf-8")).hexdigest(),
            is_stale=False,
        )

        # Chunk B on page 22 (Board meeting details)
        content_b = "The Board of Directors met regularly during the financial year to review operations."
        self.chunk_b = CanonicalChunk(
            chunk_id="chunk_syn_p022_b",
            document_id="doc_syn",
            version_id="v1",
            source_id="syn_doc",
            source_filename="syn.pdf",
            section_id="sec_02",
            section_title="Board of Directors",
            ancestor_headings=["Overview", "Board"],
            chunk_index_in_section=1,
            chunk_index_in_page=1,
            physical_page=22,
            printed_page="20",
            char_count=len(content_b),
            token_estimate=len(content_b) // 4,
            has_table=False,
            structured_tables=[],
            content=content_b,
            content_sha256=hashlib.sha256(content_b.encode("utf-8")).hexdigest(),
            is_stale=False,
        )

        # Chunk C on page 215 (Registered Office)
        content_c = "The Registered Office of HUDCO is located at HUDCO Bhawan India Habitat Centre Lodhi Road New Delhi."
        self.chunk_c = CanonicalChunk(
            chunk_id="chunk_syn_p215_c",
            document_id="doc_syn",
            version_id="v1",
            source_id="syn_doc",
            source_filename="syn.pdf",
            section_id="sec_14",
            section_title="Corporate Governance",
            ancestor_headings=["Corporate Governance", "Offices"],
            chunk_index_in_section=0,
            chunk_index_in_page=0,
            physical_page=215,
            printed_page="213",
            char_count=len(content_c),
            token_estimate=len(content_c) // 4,
            has_table=False,
            structured_tables=[],
            content=content_c,
            content_sha256=hashlib.sha256(content_c.encode("utf-8")).hexdigest(),
            is_stale=False,
        )

        self.chunks = [self.chunk_a, self.chunk_b, self.chunk_c]

    def test_synthetic_evaluation_metrics_manual_verification(self):
        from scripts.run_retrieval_eval import evaluate_retrieval

        questions = [
            # Q1: Target is Chunk A, Page 22 (multiple valid pages supported [22, 23])
            {
                "question_id": "SYN_Q1",
                "question": "Who is the Chairman and Managing Director?",
                "category": "leadership",
                "answerability": "answerable",
                "expected_relevant_chunk_ids": ["chunk_syn_p022_a"],
                "expected_pdf_pages": [22, 23],
            },
            # Q2: Target is Chunk C, Page 215
            {
                "question_id": "SYN_Q2",
                "question": "Where is the HUDCO Registered Office located in New Delhi?",
                "category": "contact",
                "answerability": "answerable",
                "expected_relevant_chunk_ids": ["chunk_syn_p215_c"],
                "expected_pdf_pages": [215],
            },
            # Q3: Unanswerable query
            {
                "question_id": "SYN_Q3",
                "question": "What is HUDCO policy on Bitcoin cryptocurrency in Frankfurt Germany?",
                "category": "unanswerable",
                "answerability": "unanswerable",
                "expected_relevant_chunk_ids": [],
                "expected_pdf_pages": [],
            },
        ]

        metrics, details = evaluate_retrieval(
            chunks=self.chunks,
            questions=questions,
            k1=1.2,
            b=0.45,
            score_threshold=1.0,
            min_term_coverage=0.40,
        )

        # Denominators verification
        self.assertEqual(metrics["total_questions"], 3)
        self.assertEqual(metrics["answerable_questions"], 2)
        self.assertEqual(metrics["unanswerable_questions"], 1)

        # Q1 and Q2 should be rank 1 hits
        self.assertEqual(metrics["metrics"]["chunk_recall_at_1"], 1.0)
        self.assertEqual(metrics["metrics"]["chunk_recall_at_3"], 1.0)
        self.assertEqual(metrics["metrics"]["chunk_recall_at_5"], 1.0)

        self.assertEqual(metrics["metrics"]["page_recall_at_1"], 1.0)
        self.assertEqual(metrics["metrics"]["page_recall_at_3"], 1.0)
        self.assertEqual(metrics["metrics"]["page_recall_at_5"], 1.0)

        self.assertEqual(metrics["metrics"]["page_citation_accuracy_at_1"], 1.0)
        self.assertEqual(metrics["metrics"]["mrr_chunk"], 1.0)
        self.assertEqual(metrics["metrics"]["mrr_page"], 1.0)

        # Citation precision at 5:
        # In Q1: Top results are chunk A (p22), chunk B (p22) -> both match p22!
        # In Q2: Top result is chunk C (p215) -> matches p215!
        self.assertGreater(metrics["metrics"]["page_citation_accuracy_at_5"], 0.0)
        self.assertIn("page_citation_accuracy_at_5_denominator", metrics["denominators"])

        # Abstention verification
        self.assertEqual(metrics["metrics"]["abstention_recall"], 1.0)
        self.assertEqual(metrics["metrics"]["abstention_precision"], 1.0)
        self.assertEqual(metrics["metrics"]["abstention_f1"], 1.0)


class TestBenchmarkGroundTruthIntegrity(unittest.TestCase):
    """
    Automated regression checks to detect stale chunk IDs and page mismatches in evaluation ground truth.
    Guarantees 100% agreement between evaluation_questions.jsonl and canonical full-run chunks.
    """

    def test_all_benchmark_chunk_ids_exist_in_active_canonical_dataset(self):
        import json
        from pathlib import Path
        from pipeline.retrieval.loader import load_canonical_chunks

        proj_root = Path(__file__).resolve().parent.parent
        q_path = proj_root / "evaluation" / "data" / "evaluation_questions.jsonl"
        chunks_path = proj_root / "data" / "output_chunks" / "run_full_ar26_p1_520_v1" / "chunks.jsonl"

        if not chunks_path.exists():
            self.skipTest("Canonical chunks file not present; skipping benchmark integrity test.")

        chunks = load_canonical_chunks(str(chunks_path))
        chunk_map = {c.chunk_id: c for c in chunks}

        with open(q_path, "r", encoding="utf-8") as f:
            questions = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(questions), 20)

        for q in questions:
            qid = q["question_id"]
            ans = q["answerability"]
            c_ids = q.get("expected_relevant_chunk_ids", [])
            pages = q.get("expected_pdf_pages", [])

            if ans == "unanswerable":
                self.assertEqual(len(c_ids), 0, f"{qid} unanswerable but has chunk IDs")
                self.assertEqual(len(pages), 0, f"{qid} unanswerable but has pages")
                self.assertIsNone(q.get("expected_answer"), f"{qid} unanswerable but has expected_answer")
            else:
                self.assertGreater(len(c_ids), 0, f"{qid} answerable but has no chunk IDs")
                self.assertGreater(len(pages), 0, f"{qid} answerable but has no expected pages")
                self.assertIsNotNone(q.get("expected_answer"), f"{qid} answerable but missing expected_answer")

                # Verify each chunk ID exists in active canonical chunks
                for cid in c_ids:
                    self.assertIn(
                        cid,
                        chunk_map,
                        f"Question {qid} references stale chunk ID '{cid}' not found in active chunks!"
                    )
                    # Verify physical page of the chunk matches expected_pdf_pages
                    c = chunk_map[cid]
                    self.assertIn(
                        c.physical_page,
                        pages,
                        f"Question {qid} chunk '{cid}' is on page {c.physical_page}, but expected_pdf_pages is {pages}!"
                    )


if __name__ == "__main__":
    unittest.main()
