"""
AI Content Generator
Uses Claude API to generate LinkedIn posts about AI & Data Engineering.
Also generates contextual replies to comments and messages.

Improvements:
- Thread-safe topic cycling (was: race condition with _topic_index)
- Full Anthropic API error handling (rate limits, connection errors, API errors)
- Post length validation before returning
- Proper logging instead of print statements
"""

import threading
import logging
import anthropic
from typing import Optional

logger = logging.getLogger(__name__)

TOPIC_POOL = [
    "Building real-time data pipelines with Apache Kafka and Flink",
    "How AI agents are transforming data engineering workflows",
    "Modern data lakehouse architecture: Delta Lake vs Apache Iceberg",
    "MLOps best practices for production AI systems",
    "The rise of agentic AI: from chatbots to autonomous data pipelines",
    "dbt + Airflow: orchestrating analytics engineering at scale",
    "Vector databases explained: Pinecone, Weaviate, and pgvector compared",
    "LLM fine-tuning vs RAG: when to use each approach",
    "Data mesh architecture: decentralizing data ownership",
    "Real-world lessons from deploying AI agents in enterprise settings",
    "The future of the Modern Data Stack in the AI era",
    "Building an event-driven architecture for ML feature stores",
    "Cost optimization strategies for cloud data warehouses",
    "How to design fault-tolerant AI pipelines",
    "Emerging patterns in multi-agent AI systems for data processing",
    "Semantic layer: the missing piece in your data platform",
    "Observability in AI/ML systems: beyond basic logging",
    "Spark vs Flink vs Ray: choosing the right distributed compute engine",
    "How I architected a zero-copy data platform for petabyte-scale analytics",
    "The impact of foundation models on traditional ETL pipelines",
]

_MAX_POST_CHARS    = 3000
_MAX_COMMENT_CHARS = 1250


