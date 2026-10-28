from rag import chunk


# JOURNAL: chunk() lost pieces with no error twice. 60 of 140 files never got indexed because a small
# file with frontmatter fits whole in chunk 0, which was dropped; later 14 of 22 chunks went missing
# until "header only" and "header with body" were told apart.


def chunks_of(content):
    return chunk({"note.md": {"content": content}})["note.md"].get("chunks", [])


def test_a_small_file_with_frontmatter_still_gets_a_chunk():
    result = chunks_of("---\ntitle: note\n---\nthe only content of a small file")

    assert [c["content"] for c in result] == ["the only content of a small file"]


def test_a_header_with_body_keeps_both():
    result = chunks_of("# Decision\nkept the hybrid search")

    assert result == [{"header": "# Decision", "content": "kept the hybrid search"}]


def test_a_header_only_piece_is_dropped_but_labels_the_body_after_it():
    long_section = "# Section\n" + "word " * 700  # longer than one chunk: the splitter cuts the header alone

    result = chunks_of(long_section)

    assert len(result) >= 2
    assert all(c["header"] == "# Section" for c in result)
    assert "".join(c["content"] for c in result).count("word") == 700
