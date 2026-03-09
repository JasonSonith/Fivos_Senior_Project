from security.sanitizer import sanitize_html


class TestDangerousTagRemoval:
    def test_script_tag_removed(self):
        result = sanitize_html("<html><body><script>alert('xss')</script></body></html>")
        assert "<script>" not in result

    def test_iframe_tag_removed(self):
        result = sanitize_html('<html><body><iframe src="evil.com"></iframe></body></html>')
        assert "<iframe" not in result

    def test_object_tag_removed(self):
        result = sanitize_html('<html><body><object data="x.swf"></object></body></html>')
        assert "<object" not in result

    def test_embed_tag_removed(self):
        result = sanitize_html('<html><body><embed src="x.swf"></body></html>')
        assert "<embed" not in result

    def test_form_tag_removed(self):
        result = sanitize_html('<html><body><form action="/steal"><input></form></body></html>')
        assert "<form" not in result

    def test_script_content_also_removed(self):
        result = sanitize_html("<html><body><script>var secret = 'data';</script></body></html>")
        assert "var secret" not in result


class TestEventAttributeRemoval:
    def test_onerror_removed(self):
        result = sanitize_html('<html><body><img src="x" onerror="alert(1)"></body></html>')
        assert "onerror" not in result

    def test_onclick_removed(self):
        result = sanitize_html('<html><body><a onclick="steal()" href="/page">link</a></body></html>')
        assert "onclick" not in result

    def test_onload_removed(self):
        result = sanitize_html('<html><body onload="x()">content</body></html>')
        assert "onload" not in result

    def test_safe_attributes_preserved(self):
        result = sanitize_html('<html><body><a href="/page" class="nav" id="main-link">link</a></body></html>')
        assert 'href="/page"' in result
        assert 'class="nav"' in result
        assert 'id="main-link"' in result


class TestCleanHtmlPassthrough:
    def test_clean_html_unchanged_structure(self):
        result = sanitize_html("<html><body><p>text</p></body></html>")
        assert "<p>" in result
        assert "text" in result

    def test_empty_string(self):
        result = sanitize_html("")
        assert isinstance(result, str)

    def test_plain_text(self):
        result = sanitize_html("just plain text no tags")
        assert "just plain text no tags" in result