class ContentGenerator:
    """
    Generates LinkedIn posts, replies, and message responses using Claude AI.
    Maintains Satyam's voice as a senior AI/Data Engineering Architect.
    """

    AUTHOR_PERSONA = """
You are ghostwriting for Satyam Agarwal, a professional AI/Data Engineering Architect.
His LinkedIn voice is:
- Authoritative but approachable — speaks from real project experience
- Uses concrete examples, architecture diagrams described in text, and code snippets when helpful
- Balances technical depth with business impact
- Occasionally uses emojis (🚀, 🔥, 💡, ⚡) but never overdoes it
- Ends posts with a thought-provoking question to drive engagement
- Uses line breaks and short paragraphs for LinkedIn readability
- Hashtags: 3–5 relevant ones at the end (e.g. #DataEngineering #AIAgents #MLOps)
"""

    def __init__(self, api_key: str, model: str = "claude-opus-4-6"):
        self.client       = anthropic.Anthropic(api_key=api_key)
        self.model        = model
        self._topic_index = 0
        self._topic_lock  = threading.Lock()   # Thread-safe cycling

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _call_claude(self, prompt: str, max_tokens: int) -> str:
        """
        Call Claude API with full error handling.
        Raises on persistent failure so caller can decide recovery strategy.
        """
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except anthropic.RateLimitError as e:
            logger.error("[ContentGen] ❌ Claude rate limit hit: %s", e)
            raise
        except anthropic.APIConnectionError as e:
            logger.error("[ContentGen] ❌ Claude connection error: %s", e)
            raise
        except anthropic.APIStatusError as e:
            logger.error("[ContentGen] ❌ Claude API error %s: %s", e.status_code, e.message)
            raise
        except Exception as e:
            logger.error("[ContentGen] ❌ Unexpected Claude error: %s", e, exc_info=True)
            raise

    def _next_topic(self) -> str:
        """Thread-safe topic cycling."""
        with self._topic_lock:
            topic = TOPIC_POOL[self._topic_index % len(TOPIC_POOL)]
            self._topic_index += 1
            return topic

    # ──────────────────────────────────────────────
    # Post Generation
    # ──────────────────────────────────────────────

    def generate_weekly_post(self, custom_topic: Optional[str] = None) -> str:
        """
        Generate a LinkedIn post for the week.
        Cycles through built-in topics or uses a custom topic if provided.
        """
        from datetime import datetime
        topic    = custom_topic or self._next_topic()
        week_str = datetime.now().strftime("Week of %B %d, %Y")

        prompt = f"""{self.AUTHOR_PERSONA}

Write a compelling LinkedIn post for {week_str} on this topic:
"{topic}"

Requirements:
- Length: 150–300 words (MUST stay under 3000 characters total)
- Start with a strong hook (first line must grab attention — no "I am excited to share...")
- Include 1–2 concrete technical insights or real-world observations
- Mention a specific tool, framework, or architecture pattern
- End with an engaging question to invite comments
- Add 3–5 relevant hashtags on the last line
- Format for LinkedIn: short paragraphs, line breaks, optional emojis

Output ONLY the post text, nothing else.
"""
        post_text = self._call_claude(prompt, max_tokens=600)

        # Safety: enforce LinkedIn character limit
        if len(post_text) > _MAX_POST_CHARS:
            logger.warning("[ContentGen] ⚠️  Post truncated from %d → %d chars.",
                           len(post_text), _MAX_POST_CHARS)
            post_text = post_text[:_MAX_POST_CHARS - 3] + "..."

        logger.info("[ContentGen] ✅ Generated post on: %s", topic)
        return post_text

    def generate_post_on_topic(self, topic: str) -> str:
        return self.generate_weekly_post(custom_topic=topic)

    # ──────────────────────────────────────────────
    # Comment Reply Generation
    # ──────────────────────────────────────────────

    def generate_comment_reply(self, original_post: str, commenter_name: str,
                                comment_text: str,
                                previous_replies: Optional[list] = None) -> str:
        """Generate a contextual reply to a LinkedIn comment."""
        context = ""
        if previous_replies:
            context = "\n\nPrevious replies in this thread:\n" + "\n".join(
                [f"- {r}" for r in previous_replies[-3:]]
            )

        prompt = f"""{self.AUTHOR_PERSONA}

You are replying to a comment on one of Satyam's LinkedIn posts.

Original post excerpt:
"{original_post[:400]}..."

Comment by {commenter_name}:
"{comment_text}"
{context}

Write a reply that:
- Directly addresses what {commenter_name} said
- Is warm and professional (not robotic)
- Adds value: a quick insight, a follow-up question, or an acknowledgment with extra context
- Is concise: 1–3 sentences max (MUST stay under 1250 characters)
- Do NOT start with "Great comment!" or "Thanks for sharing!" — be more specific
- No hashtags in replies
- Address them by first name if possible

Output ONLY the reply text, nothing else.
"""
        reply = self._call_claude(prompt, max_tokens=200)

        if len(reply) > _MAX_COMMENT_CHARS:
            reply = reply[:_MAX_COMMENT_CHARS - 3] + "..."

        logger.info("[ContentGen] ✅ Generated reply to %s", commenter_name)
        return reply

    # ──────────────────────────────────────────────
    # DM Reply Generation
    # ──────────────────────────────────────────────

    def generate_message_reply(self, sender_name: str, message_text: str,
                                conversation_history: Optional[list] = None) -> str:
        """Generate a reply to a LinkedIn direct message."""
        history_context = ""
        if conversation_history:
            history_context = "\n\nPrevious messages:\n"
            for msg in conversation_history[-4:]:
                history_context += f"{msg.get('role', 'unknown')}: {msg.get('text', '')}\n"

        prompt = f"""{self.AUTHOR_PERSONA}

Satyam received a LinkedIn direct message. Write a professional, personalised reply.

Sender: {sender_name}
Message: "{message_text}"
{history_context}

Guidelines:
- If collaboration/consulting request: express interest, suggest a brief call
- If job offer: politely note current focus, thank them
- If technical question: concise helpful answer, offer to connect further
- If introduction/connection request: warm and welcoming
- If spam/irrelevant: polite brief decline
- Keep to 2–4 sentences, sound genuine not robotic

Output ONLY the reply text, nothing else.
"""
        reply = self._call_claude(prompt, max_tokens=250)
        logger.info("[ContentGen] ✅ Generated DM reply to %s", sender_name)
        return reply

    # ──────────────────────────────────────────────
    # Comment Classification
    # ──────────────────────────────────────────────

    def classify_comment(self, comment_text: str) -> str:
        """
        Classify a comment: question | praise | disagreement | spam | engagement
        Falls back to 'engagement' on any API error.
        """
        prompt = f"""Classify this LinkedIn comment into exactly one category:
- question: asks a technical or general question
- praise: complimentary or agreeable
- disagreement: challenges or disputes the post
- spam: promotional, irrelevant, or bot-like
- engagement: general engagement (tagging someone, sharing experience)

Comment: "{comment_text}"

Output ONLY the category word, nothing else.
"""
        try:
            result = self._call_claude(prompt, max_tokens=10).lower()
            if result not in ("question", "praise", "disagreement", "spam", "engagement"):
                result = "engagement"
            return result
        except Exception:
            logger.warning("[ContentGen] Comment classification failed, defaulting to 'engagement'.")
            return "engagement"
