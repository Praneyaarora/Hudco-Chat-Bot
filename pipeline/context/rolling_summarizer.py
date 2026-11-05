"""
HUDCO Bot — Rolling Conversation Summarizer
Maintains an accurate, factual running summary of older conversational turns
when total conversation history exceeds the active LLM context budget.
"""

from typing import List, Optional
import logging
from pipeline.storage.contracts import ChatMessage, ConversationSummaryItem

logger = logging.getLogger("hudco_bot.rolling_summarizer")


class RollingSummarizer:
    """
    Condenses older conversation turns into a coherent, high-signal factual summary.
    Preserves:
    - User topics, specific inquiries, and entities (e.g. HUDCO FY results, loan sanctions, schemes).
    - Assistant conclusions, specific numbers, and decisions made.
    - Resolves coreferences and maintains context across long sessions.
    """

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    def build_heuristic_summary(
        self,
        existing_summary: Optional[str],
        messages_to_summarize: List[ChatMessage]
    ) -> str:
        """
        Fast, zero-latency deterministic extraction for older messages.
        Used as a high-reliability fallback if LLM synthesis is offline or constrained.
        """
        summary_points = []
        if existing_summary and existing_summary.strip():
            summary_points.append(f"Prior Context: {existing_summary.strip()}")

        for msg in messages_to_summarize:
            role = "User" if msg.role == "user" else "Assistant"
            text = msg.content.strip()
            # Truncate very long answers to key takeaways
            if len(text) > 220:
                text = text[:210].rsplit(" ", 1)[0] + "..."
            summary_points.append(f"• {role}: {text}")

        # Keep rolling summary concise (capped at ~1200 characters)
        combined = "\n".join(summary_points)
        if len(combined) > 1500:
            lines = combined.split("\n")
            combined = "\n".join(lines[-15:])
        return combined

    def summarize_turns(
        self,
        existing_summary: Optional[str],
        pruned_turns: List[ChatMessage],
        active_provider: str = "local_qwen",
        gemini_api_key: Optional[str] = None
    ) -> str:
        """
        Summarizes pruned turns, updating the rolling summary.
        If an LLM manager is available, uses concise LLM condensation;
        otherwise falls back cleanly to the heuristic extractor.
        """
        if not pruned_turns:
            return existing_summary or ""

        # Format conversation segment to condense
        transcript_lines = []
        for msg in pruned_turns:
            role_label = "User" if msg.role == "user" else "HUDCO Assistant"
            transcript_lines.append(f"{role_label}: {msg.content}")
        transcript_text = "\n".join(transcript_lines)

        # If LLM Manager is available and cloud/local model is operational, run fast summary prompt
        if self.llm_manager is not None:
            prompt = (
                "You are an expert conversational summarizer for HUDCO Enterprise Bot.\n"
                "Condense the following conversation history into a concise factual summary (2 to 5 bullet points).\n"
                "Focus on key questions asked, financial figures mentioned, HUDCO projects discussed, and verified facts.\n"
                "Do NOT include meta commentary. Return only the bullet points.\n\n"
            )
            if existing_summary and existing_summary.strip():
                prompt += f"Existing Summary:\n{existing_summary.strip()}\n\n"
            prompt += f"Recent Turns to Integrate:\n{transcript_text}\n\nUpdated Concise Summary:"

            try:
                # Attempt fast generation
                result = self.llm_manager.generate_answer(
                    prompt=prompt,
                    evidence_chunks=[],
                    provider=active_provider,
                    gemini_api_key=gemini_api_key,
                    max_new_tokens=256,
                    temperature=0.2
                )
                if result and result.get("answer"):
                    summary_text = result["answer"].strip()
                    if summary_text and not summary_text.startswith("Error"):
                        return summary_text
            except Exception as e:
                logger.warning("LLM rolling summarization encountered error, falling back to heuristic: %s", e)

        # Fallback to heuristic condensation
        return self.build_heuristic_summary(existing_summary, pruned_turns)

