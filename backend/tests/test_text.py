from app.pipeline.text import (
    detect_lang,
    hamming_hex,
    normalize_url,
    simhash64,
    strip_html,
    title_fingerprint,
)


def test_normalize_url_drops_tracking_params_and_fragment():
    url = "https://WWW.Example.com/post/?utm_source=x&utm_medium=y&id=1&fbclid=z#section"
    assert normalize_url(url) == "https://example.com/post?id=1"


def test_normalize_url_sorts_query_and_strips_trailing_slash():
    assert normalize_url("http://example.com/a/?b=2&a=1") == "http://example.com/a?a=1&b=2"
    assert normalize_url("http://example.com") == "http://example.com/"


def test_title_fingerprint_is_case_and_punctuation_insensitive():
    assert title_fingerprint("OpenAI 发布 GPT-5!") == title_fingerprint("openai 发布 gpt-5")


def test_simhash_similar_texts_are_close():
    left = simhash64("OpenAI releases GPT-5 with multimodal capabilities and agent tools")
    right = simhash64("OpenAI releases GPT-5 with multimodal capabilities and agent features")
    other = simhash64("The weather is nice today for a long walk outside")
    assert hamming_hex(left, right) <= 10
    assert hamming_hex(left, other) > 10


def test_detect_lang():
    assert detect_lang("今天北京的天气非常不错") == "zh"
    assert detect_lang("This is an English sentence about machine learning") == "en"


def test_strip_html_removes_tags_and_entities():
    assert strip_html("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
