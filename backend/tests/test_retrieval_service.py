import asyncio
import uuid

from app.services import retrieval_service


def _run(coro):
    return asyncio.run(coro)


class DummyChunk:
    def __init__(self, text: str, embedding: list[float], chunk_index: int = 0) -> None:
        self.id = uuid.uuid4()
        self.text = text
        self.embedding = embedding
        self.chunk_index = chunk_index


def test_pick_chunk_prefers_high_quality_grounded_chunks(monkeypatch) -> None:
    ranked_chunks = [
        DummyChunk('db.similarity_search("What is total amount?")', [0.1], chunk_index=0),
        DummyChunk("Q1: What is Python? Answer: Python is a programming language.", [0.2], chunk_index=1),
        DummyChunk("Q2: What is Pandas? Answer: Pandas is a data analysis library.", [0.3], chunk_index=2),
    ]

    async def _mock_embed(*_args, **_kwargs):
        return [1.0]

    monkeypatch.setattr(retrieval_service.embedding_service, "embed", _mock_embed)

    async def _mock_retrieve(_db, _document_id, _query_embedding, limit):
        return ranked_chunks[:limit]

    monkeypatch.setattr(
        retrieval_service,
        "retrieve_relevant_chunks",
        _mock_retrieve,
    )

    chosen = _run(retrieval_service.pick_chunk_for_session(None, uuid.uuid4(), answered_count=0, difficulty=2))

    assert "What is Python?" in chosen.text or "What is Pandas?" in chosen.text


def test_choose_chunk_candidate_prefers_unused_then_non_recent() -> None:
    first = DummyChunk("chunk-a", [0.1], chunk_index=0)
    second = DummyChunk("Q1: What is Python? Answer: Python is a language.", [0.2], chunk_index=1)
    third = DummyChunk("chunk-c", [0.3], chunk_index=2)
    ranked_chunks = [first, second, third]

    chosen = _run(retrieval_service.choose_chunk_candidate(
        ranked_chunks,
        usage_counts={first.id: 2, second.id: 0, third.id: 1},
        recent_chunk_ids=[second.id],
        answered_count=0,
    ))

    assert chosen.id == second.id


def test_chunk_quality_score_penalizes_code_noise() -> None:
    clean_score = _run(retrieval_service.chunk_quality_score(
        "Q1: What is NumPy? Answer: NumPy is used for numerical computing and array operations."
    ))
    noisy_score = _run(retrieval_service.chunk_quality_score('db.similarity_search("What is total amount?") return result'))

    assert clean_score > noisy_score


def test_build_retrieval_query_async() -> None:
    query = _run(retrieval_service.build_retrieval_query(answered_count=0, difficulty=2))
    assert "medium" in query.lower()


def test_build_retrieval_query_async_includes_role_and_focus_skills() -> None:
    query = _run(
        retrieval_service.build_retrieval_query(
            answered_count=1,
            difficulty=1,
            role_title="Backend Engineer",
            focus_skills=["Python", "SQL"],
        )
    )

    lowered = query.lower()
    assert "backend engineer" in lowered
    assert "python" in lowered
    assert "sql" in lowered
