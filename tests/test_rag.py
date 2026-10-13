from core.rag import KnowledgeBase, HashEmbedder, chunk_text


def kb(tmp_path):
    return KnowledgeBase(tmp_path / "kb", embedder=HashEmbedder())


def test_chunking():
    assert chunk_text("") == []
    c = chunk_text("word " * 1000)
    assert len(c) > 1 and all(len(x) <= 800 for x in c)


def test_add_and_search(tmp_path):
    k = kb(tmp_path)
    k.add_text("cooking.txt", "To make masala chai boil water with tea leaves, ginger, cardamom and milk.")
    k.add_text("space.txt", "The Moon orbits the Earth about every twenty seven days.")
    hit = k.search("how do I make chai with ginger")[0]
    assert hit["source"] == "cooking.txt"
    assert k.search("moon orbit earth")[0]["source"] == "space.txt"


def test_persists_and_replaces(tmp_path):
    k = kb(tmp_path); k.add_text("a.txt", "alpha beta gamma")
    k2 = kb(tmp_path)
    assert k2.sources() == ["a.txt"]
    k2.add_text("a.txt", "completely different delta text")
    assert len(k2.search("delta")) == 1 and not k2.search("gamma")


def test_file_and_remove(tmp_path):
    f = tmp_path / "n.md"; f.write_text("FRIDAY was built by Ravi and Jarvis.")
    k = kb(tmp_path); assert k.add_file(str(f)) == 1
    assert k.remove("n.md") == 1 and k.sources() == []


def test_unsupported_and_missing(tmp_path):
    import pytest
    k = kb(tmp_path)
    with pytest.raises(FileNotFoundError): k.add_file(str(tmp_path / "x.txt"))
    b = tmp_path / "x.bin"; b.write_bytes(b"\0")
    with pytest.raises(ValueError): k.add_file(str(b))


def test_empty_search(tmp_path):
    assert kb(tmp_path).search("anything") == []
