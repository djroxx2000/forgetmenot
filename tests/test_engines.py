"""Unit tests for source engines and dedup filter.

These tests don't require running infrastructure.
"""

from forgetmenot.core.dedup import DedupFilter
from forgetmenot.engines.conversation import ConversationEngine, normalize_cursor_jsonl, normalize_raw_text
from forgetmenot.models.artifact import MemoryArtifact


class TestConversationEngine:
    def setup_method(self):
        self.engine = ConversationEngine()

    def test_normalize_standard_messages(self):
        raw = {
            "source": "api",
            "session_id": "test-session",
            "conversation": [
                {"role": "user", "content": "Hello world"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            "metadata": {"project": "test", "domain_tags": ["greeting"]},
        }
        artifacts = self.engine.normalize(raw)
        assert len(artifacts) == 2
        assert all(isinstance(a, MemoryArtifact) for a in artifacts)
        assert artifacts[0].content == "Hello world"
        assert artifacts[0].metadata["role"] == "user"
        assert artifacts[1].content == "Hi there!"
        assert artifacts[1].engine_type == "conversation"
        assert artifacts[0].tags == ["greeting"]

    def test_normalize_empty_conversation(self):
        raw = {
            "source": "api",
            "session_id": "test-session",
            "conversation": [],
        }
        artifacts = self.engine.normalize(raw)
        assert artifacts == []

    def test_deterministic_artifact_ids(self):
        raw = {
            "source": "api",
            "session_id": "same-session",
            "conversation": [{"role": "user", "content": "Same content"}],
        }
        a1 = self.engine.normalize(raw)
        a2 = self.engine.normalize(raw)
        assert a1[0].id == a2[0].id

    def test_extract_for_mem0(self):
        raw = {
            "source": "cursor",
            "session_id": "session-1",
            "conversation": [
                {"role": "user", "content": "I like Python"},
                {"role": "assistant", "content": "Python is great!"},
            ],
            "metadata": {"project": "demo"},
        }
        artifacts = self.engine.normalize(raw)
        payloads = self.engine.extract_for_mem0(artifacts)
        assert len(payloads) == 1
        assert len(payloads[0]["messages"]) == 2
        assert payloads[0]["messages"][0]["role"] == "user"
        assert payloads[0]["metadata"]["session_id"] == "session-1"

    def test_archive_schema(self):
        from forgetmenot.engines.conversation import ConversationArchive
        assert self.engine.archive_schema() is ConversationArchive

    def test_prepare_archive_record(self):
        raw = {
            "source": "cli",
            "session_id": "archive-test",
            "conversation": [{"role": "user", "content": "test"}],
            "metadata": {"project": "proj1"},
        }
        record = self.engine.prepare_archive_record(raw)
        assert record.session_id == "archive-test"
        assert record.source == "cli"
        assert record.message_count == 1
        assert record.project == "proj1"


class TestNormalizationHelpers:
    def test_normalize_cursor_jsonl(self):
        jsonl = '{"role": "user", "content": "Hello"}\n{"role": "assistant", "content": "Hi"}\n'
        result = normalize_cursor_jsonl(jsonl)
        assert result["source"] == "cursor"
        assert len(result["conversation"]) == 2

    def test_normalize_cursor_jsonl_with_content_blocks(self):
        jsonl = '{"role": "assistant", "content": [{"type": "text", "text": "Hello from blocks"}]}\n'
        result = normalize_cursor_jsonl(jsonl)
        assert result["conversation"][0]["content"] == "Hello from blocks"

    def test_normalize_raw_text(self):
        result = normalize_raw_text("Remember this fact")
        assert result["source"] == "api"
        assert len(result["conversation"]) == 1
        assert result["conversation"][0]["content"] == "Remember this fact"


class TestDedupFilter:
    def setup_method(self):
        from forgetmenot.config import Settings
        self.settings = Settings(dedup_similarity_threshold=0.95)
        self.dedup = DedupFilter(self.settings)

    def test_session_exclusion(self):
        results = [
            {"id": "1", "memory": "fact A", "metadata": {"session_id": "exclude-me"}, "score": 0.8},
            {"id": "2", "memory": "fact B", "metadata": {"session_id": "keep-me"}, "score": 0.7},
        ]
        filtered = self.dedup.filter(results, exclude_session_id="exclude-me")
        assert len(filtered) == 1
        assert filtered[0].id == "2"

    def test_near_duplicate_exclusion(self):
        results = [
            {"id": "1", "memory": "the user prefers python for backend", "metadata": {}, "score": 0.99},
            {"id": "2", "memory": "the user prefers python for backend", "metadata": {}, "score": 0.98},
        ]
        filtered = self.dedup.filter(results)
        assert len(filtered) == 1

    def test_no_filtering_for_distinct_memories(self):
        results = [
            {"id": "1", "memory": "likes Python", "metadata": {"session_id": "s1"}, "score": 0.8},
            {"id": "2", "memory": "uses PostgreSQL", "metadata": {"session_id": "s2"}, "score": 0.7},
        ]
        filtered = self.dedup.filter(results, exclude_session_id="other-session")
        assert len(filtered) == 2


class TestMemoryArtifact:
    def test_auto_generated_id(self):
        a = MemoryArtifact(engine_type="test", source="api", session_id="s1", content="hello", content_type="text")
        assert len(a.id) == 16

    def test_deterministic_id(self):
        kwargs = {
            "engine_type": "test", "source": "api", "session_id": "s1",
            "content": "hello", "content_type": "text",
        }
        a1 = MemoryArtifact(**kwargs)
        a2 = MemoryArtifact(**kwargs)
        assert a1.id == a2.id

    def test_different_content_different_id(self):
        base = {"engine_type": "test", "source": "api", "session_id": "s1", "content_type": "text"}
        a1 = MemoryArtifact(content="hello", **base)
        a2 = MemoryArtifact(content="world", **base)
        assert a1.id != a2.id
