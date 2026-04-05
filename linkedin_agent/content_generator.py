"""
AI Content Generator
Uses Claude API to generate LinkedIn posts about AI & Data Engineering.
Also generates contextual replies to comments and messages.
"""

import anthropic
from datetime import datetime
from typing import Optional


# ── Topic bank for weekly AI/Data Engineering posts ──────────────────────────
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
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self._topic_index = 0  # Cycles through TOPIC_POOL week by week

    # ──────────────────────────────────────────────
    # Post Generation
    # ──────────────────────────────────────────────

    def generate_weekly_post(self, custom_topic: Optional[str] = None) -> str:
        """
        Generate a LinkedIn post for the week.
        If custom_topic is None, cycles through the built-in topic pool.
        """
        topic = custom_topic or self._next_topic()
        week_str = datetime.now().strftime("Week of %B %d, %Y")

        prompt = f"""{self.AUTHOR_PERSONA}

Write a compelling LinkedIn post for {week_str} on this topic:
"{topic}"

Requirements:
- Length: 150–300 words
- Start with a strong hook (first line must grab attention — no "I am excited to share...")
- Include 1–2 concrete technical insights or real-world observations
- Mention a specific tool, framework, or architecture pattern
- End with an engaging question to invite comments
- Add 3–5 relevant hashtags on the last line
- Format for LinkedIn: short paragraphs, line breaks, optional emojis

Output ONLY the post text, nothing else.
"""

        message = self.client.messages.create(
            model=self.model,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        post_text = message.content[0].text.strip()
        print(f"[ContentGen] ✅ Generated post on: {topic}")
        return post_text

    def generate_post_on_topic(self, topic: str) -> str:
        """Generate a post on a specific topic provided by the user."""
        return self.generate_weekly_post(custom_topic=topic)

    def _next_topic(self) -> str:
        topic = TOPIC_POOL[self._topic_index % len(TOPIC_POOL)]
        self._topic_index += 1
        return topic

    # ──────────────────────────────────────────────
    # Comment Reply Generation
    # ──────────────────────────────────────────────

    def generate_comment_reply(
        self,
        original_post: str,
        commenter_name: str,
        comment_text: str,
        previous_replies: list = None,
    ) -> str:
        """
        Generate a contextual, human-sounding reply to a LinkedIn comment.
        """
        context = ""
        if previous_replies:
            context = "\n\nPrevious replies in this thread:\n" + "\n".join(
                [f"- {r}" for r in previous_replies[-3:]]  # last 3 replies for context
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
- Is concise: 1–3 sentences max
- Do NOT start with "Great comment!" or "Thanks for sharing!" — be more specific
- No hashtags in replies
- Address them by first name if possible

Output ONLY the reply text, nothing else.
"""

        message = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        reply = message.content[0].text.strip()
        print(f"[ContentGen] ✅ Generated reply to {commenter_name}")
        return reply

    # ──────────────────────────────────────────────
    # Message (DM) Reply Generation
    # ──────────────────────────────────────────────

    def generate_message_reply(
        self,
        sender_name: str,
        message_text: str,
        conversation_history: list = None,
    ) -> str:
        """
        Generate a reply to a LinkedIn direct message.
        Handles common scenarios: collaboration requests, job offers, questions, etc.
        """
        history_context = ""
        if conversation_history:
            history_context = "\n\nPrevious messages in this conversation:\n"
            for msg in conversation_history[-4:]:
                role = msg.get("role", "unknown")
                text = msg.get("text", "")
                history_context += f"{role}: {text}\n"

        prompt = f"""{self.AUTHOR_PERSONA}

Satyam received a LinkedIn direct message. Write a professional, personalized reply.

Sender: {sender_name}
Message: "{message_text}"
{history_context}

Guidelines for the reply:
- Be genuine and professional
- If it's a collaboration/consulting request: express interest and suggest a brief call
- If it's a job offer: politely note Satyam is focused on his current work but thanks them
- If it's a technical question: give a concise helpful answer and offer to connect further
- If it's a connection request/introduction: be warm and welcoming
- If it's spam or irrelevant: write a polite, brief decline
- Keep it to 2–4 sentences
- Do NOT sound like a bot — vary your opening

Output ONLY the reply text, nothing else.
"""

        message = self.client.messages.create(
            model=self.model,
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        reply = message.content[0].text.strip()
        print(f"[ContentGen] ✅ Generated DM reply to {sender_name}")
        return reply

    # ──────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────

    def classify_comment(self, comment_text: str) -> str:
        """
        Classify a comment to help the agent decide the reply strategy.
        Returns one of: 'question', 'praise', 'disagreement', 'spam', 'engagement'
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
        message = self.client.messages.create(
            model=self.model,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip().lower()
