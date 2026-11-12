import uuid

from masters_cycling_lab.domain.retrieval import SearchHit, fuse


def hit(name: str, rank: int, *, distance: float | None = None, lexical: float | None = None) -> SearchHit:
    return SearchHit(
        rank=rank,
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, name),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, "paper"),
        index_version_id=uuid.uuid5(uuid.NAMESPACE_URL, "version"),
        document_title=None,
        publication_year=None,
        text=name,
        spans=(),
        cosine_distance=distance,
        lexical_score=lexical,
    )


def names(hits: list[SearchHit]) -> list[str]:
    return [h.text for h in hits]


def test_a_passage_found_by_both_rankings_comes_first_and_keeps_both_scores() -> None:
    vector = [hit("a", 1, distance=0.1), hit("b", 2, distance=0.2)]
    lexical = [hit("c", 1, lexical=0.9), hit("b", 2, lexical=0.5)]

    fused = fuse(vector, lexical, 10)

    assert names(fused) == ["b", "a", "c"]
    assert (fused[0].cosine_distance, fused[0].lexical_score) == (0.2, 0.5)
    assert [h.rank for h in fused] == [1, 2, 3]


def test_lexical_counts_half_as_much_as_vector() -> None:
    # Vector rank 2 (1/62) beats lexical rank 1 at half weight (0.5/61).
    fused = fuse([hit("a", 1), hit("b", 2)], [hit("c", 1)], 10)
    assert names(fused) == ["a", "b", "c"]


def test_equal_scores_keep_the_vector_order_first() -> None:
    # Vector rank 62 scores 1/122, exactly what lexical rank 1 scores at half weight (0.5/61).
    vector = [hit(f"v{rank}", rank) for rank in range(1, 62)] + [hit("tied vector", 62)]
    lexical = [hit("tied lexical", 1)]

    fused = fuse(vector, lexical, 100)

    assert names(fused)[61:] == ["tied vector", "tied lexical"]
    assert names(fuse(vector, lexical, 3)) == ["v1", "v2", "v3"]
    assert fuse([], [], 10) == []
